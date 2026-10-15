"""
BidBox MCP server - value-for-money checks on Kenyan public procurement (OCDS).

Tools
  1. dataset_summary      - what data is loaded, and how messy it is
  2. search_awards        - find past awards by keyword / buyer (every row cites its OCID)
  3. price_benchmark      - robust price statistics for comparable past awards
  4. flag_price_outliers  - check a value against the benchmark; every flag cites source OCIDs
  5. draft_committee_memo - WRITES a sourced memo to disk. Irreversible: needs a named approver.

Every tool call is logged to logs/actions.jsonl (timestamp, tool, inputs, output summary).

Data: Kenya PPRA / PPIP OCDS bulk download (one compiled release per line, .jsonl or .jsonl.gz)
from https://data.open-contracting.org/en/publication/147 - put the file(s) in ./data/
The agent never awards a tender. It prepares a file; the evaluation committee decides.
"""

from __future__ import annotations

import functools
import gzip
import json
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

BASE = Path(__file__).parent
DATA_DIR = Path(os.getenv("BIDBOX_DATA_DIR", BASE / "data"))
LOG_FILE = Path(os.getenv("BIDBOX_LOG_FILE", BASE / "logs" / "actions.jsonl"))
OUT_DIR = Path(os.getenv("BIDBOX_OUT_DIR", BASE / "output"))
SOURCE_URL = "https://data.open-contracting.org/en/publication/147"

mcp = MCPServer("BidBox")


# ---------------------------------------------------------------- logging

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(entry: dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def logged(fn):
    """Log every call: inputs, output (truncated), status, timestamps."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = _now()
        try:
            result = fn(*args, **kwargs)
            _log({"ts": started, "finished": _now(), "tool": fn.__name__,
                  "inputs": kwargs or args, "status": "ok",
                  "output": json.dumps(result, default=str)[:2000]})
            return result
        except Exception as e:  # logged, then re-raised so the agent sees it
            _log({"ts": started, "finished": _now(), "tool": fn.__name__,
                  "inputs": kwargs or args, "status": "error", "error": repr(e)})
            raise

    return wrapper


# ---------------------------------------------------------------- data loading

_AWARDS: list[dict[str, Any]] | None = None
_STATS: dict[str, int] = {}


def _num(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" \
        else path.open(encoding="utf-8")


def _load() -> list[dict[str, Any]]:
    """Flatten compiled releases into one row per award. Tolerates messy data."""
    global _AWARDS, _STATS
    if _AWARDS is not None:
        return _AWARDS
    rows: list[dict[str, Any]] = []
    stats = {"files": 0, "processes": 0, "bad_lines": 0, "processes_without_awards": 0,
             "awards_without_value": 0, "awards_without_supplier": 0, "missing_buyer": 0}
    files = sorted(list(DATA_DIR.glob("*.jsonl")) + list(DATA_DIR.glob("*.jsonl.gz")))
    for path in files:
        stats["files"] += 1
        with _open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rel = json.loads(line)
                except json.JSONDecodeError:
                    stats["bad_lines"] += 1
                    continue
                stats["processes"] += 1
                tender = rel.get("tender") or {}
                buyer = (rel.get("buyer") or {}).get("name") or ""
                if not buyer:
                    stats["missing_buyer"] += 1
                awards = rel.get("awards") or []
                if not awards:
                    stats["processes_without_awards"] += 1
                item_text = " ".join(
                    (i.get("description") or "") for i in (tender.get("items") or [])
                )
                for a in awards:
                    value = _num((a.get("value") or {}).get("amount"))
                    suppliers = [s.get("name") for s in (a.get("suppliers") or []) if s.get("name")]
                    if value is None:
                        stats["awards_without_value"] += 1
                    if not suppliers:
                        stats["awards_without_supplier"] += 1
                    rows.append({
                        "ocid": rel.get("ocid"),
                        "award_id": a.get("id"),
                        "buyer": buyer or "(missing buyer name)",
                        "title": tender.get("title") or a.get("title") or "",
                        "items": item_text,
                        "category": tender.get("mainProcurementCategory") or "",
                        "method": tender.get("procurementMethodDetails") or tender.get("procurementMethod") or "",
                        "award_value": value,
                        "currency": (a.get("value") or {}).get("currency") or "KES",
                        "tender_value": _num((tender.get("value") or {}).get("amount")),
                        "suppliers": suppliers,
                        "date": a.get("date") or rel.get("date"),
                        "source_file": path.name,
                    })
    _STATS = stats
    _AWARDS = rows
    return rows


def _matches(row: dict[str, Any], keyword: str, buyer: str | None) -> bool:
    text = f"{row['title']} {row['items']}".lower()
    words = [w for w in re.split(r"\W+", keyword.lower()) if w]
    if not words or not all(w in text for w in words):
        return False
    return not buyer or buyer.lower() in row["buyer"].lower()


def _cite(row: dict[str, Any]) -> str:
    return f"{row['ocid']} (award {row['award_id']}, {row['source_file']})"


def _robust(values: list[float]) -> dict[str, float]:
    """Median and MAD on log scale - procurement values are heavily skewed."""
    logs = [math.log10(v) for v in values]
    med = statistics.median(logs)
    mad = statistics.median([abs(x - med) for x in logs]) or 1e-9
    q = statistics.quantiles(values, n=4) if len(values) >= 4 else [min(values), statistics.median(values), max(values)]
    return {"log_median": med, "log_mad": mad, "median": 10 ** med,
            "p25": q[0], "p75": q[-1], "min": min(values), "max": max(values)}


# ---------------------------------------------------------------- tools

@mcp.tool()
@logged
def dataset_summary() -> dict[str, Any]:
    """Report which OCDS files are loaded and the data-quality problems found in them.
    Call this first so every later finding can be read in context."""
    rows = _load()
    return {"source": SOURCE_URL, "data_dir": str(DATA_DIR), "award_rows": len(rows),
            "quality": _STATS,
            "note": "PPIP publishes tenders and awards, not bid documents. "
                    "BidBox analyses award history only."}


@mcp.tool()
@logged
def search_awards(keyword: str, buyer: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Find past awards whose tender title or item descriptions contain ALL words in `keyword`.
    Optionally filter by procuring entity name (`buyer`, partial match).
    Every result carries its OCID so it can be cited."""
    hits = [r for r in _load() if _matches(r, keyword, buyer)]
    hits.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    return {"keyword": keyword, "buyer": buyer, "total_matches": len(hits),
            "results": [{**{k: r[k] for k in ("ocid", "award_id", "buyer", "title", "award_value",
                                                 "currency", "suppliers", "date")},
                         "cite": _cite(r)} for r in hits[: max(1, min(limit, 100))]]}


@mcp.tool()
@logged
def price_benchmark(keyword: str, buyer: str | None = None, min_samples: int = 5) -> dict[str, Any]:
    """Robust price statistics (median, quartiles) for past awards matching `keyword`.
    Refuses to produce a benchmark from fewer than `min_samples` valued awards."""
    rows = [r for r in _load() if _matches(r, keyword, buyer) and r["award_value"]]
    if len(rows) < min_samples:
        return {"keyword": keyword, "status": "insufficient_data", "samples": len(rows),
                "message": f"Only {len(rows)} valued awards match; need {min_samples}. "
                           "Try a broader keyword. No benchmark produced."}
    s = _robust([r["award_value"] for r in rows])
    return {"keyword": keyword, "buyer": buyer, "status": "ok", "samples": len(rows),
            "currency": "KES", "median": round(s["median"], 2), "p25": round(s["p25"], 2),
            "p75": round(s["p75"], 2), "min": s["min"], "max": s["max"],
            "sources": [_cite(r) for r in rows[:50]]}


@mcp.tool()
@logged
def flag_price_outliers(keyword: str, amount: float | None = None, ocid: str | None = None,
                        threshold: float = 3.5, min_samples: int = 5) -> dict[str, Any]:
    """Check a price against comparable past awards.
    Give either `amount` (a quoted/tender value in KES) or `ocid` (an existing award to check).
    Uses a robust z-score on log values; |z| >= threshold is flagged.
    Every flag cites the comparison set. A flag is a question for the committee, not a finding of wrongdoing."""
    rows = [r for r in _load() if _matches(r, keyword, None) and r["award_value"]]
    target_cite = None
    if ocid:
        own = [r for r in _load() if r["ocid"] == ocid and r["award_value"]]
        if not own:
            return {"status": "not_found", "message": f"No valued award with OCID {ocid}."}
        amount = own[0]["award_value"]
        target_cite = _cite(own[0])
        rows = [r for r in rows if r["ocid"] != ocid]
    if amount is None or amount <= 0:
        return {"status": "error", "message": "Provide a positive `amount` or a valid `ocid`."}
    if len(rows) < min_samples:
        return {"status": "insufficient_data", "samples": len(rows),
                "message": "Too few comparable awards to judge. No flag raised."}
    s = _robust([r["award_value"] for r in rows])
    z = 0.6745 * (math.log10(amount) - s["log_median"]) / s["log_mad"]
    ratio = amount / s["median"]
    flagged = abs(z) >= threshold
    closest = sorted(rows, key=lambda r: abs(math.log10(r["award_value"]) - s["log_median"]))[:10]
    return {"status": "flagged" if flagged else "within_range", "keyword": keyword,
            "amount_checked": amount, "checked_award": target_cite,
            "benchmark_median": round(s["median"], 2), "ratio_to_median": round(ratio, 2),
            "robust_z": round(z, 2), "threshold": threshold, "samples": len(rows),
            "direction": "above" if z > 0 else "below",
            "explanation": (f"{amount:,.0f} KES is {ratio:.1f}x the median of {len(rows)} comparable "
                            f"awards (robust z = {z:.1f})."),
            "comparison_sources": [_cite(r) for r in closest]}


@mcp.tool()
@logged
def draft_committee_memo(title: str, findings_markdown: str, sources: list[str],
                         approved_by: str, approval_note: str = "") -> dict[str, Any]:
    """IRREVERSIBLE: writes a value-for-money memo for the evaluation committee to output/.
    Only call AFTER a named human has approved; pass their name as `approved_by`.
    Every finding must be backed by at least one OCID in `sources`.
    The memo recommends questions for the committee; it never awards or rejects a bidder."""
    if not approved_by or not approved_by.strip():
        raise ValueError("Refused: a named human approver is required before filing a memo.")
    if not sources:
        raise ValueError("Refused: an unsourced memo is not allowed. Provide OCIDs in `sources`.")
    known = {r["ocid"] for r in _load()}
    unknown = [s for s in sources if s.split(" ")[0] not in known]
    if unknown:
        raise ValueError(f"Refused: these sources are not in the loaded dataset: {unknown}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "memo"
    path = OUT_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    body = "\n".join([
        f"# {title}", "",
        f"*Prepared by BidBox agent - {_now()}*  ",
        f"*Approved for filing by: **{approved_by.strip()}***" + (f" - {approval_note}" if approval_note else ""), "",
        "> This memo raises questions for the evaluation committee. It does not award, "
        "reject or rank any bidder. The decision rests with the committee.", "",
        "## Findings", "", findings_markdown.strip(), "",
        "## Sources (OCDS, Kenya PPRA)", "", *[f"- {s}" for s in sources], "",
        f"Data: {SOURCE_URL}",
    ])
    path.write_text(body, encoding="utf-8")
    return {"status": "filed", "path": str(path), "approved_by": approved_by.strip(),
            "source_count": len(sources)}


if __name__ == "__main__":
    # stdio for the Inspector; set BIDBOX_TRANSPORT=streamable-http for n8n
    transport = os.getenv("BIDBOX_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        from mcp.server.transport_security import TransportSecuritySettings

        # Listen on all interfaces so n8n in Docker can reach us via host.docker.internal,
        # but keep DNS-rebinding protection with an explicit host allowlist.
        mcp.run(
            transport=transport,
            host=os.getenv("BIDBOX_HOST", "0.0.0.0"),
            port=int(os.getenv("BIDBOX_PORT", "8000")),
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*", "bidbox:*"],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*",
                                 "http://host.docker.internal:*"],
            ),
        )
