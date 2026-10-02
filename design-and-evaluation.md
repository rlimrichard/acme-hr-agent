# Design and evaluation

This document describes the current implementation. The app runs at
https://hrapp.elcaro.io on an always-on Oracle Cloud Infrastructure VPS.
See [README.md](README.md) for setup and authenticated demo commands and
[deployed.md](deployed.md) for the production layout.

## Architecture

```text
Employee browser or authenticated API client
  → FastAPI /chat (signed employee session)
  → HRAgent: LLM intent classification, deterministic fallback and narrow routing safeguards
  → MCP SDK client over localhost Streamable HTTP /mcp
  → MCP server (8 tools)
      ├─ Chroma policy index → retrieved chunks, metadata and snippets
      ├─ synthetic employee JSON → profile, PTO balance and benefits
      └─ append-only demo ticket store → HR or manager review queue
  → OpenRouter LLM for grounded response synthesis, with local fallback
  → answer, citations, snippets, tool trace and escalation status

Admin-only audit logs record the routing and synthesis prompts, MCP calls and
results, retrieved evidence, and the answer-confidence diagnostic. Employee
responses do not expose those prompts or a hidden chain of thought.
```

The deployment uses one OCI compute instance. FastAPI starts a separate MCP
process on `127.0.0.1:8001`; the SDK client connects to `/mcp`. The official
MCP server implements Streamable HTTP `tools/list` and `tools/call`. The
legacy REST `/tools` and `/tools/{name}` routes remain for diagnostics; the
agent does not use them. The MCP server is bound only to localhost, not
published through nginx. No paid database is required: Chroma and the
synthetic JSON/JSONL data live on disk. The Chroma index is persisted across
code deployments and must be rebuilt after policy-document changes.

## Design decisions

| Concern | Current choice and reason |
|---|---|
| Orchestration | Manual `HRAgent` state machine keeps tool order, confirmation gates, and audit steps inspectable. The LLM classifies intent first; a deterministic fallback handles provider failure. Narrow safeguards preserve multi-policy and out-of-scope intent when a single-label classifier misroutes a question. |
| Policy corpus | 20 synthetic documents in Markdown, HTML, TXT, and PDF. Heading-aware splitting where structure exists, with 512-character chunks and 64-character overlap. |
| Embeddings and store | Local `all-MiniLM-L6-v2` embeddings and persistent Chroma avoid a paid vector service. Metadata includes document ID/title, section, and snippet. |
| Retrieval | Default `top_k=5`, with optional document filtering and exact section-name preference. `/chat` accepts `top_k` from 1–20 for a real retrieval comparison. |
| MCP | Eight typed tools are registered with the official MCP Python SDK. See [project_plan/mcp_tools_schema.json](project_plan/mcp_tools_schema.json) for the documented argument and result contracts. |
| Safety | Tickets require a `confirmed=true` chat request and an eligible request intent; informational remote-work questions do not offer tickets. Draft emails are never sent and are not generated for vague PTO questions. Missing employee records and insufficient evidence trigger review or a guarded fallback. |
| Authentication | Synthetic employee sessions control chat and ticket access. HR reviews non-PTO tickets; a recorded direct manager reviews PTO tickets. This is a demo, not a production identity system. |

The eight tools are `search_policy_documents`, `get_policy_section`,
`lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`,
`create_mock_hr_ticket`, `draft_hr_email`, and `check_policy_compliance`.
The agent client discovers tools with MCP `tools/list` for health checks and
invokes them with MCP `tools/call`. The expense workflow now uses this same
client rather than calling tool functions directly. Results are returned as
structured content and included in the operational trace.

The remote-work workflow distinguishes a proposed change of work location
from an informational policy question and retrieves the named eligibility
section so its citation cannot drift to an unrelated travel section. Combined
questions retrieve named sections from each governing document, such as
remote-work and expense rules
for an overseas internet question. The no-index lexical fallback parses all
four policy formats, but production uses the persisted Chroma index. A
concise evidence-bounded fallback is used when the model is unavailable or
misses a required topic; it does not treat the compliance heuristic's
"no explicit prohibitions" message as approval.

Routing and answer-generation model calls each have a 12-second deadline and
no automatic retry. An upstream timeout uses the deterministic route or
grounded answer fallback rather than leaving a chat request hanging. The
admin-only answer-quality review has a separate six-second deadline. These
deadlines bound provider waiting, not total request duration across tools.

## Agentic demo tasks

1. **PTO request:** Sign in as `EMP-002` and ask to submit a PTO request for
   November 2. The agent calls `lookup_employee_profile`,
   `check_pto_balance`, `search_policy_documents`, and
   `check_policy_compliance`. It asks for confirmation. Only a second request
   with `confirmed=true` calls `create_mock_hr_ticket`; the request then
   appears in that employee's manager queue.
2. **Expense assessment:** Sign in as `EMP-001` and ask whether a $1,200
   standing desk can be expensed. The agent calls
   `lookup_employee_profile`, `search_policy_documents`,
   `get_policy_section` for the expense office-supplies rule,
   `get_policy_section` for the remote ergonomics stipend, and
   `check_policy_compliance`, then synthesizes a cited answer. This is
   read-only; it does not create a ticket or promise full reimbursement.

## Evaluation method

`evaluation/questions.json` contains 25 cases: eight straightforward policy
questions, five multi-document questions, seven agentic tasks, three ambiguous
requests, and two out-of-scope requests. Each case has expected tools,
citations, escalation, and key concepts. Human-authored short reference
answers are in `evaluation/gold_answers.json`. They are review references,
not string-exact answer targets.

Run with `PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py
--endpoint http://localhost:8080`. The runner authenticates each synthetic
employee, then measures the chat request separately from login. By default
it changes confirmed test cases to `confirmed=false` to avoid writing test
tickets to a live queue. `--allow-write-actions` is for disposable data only.

The runner records per-case and aggregate:

- Keyword match against the annotated concepts, expected-tool recall, and
  expected-document citation recall (continuity with the original evaluation).
- Tool-selection F1, which penalizes both missing and extra calls; workflow
  completion, which requires the expected tools and a non-error answer;
  escalation and ambiguous-request clarification accuracy; and action safety.
- Citation accuracy as the fraction of cited document/section pairs present
  in returned tool evidence. This checks attribution, not whether a natural-
  language claim semantically follows from the cited text.
- A **lexical groundedness proxy**: overlap between answer content words and
  retrieved policy or structured tool evidence. This is not an entailment or
  factual-correctness score. Human review of the full answers, gold answers,
  and cited excerpts remains needed for substantive answer quality.
- Warm-request latency p50 and p95 across all 25 cases, plus a fixed 15-case
  representative subset reported by `evaluation/summarize_results.py`. The
  subset spans five direct policy, four multi-document, four agentic, one
  ambiguous, and one out-of-scope case (IDs are fixed in that script before
  measuring). Authentication is excluded. The OCI VPS does not spin down;
  upstream LLM latency can still vary.

`--top-k` now changes the actual policy-search parameter in `/chat`. Run
`--top-k 3`, `5`, and `8` into separate CSV files to compare retrieval depth.
The compliance tool's internal retrieval remains fixed at five, so this
ablation isolates the primary policy-search evidence rather than every
retrieval in the system. Keep model, corpus, and question set constant when
comparing runs.

The composite pass rule requires matching escalation, at least half of the
expected concepts and citations, safe action behavior, tool-selection F1 of
at least 0.6, evidence-backed citation accuracy of at least 0.8, successful
clarification where needed, and workflow completion. An unconfirmed case
that originally requested a write action must offer confirmation without
creating a ticket. This is a diagnostic rubric, not a substitute for human
review of answer correctness.

The checked-in `evaluation/results.csv` and older numbers in Git history
predate authenticated evaluation and real `top_k` support. They are historical
artifacts, not current performance claims.

### Live evaluation — October 2, 2026

These runs used the same deployed application commit (`e7f3062`), question
set, policy index, and `google/gemini-2.5-flash-lite` OpenRouter model at
`https://hrapp.elcaro.io`. Each run authenticated the synthetic employee and
sent `confirmed=false`, so it created no test tickets. The per-case answers
and metrics are in `evaluation/results-2026-10-02-k3.csv`,
`evaluation/results-2026-10-02-k5.csv`, and
`evaluation/results-2026-10-02-k8.csv`.

| Primary retrieval top-k | Composite pass | Tool F1 / citation accuracy / action safety | Lexical groundedness proxy | All-25 request p50 / p95 | Fixed-15 request p50 / p95 |
|---|---:|---:|---:|---:|---:|
| 3 | 25/25 | 100% / 100% / 100% | 51.6% | 1,828 / 2,281 ms | 1,868 / 2,936 ms |
| 5 | 25/25 | 100% / 100% / 100% | 58.6% | 1,804 / 3,394 ms | 1,858 / 3,558 ms |
| 8 | 25/25 | 100% / 100% / 100% | 63.8% | 1,962 / 2,572 ms | 1,968 / 3,486 ms |

The fixed-15 sample IDs are listed by `evaluation/summarize_results.py`.
Login is excluded from latency. A single sweep is not enough to attribute
latency differences to top-k rather than provider variability. The higher
lexical-overlap score at k=8 is **not** evidence of greater factual accuracy.
All three runs also scored 100% for escalation, clarification, and workflow
completion under the annotated rubric. In a spot check of the full k=5
answers, the mouse used the company-provided equipment route, the $1,200 desk
answer called out the $500 stipend shortfall, the combined desk/supplies
answer separated the two allowances, and vague leave prompted for details.
This is targeted human review, not an exhaustive policy-entailment study.

The 75 corresponding audit entries recorded 57 LLM-selected routes, nine
mixed-policy safeguards, six out-of-scope safeguards, and three direct-help
routes. None recorded the provider-failure fallback as its route. Sixty
answers received an LLM audit quality score; that score is diagnostic, not a
calibrated probability of correctness. The model is a paid service; OpenRouter
[lists its current token pricing](https://openrouter.ai/google/gemini-2.5-flash-lite/pricing),
which should be checked before a larger evaluation run.

## Known limitations

This is a synthetic HR demo. A shared demo password, local ticket store, and
local policy index are not a production HR integration. Retrieval may miss a
relevant cross-policy section, and the deterministic compliance heuristic is
not an authoritative approval decision. The agent must not promise approval
or reimbursement solely because a tool returns `compliant=true`. The lexical
groundedness proxy cannot replace human review or a separately validated
semantic judge.
