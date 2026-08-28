"""INTELX Memory and Normalization Package."""

from intelx.memory.normalize import (
    ChunkSpec,
    NormalizedDocument,
    chunk_text_with_offsets,
    ingest_and_normalize,
    normalize_text_content,
)

__all__ = [
    "ChunkSpec",
    "NormalizedDocument",
    "normalize_text_content",
    "chunk_text_with_offsets",
    "ingest_and_normalize",
]
