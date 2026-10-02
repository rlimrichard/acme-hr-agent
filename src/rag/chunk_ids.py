"""Stable IDs for policy chunks across identical ingestion runs."""

import hashlib
import json


def stable_chunk_id(doc_id: str, section_index: int, chunk_index: int, text: str) -> str:
    """Identify a chunk by source, position, and exact text, without randomness."""
    payload = json.dumps(
        [doc_id, section_index, chunk_index, text],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

