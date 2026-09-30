# Design and Evaluation — Acme Corp HR Agentic AI System

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Browser / API Client                │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP
                        ▼
┌─────────────────────────────────────────────────────┐
│            FastAPI Web Application                   │
│         POST /chat    GET /health                    │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│              Agent Orchestrator                      │
│  1. Parse intent                                     │
│  2. Decide: RAG-only vs tool call(s)                 │
│  3. Call MCP tools, accumulate results               │
│  4. Synthesize final response with citations         │
└──────────┬──────────────────────────┬───────────────┘
           │ REST HTTP (localhost)    │ API
           ▼                          ▼
┌─────────────────────┐    ┌──────────────────────────┐
│    MCP Server        │    │     LLM Provider          │
│  localhost:8001      │    │  (Claude / OpenRouter)    │
│                      │    └──────────────────────────┘
│  8 tools exposed     │
│  ┌────────────────┐  │
│  │ RAG tools (2)  │──┼──► ChromaDB (local, persistent)
│  │                │  │    20 policy docs, 638 chunks
│  ├────────────────┤  │
│  │ Data tools (4) │──┼──► data/employees.json
│  │                │  │    (mock employee, PTO, benefits)
│  ├────────────────┤  │
│  │ Write tool (1) │──┼──► In-memory ticket store
│  │ (mock, gated)  │  │    (confirmation required)
│  └────────────────┘  │
└─────────────────────┘
```

All components run in a single deployed service on Render/Railway to stay within free-tier limits. The MCP server runs as a subprocess on `localhost:8001`; the FastAPI app and agent run on `$PORT`. Communication between the agent and MCP server uses localhost HTTP, eliminating network latency in single-service deployments.

---

## 2. Policy Corpus

**20 policy documents** covering: PTO, company holidays, remote work, expenses, data security, employee benefits, onboarding, equipment, leave of absence, workplace conduct, performance management, offboarding, compensation, learning & development, DEI, health & safety, recruitment, AI acceptable use, employee privacy, and vendor management.

**Multi-format corpus** (satisfies ≥2 format requirement):

| Format | Documents | Notes |
|--------|-----------|-------|
| `.md`  | remote_work, pto, data_security, employee_benefits, workplace_conduct | Native markdown, heading-aware parsing |
| `.html`| expense_reimbursement, onboarding, company_holidays, leave_of_absence, offboarding | Converted from md; h1/h2/h3 tags reconstructed to `#` markers |
| `.txt` | compensation, dei, health_safety, recruitment_hiring, vendor_management | Plain text; markdown symbols stripped |
| `.pdf` | ai_acceptable_use, employee_privacy, equipment_asset_management, learning_development, performance_management | Generated via reportlab; text extracted with pypdf |

---

## 3. RAG Design

### 3.1 Ingestion pipeline (`src/rag/ingest.py`)

**Format parsing:** Each format has a dedicated parser (`_parse_md`, `_parse_html`, `_parse_txt`, `_parse_pdf`) that normalises its output to markdown-like text before chunking:

| Format | Parser | Heading preservation |
|--------|--------|----------------------|
| `.md`  | Read directly | Full H1/H2/H3 via `#` markers |
| `.html`| BeautifulSoup — `<h1/h2/h3>` tags reconstructed as `# / ## / ###` | Full heading structure |
| `.txt` | Read directly (markdown symbols stripped at conversion time) | None — flat text |
| `.pdf` | pypdf page-by-page text extraction | None — flat text |

**Chunking strategy — two-pass heading-aware + recursive character split:**

1. **Heading-aware split:** Walk all H1/H2/H3 headings and collect the body text beneath each, building a breadcrumb path (e.g. `Remote Work Policy > 3. Approval Process > 3.1 Manager Sign-off`). This preserves semantic section boundaries and produces focused, citable chunks for `.md` and `.html` files.
2. **Recursive character split** (CHUNK_SIZE=512 chars, CHUNK_OVERLAP=64): Each heading section is further split if it exceeds 512 characters, trying separators `["\n\n", "\n", ". ", " "]` in order. Overlap of 64 characters is applied between consecutive chunks to prevent context loss at boundaries. For `.txt` and `.pdf` files (which have no heading structure), the entire document is treated as one flat section and split entirely by this step.

**Document title fallback:** When no H1 heading is found (PDF and TXT files), `doc_title` is derived from the filename stem via `_title_from_stem()` (e.g. `performance_management_policy` → `"Performance Management Policy"`). This ensures every chunk carries a human-readable source title for citations.

**Justification:** Heading-aware splitting retains policy section semantics and produces highly focused chunks for structured formats. The recursive character split with overlap handles long tables and lists without hard cuts that lose context. The flat-section fallback for PDF/TXT is an acceptable trade-off — retrieval quality is validated to be equivalent across formats (see Section 8.5 diagnostic results).

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` — free, runs locally, no API key required, 384-dimensional dense embeddings.

**Vector store:** ChromaDB (persistent local client, cosine similarity space). No external service, no paid tier. The collection is rebuilt deterministically on each deployment by the build command. The current index contains **638 chunks** across 20 documents.

**Chunk metadata stored per chunk:**

| Field | Purpose |
|-------|---------|
| `doc_id` | Policy document ID (e.g. `POL-PTO-002`) for citation |
| `doc_title` | Human-readable title (from H1 for md/html; from filename stem for txt/pdf) |
| `section` | Breadcrumb heading path (md/html) or document title (txt/pdf) |
| `snippet` | First 120 characters for quick trace display |

### 3.2 Retrieval (`src/rag/retrieval.py`)

- **Top-k retrieval:** Default `k=5`; configurable per call. Optional `filter_doc_id` restricts search to a single policy document.
- **Cosine similarity:** ChromaDB's HNSW index with cosine space.
- **Context injection:** Retrieved chunks are rendered into a clearly delimited context block with per-chunk citations injected into the LLM system prompt.

### 3.3 Guardrails (6 rules in system prompt)

| # | Rule |
|---|------|
| 1 | Cite every factual claim with `[DOC-ID § Section]` |
| 2 | Refuse out-of-corpus questions with a fixed escalation message |
| 3 | Label `[OFFICIAL POLICY]` vs `[GENERAL GUIDANCE]` |
| 4 | Never hallucinate document IDs or section names not in the context |
| 5 | Acknowledge ambiguity; escalate to People Ops rather than guess |
| 6 | Never reveal another employee's PII |

---

## 4. Agentic System Design

### 4.1 Orchestrator

The agent orchestrator interprets each user message and decides between two paths:

- **RAG-only path:** Simple policy Q&A where no employee-specific data is needed. The agent calls `search_policy_documents`, injects context into the LLM prompt, and returns a cited answer.
- **Tool-call path:** Tasks requiring structured data (employee record, PTO balance, benefits) or actions (ticket creation). The orchestrator selects tools, calls them sequentially via the MCP layer, and synthesises a final response from tool outputs + retrieved policy context.

Every request produces an **operational trace** — a structured log of each step (tool selected, arguments, output, policy sources used, final answer basis) — returned in the `/chat` response under `tool_trace`.

**Failure handling:**

| Failure | Behaviour |
|---------|-----------|
| MCP tool unavailable | Return partial answer; flag tool as unavailable in trace |
| Missing employee ID | Ask the user for clarification before proceeding |
| Incomplete policy evidence | Acknowledge gap; recommend escalation to People Ops |
| Ambiguous request | Ask one clarifying question before taking action |

**Safety gate:** The `create_mock_hr_ticket` tool and any draft actions require explicit user confirmation (`"confirm": true` in the `/chat` request body) before the agent calls them.

### 4.2 Two Demo Agentic Tasks

#### Demo Task 1 — PTO Request Guidance

> *"Can I take 5 days off starting next Monday?"*

Expected tool-call sequence:

1. `lookup_employee_profile(employee_id)` → confirms role, hire date, manager
2. `check_pto_balance(employee_id)` → confirms available days
3. `search_policy_documents("PTO request approval blackout periods")` → retrieves approval requirements, blackout windows
4. `check_policy_compliance(employee_id, "take 5 days PTO starting next Monday")` → compliance verdict with citations
5. `draft_hr_email(employee_id, "pto_request", ...)` → personalised manager approval request drafted
6. *(if user confirms)* `create_mock_hr_ticket(employee_id, type="pto_request", ...)` → mock ticket created

**Expected final response:** Grounded answer citing `[POL-PTO-002 § 3.1 Requesting Time Off]` with the employee's balance, approval instructions, the drafted email, and ticket ID.

---

#### Demo Task 2 — Expense Compliance Check

> *"Can I expense a $1,200 standing desk for my home office?"*

Expected tool-call sequence:

1. `lookup_employee_profile(employee_id)` → confirms employment type (full-time vs contractor), remote status
2. `search_policy_documents("home office equipment reimbursement limit")` → retrieves expense policy
3. `get_policy_section("POL-EXP-001", "Home Office Equipment")` → retrieves exact dollar limits
4. `check_policy_compliance(employee_id, "expense $1200 standing desk", "employee is fully remote")` → compliance verdict

**Expected final response:** Grounded answer citing `[POL-EXP-001 § 4.2 Home Office Equipment]` with the approved limit, any role or remote-status conditions, and next steps.

---

## 5. MCP Server Design

**Implementation:** `src/mcp/server.py` — a plain FastAPI REST server (440 lines). No MCP Python SDK, no JSON-RPC framing; all routing is handled by FastAPI directly with three endpoints: `GET /tools` (schema discovery), `POST /tools/{name}` (tool invocation), and `GET /health`.

**Transport:** REST HTTP on `localhost:8001`. Chosen over the MCP SDK's Streamable HTTP transport because it eliminates SDK dependency issues and matches exactly how the orchestrator (`MCPClient` using `httpx`) calls tools — no protocol overhead. In production the MCP server is launched as a subprocess by the FastAPI startup event.

**Run the server:**
```bash
python -m src.mcp.server
# → Starting Acme HR Tool Server on http://127.0.0.1:8001
# → INFO: Uvicorn running on http://127.0.0.1:8001
```

**Tool discovery:** The agent client calls `GET /tools` on startup to retrieve the full list of tool names and schemas. This satisfies the MCP tool-discovery requirement without hard-coding tool names in the orchestrator.

**8 tools implemented:**

| Tool | Data Source | Key behaviour |
|------|-------------|---------------|
| `search_policy_documents` | ChromaDB | Semantic search; `score = 1 − cosine_distance`; optional `doc_id` filter |
| `get_policy_section` | ChromaDB (filtered by `doc_id`) | Returns best-matching section chunk for a given section name query |
| `lookup_employee_profile` | `data/employees.json` | Employee record by ID; returns `found: false` if unknown |
| `check_pto_balance` | `data/employees.json` | Balance + pending requests (start/end date, days, status) |
| `lookup_benefits_status` | `data/employees.json` | Health plan, dental, vision, FSA/HSA, 401k contribution + match |
| `create_mock_hr_ticket` | In-memory dict | Generates `TKT-xxxxxxxx` ID; routes to team email by `ticket_type`; requires explicit confirmation |
| `check_policy_compliance` | RAG + `data/employees.json` | Retrieves top-5 policy chunks; runs prohibition-keyword heuristic on best match; returns `compliant: bool` + `citations` array |
| `draft_hr_email` | `data/employees.json` | Generates a personalised email draft; resolves manager from employee record; `draft_only: true` always — never sends |

**Compliance heuristic detail:** `check_policy_compliance` applies a conservative rule — `compliant: false` only when the best-matching chunk has cosine distance < 0.30 (strong semantic match) AND contains an explicit prohibition keyword (`"prohibited"`, `"must not"`, `"not permitted"`, etc.). This avoids false positives from tangentially related policy text. The agent layer synthesises the final answer from the returned citations.

**Data singletons:** `data/employees.json` is loaded once at first call and cached in a module-level dict. The ChromaDB collection and embedding model use the same lazy-singleton pattern as `retrieval.py` — no reloading across tool calls within a server session.

**Smoke tests:** `scripts/test_mcp.py` — 25 checks across 3 test suites (employee data tools, ticket creation, RAG-backed tools). Runs in CI immediately after the RAG diagnostic suite.

Full JSON schemas for all tools are defined in `project_plan/mcp_tools_schema.json`.

---

## 6. Web Application

**Framework:** FastAPI (backend) + HTML/JS chat UI (frontend).

**Endpoints:**

- `POST /chat` — receives `{query, employee_id, confirm}`, returns `{answer, citations, snippets, tool_trace}`
- `GET /health` — returns `{status, mcp_connected, chroma_loaded, doc_count}`

The chat UI displays the answer with inline citations, expandable tool-call trace panel, and a confirmation prompt when the agent proposes a write action.

---

## 7. Deployment

**Platform:** Render (free tier), single-service deployment.

- **Build command:** `pip install -r requirements.txt && python -m src.rag.ingest` — installs deps and rebuilds ChromaDB from the committed policy files.
- **Start command:** `uvicorn src.app.main:app --host 0.0.0.0 --port $PORT`
- **MCP server:** Launched as a subprocess by the FastAPI startup event on `localhost:8001`.
- **Storage:** ChromaDB persisted to local filesystem (rebuilt on each deploy); `data/employees.json` committed to repo; no paid database required.
- **Cold-start:** See `deployed.md` for measured cold-start latency.

---

## 8. Evaluation

### 8.1 Evaluation Set (25 questions)

| Category | Count | File |
|----------|-------|------|
| Straightforward policy Q&A | 8 | `evaluation/questions.json` (Q001–Q008) |
| Multi-document questions | 5 | Q009–Q013 |
| Tool-requiring agentic tasks | 7 | Q014–Q020 |
| Ambiguous requests | 3 | Q021–Q023 |
| Out-of-scope requests | 2 | Q024–Q025 |

Each question carries: `expected_escalated`, `expected_tools` (list), `expected_citation_docs` (list of policy doc IDs), `gold_keywords` (list of strings that must appear in the answer), and `confirmed` (whether the request should trigger write-action safety checks).

### 8.2 Automated Evaluation Runner

`evaluation/eval_runner.py` POSTs every question to `/chat`, measures latency, and scores five metrics automatically:

| Metric | Computation | Target |
|--------|------------|--------|
| Escalation accuracy | `response.escalated == expected_escalated` | ≥ 0.90 |
| Tool recall | Fraction of `expected_tools` present in `response.tool_trace` | ≥ 0.50 avg |
| Citation recall | Fraction of `expected_citation_docs` present in `response.citations` | ≥ 0.50 avg |
| Keyword match | Fraction of `gold_keywords` found (case-insensitive) in answer text | ≥ 0.50 avg |
| Action safety | `create_mock_hr_ticket` only called when `confirmed=True` | 1.00 |

A question is an **overall pass** when all five metrics meet their thresholds. The runner exits with code 1 if overall pass rate < 70%.

**Run against local dev:**
```bash
python evaluation/eval_runner.py --endpoint http://localhost:8000
```

**Run against the live deployment:**
```bash
python evaluation/eval_runner.py --endpoint https://acme-hr-agent.onrender.com
```

**Ablation (tag results with a top-k label for comparison):**
```bash
python evaluation/eval_runner.py --endpoint http://localhost:8000 --top-k 3
python evaluation/eval_runner.py --endpoint http://localhost:8000 --top-k 8
```

Results are written to `evaluation/results.csv` with one row per question.

### 8.3 System Metrics

Latency measured across warm queries (cold-start reported separately in `deployed.md`).

| Metric | Result |
|--------|--------|
| p50 latency (local, k=5) | 58 ms |
| p95 latency (local, k=5) | 23,394 ms (expense workflow — full LLM call) |
| Cold-start latency | N/A — OCI VPS runs always-on (no spin-down) |

### 8.4 Evaluation Results

| Metric | Result | Target | Status |
|--------|--------|--------|--------|
| Overall pass rate | 88% (22/25) | ≥ 70% | ✅ |
| Escalation accuracy | 96% | ≥ 90% | ✅ |
| Tool recall (avg) | 99% | ≥ 50% | ✅ |
| Citation recall (avg) | 94% | ≥ 50% | ✅ |
| Keyword match (avg) | 88% | ≥ 50% | ✅ |
| Action safety | 100% | 100% | ✅ |
| Latency p50 (local, k=5) | 55 ms | — | — |
| Latency p95 (local, k=5) | 2,346 ms | — | — |

**Per-category breakdown:**

| Category | Pass | Total |
|----------|------|-------|
| policy_qa | 8 | 8 |
| agentic | 6 | 7 |
| ambiguous | 3 | 3 |
| out_of_scope | 2 | 2 |
| multi_doc | 3 | 5 |

The multi_doc failures (Q009, Q011, Q012) arise because the single-workflow router picks one policy domain per request; cross-domain questions that need both expense and remote-work context only partially satisfy citation recall.

### 8.5 RAG Diagnostic Test Results

`scripts/test_rag.py` runs five automated diagnostic suites against the live ChromaDB index. Results after the current build (638 chunks):

**Coverage (21 checks — all PASS)**
- All 20 doc IDs present in the index
- Every document produces ≥5 chunks

**Metadata quality (50 checks — all PASS)**
- `doc_title` non-Unknown for all 638 chunks across all 4 formats
- Section breadcrumb present on all md and html chunks
- Snippet populated on all chunks

**Chunk text quality (3 checks — all PASS)**
- 0 empty chunks
- 0 chunks exceeding 700 characters (target: ≤512 + overlap)
- 0 chunks with detectable overlap duplication

**Retrieval quality — 10 targeted queries (all PASS, 3 WARN)**

| Query | Expected doc | Result | Best distance |
|-------|-------------|--------|---------------|
| PTO accrual | POL-PTO-002 | ✅ rank 1 | 0.234 |
| Remote work eligibility | POL-RW-001 | ✅ rank 1 | 0.493 ⚠ |
| Expense reimbursement limit | POL-EXP-001 | ✅ rank 1 | 0.487 ⚠ |
| Benefits eligibility | POL-BEN-005 | ✅ rank 1 | 0.409 |
| Workplace misconduct | POL-WPC-009 | ✅ rank 1 | 0.323 |
| Leave of absence | POL-LOA-008 | ✅ rank 1 | 0.248 |
| Data security requirements | POL-SEC-004 | ✅ rank 1 | 0.343 |
| AI tools acceptable use (PDF) | POL-AIU-017 | ✅ rank 1 | 0.368 |
| Performance review (PDF) | POL-PFM-010 | ✅ rank 2 | 0.480 ⚠ |
| Onboarding process (HTML) | POL-ONB-006 | ✅ rank 1 | 0.347 |

⚠ Distances above 0.45 indicate weaker semantic alignment for generic queries. All three affected cases still return the correct document in the top 3. Query rewriting (expanding short queries before embedding) will be used in the agent layer to improve these scores.

**Multi-document retrieval (2 checks — all PASS)**
- "Expense home office chair + remote work stipend" → correctly retrieves both POL-EXP-001 and POL-RW-001 within top 6
- "PTO rules during leave of absence" → correctly retrieves both POL-PTO-002 and POL-LOA-008 within top 6

### 8.6 Ablation Study

Three top-k configurations run locally using `evaluation/eval_runner.py --top-k <k>` (25 questions each):

| Config | k | Citation recall | Tool recall | Escalation accuracy | p50 latency |
|--------|---|----------------|-------------|---------------------|-------------|
| A (baseline) | 5 | 94% | 99% | 96% | 58 ms |
| B | 3 | 94% | 99% | 96% | 56 ms |
| C | 8 | 94% | 99% | 96% | 62 ms |

**Finding:** Citation recall and tool recall are stable across k=3/5/8 because the orchestrator uses fixed tool sequences per workflow type — retrieval k affects LLM context depth but not tool selection. Latency scales slightly with k (more chunks injected into the prompt) but the effect is within noise at p50; p95 variance is dominated by LLM response time rather than retrieval. k=5 is selected as the default since it provides full policy coverage without inflating prompt size.
