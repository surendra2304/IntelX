"""INTELX Normalization and Chunking Pipeline Preserving Absolute Character Offsets."""

import hashlib
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import bs4
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.connectors.sanitize import IngestionSanitizer
from intelx.core.enums import SourceKind, TrustTier
from intelx.core.settings import Settings, get_settings
from intelx.db.models import Chunk, Document, Source
from intelx.db.repos import SourceRepo

logger = logging.getLogger(__name__)


@dataclass
class ChunkSpec:
    """Indexed chunk specification with absolute character boundaries."""

    idx: int
    start_char: int
    end_char: int
    text: str


@dataclass
class NormalizedDocument:
    """Normalized plain text extraction with computed chunks and cryptographic hash."""

    text: str
    fingerprint: str
    chunks: list[ChunkSpec]
    injection_risk: bool
    flags_count: int


def normalize_text_content(raw_bytes: bytes, content_type: str, filename: str = "") -> str:
    """Convert arbitrary content bytes to normalized text preserving reading order."""
    mime = content_type.split(";")[0].strip().lower()

    if mime in ("text/plain", "text/markdown", "text/csv"):
        return raw_bytes.decode("utf-8", errors="replace")

    elif mime == "application/json":
        try:
            parsed = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            return json.dumps(parsed, indent=2)
        except Exception:
            return raw_bytes.decode("utf-8", errors="replace")

    elif mime == "text/html":
        soup = bs4.BeautifulSoup(raw_bytes.decode("utf-8", errors="replace"), "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    elif mime == "application/pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for p in reader.pages:
                t = p.extract_text()
                if t:
                    pages.append(t.strip())
            return "\n\n".join(pages)
        except Exception as e:
            logger.warning(f"PDF extraction fallback: {e}")
            return raw_bytes.decode("utf-8", errors="replace")

    elif "wordprocessingml" in mime or filename.endswith(".docx"):
        try:
            import docx

            doc = docx.Document(io.BytesIO(raw_bytes))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.warning(f"DOCX extraction fallback: {e}")
            return raw_bytes.decode("utf-8", errors="replace")

    return raw_bytes.decode("utf-8", errors="replace")


def chunk_text_with_offsets(
    text: str,
    target_size: int = 1200,
    overlap: int = 150,
) -> list[ChunkSpec]:
    """Slice document text into overlapping chunks with guaranteed absolute character offsets."""
    if not text:
        return []

    total_len = len(text)
    if total_len <= target_size:
        return [ChunkSpec(idx=0, start_char=0, end_char=total_len, text=text)]

    chunks: list[ChunkSpec] = []
    start = 0
    idx = 0

    while start < total_len:
        end = min(start + target_size, total_len)

        # If not at the very end of text, attempt to find a clean sentence or newline boundary
        if end < total_len:
            newline_pos = text.rfind("\n", start + overlap, end)
            period_pos = text.rfind(". ", start + overlap, end)

            if newline_pos != -1 and newline_pos > start + (target_size // 2):
                end = newline_pos + 1
            elif period_pos != -1 and period_pos > start + (target_size // 2):
                end = period_pos + 2

        chunk_slice = text[start:end]
        chunks.append(
            ChunkSpec(
                idx=idx,
                start_char=start,
                end_char=end,
                text=chunk_slice,
            )
        )
        idx += 1

        if end >= total_len:
            break

        start = max(start + 1, end - overlap)

    return chunks


async def ingest_and_normalize(
    session: AsyncSession,
    raw_bytes: bytes,
    location: str,
    kind: SourceKind,
    content_type: str = "text/html",
    title: str | None = None,
    domain: str | None = None,
    publisher: str | None = None,
    robots_ok: bool = True,
    created_by_run_id: str | None = None,
    settings: Settings | None = None,
) -> tuple[Source, Document, list[Chunk], bool]:
    """Normalize raw content, enforce deduplication, persist document and chunk hierarchy."""
    cfg = settings or get_settings()

    # 1. Normalize plain text
    normalized_text = normalize_text_content(raw_bytes, content_type, filename=location)
    fingerprint = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

    # 2. Check for deduplication
    existing_source = await SourceRepo.get_source_by_fingerprint(session, fingerprint)
    if existing_source:
        doc = await SourceRepo.get_document_by_source_id(session, existing_source.id)
        if doc is None:
            doc = await SourceRepo.create_document(
                session=session, source_id=existing_source.id, text_content=normalized_text
            )
        return existing_source, doc, [], False

    # 2.5 Redact high-entropy secrets while preserving character offsets
    from intelx.core.security import redact_document_text_preserving_length

    processed_text, redactions = redact_document_text_preserving_length(normalized_text)
    if redactions:
        sidecar_path = Path("./data/raw").resolve() / f"{fingerprint}.redactions.json"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(redactions, indent=2), encoding="utf-8")

    # 3. Prompt injection scan
    sanitizer = IngestionSanitizer()
    scan_res = sanitizer.scan(processed_text, fingerprint=fingerprint)

    # 4. Determine initial trust tier
    if kind == SourceKind.FILE:
        trust_tier = TrustTier.STANDARD
    else:
        # Web domain check against allowlist
        if domain and any(
            domain.lower() == a.lower() or domain.lower().endswith(f".{a.lower()}")
            for a in cfg.DOMAIN_ALLOWLIST
        ):
            trust_tier = TrustTier.STANDARD
        else:
            trust_tier = TrustTier.QUARANTINE

    # 5. Persist raw bytes on disk
    ext = Path(location).suffix if Path(location).suffix else ".bin"
    raw_dir = Path("./data/raw").resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{fingerprint}{ext}"
    raw_path.write_bytes(raw_bytes)

    # 6. Create Source record
    source = await SourceRepo.create_source(
        session=session,
        kind=kind,
        location=location,
        domain=domain,
        publisher=publisher,
        title=title,
        content_type=content_type,
        fingerprint=fingerprint,
        trust_tier=trust_tier,
        robots_ok=robots_ok,
        injection_risk=scan_res.injection_risk,
        raw_path=str(raw_path),
        created_by_run_id=created_by_run_id,
    )

    # 7. Create Document record
    doc = await SourceRepo.create_document(
        session=session,
        source_id=source.id,
        text_content=processed_text,
    )
    if redactions:
        doc.version = 2

    # 8. Create Chunks with strict offset verification
    chunks_spec = chunk_text_with_offsets(processed_text)
    persisted_chunks: list[Chunk] = []

    for spec in chunks_spec:
        assert normalized_text[spec.start_char : spec.end_char] == spec.text
        chunk = await SourceRepo.create_chunk(
            session=session,
            document_id=doc.id,
            idx=spec.idx,
            start_char=spec.start_char,
            end_char=spec.end_char,
            text_content=spec.text,
        )
        persisted_chunks.append(chunk)

    return source, doc, persisted_chunks, True
