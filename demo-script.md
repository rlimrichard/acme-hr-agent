# Acme HR Agent: 7–10 minute screen-share script

This is a recording guide for the synthetic HR-agent demo at <https://hrapp.elcaro.io>. It shows two complete tasks, the policy evidence behind each answer, and the human-review step. The presenter should use the *deployed* app, not a local server, and describe only results visible in the recording. Budget about nine minutes; leave a minute for page loads.

Suggested speaking split for the three listed contributors: Richard opens with the architecture (0:00–0:50), Moe narrates both live tasks (0:50–6:20), and Diva presents evaluation, deployment, and limitations (6:20–9:00). Every member should speak and appear on camera as the course requires; adjust the names and handoffs if the actual presenting group differs.

## Before recording

- Confirm <https://hrapp.elcaro.io/health> reports `status: ok`, `mcp_connected: true`, `chroma_loaded: true`, and eight tools. Confirm the latest GitHub Actions run for `main` succeeded and the deployed commit matches it.
- Sign out of any prior employee and admin sessions. The synthetic employee accounts use password `acme123`; choose IDs from the app's login selector. Do not display API keys, SSH material, browser password-manager popups, or unrelated audit entries.
- If demonstrating ticket creation, check the review queue first so a prior run does not obscure the new ticket. Note the new ticket ID on screen. Never claim that the ticket reached an external HR or payroll system: it is persisted in this demo app.
- Have the repository open to `README.md`, `design-and-evaluation.md`, `evaluation/questions.json`, `evaluation/results-current.csv` (if present), `.github/workflows/ci.yml`, and `src/mcp/server.py`. Show actual current evaluation output, not a historical pass rate.
- Arrange the course-required camera, speaking, and ID check for *each* group member using the school's approved sharing method. Do not put student IDs in the public repository or expose them to an unintended audience.

## 0:00–0:50 — What is running

**Presenter:** “This is Acme HR Agent, a synthetic policy assistant deployed at `hrapp.elcaro.io`. The browser talks to FastAPI. Its agent routes a request, calls an MCP server over Streamable HTTP, retrieves from a Chroma policy index, and uses an LLM to synthesize a cited answer. Employee sessions govern access to request queues. All policy and employee records shown here are mock data.”

**On screen:** Show the home page and `/health`. Point to the eight-tool count and Chroma/MCP health indicators. Briefly show the four policy formats and 20 documents in the repository.

## 0:50–3:55 — Task 1: PTO request and manager decision

**Presenter:** “I’ll sign in as Marcus Johnson, `EMP-002`, whose recorded manager is Linda, `EMP-005`. I’ll ask: ‘I want to submit a PTO request for November 2.’”

**On screen:** Select `EMP-002` at `/login`, enter the demo password, submit the question, then expand *How I got the answer*. The first response should offer a confirmation choice. Explain that a question alone is not an authorization to create a ticket. Choose **Yes, confirm** only when ready to create this demo-app request; mention the **No, don’t** option also exists. Copy the resulting ticket ID.

**Explain the visible trace, without inventing exact output:**

1. `lookup_employee_profile({"employee_id":"EMP-002"})` supplies the employee, hybrid status, and manager ID `EMP-005`.
2. `check_pto_balance({"employee_id":"EMP-002"})` supplies the current mock PTO balance. Read the number actually returned; the seed record starts at 8.0 days, but live data may differ.
3. `search_policy_documents` retrieves PTO policy evidence; identify the returned `POL-PTO-002` section and its citation on screen.
4. `check_policy_compliance` checks the described leave action against retrieved policy. This heuristic is a guardrail, not manager approval.
5. Only the confirmed follow-up calls `create_mock_hr_ticket`; the tool returns the new `TKT-…` ID and routes the PTO request to the recorded direct manager.

**On screen:** Sign out, sign in as `EMP-005` (Linda), open the manager PTO queue, find that exact ticket, enter a short review message, and approve or deny it. Sign back in as `EMP-002` and show *My Requests* with the closed decision and message. Say: “The manager made the decision; the model did not approve its own request.” If the request does not appear or review fails, stop and show the failure honestly rather than narrating a completed workflow.

## 3:55–6:20 — Task 2: cross-policy expense assessment

**Presenter:** “Next, I’m Sarah Chen, `EMP-001`, a fully remote employee. I’ll ask: ‘Can I expense a $1,200 standing desk for my home office?’ This needs both the expense rules and the remote-work ergonomics rule.”

**On screen:** Sign in as `EMP-001`, ask the question, and expand *How I got the answer*. Show the answer citations and relevant snippets.

**Explain the trace:**

1. `lookup_employee_profile({"employee_id":"EMP-001"})` establishes that this synthetic employee is fully remote.
2. `search_policy_documents` searches the original question and retrieves candidate policy chunks.
3. `get_policy_section({"doc_id":"POL-EXP-001","section":"Office Supplies (Remote)"})` retrieves the expense-side rule. Read the exact returned condition.
4. `get_policy_section({"doc_id":"POL-RW-001","section":"5.2 Ergonomics"})` retrieves the one-time $500 ergonomics stipend and receipt timing. A standing desk is listed as an eligible purchase, but a $1,200 purchase is not automatically fully reimbursable.
5. `check_policy_compliance` checks the proposed expense. Explain that “no explicit prohibition” is not an approval or a promise of payment.

**Presenter:** “The answer should distinguish eligibility for a *possible* $500 stipend from reimbursement of the full $1,200, cite both policies, and avoid creating a ticket or drafting an email that I did not ask for.” If the actual answer does not meet that bar, identify the gap candidly.

## 6:20–7:40 — Implementation and evaluation evidence

**On screen:** Show `src/mcp/server.py` tool registration, `src/agent/orchestrator.py`, the 25-case `evaluation/questions.json`, and the latest generated evaluation summary/CSV. Then show the GitHub Actions workflow and most recent passing run.

**Presenter:** “The agent classifies intent with the configured LLM, uses narrow safeguards for known high-risk misroutes, retrieves policy evidence through MCP, and synthesizes a grounded answer. The deterministic fallback is used if the model is unavailable or omits required policy distinctions. Our evaluation covers eight direct policy questions, five multi-document questions, seven agentic tasks, three ambiguous requests, and two out-of-scope requests. It scores tool choice, citations, clarification, safe write behavior, workflow completion, and latency. The groundedness number is a lexical overlap proxy—not a claim that every answer is factually correct.”

Read only the **verified deployed-run** pass rate and p50/p95 latency visible in the current results. If no deployed evaluation is available, say so and show local results clearly labeled as local fallback testing. Briefly compare the measured top-k 3/5/8 runs only if all three were made against the same deployed build; do not infer higher quality from overlap alone.

## 7:40–9:00 — Deployment, limits, and handoff

**On screen:** Show `.github/workflows/ci.yml`, the live URL, `deployed.md`, and `ai-tooling.md`. If a course teammate is presenting this segment, hand over here.

**Presenter:** “A push to `main` runs import, ingestion, RAG, MCP, unit/protocol, and app-start checks; a passing main build deploys to an OCI instance behind nginx and TLS. The MCP server is bound to localhost, while the browser reaches only the web app. Our policy corpus and people records are synthetic. The shared demo password, local JSON ticket store, and compliance heuristic are demonstration choices, not a production HR security or approval design. AI coding tools helped build and repair the project; `ai-tooling.md` documents where human testing found and corrected their mistakes.”

Close by showing that the repository invitation to `quantic-grader` has been accepted, if it has. Do not claim acceptance merely because an invitation was sent. Before submission, verify the recording duration, link permissions, group-member participation, and that both tasks' tools, arguments, results, and citations are readable on screen.
