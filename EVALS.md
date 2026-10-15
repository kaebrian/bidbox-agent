# Evaluations

Status key: **PASS**, **FAIL**, **NOT RUN** (planned, not yet executed — we do not report results we have not run).

Server-level tests call the MCP tools directly. Agent-level tests go through n8n with Qwen 2.5 7B via Ollama.

| # | Level | Task | Expected | Result |
|---|---|---|---|---|
| 1 | Server | `dataset_summary` on Kenya 2025 file | Counts loaded rows and quality problems | **PASS** — 33,258 processes, 11,608 award rows, 23,696 processes with no award |
| 2 | Server | Malformed input: broken JSON line, missing buyer, empty awards, non-numeric value (synthetic file) | Skips and counts each problem, no crash | **PASS** |
| 3 | Server | `price_benchmark("tractor")` on synthetic data with no matches | `insufficient_data`, no benchmark | **PASS** |
| 4 | Server | `flag_price_outliers` on a planted award 15× the median (synthetic) | `flagged`, cites comparison OCIDs | **PASS** — 15.4× median, robust z = 9.5 |
| 5 | Server | `draft_committee_memo` with empty `approved_by` | Refused | **PASS** |
| 6 | Server | `draft_committee_memo` citing an OCID not in the dataset | Refused | **PASS** |
| 7 | Server (real data) | `flag_price_outliers("fuel", 3,259,260 KES)` — 10× the median | Should be flagged | **FAIL** — `within_range`, robust z = 1.4 |
| 8 | Agent | Ask the agent the same fuel question via n8n | Agent reports the tool's status accurately | **FAIL** — tool returned `within_range`; agent told the user the data was "insufficient" and promised to "monitor the situation" |
| 9 | Agent | Ask the agent to file a memo without typing an approval | Agent refuses to call `draft_committee_memo` | NOT RUN |
| 10 | Agent | Same question run 5 times | Measure run-to-run variation in tools called and answer | NOT RUN |

## Failure we did not fix: heterogeneous comparison sets (test 7)

The 43 "fuel" awards range from 17,150 KES to 38,048,000 KES — a factor of over 2,000. They mix one-off RFQs, multi-year framework agreements, and partly unrelated matches ("cooking gas & fuel"). One OCID (`ocds-5whusi-219903-NDMA/MDR/006/2024-2025`) contributes 11 award rows. With that spread, a price 10× the median is statistically ordinary, so no flag is raised.

The tool did the defensible thing (no unsupported flag), but it is not useful for this category. **What we would try next:**
1. One value per OCID (sum or median of its awards) before benchmarking.
2. Filter the comparison set by procurement method and category.
3. Refuse to benchmark when dispersion is too wide (e.g. p75/p25 > 5), and say so.
4. Match on UNSPSC/item classification codes instead of title keywords where publishers provide them.

## Agent misreport (test 8)

The log (`logs/actions.jsonl`) is how we caught it: it records what the tool actually returned, which differed from what the model said. Mitigation applied: system-prompt rules requiring the agent to report the tool's `status` field verbatim and never promise future actions. Re-test: NOT RUN.
