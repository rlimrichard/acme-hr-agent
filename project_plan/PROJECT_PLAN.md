# Project Plan — Acme Corp HR Agentic AI System
**Quantic MSAIE — AI Engineering Techniques and Architectures**  
**Team size:** 3 engineers | **Target score:** 5/5

---

## Day 0 — Pre-Work (All Engineers, 30-min sync)

Before any coding begins, all three engineers agree on and commit the following contracts to the repo:

| Artifact | File | Purpose |
|---|---|---|
| MCP tool schemas | `mcp/tools_schema.json` | Defines tool names, input/output JSON for all 7 tools |
| API contract | `api_contract.json` | Defines `/chat` request/response shape |
| Employee data schema | `mock_data/employees.json` | Defines field names and types for structured data |

Once committed, all three tracks are fully independent.

---

## Engineer 1 — Knowledge Layer
### RAG Pipeline · Policy Corpus · Mock Data

---

### § 1 — Environment & Reproducibility *(partial ownership)*
> *"Create a virtual environment… List dependencies in requirements.txt… Set fixed seeds where applicable… Ensure secrets are read from environment variables."*

- [ ] Initialize the repo with a Python `venv`
- [ ] Populate `requirements.txt` with all ingestion and RAG dependencies
- [ ] Set a fixed random seed in the chunking pipeline for deterministic chunk IDs
- [ ] Ensure no API keys are hardcoded — all credentials read from `.env` via `python-dotenv`

---

### § 2 — Policy Corpus Ingestion & Indexing
> *"Parse and clean policy documents, handling at least two supported source formats… Chunk documents using a justified strategy… Embed chunks using a free embedding model… Store embedded chunks in a local vector database… Persist enough metadata to support citations."*

- [ ] Author or source 5–20 policy documents covering: PTO, holidays, remote work, expenses, data security, benefits, onboarding, equipment, leave, workplace conduct
- [ ] Support **at least two file formats** (Markdown + PDF or HTML — the rubric requires this explicitly)
- [ ] Implement a justified chunking strategy:
  - Heading-aware splitting — preserves semantic sections and builds breadcrumb paths
  - Recursive character splitter with overlap — handles sections that exceed token limits
  - Heading text prepended to each chunk body for richer embeddings
- [ ] Embed using `sentence-transformers/all-MiniLM-L6-v2` (free, runs locally)
- [ ] Store in **ChromaDB** (persistent, free, no external service required)
- [ ] Attach metadata to every chunk: `doc_id`, `doc_title`, `section` (breadcrumb), `snippet`

**Mock structured data** (`mock_data/` directory):
- [ ] `employees.json` — 5+ employees with: `employee_id`, `name`, `role`, `office_location`, `remote_status`, `pto_balance_days`, `benefits_election`, `manager_id`
- [ ] Optionally: `ticket_records.json` for mock HR case history

---

### § 3 — Retrieval Augmented Generation (RAG)
> *"Implement top-k retrieval with optional filtering, query rewriting, or reranking… Generate answers that cite source document IDs, titles, or sections… Add guardrails that refuse or redirect out-of-corpus questions… Include at least one complex question requiring retrieval from multiple policy documents."*

- [ ] `retrieve_chunks(query, top_k, filter_doc_id)` — cosine similarity search against ChromaDB
- [ ] Optional query rewriting: expand short queries before embedding (e.g. "PTO carryover" → "How many unused PTO days can an employee carry over to the next year?")
- [ ] Optional reranking: re-score top-k results with a cross-encoder for precision
- [ ] Prompt template injecting retrieved context + source metadata into LLM system prompt
- [ ] **6 guardrails in the system prompt:**
  1. Cite every claim with `[DOC-ID § Section]`
  2. Refuse questions not covered by retrieved context (exact refusal phrasing)
  3. Label `[OFFICIAL POLICY]` vs `[GENERAL GUIDANCE]`
  4. Never hallucinate document IDs or section names
  5. Acknowledge ambiguity; escalate rather than guess
  6. Never reveal other employees' PII
- [ ] Demonstrate one **multi-document retrieval** example (e.g. "Can I expense my home office chair AND get the ergonomics stipend?" → requires both Expense Policy and Remote Work Policy)

**Deliverable for team integration:** a running MCP server at `localhost:8000` with all 7 tools returning responses matching the agreed schemas.

---

## Engineer 2 — Reasoning Layer
### Agent Orchestrator · MCP Server · Web Application

---

### § 4 — Agentic System Design
> *"Build an agent orchestrator that can interpret user intent, decide whether RAG alone is sufficient, select tools, call MCP-exposed tools, and synthesize final responses… Support at least two multi-step HR workflows… Implement a visible or logged trace of agent reasoning steps… Handle failures gracefully… Prevent irreversible actions."*

- [ ] Agent orchestrator loop:
  1. Parse user intent
  2. Decide: RAG-only answer OR tool call(s) required
  3. Select and call relevant MCP tools with correct arguments
  4. Synthesize final response from tool outputs + retrieved context
- [ ] **Two complete multi-step workflows:**
  - **PTO Request Guidance:** `lookup_employee_profile` → `check_pto_balance` → `search_policy_documents` (PTO policy) → check manager approval requirements → `create_mock_hr_ticket` (with user confirmation)
  - **Expense Compliance Check:** `lookup_employee_profile` → `search_policy_documents` (expense policy) → check employee role/location eligibility → return cited decision
- [ ] **Operational trace** logged per request (not hidden chain-of-thought):
  ```json
  { "step": 1, "tool": "check_pto_balance", "args": {"employee_id": "EMP-002"},
    "result": {"balance_days": 8.0}, "policy_sources": ["POL-PTO-002 § 2.1"] }
  ```
- [ ] Graceful failure handling: unavailable MCP tools, missing employee IDs, ambiguous requests → ask clarifying question
- [ ] **Confirmation gate** before any mock write action (`create_mock_hr_ticket`, `draft_hr_email`)

**Start with a stub MCP server** matching the agreed tool schemas. Swap for Eng 1's real server via `MCP_SERVER_URL` env var when ready — no code changes required.

---

### § 5 — MCP Server & Tool Integration
> *"Implement one or more MCP servers that expose tools for the agent… Expose at least five MCP tools… The agent must actually call MCP-exposed tools during execution; hard-coded direct function calls are not sufficient… Document the MCP architecture, transport choice, tool schemas, and how the agent client discovers and calls tools."*

- [ ] MCP server implementation in `mcp/server.py`
- [ ] **Transport:** localhost HTTP (Streamable HTTP) — simple, free-tier compatible, survives deployment
- [ ] **7 tools exposed:**

| Tool | Data Source | Type |
|---|---|---|
| `search_policy_documents` | ChromaDB (RAG) | Read |
| `get_policy_section` | ChromaDB filtered by doc_id + section | Read |
| `lookup_employee_profile` | `employees.json` | Read |
| `check_pto_balance` | `employees.json` | Read |
| `lookup_benefits_status` | `employees.json` | Read |
| `create_mock_hr_ticket` | In-memory / `tickets.json` | **Mock write** |
| `check_policy_compliance` | RAG + employee profile combined | Read |

- [ ] Agent calls tools via HTTP — no direct function imports across the boundary
- [ ] Tool discovery: agent calls `GET /tools` on startup to list available tools and schemas
- [ ] Document in `design-and-evaluation.md`: transport choice rationale, full tool schemas, how the agent discovers tools

---

### § 6 — Web Application
> *"The web app should include a chat interface… Provide a /chat endpoint that receives user requests and returns the final answer, citations, snippets, and a concise tool-call trace… Provide a /health endpoint… Provide a way for the grader to reproduce at least two agentic demo tasks."*

- [ ] **Framework:** FastAPI (backend) + Streamlit or plain HTML/JS (chat UI)
- [ ] `POST /chat` request/response per agreed contract:
  ```json
  // request
  { "query": "Can I take 3 days PTO next week?", "employee_id": "EMP-002" }
  // response
  { "answer": "...", "citations": [...], "snippets": [...], "tool_trace": [...] }
  ```
- [ ] `GET /health`:
  ```json
  { "status": "ok", "mcp_connected": true, "chroma_loaded": true, "doc_count": 769 }
  ```
- [ ] Chat UI displays: answer, inline citations, expandable tool-call trace panel
- [ ] Two **reproducible demo tasks** accessible via UI buttons or documented `curl` commands in `README.md`

**Start with a skeleton app** (`/health` returns 200, `/chat` returns stub). Hands off to Eng 3 for deployment on day 1. Swaps in real agent when orchestrator is complete.

---

## Engineer 3 — Quality Layer
### Deployment · CI/CD · Evaluation · Documentation

---

### § 7 — Deployment
> *"Deploy the application to Render, Railway, or an equivalent free-tier host… A single-service deployment is acceptable… The application should not require a paid database… Document expected cold-start behavior."*

- [ ] Deploy **skeleton app** to Render (free tier) on **Day 1** — establishes the live URL immediately
- [ ] Single-service deployment: web app + agent + MCP server + ChromaDB + JSON data in one process
- [ ] `render.yaml` or `railway.json` deployment config committed to repo
- [ ] All secrets (LLM API key, MCP server URL) configured as Render/Railway environment variables — never in code
- [ ] Build command: `pip install -r requirements.txt && python src/ingest.py` (rebuilds ChromaDB on deploy)
- [ ] Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] `deployed.md` — deployed URL, `/health` URL, cold-start time measured and documented

---

### § 8 — CI/CD
> *"Create a GitHub Actions workflow that runs on push or pull request… Install dependencies, run a build/start/import check… Include at least one test that verifies the app can start and at least one test or script that verifies MCP tool discovery or a simple MCP tool call… Deployment must only occur if tests pass."*

- [ ] `.github/workflows/ci.yml` — triggers on push and pull_request to `main`
- [ ] Pipeline steps:
  1. `pip install -r requirements.txt`
  2. `python -c "from src.ingest import load_and_chunk_policies"` — import check
  3. `pytest tests/` — run test suite
  4. Deploy to Render (via Render deploy hook) only if all tests pass
- [ ] **Test 1:** `tests/test_app_startup.py` — start FastAPI with TestClient, assert `GET /health` returns 200 with `status: ok`
- [ ] **Test 2:** `tests/test_mcp_tools.py` — call stub MCP server, assert `GET /tools` returns list of ≥5 tool names; call `check_pto_balance` with a known employee ID, assert response matches schema

---

### § 9 — Evaluation
> *"Provide an evaluation set of 20–30 questions or tasks… Report answer quality metrics: groundedness, citation accuracy… Report agent behavior metrics: tool selection accuracy, workflow completion rate, escalation accuracy, action-safety pass rate… Report latency p50/p95… Include at least one ablation or comparison."*

**Evaluation set (`evaluation/questions.json`) — 25 questions:**

| Category | Count | Examples |
|---|---|---|
| Straightforward policy Q&A | 8 | "How many PTO days does an employee accrue per year after 3 years of service?" |
| Multi-document questions | 5 | "Can I expense a home office chair AND claim the remote work ergonomics stipend?" |
| Tool-requiring agentic tasks | 6 | "Check if EMP-002 has enough PTO to take 5 days off next week and draft a ticket" |
| Ambiguous requests | 3 | "Can I work from abroad?" (missing duration, country, role) |
| Out-of-scope requests | 3 | "What is the capital of France?" |

- [ ] `evaluation/eval_runner.py` — runs all 25 questions against the live `/chat` endpoint
- [ ] **Answer quality metrics:** groundedness (LLM-as-judge or keyword match), citation accuracy (cited doc IDs appear in retrieved context)
- [ ] **Agent behavior metrics:** tool selection accuracy (correct tool called vs gold), workflow completion rate, action-safety pass rate (no unrequested writes)
- [ ] **Latency:** p50/p95 across 20 warm queries; separate cold-start measurement
- [ ] **Ablation study** — compare two configurations, e.g.:
  - `k=3` vs `k=5` vs `k=8` on citation accuracy and groundedness
  - Chunk size 512 chars vs 900 chars on retrieval precision

---

### § 10 — Design Documentation
> *"Briefly justify design choices… Include an architecture diagram… Describe the two required agentic demo tasks and the expected sequence of MCP tool calls for each task."*

- [ ] **`README.md`** — repo overview, setup, local run (`python src/ingest.py` + `uvicorn`), deployment instructions, two demo task curl commands
- [ ] **`design-and-evaluation.md`** — architecture diagram + justification of: agent framework, MCP transport, tool schemas, embedding model, chunking strategy, retrieval k, guardrails, deployment, evaluation results table
- [ ] **`ai-tooling.md`** — document Claude Code usage: what was generated, what was reviewed/corrected, what worked well, what needed manual intervention
- [ ] **`deployed.md`** — live URL, `/health` URL, cold-start latency, notes
- [ ] **`evaluation/`** — questions JSON, gold answers, eval runner script, results CSV

---

## Parallel Work Timeline

```
Day 0     All:  30-min sync → commit tool schemas + API contract + data schema
          ─────────────────────────────────────────────────────────────────────
Day 1+    Eng 1: corpus authoring, chunking, ChromaDB, RAG retrieval, MCP tools
          Eng 2: stub MCP server → agent orchestrator → web app (no waiting)
          Eng 3: skeleton deploy → CI/CD green → eval questions → docs skeleton

Integration (no fixed date — swap env vars when each component is ready):
          Eng 2 sets MCP_SERVER_URL → Eng 1's real server  (1 env var)
          Eng 3 points deployment  → Eng 2's real app      (1 env var)
          Eng 3 runs eval suite    → fills in real metrics

Final     All:  integration test → demo rehearsal → video recording
```

---

## Grading Checklist

| Requirement | Owner | Status |
|---|---|---|
| venv + requirements.txt + env vars | Eng 1 | — |
| ≥2 file formats parsed | Eng 1 | — |
| Heading-aware chunking with metadata | Eng 1 | — |
| Local vector store (ChromaDB) | Eng 1 | — |
| Top-k retrieval + guardrails | Eng 1 | — |
| Multi-document retrieval example | Eng 1 | — |
| Agent orchestrator with reasoning trace | Eng 2 | — |
| 2 multi-step agentic workflows | Eng 2 | — |
| MCP server with ≥5 tools via HTTP | Eng 2 | — |
| Agent calls tools through MCP layer | Eng 2 | — |
| /chat and /health endpoints | Eng 2 | — |
| Chat UI with citation + trace display | Eng 2 | — |
| Deployed to Render/Railway | Eng 3 | — |
| GitHub Actions CI/CD + deploy gate | Eng 3 | — |
| 25-question eval set with gold answers | Eng 3 | — |
| Groundedness + citation accuracy reported | Eng 3 | — |
| Tool selection + workflow completion reported | Eng 3 | — |
| Latency p50/p95 reported | Eng 3 | — |
| Ablation study | Eng 3 | — |
| README.md | Eng 3 | — |
| design-and-evaluation.md | Eng 3 | — |
| ai-tooling.md | Eng 3 | — |
| deployed.md | Eng 3 | — |
| Repo shared with quantic-grader | Any | — |
| Demo video (7–10 min, all 3 on camera with ID) | All | — |
