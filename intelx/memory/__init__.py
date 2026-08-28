"""INTELX Memory and Normalization Package."""

from intelx.memory.entities import (
    EntityResolver,
    compute_entity_similarity,
    normalize_entity_name,
)
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
    "EntityResolver",
    "normalize_entity_name",
    "compute_entity_similarity",
]
