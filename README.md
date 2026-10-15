# BidBox — value-for-money checks on Kenyan public tenders

An agentic AI that helps a tender evaluation committee check prices against Kenya's own procurement history. It searches past awards, builds a price benchmark, flags outliers, and drafts a **sourced** memo for the committee. It never awards, rejects or ranks a bidder: **the agent recommends, the committee decides.**

Built for the **African Agentic AI Design Challenge — Governance track (The Bid Box Challenge), theme: Value for money.**

   ![BidBox architecture](architecture%20diag.png)

## Problem statement

Tender evaluation committees must judge whether a bidder's price is reasonable, but they have no quick, sourced way to compare it with what other public bodies actually paid. Checking documents, comparing prices and writing the evaluation report is slow, manual work (the challenge brief puts the full cycle at about 26 days), and price comparisons often rely on memory or a few informal quotes.

The evidence already exists: Kenya's Public Procurement Information Portal (PPIP) publishes tens of thousands of tenders and awards in the Open Contracting Data Standard (OCDS). But the data is large and messy, and unusable by a busy committee member without technical help. Value for money is a constitutional requirement (Article 227), and overpricing diverts money from public services.

## Solution overview

A committee member asks a question in plain language, e.g. *"Is 2,000,000 KES reasonable for this toner supply?"* The agent:

1. checks what data is loaded and how reliable it is,
2. searches comparable past awards,
3. builds a robust price benchmark (refusing when there are too few comparable awards),
4. tests the price against it, citing the official records (OCIDs) it compared against,
5. after a **named human approves**, files a sourced memo for the evaluation file.

Everything runs locally: the data file, the MCP server and the open-weights model. Nothing is sent to an external API.

## Target users

- **Primary:** tender evaluation committees and procurement officers in Kenyan procuring entities (county governments, ministries, state corporations).
- **Secondary:** internal auditors, the Office of the Auditor-General and oversight bodies, who need traceable evidence; civil-society monitors working with open contracting data.
- **Indirect beneficiaries:** citizens and honest suppliers, through fairer pricing of public contracts.

## Architecture

```
Committee member ──question──▶ n8n Chat Trigger ──▶ AI Agent (planner)
                                                      │  LLM: Qwen 2.5 7B via Ollama (open weights, local)
                                                      │  Memory: n8n Simple Memory (per chat session)
                                                      │
                               ┌──────── MCP Client Tool (Streamable HTTP) ────────┐
                               ▼                                                   ▼
                  MCP server 1: BidBox (built)                  MCP server 2: Filesystem (borrowed)
                  5 tools over Kenya OCDS file                  reads output/ and logs/
                               │
                  read tools ─▶ sourced findings
                               │
                  HUMAN APPROVAL (named approver)
                               ▼
                  draft_committee_memo ─▶ output/*.md   (every call ─▶ logs/actions.jsonl)
```

Full write-up: [`ARCHITECTURE.md`](ARCHITECTURE.md).

### Agent architecture

A single planning agent (n8n AI Agent node), not a fixed pipeline. It decides which tools to call and in what order, checks each result, and reports `insufficient_data` / `not_found` instead of guessing. Its rules (system message) require it to cite OCIDs, report tool status verbatim, never award or rank bidders, and never call the write tool without an explicit named approval.

### MCP implementation

| Server | Built or borrowed | Transport | Role |
|---|---|---|---|
| **BidBox** (`main.py`) | **Built** — Python, official MCP SDK (`MCPServer`) | Streamable HTTP `/mcp` (stdio for the Inspector) | Procurement analysis over Kenya OCDS |
| **Filesystem** (`modelcontextprotocol/servers`) | **Borrowed** — official reference server | stdio, bridged to HTTP | Read-only access to `output/` (memos) and `logs/` (audit log) |

Why borrow the Filesystem server: it already has well-tested path sandboxing and file handling that we should not reimplement in five days.

The HTTP server keeps DNS-rebinding protection with an explicit host allowlist (localhost and the Docker host name only). Resources and prompts: none yet; we expose functionality as tools only.

### MCP tools (our server)

| Tool | Type | What it does |
|---|---|---|
| `dataset_summary` | read | Files loaded and data-quality counts |
| `search_awards` | read | Past awards by keyword / buyer; every row carries its OCID |
| `price_benchmark` | read | Robust median and quartiles; refuses with < 5 samples |
| `flag_price_outliers` | analyse | Robust z-score on log prices; every flag cites the comparison set |
| `draft_committee_memo` | **write (irreversible)** | Files a sourced memo to `output/`. Refuses without a named approver or with any source not in the dataset |

## Human-in-the-loop workflow

1. The agent investigates and presents sourced findings. Read-only tools need no approval.
2. To file anything, a committee member must type an explicit approval with their name (e.g. `APPROVED by Jane Wanjiru`).
3. Only then does the agent call `draft_committee_memo`, passing the approver's name. **The tool itself enforces the gate:** it refuses without a named approver, and refuses any source not found in the official dataset, so safety does not depend only on the model following its prompt.
4. The memo states that it raises questions for the committee and does not award, reject or rank any bidder.
5. Every tool call (inputs, outputs, status, timestamps) is appended to `logs/actions.jsonl`, so a reviewer can compare what the agent did with what it said.

## Technology stack

| Layer | Choice |
|---|---|
| MCP server | Python 3.10+, [MCP Python SDK](https://pypi.org/project/mcp/) |
| Borrowed MCP server | Official MCP Filesystem server |
| Orchestration | [n8n](https://n8n.io) (self-hosted) — AI Agent, Chat Trigger, Simple Memory, MCP Client Tool |
| Model | Qwen 2.5 7B (open weights) via [Ollama](https://ollama.com) |
| Data | Kenya PPRA / PPIP, OCDS JSONL bulk file |
| Packaging | Docker, Docker Compose, uv |
| Licence | MIT |

## Setup / installation

### Option A — Docker (one command)

Prerequisites: Docker Desktop, and the Kenya OCDS data file (see *Data*) in `./data/`.

```bash
docker compose up
```

| Service | What it is | URL |
|---|---|---|
| `bidbox` | Our MCP server | http://localhost:8000/mcp |
| `ollama` | Open-weights model runtime (Qwen 2.5 7B, pulled on first start) | http://localhost:11434 |
| `n8n` | Orchestration | http://localhost:5678 |

Inside Compose, n8n reaches the other services by name: Ollama Base URL `http://ollama:11434`, MCP endpoint `http://bidbox:8000/mcp`. When n8n runs alone in Docker and the others on the host, use `host.docker.internal` instead.

### Option B — run the MCP server directly

```bash
uv sync
uv run python main.py                                          # stdio, for the MCP Inspector
BIDBOX_TRANSPORT=streamable-http uv run python main.py         # HTTP on :8000 for n8n
npx @modelcontextprotocol/inspector uv run python main.py      # browse and call the tools
```

On Windows Command Prompt use `set BIDBOX_TRANSPORT=streamable-http` on its own line first.

## Usage

1. Open n8n at http://localhost:5678 and import `n8n/bidbox-workflow.json`.
2. Open the chat and ask, for example:
   - *"Check dataset quality, then tell me whether a toner award of 2,000,000 KES is a price outlier. Cite your sources."*
   - *"Show me recent awards for surgical gloves by Kenya Medical Supplies Authority."*
3. To file a memo, approve explicitly: *"APPROVED by <your full name>. File the memo."*
4. Find the memo in `output/` and the audit trail in `logs/actions.jsonl`.

## Data

Kenya Public Procurement Regulatory Authority (PPRA), Public Procurement Information Portal (PPIP), in OCDS: https://data.open-contracting.org/en/publication/147

Download a year in **JSONL** format (e.g. `2025.jsonl.gz`) into `./data/`. The server reads `.jsonl` and `.jsonl.gz` directly and runs fully offline.

**Which half we built on:** PPIP publishes tenders and awards, *not bid documents*. BidBox works on **award history** (prices, suppliers, buyers). It does not evaluate bids.

| Measure (2025 file) | Count |
|---|---|
| Contracting processes | 33,258 |
| Processes with **no award attached** | 23,696 (71%) |
| Award rows available for benchmarking | 11,608 |
| Awards with no value | 73 |
| Awards with no supplier | 54 |
| Missing buyer names | 0 |

We do not clean the data; the server counts and reports every problem (`dataset_summary`) so findings can be read in context.

## Limitations (honest status)

- **Comparison sets can be too mixed.** Keyword matching mixes one-off RFQs with multi-year frameworks; a 10× fuel price was *not* flagged (see [`EVALS.md`](EVALS.md)).
- **Framework agreements** with many awards under one OCID are counted as separate samples.
- **The 7B model can misreport tool results.** In one run it called the right tool but told the user the data was "insufficient"; the action log exposed this.
- **Award history only.** No bid documents are published, so BidBox cannot evaluate bids themselves.
- **Kenya only** so far.
- **Work in progress at submission:** the exported n8n workflow (`n8n/bidbox-workflow.json`) and the borrowed Filesystem server connection are being finalised; check the commit history for their status.

## Future improvements

1. One value per OCID before benchmarking; filter comparison sets by procurement method and category; refuse when dispersion is too wide.
2. Match on item classification codes (e.g. UNSPSC) where publishers provide them, instead of title keywords.
3. Extend to the other African OCDS publishers (Rwanda, Tanzania, Nigeria, South Africa, Liberia, Ghana, Zambia, Uganda).
4. Expose the dataset summary and benchmarks as MCP **resources**, not just tools.
5. Run evaluations repeatedly to measure run-to-run variation, and compare open-weights models.
6. Add an inclusion lens (AGPO reserved-procurement quotas, local vs outside suppliers).

## Licence

MIT — see [`LICENSE`](LICENSE). Data: PPRA Kenya via the Open Contracting Data Registry.
