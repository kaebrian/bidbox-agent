# Architecture

```
Committee member (chat)
        │
        ▼
n8n  ── Chat Trigger ──▶ AI Agent (open-source orchestration)
                           │  model: Qwen 2.5 7B via Ollama (open weights, runs locally)
                           │
             ┌─────────────┴──────────────┐
             ▼                            ▼
   BidBox MCP server (BUILT)      Borrowed MCP server (NOT ours)
   Python, official MCP SDK       see "Borrowed" below
   streamable HTTP :8000
             │
             ▼
   Kenya PPRA OCDS file (local, offline)
             │
   read tools ─▶ findings with OCIDs
             │
   HUMAN APPROVAL in n8n (named approver)
             │
             ▼
   draft_committee_memo ─▶ output/*.md   (irreversible, gated)
   every call ─▶ logs/actions.jsonl
```

## Agent shape

One planning agent with tools, not a fixed pipeline. It decides which tools to call and in what order. A typical run: `dataset_summary` → `search_awards` → `price_benchmark` → `flag_price_outliers` → (human approves) → `draft_committee_memo`. When a tool returns `insufficient_data` or `not_found`, the agent reports that instead of guessing.

## Built versus borrowed

**Built — BidBox MCP server.** Five tools around one job: is this price defensible against Kenya's own award history? We wrote it because no existing server reads OCDS award history, computes robust price benchmarks, or enforces sourcing and approval on its write action.

**Borrowed — TODO: name the server.** One community/official MCP server we did not write, with one line on why it beats writing it ourselves.

## Design choices

- **Robust statistics on log prices** (median and MAD). Procurement values are heavily skewed; a mean and standard deviation would be dominated by a few huge frameworks.
- **Refuse rather than guess.** Fewer than 5 comparable awards means no benchmark and no flag.
- **The write tool enforces its own rules** (named approver, every source must exist in the dataset), so safety does not depend only on the model following its prompt.
- **Data sovereignty.** Data and model both run locally; nothing is sent to an external API.
- **Security.** The HTTP server keeps DNS-rebinding protection with an explicit host allowlist (localhost and the Docker host name only).
