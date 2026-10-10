"""Document processing: file -> text per page -> overlapping chunks -> embeddings -> chunks table."""

import logging
import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete

from app import embeddings, storage
from app.config import settings
from app.db import SessionLocal
from app.models import Chunk, Document

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


def extract_pages(path: Path, filename: str) -> list[tuple[int | None, str]]:
    """Return (page_number, text) pairs. Text files have no pages, so page is None."""
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, start=1)]
    return [(None, path.read_text(encoding="utf-8", errors="replace"))]


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of about `size` characters.

    Each chunk tries to end at a paragraph, line, sentence or word boundary (in that order),
    and the next chunk starts `overlap` characters earlier so context isn't lost at the cut.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            for separator in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(separator, start + size // 2, end)
                if cut != -1:
                    end = cut + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest_document(document_id: int) -> None:
    """Index one document. Runs as a background task after upload or re-index.

    Never raises: on any error the document is marked "failed" with the reason, so the user can see it.
    """
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None:  # deleted before we got to it
            return
        try:
            pieces = [
                (page, chunk)
                for page, text in extract_pages(storage.file_path(document.id), document.filename)
                for chunk in split_text(text, settings.chunk_size, settings.chunk_overlap)
            ]
            if not pieces:
                raise ValueError("No text could be extracted (is it a scanned PDF?)")

            vectors = embeddings.embed_texts([chunk for _, chunk in pieces])

            # Replace old chunks (re-index) and add new ones in one transaction.
            db.execute(delete(Chunk).where(Chunk.document_id == document.id))
            db.add_all(
                Chunk(document_id=document.id, chunk_index=i, page=page, content=chunk, embedding=vector)
                for i, ((page, chunk), vector) in enumerate(zip(pieces, vectors))
            )
            document.status, document.num_chunks, document.error = "ready", len(pieces), None
            db.commit()
            logger.info("document indexed", extra={"document_id": document.id, "chunks": len(pieces)})
        except Exception as exc:
            db.rollback()
            logger.exception("document indexing failed", extra={"document_id": document_id})
            document.status, document.num_chunks, document.error = "failed", 0, str(exc)[:500]
            db.commit()
