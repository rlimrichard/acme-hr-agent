# Acme Corp HR Agent

An agentic AI system that answers employee HR questions by reasoning over 20 company policy documents. Built for Quantic MSAIE — AI Engineering Techniques and Architectures.

**Architecture:** Employee chat UI → FastAPI `/chat` → Agent orchestrator → MCP server (7 tools) → ChromaDB RAG + employee JSON data → LLM

---

## Repository Structure

```
acme-hr-agent/
├── src/
│   ├── ingest.py          # Policy ingestion pipeline (chunk → embed → store)
│   └── retrieval.py       # RAG retrieval and prompt construction
├── data/
│   ├── policies/          # 20 Markdown HR policy documents
│   └── employees.json     # Mock employee profiles (5 employees)
├── project_plan/
│   ├── PROJECT_PLAN.md    # Per-engineer task breakdown
│   ├── mcp_tools_schema.json  # Day 0 MCP tool contracts
│   └── api_contract.json  # Day 0 API contracts
├── requirements.txt
└── .env.example
```

> **Not in the repo (built at runtime):** `chroma_db/` — the ChromaDB vector index is rebuilt during setup and on every deployment.

---

## Prerequisites

- Python 3.10+
- Git

---

## Local Setup

### 1. Clone the repo

```bash
git clone https://github.com/rlimrichard/acme-hr-agent.git
cd acme-hr-agent
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> The first install downloads PyTorch and the `all-MiniLM-L6-v2` embedding model (~90 MB). Subsequent runs use the cached model.

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...          # LLM provider key
MCP_SERVER_URL=http://localhost:8000  # MCP server (use stub for local dev)
```

**Never commit `.env`.** It is already in `.gitignore`.

---

## Build the RAG Index

Run the ingestion pipeline to chunk the 20 policy documents, embed them, and write `chroma_db/` locally:

```bash
python src/ingest.py
```

Expected output:
```
HR Policy RAG Ingestion Pipeline
Scanning: data/policies
  [POL-AIU-017] ai_acceptable_use_policy.md: 28 sections → 39 chunks
  ...
Total chunks generated: 769
Embedding 769 chunks …
Inserted 769 chunks into collection 'hr_policies'.
Ingestion complete.
```

This takes ~30 seconds on the first run (model load + encoding). Re-running is idempotent — it drops and recreates the collection.

---

## Local Run

### Test retrieval directly

```bash
python src/retrieval.py "How many PTO days do I carry over after 5 years?"
```

This prints the top-5 retrieved chunks and a preview of the LLM system prompt with guardrails.

### Start the web app

```bash
uvicorn app.main:app --reload --port 8080
```

> `app/` is built by Engineer 2. Once available, this command starts the full agent + web UI.

Health check:
```bash
curl http://localhost:8080/health
```

Expected response:
```json
{ "status": "ok", "mcp_connected": true, "chroma_loaded": true, "doc_count": 769 }
```

---

## Demo Tasks

Two reproducible agentic workflows for grading. Run them via the chat UI or the curl commands below.

### Demo 1 — PTO Request Guidance

**Query:** "I'm EMP-002. Can I take 5 days off starting next Monday and submit a request?"

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Can I take 5 days off starting next Monday and submit a request?", "employee_id": "EMP-002"}'
```

**Expected tool sequence:**
1. `lookup_employee_profile` (EMP-002)
2. `check_pto_balance` (EMP-002)
3. `search_policy_documents` (query: PTO request approval process)
4. `create_mock_hr_ticket` (after user confirmation)

### Demo 2 — Expense Compliance Check

**Query:** "I'm EMP-001 (fully remote). Can I expense a $300 home office chair?"

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Can I expense a $300 home office chair?", "employee_id": "EMP-001"}'
```

**Expected tool sequence:**
1. `lookup_employee_profile` (EMP-001 — confirms fully remote)
2. `check_policy_compliance` (action: expense $300 home office chair, context: fully remote)
3. `search_policy_documents` (filtered to POL-EXP-001 and POL-RW-001)

---

## Deployment

The app is deployed on Render (free tier). A single service runs the web app, agent, MCP server, and ChromaDB.

**Live URL:** *(added to `deployed.md` once deployed)*

**Build command (Render):**
```bash
pip install -r requirements.txt && python src/ingest.py
```

**Start command (Render):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

All secrets are set as Render environment variables — never in code. Cold-start behavior is documented in [`deployed.md`](deployed.md).

---

## CI/CD

GitHub Actions runs on every push and pull request to `main`.

**Pipeline:** install → import check → pytest → deploy (only if all tests pass)

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

Required tests:
- `tests/test_app_startup.py` — `GET /health` returns 200 with `status: ok`
- `tests/test_mcp_tools.py` — MCP tool discovery returns ≥5 tools; `check_pto_balance` matches output schema

---

## Evaluation

Run the full evaluation suite against the live `/chat` endpoint:

```bash
python evaluation/eval_runner.py --endpoint http://localhost:8080/chat
```

This runs 25 questions and writes results to `evaluation/results.csv`.

**Question set breakdown:**

| Category | Count |
|---|---|
| Straightforward policy Q&A | 8 |
| Multi-document questions | 5 |
| Tool-requiring agentic tasks | 6 |
| Ambiguous requests | 3 |
| Out-of-scope requests | 3 |

**Metrics reported:** groundedness, citation accuracy, tool selection accuracy, workflow completion rate, latency p50/p95, ablation study (k=3 vs k=5 vs k=8).

Full results are in [`design-and-evaluation.md`](design-and-evaluation.md).

---

## Policy Documents

20 synthetic HR policy documents covering:

| Doc ID | Title |
|---|---|
| POL-RW-001 | Remote Work Policy |
| POL-PTO-002 | PTO Policy |
| POL-EXP-001 | Expense Reimbursement Policy |
| POL-HOL-003 | Company Holidays Policy |
| POL-SEC-004 | Data Security Policy |
| POL-BEN-005 | Employee Benefits Policy |
| POL-ONB-006 | Onboarding Policy |
| POL-EQP-007 | Equipment & Asset Management Policy |
| POL-LOA-008 | Leave of Absence Policy |
| POL-WPC-009 | Workplace Conduct Policy |
| POL-PFM-010 | Performance Management Policy |
| POL-OFB-011 | Offboarding Policy |
| POL-CMP-012 | Compensation Policy |
| POL-LND-013 | Learning & Development Policy |
| POL-DEI-014 | DEI Policy |
| POL-HSF-015 | Health & Safety Policy |
| POL-REC-016 | Recruitment & Hiring Policy |
| POL-AIU-017 | AI Acceptable Use Policy |
| POL-PRV-018 | Employee Privacy Policy |
| POL-VND-019 | Vendor Management Policy |

All documents are synthetic and do not contain real personal information.

---

## Team

Built by a team of 3 engineers for the Quantic MSAIE program.

- **Engineer 1 — Knowledge Layer:** RAG pipeline, policy corpus, ChromaDB, MCP tools
- **Engineer 2 — Reasoning Layer:** Agent orchestrator, MCP server, web application
- **Engineer 3 — Quality Layer:** Deployment, CI/CD, evaluation, documentation
