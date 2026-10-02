# AI Tooling — How We Used AI Code Generation

## Tools Used

### Claude Code (Anthropic)

Claude Code (the Anthropic CLI) was used in the initial project build through the VS Code extension. It helped scaffold the policy corpus, ingestion pipeline, tool schemas, and initial evaluation suite. The team reviewed and tested the generated work.

### Codex (OpenAI)

Codex was used for later integration and repair work. It inspected the running OCI service and audit traces, edited the orchestrator and web app, added employee authentication and review queues, replaced the REST-only agent integration with actual MCP discovery and tool calls, strengthened CI startup checks, and revised the evaluation runner. We validated these changes with local tests, GitHub Actions, and live service checks. The latest work also corrected mixed-policy routing, out-of-scope handling, and fallback answer relevance; any production-quality claims depend on a fresh deployed evaluation rather than generated code alone.

---

## What Was Generated with AI Assistance

### RAG Pipeline (`src/rag/ingest.py`, `src/rag/retrieval.py`)

The entire ingestion and retrieval layer was written with Claude Code. This included:

- The heading-aware markdown splitter (`split_by_headings`) and its breadcrumb path logic
- The recursive character splitter with overlap (`_split_text`)
- The ChromaDB collection setup, batch embedding loop, and metadata schema
- The lazy singleton pattern for the embedding model and collection in `retrieval.py`
- The RAG system prompt with all 6 guardrails (`build_rag_prompt`)

**What worked well:** Claude correctly chose heading-aware chunking over naive fixed-size splitting without prompting, and it built the breadcrumb path logic (`crumb` stack) in one pass that was logically correct from the first attempt. The guardrail prompt language was also strong on the first generation — especially the distinction between `[OFFICIAL POLICY]` and `[GENERAL GUIDANCE]` labels.

**What needed correction:** The initial `load_and_chunk_policies` function only handled `.md` files (`glob("*.md")`). After we decided to support multiple document formats, we had to explicitly ask Claude to add format-aware parsers for `.html`, `.txt`, and `.pdf`, and update the glob to use `iterdir()` filtered by extension. This was a natural omission — Claude generated what was asked for — but it illustrates that AI tools generate to the spec they're given, not beyond it.

---

### Multi-Format Policy Conversion (`scripts/convert_policies.py`)

Claude Code generated the full conversion script that converts `.md` policy files into HTML, TXT, and PDF outputs. The HTML and TXT converters worked correctly on the first run. The PDF converter using `fpdf2` ran into a production error:

```
fpdf.errors.FPDFException: Not enough horizontal space to render a single character
```

This occurred on long unbreakable tokens (URLs, hyphenated strings) in several policy documents. Claude diagnosed the root cause correctly — fpdf2's default `WORD` wrap mode cannot break tokens with no whitespace — and proposed `wrapmode="CHAR"` as a fix. The fix silenced the error but introduced a severe regression: the script hung for 17+ minutes on a single document due to fpdf2's character-level layout loop on long paragraphs.

**Final fix:** Replaced `fpdf2` entirely with `reportlab`, using `SimpleDocTemplate` + `Paragraph` flowables. A helper `_md_to_story()` maps markdown heading and list syntax to reportlab styles. All 5 PDFs now generate in under 5 seconds. The switch required discovering the regression at runtime — static generation cannot anticipate performance cliffs in library internals.

**What worked well:** The overall script structure, the markdown-to-HTML conversion using the `markdown` library, and the txt stripping logic using regex were all solid on first generation.

**What needed correction:** Two iterations were required for the PDF path: first the `FPDFException`, then the `wrapmode="CHAR"` hang. Both required running the code to observe — neither was statically predictable.

---

### MCP Tool Schemas (`project_plan/mcp_tools_schema.json`)

The 8 MCP tool schemas (input/output JSON Schema definitions) were generated with Claude Code. All field types, enums, required arrays, and descriptions were produced in one pass and required no structural corrections.

**What worked well:** Claude correctly applied JSON Schema conventions (`"type": "object"`, `"required": []`, `enum` constraints) and added sensible descriptions to every field — detail that is easy to skip when writing by hand but important for the MCP client's tool-discovery behaviour.

---

### MCP Server Implementation (`src/mcp/server.py`)

Claude Code generated the initial MCP server using `FastMCP` from the `mcp` Python SDK. Its first-pass tool logic included embedding-backed policy retrieval, JSON-backed employee lookups, ticket creation, and a prohibition-keyword compliance heuristic. Ticket records were later made file-backed so review queues survive service restarts.

**What needed correction — protocol integration:** An intermediate deployment exposed the tools only through REST (`GET /tools`, `POST /tools/{name}`). That was useful for smoke tests but did not satisfy the project's MCP requirement. Codex later added the official MCP Python SDK, registered the eight tools on a Streamable HTTP endpoint at `/mcp/`, and changed the orchestrator to use `tools/list` and `tools/call`. The REST routes remain only as diagnostic compatibility endpoints. A protocol test and app-startup discovery check now guard against reverting to REST-only integration.

**What worked well:** The lazy singleton pattern for the employees dict (mirroring the existing pattern in `retrieval.py`) was applied correctly without prompting. The 25-check `scripts/test_mcp.py` test suite was generated in one pass and all checks passed immediately after the rewrite.

---

### LLM Provider (OpenRouter)

The project was initially configured to use the Anthropic API directly (`anthropic.Anthropic()`). This was replaced with OpenRouter using the `openai` SDK with `base_url="https://openrouter.ai/api/v1"`. The switch required: (1) adding `OPENROUTER_API_KEY` to `.env`; (2) changing the client instantiation from `anthropic.Anthropic()` to `openai.OpenAI(base_url=..., api_key=...)`. The initial free-model configuration became unreliable due to model availability and upstream rate limits; the deployed setting was changed to the low-cost paid `google/gemini-2.5-flash-lite` after owner approval. Provider failures still trigger an evidence-bounded fallback, and the admin audit records whether the LLM route and quality review actually ran.

---

### Evaluation Suite (`evaluation/questions.json`, `evaluation/eval_runner.py`)

Claude Code produced the initial 25-question set and automated runner. Codex later added short reference answers, authenticated employee requests, genuine `top_k` variation, citation and tool-selection checks, clarification and workflow metrics, and a safer default that does not create test tickets. The initial 88% figure is historical and must not be presented as current performance. A later live run exposed zero passing multi-document cases, which led to the routing and evidence fixes. The current runner saves full answer text for review and reports its lexical groundedness measure explicitly as a proxy, not a semantic judge.

---

### Project Planning (`project_plan/PROJECT_PLAN.md`)

The project plan, including engineer assignments, task breakdown, daily timeline, and grading checklist, was drafted with Claude Code and then reviewed and adjusted by the team.

**What worked well:** The parallel work structure — pre-agreeing on API contracts and schemas on Day 0, then letting three engineers work independently — was suggested by Claude as a way to avoid blocking dependencies. This proved effective in practice.

**What needed correction:** The initial plan assigned deployment to a third engineer but did not explicitly include a "skeleton deploy on Day 1" step. This was added manually to ensure the live URL existed early.

---

### Design Documentation (`design-and-evaluation.md`)

The initial architecture and design documents were drafted with Claude Code using the codebase and project plan as source material. Codex later revised them to reflect authenticated workflows, the deployed MCP SDK transport, production layout, and evaluation limitations. Documents are checked against running code because earlier generated descriptions became stale after implementation changed.

**What worked well:** Claude produced accurate documentation by reading the actual code rather than relying on the project prompt alone. The demo task tool-call sequences correctly matched the tool schemas and employee data fields.

---

## General Observations

**Strengths of AI-assisted development on this project:**

- **Scaffolding speed:** Boilerplate code (ChromaDB setup, FastAPI endpoint skeletons, CI/CD yaml) that would take hours by hand was produced in minutes.
- **Library knowledge:** Claude correctly identified appropriate libraries for each task (`sentence-transformers`, `chromadb`, `beautifulsoup4`, `pypdf`, `fpdf2`) and knew their APIs without requiring documentation lookups.
- **Consistency:** Naming conventions, metadata field names, and citation formats stayed consistent across files because Claude held the context of earlier decisions across turns.
- **Documentation quality:** Comments, docstrings, and external documentation were significantly more thorough than typical hand-written first drafts.

**Limitations observed:**

- **Runtime errors require running the code:** Static generation cannot anticipate library-specific runtime behaviour (the `fpdf2` `wrapmode` issue, for example). AI tools are most effective in a tight edit-run-debug loop, not as one-shot code generators.
- **Scope creep risk:** Claude occasionally suggested adding features beyond what was needed (e.g., offering to add query rewriting or reranking during the RAG pipeline discussion). These suggestions were acknowledged but deferred to avoid scope creep.
- **Generates to the spec given:** The multi-format parsing gap (only `.md` files handled initially) is representative of a broader pattern: AI tools produce what is asked for. Requirements that are implicit or discovered later require explicit follow-up prompts.

---

## Time Impact

The initial AI-assisted scaffolding was faster than writing each layer from scratch, but the largest effort was validation and repair: protocol compliance, deployment authentication, answer relevance, evaluation labels, and documentation all required multiple test-and-debug cycles. We do not treat an AI-generated implementation or an early passing score as evidence of correctness until it has been exercised against the running system.
