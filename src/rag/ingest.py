"""
HR Policy Ingestion Pipeline
Supports .md, .html, .txt, and .pdf source documents.
Chunks each document (heading-aware for md/html, paragraph-based for txt/pdf)
and embeds them into a local ChromaDB collection.
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from bs4 import BeautifulSoup
from chromadb.config import Settings
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLICIES_DIR = Path(__file__).parent.parent.parent / "data" / "policies"
CHROMA_DIR   = Path(__file__).parent.parent.parent / "chroma_db"
COLLECTION_NAME = "hr_policies"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Recursive splitter parameters
CHUNK_SIZE    = 512   # characters
CHUNK_OVERLAP = 64    # characters

# Document ID mapping  (filename stem → stable doc ID from the policy header)
DOC_ID_MAP = {
    "remote_work_policy":              "POL-RW-001",
    "pto_policy":                      "POL-PTO-002",
    "expense_reimbursement_policy":    "POL-EXP-001",
    "company_holidays_policy":         "POL-HOL-003",
    "data_security_policy":            "POL-SEC-004",
    "employee_benefits_policy":        "POL-BEN-005",
    "onboarding_policy":               "POL-ONB-006",
    "equipment_asset_management_policy": "POL-EQP-007",
    "leave_of_absence_policy":         "POL-LOA-008",
    "workplace_conduct_policy":        "POL-WPC-009",
    "performance_management_policy":   "POL-PFM-010",
    "offboarding_policy":              "POL-OFB-011",
    "compensation_policy":             "POL-CMP-012",
    "learning_development_policy":     "POL-LND-013",
    "dei_policy":                      "POL-DEI-014",
    "health_safety_policy":            "POL-HSF-015",
    "recruitment_hiring_policy":       "POL-REC-016",
    "ai_acceptable_use_policy":        "POL-AIU-017",
    "employee_privacy_policy":         "POL-PRV-018",
    "vendor_management_policy":        "POL-VND-019",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HeadingSection:
    """Represents a contiguous block of text under a particular Markdown heading."""
    doc_id:      str
    doc_title:   str
    heading:     str          # e.g. "## 3. PTO Usage > ### 3.1 Requesting Time Off"
    heading_level: int        # 1 / 2 / 3
    content:     str          # raw text below the heading


@dataclass
class Chunk:
    """A single embeddable unit with full provenance metadata."""
    chunk_id:    str
    doc_id:      str
    doc_title:   str
    section:     str          # breadcrumb heading path
    text:        str          # the chunk text
    snippet:     str          # first 120 chars for quick inspection


# ---------------------------------------------------------------------------
# Step 1 – Heading-aware splitting
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _extract_doc_title(text: str, fallback: str = "Unknown") -> str:
    """Return the H1 title if present, otherwise the provided fallback."""
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _title_from_stem(stem: str) -> str:
    """Derive a human-readable title from a filename stem, e.g. 'pto_policy' → 'Pto Policy'."""
    return stem.replace("_", " ").title()


def split_by_headings(markdown: str, doc_id: str, fallback_title: str = "Unknown") -> list[HeadingSection]:
    """
    Walk all H1/H2/H3 headings and collect the text that follows each one
    until the next heading of equal or higher level.
    Returns a flat list of HeadingSection objects with a breadcrumb path.
    """
    doc_title = _extract_doc_title(markdown, fallback=fallback_title)

    # Collect (start_pos, level, heading_text) for every heading
    headings: list[tuple[int, int, str]] = []
    for m in HEADING_RE.finditer(markdown):
        level = len(m.group(1))
        text  = m.group(2).strip()
        headings.append((m.start(), level, text))

    if not headings:
        # No headings — treat entire document as one section
        return [HeadingSection(doc_id, doc_title, doc_title, 1, markdown)]

    sections: list[HeadingSection] = []
    # Breadcrumb stack: index = heading level-1, value = current label
    crumb: list[str] = ["", "", ""]

    for i, (start, level, label) in enumerate(headings):
        crumb[level - 1] = label
        # Clear deeper levels when ascending
        for deeper in range(level, 3):
            crumb[deeper] = ""

        # Content = text between this heading and the next heading
        end = headings[i + 1][0] if i + 1 < len(headings) else len(markdown)
        raw = markdown[start:end]
        # Strip the heading line itself; keep only the body text
        body = raw.split("\n", 1)[1].strip() if "\n" in raw else ""

        breadcrumb = " > ".join(c for c in crumb if c)
        sections.append(HeadingSection(
            doc_id=doc_id,
            doc_title=doc_title,
            heading=breadcrumb,
            heading_level=level,
            content=body,
        ))

    return sections


# ---------------------------------------------------------------------------
# Step 2 – Recursive character splitter
# ---------------------------------------------------------------------------

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _split_text(text: str, size: int, overlap: int,
                separators: list[str]) -> list[str]:
    """
    Recursively split `text` into chunks of at most `size` characters,
    trying each separator in order. Applies `overlap` character overlap
    between consecutive chunks.
    """
    if len(text) <= size:
        return [text] if text.strip() else []

    # Try each separator in order
    for sep in separators:
        if sep == "" or sep in text:
            parts = text.split(sep) if sep else list(text)
            chunks: list[str] = []
            current = ""
            for part in parts:
                candidate = (current + sep + part) if current else part
                if len(candidate) <= size:
                    current = candidate
                else:
                    if current.strip():
                        chunks.append(current)
                    # If single part already exceeds size, recurse with next sep
                    if len(part) > size:
                        idx = separators.index(sep)
                        sub = _split_text(part, size, overlap, separators[idx + 1:])
                        chunks.extend(sub)
                        current = ""
                    else:
                        current = part
            if current.strip():
                chunks.append(current)

            # Apply overlap: prefix each chunk (except first) with the tail
            # of the previous chunk
            if overlap > 0 and len(chunks) > 1:
                overlapped: list[str] = [chunks[0]]
                for k in range(1, len(chunks)):
                    tail = overlapped[k - 1][-overlap:]
                    overlapped.append(tail + sep + chunks[k])
                return overlapped
            return chunks

    return [text]


def chunk_section(section: HeadingSection,
                  chunk_size: int = CHUNK_SIZE,
                  overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    """Convert a HeadingSection into one or more Chunk objects."""
    raw_chunks = _split_text(section.content, chunk_size, overlap, SEPARATORS)
    # If section has no body (e.g. a heading-only line), emit one minimal chunk
    if not raw_chunks:
        raw_chunks = [section.heading]

    result: list[Chunk] = []
    for text in raw_chunks:
        text = text.strip()
        if not text:
            continue
        result.append(Chunk(
            chunk_id=str(uuid.uuid4()),
            doc_id=section.doc_id,
            doc_title=section.doc_title,
            section=section.heading,
            text=text,
            snippet=text[:120].replace("\n", " "),
        ))
    return result


# ---------------------------------------------------------------------------
# Step 3 – Format-aware parsers: all return plain Markdown-like text
# ---------------------------------------------------------------------------

def _parse_md(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_html(path: Path) -> str:
    """Convert HTML headings → markdown # syntax, strip remaining tags."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "br"]):
        tag = el.name
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if tag == "h1":
            lines.append(f"# {text}")
        elif tag == "h2":
            lines.append(f"## {text}")
        elif tag == "h3":
            lines.append(f"### {text}")
        elif tag == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _parse_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text.strip())
    return "\n\n".join(p for p in pages if p)


_PARSERS = {
    ".md":   _parse_md,
    ".html": _parse_html,
    ".txt":  _parse_txt,
    ".pdf":  _parse_pdf,
}

SUPPORTED_EXTENSIONS = set(_PARSERS)


# ---------------------------------------------------------------------------
# Step 4 – Load, parse, and chunk all policy files
# ---------------------------------------------------------------------------

def load_and_chunk_policies(policies_dir: Path) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    policy_files = sorted(
        f for f in policies_dir.iterdir()
        if f.suffix in SUPPORTED_EXTENSIONS
    )
    for policy_file in policy_files:
        stem   = policy_file.stem
        doc_id = DOC_ID_MAP.get(stem, stem.upper())
        fmt    = policy_file.suffix

        parser         = _PARSERS[fmt]
        text           = parser(policy_file)
        fallback_title = _title_from_stem(stem)

        sections = split_by_headings(text, doc_id, fallback_title=fallback_title)
        file_chunks: list[Chunk] = []
        for section in sections:
            file_chunks.extend(chunk_section(section))

        print(f"  [{doc_id}] {policy_file.name} ({fmt}): "
              f"{len(sections)} sections → {len(file_chunks)} chunks")
        all_chunks.extend(file_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Step 5 – Embed and insert into ChromaDB
# ---------------------------------------------------------------------------

def build_chroma_collection(chunks: list[Chunk],
                             chroma_dir: Path,
                             collection_name: str) -> chromadb.Collection:
    print(f"\nLoading embedding model: {EMBEDDING_MODEL} …")
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(
        path=str(chroma_dir),
        settings=Settings(anonymized_telemetry=False),
    )

    # Drop and recreate for idempotent re-runs
    try:
        client.delete_collection(collection_name)
        print(f"Dropped existing collection '{collection_name}'.")
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    print(f"Embedding {len(chunks)} chunks …")
    texts = [c.text for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)

    # Batch-insert in groups of 500 to avoid memory spikes
    batch_size = 500
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start: start + batch_size]
        batch_emb = embeddings[start: start + batch_size].tolist()
        collection.add(
            ids        = [c.chunk_id for c in batch],
            embeddings = batch_emb,
            documents  = [c.text     for c in batch],
            metadatas  = [
                {
                    "doc_id":    c.doc_id,
                    "doc_title": c.doc_title,
                    "section":   c.section,
                    "snippet":   c.snippet,
                }
                for c in batch
            ],
        )

    print(f"Inserted {len(chunks)} chunks into collection '{collection_name}'.")
    return collection


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("HR Policy RAG Ingestion Pipeline")
    print("=" * 60)

    print(f"\nScanning: {POLICIES_DIR}")
    chunks = load_and_chunk_policies(POLICIES_DIR)
    print(f"\nTotal chunks generated: {len(chunks)}")

    collection = build_chroma_collection(chunks, CHROMA_DIR, COLLECTION_NAME)

    # Spot-check
    print("\nSpot-check: sample chunk metadata from collection:")
    sample = collection.peek(limit=2)
    for i, (doc, meta) in enumerate(zip(sample["documents"], sample["metadatas"])):
        print(f"\n  -- Chunk {i + 1} --")
        print(f"  doc_id  : {meta['doc_id']}")
        print(f"  section : {meta['section']}")
        print(f"  snippet : {meta['snippet'][:80]}…")

    print("\nIngestion complete.")


if __name__ == "__main__":
    main()
