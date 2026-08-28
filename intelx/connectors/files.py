"""INTELX Local and Uploaded File Ingestion Connector (PDF, DOCX, HTML, MD, TXT, CSV, JSON)."""

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bs4

from intelx.connectors.base import BaseConnector
from intelx.core.errors import ContentSizeExceededError, UnsupportedContentTypeError
from intelx.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

SUPPORTED_FILE_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


@dataclass
class FileIngestResult:
    """Outcome of file parsing and extraction."""

    filename: str
    extension: str
    content_type: str
    raw_bytes: bytes
    extracted_text: str


class FileConnector(BaseConnector):
    """Secure local file ingestion connector with format validation and size caps."""

    def __init__(self, settings: Settings | None = None, **kwargs: Any) -> None:
        super().__init__(
            name="file_ingest",
            capabilities=["parse_pdf", "parse_docx", "parse_html", "parse_text"],
            required_credentials=[],
            classification="LOCAL_STORAGE",
            **kwargs,
        )
        self.settings = settings or get_settings()

    def parse_bytes(self, raw_bytes: bytes, filename: str) -> FileIngestResult:
        """Extract text from in-memory byte buffer based on filename extension."""
        if len(raw_bytes) > self.settings.MAX_PAGE_BYTES:
            err_msg = (
                f"File '{filename}' ({len(raw_bytes)} bytes) exceeds "
                f"MAX_PAGE_BYTES ({self.settings.MAX_PAGE_BYTES})"
            )
            raise ContentSizeExceededError(
                err_msg,
                details={"filename": filename, "size": len(raw_bytes)},
            )

        path = Path(filename)
        ext = path.suffix.lower()
        if ext not in SUPPORTED_FILE_EXTENSIONS:
            allowed = list(SUPPORTED_FILE_EXTENSIONS.keys())
            raise UnsupportedContentTypeError(
                f"Unsupported file format '{ext}'. Supported: {allowed}",
                details={"filename": filename, "extension": ext},
            )

        content_type = SUPPORTED_FILE_EXTENSIONS[ext]
        extracted_text = self._extract_text(raw_bytes, ext, filename)

        return FileIngestResult(
            filename=filename,
            extension=ext,
            content_type=content_type,
            raw_bytes=raw_bytes,
            extracted_text=extracted_text,
        )

    def _extract_text(self, raw_bytes: bytes, ext: str, filename: str) -> str:
        """Extract normalized plain text preserving reading order."""
        if ext in (".txt", ".md", ".markdown", ".csv"):
            return raw_bytes.decode("utf-8", errors="replace")

        elif ext == ".json":
            try:
                parsed = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return json.dumps(parsed, indent=2)
            except Exception:
                return raw_bytes.decode("utf-8", errors="replace")

        elif ext in (".html", ".htm"):
            soup = bs4.BeautifulSoup(raw_bytes.decode("utf-8", errors="replace"), "html.parser")
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            return soup.get_text(separator="\n", strip=True)

        elif ext == ".pdf":
            try:
                import pypdf

                reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
                pages_text = []
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt:
                        pages_text.append(txt)
                return "\n\n".join(pages_text)
            except ImportError:
                logger.warning("pypdf not available, falling back to plain string decoding")
                return raw_bytes.decode("utf-8", errors="replace")

        elif ext == ".docx":
            try:
                import docx

                doc = docx.Document(io.BytesIO(raw_bytes))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return "\n\n".join(paragraphs)
            except ImportError:
                logger.warning("python-docx not available, falling back to plain string decoding")
                return raw_bytes.decode("utf-8", errors="replace")

        return raw_bytes.decode("utf-8", errors="replace")

    async def fetch(self, target: str, **kwargs: Any) -> FileIngestResult:
        """Read local file from disk path."""
        path = Path(target).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Target file not found: {target}")

        raw_bytes = path.read_bytes()
        return self.parse_bytes(raw_bytes, path.name)
