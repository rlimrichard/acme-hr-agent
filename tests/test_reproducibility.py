"""Checks that source-derived index identities do not depend on RNG state."""

from src.rag.chunk_ids import stable_chunk_id
from src.rag.config import EMBEDDING_MODEL, EMBEDDING_REVISION


def test_embedding_model_is_pinned_to_a_commit() -> None:
    assert EMBEDDING_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
    assert len(EMBEDDING_REVISION) == 40
    assert all(ch in "0123456789abcdef" for ch in EMBEDDING_REVISION)


def test_chunk_id_is_repeatable_and_sensitive_to_source_position_and_text() -> None:
    first = stable_chunk_id("POL-PTO-002", 4, 1, "Sick leave uses the PTO bank.")
    assert first == stable_chunk_id("POL-PTO-002", 4, 1, "Sick leave uses the PTO bank.")
    assert len(first) == 64
    assert first != stable_chunk_id("POL-PTO-002", 5, 1, "Sick leave uses the PTO bank.")
    assert first != stable_chunk_id("POL-PTO-002", 4, 2, "Sick leave uses the PTO bank.")
    assert first != stable_chunk_id("POL-PTO-002", 4, 1, "Sick leave uses a separate bank.")
    assert first != stable_chunk_id("POL-LOA-008", 4, 1, "Sick leave uses the PTO bank.")

