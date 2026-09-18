"""
HR Policy RAG Retrieval Layer
Provides:
  - retrieve_chunks()     – top-k similarity search against ChromaDB
  - build_rag_prompt()    – injects retrieved context into a guarded system prompt
  - format_context()      – formats chunks for readable injection

Usage (standalone demo):
    python src/retrieval.py "How many PTO days do I get after 3 years?"
"""

import sys
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration – must match ingest.py
# ---------------------------------------------------------------------------

CHROMA_DIR      = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "hr_policies"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K   = 5


# ---------------------------------------------------------------------------
# Lazy singletons (avoid reloading model on every call in long-running apps)
# ---------------------------------------------------------------------------

_model:      SentenceTransformer | None = None
_collection: chromadb.Collection | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


# ---------------------------------------------------------------------------
# Core retrieval function
# ---------------------------------------------------------------------------

def retrieve_chunks(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    filter_doc_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Embed `query` and return the top-k most similar chunks from ChromaDB.

    Args:
        query:         Natural-language question from the user.
        top_k:         Number of results to return.
        filter_doc_id: Optional document-level filter (e.g. "POL-PTO-002")
                       to restrict search to a single policy document.

    Returns:
        List of dicts, each containing:
            - text       : the chunk text
            - doc_id     : source policy document ID
            - doc_title  : human-readable document title
            - section    : breadcrumb heading path within the document
            - snippet    : first 120 chars of the chunk (for logging)
            - distance   : cosine distance (lower = more similar)
    """
    model      = _get_model()
    collection = _get_collection()

    query_embedding = model.encode([query])[0].tolist()

    where_filter = {"doc_id": filter_doc_id} if filter_doc_id else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict[str, Any]] = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text":      doc,
            "doc_id":    meta["doc_id"],
            "doc_title": meta["doc_title"],
            "section":   meta["section"],
            "snippet":   meta["snippet"],
            "distance":  round(dist, 4),
        })

    return chunks


# ---------------------------------------------------------------------------
# Context formatter
# ---------------------------------------------------------------------------

def format_context(chunks: list[dict[str, Any]]) -> str:
    """
    Render retrieved chunks into a clearly delimited context block
    suitable for injection into an LLM prompt.

    Each chunk is labelled with its source citation so the model can
    reference it precisely (e.g. "[POL-PTO-002 § 2.1 Full-Time …]").
    """
    if not chunks:
        return "(No relevant policy context was retrieved.)"

    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        citation = f"[{chunk['doc_id']} § {chunk['section']}]"
        parts.append(
            f"--- Context {i} {citation} ---\n"
            f"{chunk['text'].strip()}\n"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# RAG system prompt template
# ---------------------------------------------------------------------------

def build_rag_prompt(
    user_query: str,
    retrieved_chunks: list[dict[str, Any]],
    employee_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """
    Construct the (system_prompt, user_message) pair for an LLM call.

    Args:
        user_query:        The original question from the employee.
        retrieved_chunks:  Output of retrieve_chunks().
        employee_context:  Optional dict with fields from employees.json
                           (e.g. name, role, pto_balance_days) for
                           personalised responses.

    Returns:
        (system_prompt, user_message) as a tuple of strings, ready for
        passing to the LLM's messages array.
    """
    context_block = format_context(retrieved_chunks)

    # Build optional employee context section
    if employee_context:
        emp_section = f"""
## Employee Context (from HR system of record)
- **Name:** {employee_context.get('name', 'N/A')}
- **Role:** {employee_context.get('role', 'N/A')}
- **PTO Balance:** {employee_context.get('pto_balance_days', 'N/A')} days
- **Remote Status:** {employee_context.get('remote_status', 'N/A')}
- **Office Location:** {employee_context.get('office_location', 'N/A')}
"""
    else:
        emp_section = ""

    # Source citation list for easy reference
    source_list = "\n".join(
        f"  - {c['doc_id']} — {c['doc_title']} (§ {c['section']})"
        for c in retrieved_chunks
    )

    system_prompt = f"""You are an official HR Policy Assistant for Acme Corp. \
Your role is to help employees understand company policies accurately and helpfully.

════════════════════════════════════════════════════════════════
RETRIEVED POLICY CONTEXT
════════════════════════════════════════════════════════════════
{context_block}

════════════════════════════════════════════════════════════════
SOURCES USED IN THIS CONTEXT
════════════════════════════════════════════════════════════════
{source_list}
{emp_section}
════════════════════════════════════════════════════════════════
STRICT BEHAVIOURAL GUARDRAILS — YOU MUST FOLLOW THESE
════════════════════════════════════════════════════════════════

**GUARDRAIL 1 — Always cite your source.**
Every factual claim you make MUST be followed immediately by its citation
in the format: [DOC-ID § Section Name].
Example: "You must submit expenses within 30 days [POL-EXP-001 § 2.2 Submission Deadline]."
Never state a policy fact without its citation. If a claim spans multiple
sections, cite each one.

**GUARDRAIL 2 — Refuse out-of-scope questions gracefully.**
If the user's question cannot be answered using ONLY the provided context above,
respond with this exact preamble and nothing more:
"I'm sorry, I don't have enough information in the provided policy documents
to answer that question accurately. Please contact People Operations at
people-ops@acmecorp.com or your direct manager for guidance."
Do NOT attempt to answer from general knowledge, make assumptions, or
extrapolate beyond what the context explicitly states.

**GUARDRAIL 3 — Distinguish policy facts from general advice.**
When answering, clearly label your statements:
- Use the prefix **[OFFICIAL POLICY]** when quoting or directly paraphrasing
  a specific rule from the documents.
- Use the prefix **[GENERAL GUIDANCE]** if you are offering a contextual
  suggestion or interpretation that is not a verbatim policy rule.
Never blend official policy language with general advice without these labels.

**GUARDRAIL 4 — Do not fabricate or hallucinate document content.**
Only refer to documents, section numbers, and policy rules that appear in
the RETRIEVED POLICY CONTEXT block above. Do not invent policy text, document
IDs, or section names that are not present.

**GUARDRAIL 5 — Acknowledge ambiguity; do not guess.**
If the retrieved context is ambiguous or appears to conflict, say so explicitly
and recommend the employee escalate to People Operations for a definitive answer.

**GUARDRAIL 6 — Protect confidential employee data.**
Never reveal or infer specific personal employee data (salaries, benefit
elections, PTO balances of others) in your response unless it is the
authenticated employee's own data provided in the Employee Context section.
════════════════════════════════════════════════════════════════
"""

    user_message = f"Employee question: {user_query}"

    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

def _demo(query: str) -> None:
    print(f"\nQuery: {query!r}\n")

    chunks = retrieve_chunks(query, top_k=DEFAULT_TOP_K)

    print(f"Retrieved {len(chunks)} chunks:")
    for i, c in enumerate(chunks, 1):
        print(f"  {i}. [{c['doc_id']} § {c['section']}]  dist={c['distance']}")
        print(f"     {c['snippet'][:90]}…")

    system_prompt, user_message = build_rag_prompt(query, chunks)

    print("\n" + "=" * 60)
    print("SYSTEM PROMPT PREVIEW (first 1200 chars):")
    print("=" * 60)
    print(system_prompt[:1200])
    print("…\n")
    print("USER MESSAGE:")
    print(user_message)


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "How many PTO days do I carry over if I have 5 years of service?"
    _demo(query)
