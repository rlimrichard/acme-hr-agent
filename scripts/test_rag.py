"""
RAG chunking and retrieval diagnostic tests.

Run:
    python scripts/test_rag.py
"""

import sys
from pathlib import Path

# Make src importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.config import Settings
from src.rag.retrieval import retrieve_chunks

CHROMA_DIR      = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "hr_policies"

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"
WARN = "\033[93m WARN\033[0m"


def get_collection():
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_collection(COLLECTION_NAME)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def check(label: str, condition: bool, detail: str = "") -> bool:
    tag = PASS if condition else FAIL
    print(f"  [{tag}] {label}" + (f"  →  {detail}" if detail else ""))
    return condition


def warn(label: str, condition: bool, detail: str = "") -> bool:
    tag = PASS if condition else WARN
    print(f"  [{tag}] {label}" + (f"  →  {detail}" if detail else ""))
    return condition


# ---------------------------------------------------------------------------
# 1. Coverage: all 20 docs indexed
# ---------------------------------------------------------------------------

EXPECTED_DOC_IDS = {
    "POL-AIU-017", "POL-HOL-003", "POL-CMP-012", "POL-SEC-004",
    "POL-DEI-014", "POL-BEN-005", "POL-PRV-018", "POL-EQP-007",
    "POL-EXP-001", "POL-HSF-015", "POL-LND-013", "POL-LOA-008",
    "POL-OFB-011", "POL-ONB-006", "POL-PFM-010", "POL-PTO-002",
    "POL-REC-016", "POL-RW-001",  "POL-VND-019", "POL-WPC-009",
}

# Formats used during ingestion
FORMAT_BY_DOC = {
    "POL-RW-001":  "md",  "POL-PTO-002": "md",  "POL-SEC-004": "md",
    "POL-BEN-005": "md",  "POL-WPC-009": "md",
    "POL-EXP-001": "html","POL-ONB-006": "html","POL-HOL-003": "html",
    "POL-LOA-008": "html","POL-OFB-011": "html",
    "POL-CMP-012": "txt", "POL-DEI-014": "txt", "POL-HSF-015": "txt",
    "POL-REC-016": "txt", "POL-VND-019": "txt",
    "POL-AIU-017": "pdf", "POL-PRV-018": "pdf", "POL-EQP-007": "pdf",
    "POL-LND-013": "pdf", "POL-PFM-010": "pdf",
}

MIN_CHUNKS_PER_DOC = 5   # every policy should produce at least 5 chunks


def test_coverage(col):
    print("\n=== 1. Coverage ===")
    all_meta = col.get(include=["metadatas"])["metadatas"]
    total    = len(all_meta)
    by_doc   = {}
    for m in all_meta:
        by_doc.setdefault(m["doc_id"], []).append(m)

    check("Total chunks > 500", total > 500, f"{total} chunks")

    found_ids = set(by_doc.keys())
    missing   = EXPECTED_DOC_IDS - found_ids
    check("All 20 doc IDs present", not missing, f"missing: {missing}" if missing else "")

    for doc_id, chunks in sorted(by_doc.items()):
        fmt = FORMAT_BY_DOC.get(doc_id, "?")
        ok  = len(chunks) >= MIN_CHUNKS_PER_DOC
        check(f"{doc_id} ({fmt}): ≥{MIN_CHUNKS_PER_DOC} chunks",
              ok, f"{len(chunks)} chunks")


# ---------------------------------------------------------------------------
# 2. Metadata quality: section and doc_title populated
# ---------------------------------------------------------------------------

def test_metadata(col):
    print("\n=== 2. Metadata Quality ===")
    all_data = col.get(include=["metadatas", "documents"])
    by_doc   = {}
    for m, d in zip(all_data["metadatas"], all_data["documents"]):
        by_doc.setdefault(m["doc_id"], []).append((m, d))

    for doc_id, items in sorted(by_doc.items()):
        fmt = FORMAT_BY_DOC.get(doc_id, "?")

        # doc_title should never be "Unknown"
        bad_title = [m for m, _ in items if m["doc_title"] == "Unknown"]
        check(f"{doc_id} ({fmt}): doc_title not 'Unknown'",
              not bad_title, f"{len(bad_title)}/{len(items)} chunks have Unknown title")

        # section should not be empty for md/html (they have headings)
        if fmt in ("md", "html"):
            no_section = [m for m, _ in items if not m["section"].strip()]
            check(f"{doc_id} ({fmt}): section breadcrumb present",
                  not no_section,
                  f"{len(no_section)}/{len(items)} chunks missing section")

        # snippet should be non-empty
        no_snippet = [m for m, _ in items if not m["snippet"].strip()]
        check(f"{doc_id} ({fmt}): snippet populated",
              not no_snippet,
              f"{len(no_snippet)}/{len(items)} chunks missing snippet")


# ---------------------------------------------------------------------------
# 3. Chunk text quality: no excessive overlap duplication
# ---------------------------------------------------------------------------

def test_chunk_text(col):
    print("\n=== 3. Chunk Text Quality ===")
    all_data = col.get(include=["metadatas", "documents"])

    duplicated = 0
    empty      = 0
    too_long   = 0
    total      = len(all_data["documents"])

    for doc, meta in zip(all_data["documents"], all_data["metadatas"]):
        if not doc.strip():
            empty += 1
        if len(doc) > 700:   # 512 target + 64 overlap + margin
            too_long += 1
        # detect overlap duplication: same substring of ≥80 chars repeated
        if len(doc) > 160:
            half = doc[: len(doc) // 2]
            if half in doc[len(half):]:
                duplicated += 1

    check("No empty chunks",           empty == 0,      f"{empty} empty")
    check("No chunks > 700 chars",     too_long == 0,   f"{too_long}/{total} oversized")
    warn( "Minimal overlap duplication",duplicated == 0, f"{duplicated}/{total} chunks appear duplicated")


# ---------------------------------------------------------------------------
# 4. Retrieval quality: targeted queries
# ---------------------------------------------------------------------------

RETRIEVAL_TESTS = [
    # (query, expected_doc_id_in_top3, description)
    ("How many PTO days do I accrue per year?",          "POL-PTO-002",  "PTO accrual"),
    ("Can I work remotely from another country?",        "POL-RW-001",   "remote work"),
    ("What is the expense limit for home office chairs?","POL-EXP-001",  "expense policy"),
    ("What benefits am I eligible for?",                 "POL-BEN-005",  "benefits"),
    ("What counts as workplace misconduct?",             "POL-WPC-009",  "conduct policy"),
    ("How do I request a leave of absence?",             "POL-LOA-008",  "leave policy"),
    ("What are the data security requirements?",         "POL-SEC-004",  "data security"),
    ("What AI tools am I allowed to use?",               "POL-AIU-017",  "AI acceptable use (PDF)"),
    ("How does performance review work?",                "POL-PFM-010",  "perf mgmt (PDF)"),
    ("What is the onboarding process for new hires?",    "POL-ONB-006",  "onboarding (HTML)"),
]

GOOD_DISTANCE_THRESHOLD = 0.45


def test_retrieval():
    print("\n=== 4. Retrieval Quality ===")
    all_pass = True
    for query, expected_doc, label in RETRIEVAL_TESTS:
        chunks = retrieve_chunks(query, top_k=3)
        top_docs = [c["doc_id"] for c in chunks]
        top_dist = [c["distance"] for c in chunks]

        in_top3  = expected_doc in top_docs
        best     = top_dist[0] if top_dist else 1.0
        good_sim = best < GOOD_DISTANCE_THRESHOLD

        ok = check(
            f"{label}: {expected_doc} in top-3",
            in_top3,
            f"got {top_docs}  best_dist={best:.3f}",
        )
        warn(
            f"{label}: best distance < {GOOD_DISTANCE_THRESHOLD}",
            good_sim,
            f"dist={best:.3f}",
        )
        all_pass = all_pass and ok
    return all_pass


# ---------------------------------------------------------------------------
# 5. Multi-document retrieval
# ---------------------------------------------------------------------------

MULTI_DOC_TESTS = [
    (
        "Can I expense a home office chair and also get the remote work stipend?",
        {"POL-EXP-001", "POL-RW-001"},
        "expense + remote work (multi-doc)",
    ),
    (
        "What are the PTO policy rules during a leave of absence?",
        {"POL-PTO-002", "POL-LOA-008"},
        "PTO + leave of absence (multi-doc)",
    ),
]


def test_multi_doc_retrieval():
    print("\n=== 5. Multi-Document Retrieval ===")
    for query, expected_docs, label in MULTI_DOC_TESTS:
        chunks   = retrieve_chunks(query, top_k=6)
        found    = {c["doc_id"] for c in chunks}
        covered  = expected_docs & found
        check(
            f"{label}",
            len(covered) == len(expected_docs),
            f"found {covered} of {expected_docs}",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("RAG Chunking & Retrieval Diagnostic")
    print("=" * 60)

    col = get_collection()

    test_coverage(col)
    test_metadata(col)
    test_chunk_text(col)
    test_retrieval()
    test_multi_doc_retrieval()

    print("\n" + "=" * 60)
    print("Done. Review WARN/FAIL lines above for issues to fix.")
    print("=" * 60)


if __name__ == "__main__":
    main()
