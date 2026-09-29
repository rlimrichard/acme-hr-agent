# Acme Corp HR Agent

An agentic AI system that answers employee HR questions by reasoning over 20 company policy documents. Built for Quantic MSAIE — AI Engineering Techniques and Architectures.

**Architecture:** Employee chat UI → FastAPI `/chat` → Agent orchestrator → MCP server (8 tools) → ChromaDB RAG + employee JSON data → LLM

---

## Repository Structure

```
acme-hr-agent/
├── src/
│   ├── rag/
│   │   ├── ingest.py        # Policy ingestion: parse → chunk → embed → ChromaDB
│   │   └── retrieval.py     # RAG retrieval, context formatting, guarded prompt builder
│   ├── mcp/
│   │   └── server.py        # MCP server — 8 tools via REST HTTP (port 8001)
│   ├── agent/               # Agent orchestrator — PTO / remote-work / expense workflows
│   └── app/                 # FastAPI web app — POST /chat, GET /health
├── scripts/
│   ├── test_rag.py          # RAG diagnostic tests (coverage, metadata, retrieval quality)
│   ├── test_mcp.py          # MCP tool smoke tests (25 checks)
│   └── convert_policies.py  # One-off: converts .md policies to .html/.txt/.pdf
├── data/
│   ├── policies/            # 20 HR policy files (.md × 5, .html × 5, .txt × 5, .pdf × 5)
│   └── employees.json       # Mock employee profiles (5 employees, EMP-001–EMP-005)
├── project_plan/
│   ├── PROJECT_PLAN.md      # Per-engineer task breakdown
│   ├── mcp_tools_schema.json    # MCP tool contracts (JSON Schema)
│   └── api_contract.json    # Web app API contracts
├── evaluation/
│   ├── questions.json       # 25-question eval set (policy Q&A, multi-doc, agentic, ambiguous, OOS)
│   └── eval_runner.py       # Automated eval runner — POSTs to /chat, scores metrics, writes results.csv
├── design-and-evaluation.md # Architecture, RAG design, MCP design, evaluation plan
├── deployed.md              # Live deployment details and latency measurements
├── ai-tooling.md            # AI tooling usage log
├── requirements.txt
└── .env.example
```

> **Not in the repo (built at runtime):** `chroma_db/` — rebuilt by the ingestion pipeline on setup and each deployment.

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
OPENROUTER_API_KEY=sk-or-...          # LLM provider key (https://openrouter.ai/keys)
MCP_SERVER_URL=http://localhost:8001   # MCP server (default for local dev)
```

**Never commit `.env`.** It is already in `.gitignore`.

---

## Build the RAG Index

Run the ingestion pipeline to chunk all 20 policy documents, embed them, and write `chroma_db/` locally:

```bash
python -m src.rag.ingest
```

Expected output:
```
HR Policy RAG Ingestion Pipeline
Scanning: data/policies
  [POL-AIU-017] ai_acceptable_use_policy.pdf: 1 sections → 31 chunks
  ...
Total chunks generated: 638
Embedding 638 chunks …
Inserted 638 chunks into collection 'hr_policies'.
Ingestion complete.
```

This takes ~30 seconds on the first run (model load + encoding). Re-running is idempotent — it drops and recreates the collection.

---

## Run the MCP Server

The MCP server exposes all 8 HR tools over REST HTTP on port 8001:

```bash
python -m src.mcp.server
```

Expected output:
```
Starting Acme HR Tool Server on http://127.0.0.1:8001
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
```

### Test the MCP tools

**Option 1 — Automated smoke tests (no server required):**
```bash
python scripts/test_mcp.py
```

**curl (REST):**
```bash
# List all tools
curl http://localhost:8001/tools

# Call lookup_employee_profile
curl -X POST http://localhost:8001/tools/lookup_employee_profile \
  -H "Content-Type: application/json" \
  -d '{"employee_id": "EMP-001"}'
```

### Available MCP tools

| Tool | Description |
|------|-------------|
| `search_policy_documents` | Semantic search across all 20 policies; returns ranked chunks with scores |
| `get_policy_section` | Retrieve a specific section from a policy by doc_id + section name |
| `lookup_employee_profile` | Full employee record by ID (EMP-001 … EMP-005) |
| `check_pto_balance` | PTO balance and pending requests for an employee |
| `lookup_benefits_status` | Benefits elections (health, dental, vision, FSA/HSA, 401k) |
| `create_mock_hr_ticket` | Create a mock service ticket; type-based routing; returns ticket ID |
| `check_policy_compliance` | RAG search + prohibition heuristic → `compliant: bool` + citations |
| `draft_hr_email` | Personalised email draft (PTO request, remote work, expense, etc.); `draft_only: true` always |

---

## Test the RAG Pipeline

```bash
python scripts/test_rag.py
```

Runs 5 diagnostic suites: coverage (all 20 docs indexed), metadata quality, chunk text quality, retrieval quality (10 targeted queries), and multi-document retrieval. All 50+ checks must pass for CI to succeed.

### Test retrieval interactively

```bash
python -m src.rag.retrieval "How many PTO days do I carry over after 5 years?"
```

Prints the top-5 retrieved chunks and a preview of the guarded LLM system prompt.

---

## Start the Web App

```bash
uvicorn src.app.main:app --reload --port 8080
```

Health check:
```bash
curl http://localhost:8080/health
```

Expected response:
```json
{ "status": "ok", "mcp_connected": true, "chroma_loaded": true, "doc_count": 638 }
```

---

## Demo Tasks

Two reproducible agentic workflows for grading. Run them via the chat UI or the curl commands below once the web app is deployed.

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
3. `search_policy_documents` ("PTO request approval process")
4. `check_policy_compliance` (action: take 5 days PTO)
5. `create_mock_hr_ticket` (after user confirmation)

### Demo 2 — Expense Compliance Check

**Query:** "I'm EMP-001 (fully remote). Can I expense a $1,200 standing desk?"

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Can I expense a $1200 standing desk for my home office?", "employee_id": "EMP-001"}'
```

**Expected tool sequence:**
1. `lookup_employee_profile` (EMP-001 — confirms fully remote)
2. `get_policy_section` (POL-EXP-001, "Home Office Equipment")
3. `check_policy_compliance` (action: expense $1200 standing desk, context: fully remote)

---

## CI/CD

GitHub Actions runs on every push and pull request to `main`. Passing tests on `main` automatically deploy to production.

**Pipeline (`main` push):**
1. Install dependencies
2. Import checks (RAG + MCP modules)
3. Build ChromaDB index (`python -m src.rag.ingest`)
4. RAG diagnostic tests (`python scripts/test_rag.py`)
5. MCP tool smoke tests (`python scripts/test_mcp.py`)
6. Run orchestrator unit tests (`pytest tests/ -v`)
7. *(on pass)* SSH into `hrapp.elcaro.io` → `git pull` → rsync → `systemctl restart`

**Pull requests** run steps 1–6 only — they never deploy.

**Required GitHub secret:** `DEPLOY_SSH_KEY` — the OCI server's SSH private key, set under *Settings → Secrets and variables → Actions*.

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Deployment

The app is deployed on Oracle Cloud Infrastructure (`hrapp.elcaro.io`), managed by systemd with nginx as a reverse proxy and TLS via Let's Encrypt. Deployments are automated via CI/CD — every push to `main` that passes tests ships automatically.

**Live URL:** https://hrapp.elcaro.io

**Manual deploy (if needed):**
```bash
DEPLOY_SSH_KEY=/path/to/key ./scripts/deploy.sh
```

The MCP server is launched as a subprocess by the FastAPI startup event on `localhost:8001`. Secrets are stored in `/etc/sysconfig/acme-hr-agent` on the server — never in code or committed files.

See [deployed.md](deployed.md) for full server setup details.

---

## Evaluation

Run the full 25-question evaluation suite:

```bash
# Local
python evaluation/eval_runner.py --endpoint http://localhost:8080

# Live deployment
python evaluation/eval_runner.py --endpoint https://hrapp.elcaro.io
```

Results are written to `evaluation/results.csv`. The runner exits with code 1 if overall pass rate < 70%.

**Question set (25 total):**

| Category | Count |
|---|---|
| Straightforward policy Q&A | 8 |
| Multi-document questions | 5 |
| Tool-requiring agentic tasks | 7 |
| Ambiguous requests | 3 |
| Out-of-scope requests | 2 |

**Metrics scored per question:** escalation accuracy, tool recall, citation recall, keyword match, action safety (write actions only when `confirmed=True`). Latency p50/p95 reported in aggregate.

**Ablation (top-k sweep):**

```bash
python evaluation/eval_runner.py --top-k 3
python evaluation/eval_runner.py --top-k 5   # baseline
python evaluation/eval_runner.py --top-k 8
```

Full evaluation design and results are in [`design-and-evaluation.md`](design-and-evaluation.md).

---

## Policy Documents

20 synthetic HR policy documents in 4 formats (.md, .html, .txt, .pdf):

| Doc ID | Title | Format |
|---|---|---|
| POL-RW-001 | Remote Work Policy | .md |
| POL-PTO-002 | PTO Policy | .md |
| POL-EXP-001 | Expense Reimbursement Policy | .html |
| POL-HOL-003 | Company Holidays Policy | .html |
| POL-SEC-004 | Data Security Policy | .md |
| POL-BEN-005 | Employee Benefits Policy | .md |
| POL-ONB-006 | Onboarding Policy | .html |
| POL-EQP-007 | Equipment & Asset Management Policy | .pdf |
| POL-LOA-008 | Leave of Absence Policy | .html |
| POL-WPC-009 | Workplace Conduct Policy | .md |
| POL-PFM-010 | Performance Management Policy | .pdf |
| POL-OFB-011 | Offboarding Policy | .html |
| POL-CMP-012 | Compensation Policy | .txt |
| POL-LND-013 | Learning & Development Policy | .pdf |
| POL-DEI-014 | DEI Policy | .txt |
| POL-HSF-015 | Health & Safety Policy | .txt |
| POL-REC-016 | Recruitment & Hiring Policy | .txt |
| POL-AIU-017 | AI Acceptable Use Policy | .pdf |
| POL-PRV-018 | Employee Privacy Policy | .pdf |
| POL-VND-019 | Vendor Management Policy | .txt |

All documents are synthetic and do not contain real personal information.

---

## Team

Built by a team of 3 engineers for the Quantic MSAIE program.

- **Richard — Knowledge Layer:** RAG pipeline, policy corpus, ChromaDB, MCP server + tools
- **Moe — Reasoning Layer:** Agent orchestrator, web application
- **Diva — Quality Layer:** Deployment, CI/CD, evaluation, documentation
