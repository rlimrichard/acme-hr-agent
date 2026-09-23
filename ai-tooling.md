# AI Tooling — How We Used AI Code Generation

## Tools Used

### Claude Code (Anthropic)

Claude Code (the Anthropic CLI) was the primary AI tool used throughout this project. It was used interactively via the VS Code extension in an agentic mode where it could read, write, and edit files, run shell commands, and reason about the codebase across multiple turns.

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

This occurred on long unbreakable tokens (URLs, hyphenated strings) in several policy documents. Claude diagnosed the root cause correctly — fpdf2's default `WORD` wrap mode cannot break tokens with no whitespace — and fixed it by adding `wrapmode="CHAR"` to all `multi_cell` calls. The fix was correct and required no additional iteration.

**What worked well:** The overall script structure, the markdown-to-HTML conversion using the `markdown` library, and the txt stripping logic using regex were all solid on first generation. Claude also correctly identified that `fpdf2` was the right choice over `weasyprint` for free-tier compatibility (no system binary dependency).

**What needed correction:** The `wrapmode="CHAR"` fix was required after a runtime error — this is a library-specific gotcha that required running the code to discover. Claude could not have known about it statically.

---

### MCP Tool Schemas (`project_plan/mcp_tools_schema.json`)

The 7 MCP tool schemas (input/output JSON Schema definitions) were generated with Claude Code. All field types, enums, required arrays, and descriptions were produced in one pass and required no structural corrections.

**What worked well:** Claude correctly applied JSON Schema conventions (`"type": "object"`, `"required": []`, `enum` constraints) and added sensible descriptions to every field — detail that is easy to skip when writing by hand but important for the MCP client's tool-discovery behaviour.

---

### Project Planning (`project_plan/PROJECT_PLAN.md`)

The project plan, including engineer assignments, task breakdown, daily timeline, and grading checklist, was drafted with Claude Code and then reviewed and adjusted by the team.

**What worked well:** The parallel work structure — pre-agreeing on API contracts and schemas on Day 0, then letting three engineers work independently — was suggested by Claude as a way to avoid blocking dependencies. This proved effective in practice.

**What needed correction:** The initial plan assigned deployment to a third engineer but did not explicitly include a "skeleton deploy on Day 1" step. This was added manually to ensure the live URL existed early.

---

### Design Documentation (`design-and-evaluation.md`, this file)

Both documentation files were written with Claude Code, using the codebase and project plan as source material. The ASCII architecture diagram, tool table, guardrail table, and demo task sequences were generated from reading `ingest.py`, `retrieval.py`, and `mcp_tools_schema.json` directly.

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

AI tooling reduced estimated development time for the knowledge layer (RAG pipeline, policy corpus, mock data, MCP tool schemas) from approximately 3–4 days of engineering work to approximately 1 day, with the remaining time spent on integration, testing, and iteration. Documentation that would typically be written last and under time pressure was instead drafted in parallel with the code.
