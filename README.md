# BidBox — value-for-money checks on Kenyan public tenders

An agentic AI that helps a tender evaluation committee check prices against Kenya's own procurement history. It searches past awards, builds a price benchmark, flags outliers, and drafts a **sourced** memo for the committee. It never awards, rejects or ranks a bidder: **the agent recommends, the committee decides.**

Built for the **African Agentic AI Design Challenge — Governance track (The Bid Box Challenge), theme: Value for money.**

## Run it (one command)

Prerequisites: Docker Desktop, and the Kenya OCDS data file (see *Data* below) placed in `./data/`.

```bash
docker compose up
```

This starts three services:

| Service | What it is | URL |
|---|---|---|
| `bidbox` | Our MCP server (Python, official MCP SDK) | http://localhost:8000/mcp |
| `ollama` | Open-weights model runtime (Qwen 2.5 7B, pulled on first start) | http://localhost:11434 |
| `n8n` | Open-source orchestration (AI Agent + human approval) | http://localhost:5678 |

Inside Compose, n8n reaches the other services by name: Ollama Base URL `http://ollama:11434`, MCP endpoint `http://bidbox:8000/mcp`. (When n8n runs alone in Docker and the others on the host, use `host.docker.internal` instead.)

Then in n8n: import `n8n/bidbox-workflow.json`, open the chat, and ask e.g. *"Is a toner award of 2,000,000 KES a price outlier?"*

### Run the MCP server on its own (no Docker)

```bash
uv sync
uv run python main.py                                          # stdio, for the MCP Inspector
BIDBOX_TRANSPORT=streamable-http uv run python main.py         # HTTP on :8000 for n8n
npx @modelcontextprotocol/inspector uv run python main.py      # browse the tools
```

## Data

Kenya Public Procurement Regulatory Authority (PPRA), Public Procurement Information Portal (PPIP), published in the Open Contracting Data Standard (OCDS):
https://data.open-contracting.org/en/publication/147

Download a year in **JSONL** format (e.g. `2025.jsonl.gz`) into `./data/`. The server reads `.jsonl` and `.jsonl.gz` directly and runs fully offline — procurement data never leaves the machine.

**Which half we built on:** PPIP publishes tenders and awards, *not bid documents*. BidBox works on **award history** (prices, suppliers, buyers). It does not evaluate bids.

### Data limitations we found (2025 file)

| Measure | Count |
|---|---|
| Contracting processes | 33,258 |
| Processes with **no award attached** | 23,696 (71%) |
| Award rows available for benchmarking | 11,608 |
| Awards with no value | 73 |
| Awards with no supplier | 54 |
| Missing buyer names | 0 |

We do not clean the data. The server counts and reports every problem (`dataset_summary`) so each finding can be read in context.

## The MCP tools (our server)

| Tool | Type | What it does |
|---|---|---|
| `dataset_summary` | read | Files loaded and data-quality counts |
| `search_awards` | read | Past awards by keyword / buyer; every row carries its OCID |
| `price_benchmark` | read | Robust median and quartiles; refuses with < 5 samples |
| `flag_price_outliers` | analyse | Robust z-score on log prices; every flag cites the comparison set |
| `draft_committee_memo` | **write (irreversible)** | Files a sourced memo to `output/`. Refuses without a named approver or with any source not in the dataset |

## Human in the loop and logging

- **Approval gate:** `draft_committee_memo` is the only action that changes anything. It runs only after a named person approves in n8n; the approver's name is written into the memo and the log.
- **Action log:** every tool call is appended to `logs/actions.jsonl` with inputs, output, status and timestamps.
- **Sourcing:** every finding cites an OCID from the official dataset. The memo tool rejects sources it cannot find in the data.

## What is unfinished (honest status)

- Keyword matching mixes unlike contracts (one-off RFQs with multi-year frameworks). See `EVALS.md`.
- Framework agreements with many awards under one OCID are counted as separate samples.
- The 7B open-weights model sometimes misreports tool results; see `EVALS.md`.
- Only Kenya is wired up, although the OCDS schema is shared by eight other African publishers.

## Licence

MIT — see `LICENSE`. Data: PPRA Kenya via the Open Contracting Data Registry.
