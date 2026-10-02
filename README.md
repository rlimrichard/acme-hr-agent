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
│   │   └── server.py        # MCP Streamable HTTP server — 8 tools (port 8001)
│   ├── agent/               # Agent orchestrator — PTO / remote-work / expense workflows
│   └── app/                 # FastAPI web app — POST /chat, GET /health
├── scripts/
│   ├── test_rag.py          # RAG diagnostic tests (coverage, metadata, retrieval quality)
│   ├── test_mcp.py          # MCP tool smoke tests (25 checks)
│   ├── test_app_start.py    # Starts the app and verifies health plus MCP discovery
│   ├── run_regression_tests.py # Deterministic workflow regression report for /admin
│   ├── deploy.sh            # Manual OCI deployment path
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
│   ├── gold_answers.json    # Short human-authored reference answers
│   ├── eval_runner.py       # Authenticated eval runner — scores /chat responses and writes CSV
│   └── summarize_results.py # Fixed 15-case latency sample and top-k comparison
├── design-and-evaluation.md # Architecture, RAG design, MCP design, evaluation plan
├── deployed.md              # Live deployment details and latency measurements
├── ai-tooling.md            # AI tooling usage log
├── requirements.txt
└── .env.example
```

> **Not in the repo (built at runtime):** `chroma_db/` — rebuilt by the ingestion pipeline on setup and each deployment.

---

## Prerequisites

- Python 3.11+
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

Use Python 3.11 for the CI/deployment-equivalent environment.

### 3. Install dependencies

```bash
# Linux CPU-only setup (the deployed/CI configuration):
pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

On Windows or macOS, install `requirements.txt` directly; the Linux CPU-wheel
step above is not needed. Direct dependencies are pinned to the versions
verified on the Python 3.11 server. Transitive wheels still depend on the
platform; this is not a hash-locked, cross-platform environment. The first
install downloads PyTorch and the `all-MiniLM-L6-v2` embedding model (~90 MB).
Subsequent runs use the cached model.

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

### 5. Provision synthetic employee logins

On a fresh checkout, run once before using `/chat` or the browser UI:

```bash
PORTAL_INITIAL_PASSWORD=acme123 python -m scripts.provision_portal_users
```

In PowerShell: `$env:PORTAL_INITIAL_PASSWORD='acme123'; python -m scripts.provision_portal_users`.
The provisioning script refuses to overwrite an existing account file.

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
Total chunks generated: <count depends on the checked-in corpus>
Embedding <count> chunks …
Inserted <count> chunks into collection 'hr_policies'.
Ingestion complete.
```

The embedding model is pinned to [Hugging Face revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41). Input files are sorted,
chunk size/overlap are fixed, and chunk IDs are derived from document ID,
section/chunk position, and text. Thus, an unchanged corpus produces the same
chunk texts and IDs across ingestion runs. Ingestion drops and recreates the
collection; the first run takes ~30 seconds to load and encode the model.

---

## Reasoning Logic

Each employee question follows a grounded, inspectable workflow:

1. **Routing.** General greetings and capability questions receive a direct help response. Other questions go to the configured OpenRouter model for classification as `pto`, `remote`, `expense`, general `policy`, or `out_of_scope`. A deterministic router is used if the model is unavailable or returns an invalid label. Narrow safeguards keep vendor gifts out of PTO, existing remote employees' expenses out of the location-change workflow, and combined policy questions in a multi-document path. Clearly unrelated requests are redirected without inventing policy citations.
2. **Hybrid policy retrieval.** Workflows search using the employee's original question first, then add narrow workflow anchors. Exact section names receive a ranking preference. Combined questions retrieve the governing sections from each relevant policy through MCP. If Chroma is unavailable, the lexical fallback reads all four supported policy formats.
3. **Workflow-specific checks.** PTO looks up the employee profile and balance; an explicit PTO submission creates a manager-review request only after confirmation. A proposed change of remote-work location can create an internal HR review request after confirmation; an informational approval question does not offer a ticket. Expenses retrieve the relevant reimbursement and, where needed, remote-equipment sections. Ambiguous requests ask for missing details rather than drafting an email.
4. **Grounded synthesis.** The LLM receives minimal employee context, retrieved policy excerpts, a compliance assessment, and a relevant deterministic fallback. It must cite policy facts and may not invent approvals, dates, balances, or actions. Routing and synthesis calls have 12-second deadlines and no automatic retries; if the provider stalls, is unavailable, or misses a required topic in a high-risk answer, the evidence-bounded fallback is returned. The audit-only quality review has a separate 6-second deadline.
5. **High-confidence safeguards.** Deterministic policy rules remain for explicit thresholds and critical distinctions, including the unified PTO bank for vacation and sick leave, vendor gifts over $75, travel meal per-diem limits, the remote ergonomics stipend, and unanswered PTO-accrual rules during parental leave.

### Human review and employee sign-in

The chat and Requests page require employee sign-in using an employee ID and password. Identity comes from the signed session, so changing an employee ID in a browser request cannot access another employee's records. The separate `/admin` account remains for audits and database inspection.

When an HR request is created, employees in People Operations see it in their Requests review queue. When a PTO request is created, only that employee's recorded direct manager sees it in the team PTO queue. A reviewer must include a message when approving or denying. The employee sees their own pending requests and then the closed decision and message. These are internal app decisions stored in `data/ticket_reviews.jsonl`; they are not submissions to an external HR or payroll system.

Provision demo accounts once on a fresh checkout with `PORTAL_INITIAL_PASSWORD=acme123 python -m scripts.provision_portal_users`. All five synthetic employees then use password `acme123`; select an employee ID on `/login`. The script stores salted hashes in ignored `data/portal_users.json` and refuses to overwrite existing accounts. This is a shared **demo-only** password, not appropriate for real employee data. For an existing installation, use its already-provisioned password or rotate accounts separately.

### Privacy and admin auditability

The employee-facing API exposes cited answers and tool traces, but not LLM prompts or the audit score. Authenticated admins can view each conversation with its routing decision, near-complete prompts, retrieved policy excerpts, employee context used by the model, and MCP calls. Audit strings are capped at 12,000 characters; API credentials are not recorded. The audit shows a 0–100 answer relevance and evidence score when the LLM review succeeds, including its method and short reason. Direct help responses receive a deterministic intent-match score. If the model is unavailable, the score is shown as unavailable rather than inferred from raw text similarity. Scores are diagnostic signals, not calibrated probabilities of policy correctness.

---

## Run the MCP Server

The MCP server exposes all 8 HR tools through the official MCP SDK over Streamable HTTP at `http://127.0.0.1:8001/mcp`. It also retains diagnostic REST routes (`GET /tools`, `POST /tools/{name}`) for simple smoke checks; the agent does not use those REST routes.

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
pytest tests/test_mcp_protocol.py -q
```

**Diagnostic curl (legacy REST, not the agent transport):**
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
{ "status": "ok", "mcp_connected": true, "chroma_loaded": true, "doc_count": 642, "tool_count": 8, "version": "0.1.0" }
```

---

## Demo Tasks

Two reproducible agentic workflows for grading. Sign in at `/login` as the indicated synthetic employee using demo password `acme123`, or use the authenticated curl examples below. On a fresh checkout, run the account-provisioning command above first. The response includes citations, snippets, and a tool-call trace.

### Demo 1 — PTO Request Guidance

**Query:** "I want to submit a PTO request for November 2."

```bash
curl -c /tmp/acme-emp002.cookies -X POST http://localhost:8080/login \
  -d 'employee_id=EMP-002&password=acme123'
curl -b /tmp/acme-emp002.cookies -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "I want to submit a PTO request for November 2.", "employee_id": "EMP-002"}'
```

**Expected tool sequence:**
1. `lookup_employee_profile` (EMP-002)
2. `check_pto_balance` (EMP-002)
3. `search_policy_documents` (PTO policy evidence)
4. `check_policy_compliance` (action: the stated PTO request)
5. After the app asks for confirmation, repeat the same authenticated `/chat` call with `"confirmed": true`; only then does `create_mock_hr_ticket` create a manager-review request. This creates a real *demo-app* ticket, so skip the confirmation step when merely inspecting the workflow.

### Demo 2 — Expense Compliance Check

**Query:** "I'm EMP-001 (fully remote). Can I expense a $1,200 standing desk?"

```bash
curl -c /tmp/acme-emp001.cookies -X POST http://localhost:8080/login \
  -d 'employee_id=EMP-001&password=acme123'
curl -b /tmp/acme-emp001.cookies -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Can I expense a $1200 standing desk for my home office?", "employee_id": "EMP-001"}'
```

**Expected tool sequence:**
1. `lookup_employee_profile` (EMP-001 — confirms fully remote)
2. `search_policy_documents` (expense and equipment evidence)
3. `get_policy_section` (POL-EXP-001, "Office Supplies (Remote)")
4. `get_policy_section` (POL-RW-001, "5.2 Ergonomics")
5. `check_policy_compliance` (action: expense $1200 standing desk, context: fully remote)

---

## CI/CD

GitHub Actions runs on every push and pull request to `main`. Passing tests on `main` automatically deploy to production.

**Pipeline (`main` push):**
1. Install dependencies
2. Import checks (RAG + MCP modules)
3. Build ChromaDB index (`python -m src.rag.ingest`)
4. RAG diagnostic tests (`python scripts/test_rag.py`)
5. MCP tool smoke tests (`python scripts/test_mcp.py`)
6. Run unit and protocol tests (`pytest tests/ -v`)
7. Start the real ASGI app and verify `/health` and MCP discovery (`python scripts/test_app_start.py`)
8. *(on pass)* SSH into `hrapp.elcaro.io` → `git pull` → rsync → install dependencies → regression tests → `systemctl restart` → health check

**Pull requests** run every test step, including app startup and MCP discovery; they never deploy.

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

The MCP server is launched as a subprocess by FastAPI startup on `localhost:8001`. The agent uses the official MCP SDK over Streamable HTTP at `/mcp`, including `tools/list` and `tools/call`. The old REST `/tools` endpoints remain for diagnostics only. Secrets are stored in `/etc/sysconfig/acme-hr-agent` on the server — never in code or committed files. Deploying a code change does not overwrite the persisted policy index; rebuild it explicitly after changing policy documents.

See [deployed.md](deployed.md) for full server setup details.

---

## Evaluation

Run the full 25-question evaluation suite. The runner logs in for each synthetic employee with the password from `PORTAL_EVAL_PASSWORD`. By default it forces `confirmed=false` so it never creates test tickets on the live service. Use `--allow-write-actions` only against disposable data.

```bash
# Local
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint http://localhost:8080

# Live deployment
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint https://hrapp.elcaro.io
```

Results are written to ignored `evaluation/results-latest.csv` by default, so a run does not dirty the tracked historical CSV or block a server `git pull`. Use `--out` to publish a named result. The runner exits with code 1 if overall pass rate < 70%.

**Question set (25 total):**

| Category | Count |
|---|---|
| Straightforward policy Q&A | 8 |
| Multi-document questions | 5 |
| Tool-requiring agentic tasks | 7 |
| Ambiguous requests | 3 |
| Out-of-scope requests | 2 |

**Metrics scored per question:** escalation/clarification accuracy, tool recall and selection F1, citation recall and evidence-backed citation accuracy, keyword match against annotated gold concepts, workflow completion, and action safety. The overall pass rule also requires adequate tool selection, supported citations, clarification, and workflow completion. A lexical overlap score against policy and structured tool evidence is reported as a **groundedness proxy**, not a semantic correctness judgment. The runner measures warm-request latency p50/p95 across all 25 chat requests (authentication excluded); `evaluation/summarize_results.py` separately reports p50/p95 for a fixed, category-spanning 15-case sample. The CSV also records the full bounded answer for human comparison with its reference answer.

**Ablation (top-k sweep):** Each request now applies `top_k` to the policy-search tool, rather than merely labeling the CSV. Use separate output paths:

```bash
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint http://localhost:8080 --top-k 3 --out evaluation/results-k3.csv
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint http://localhost:8080 --top-k 5 --out evaluation/results-k5.csv
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint http://localhost:8080 --top-k 8 --out evaluation/results-k8.csv
python evaluation/summarize_results.py evaluation/results-k3.csv evaluation/results-k5.csv evaluation/results-k8.csv
```

Compare runs only when endpoint, deployed commit, question set, and model configuration are held constant. The comparison script lists the 15 preselected latency-case IDs. `evaluation/results.csv` is an older historical artifact; see the dated live results in [`design-and-evaluation.md`](design-and-evaluation.md) for current claims.

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
