"""Document lifecycle: upload -> processing -> ready/failed -> (re-index) -> delete."""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.config import settings
from app.db import get_db
from app.models import Document, User
from app.schemas import DocumentOut
from app.security import get_current_user
from app.services import access
from app.services.ingestion import ALLOWED_EXTENSIONS, ingest_document

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


@router.post(
    "/collections/{collection_id}/documents", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED
)
def upload_document(
    collection_id: int,
    file: UploadFile,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accepts the file and returns immediately with status "processing". Poll GET /documents/{id} for status."""
    collection = access.get_collection(db, user, collection_id)

    filename = Path(file.filename or "").name  # strip any path the client sent
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are supported")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(status_code=400, detail="File is empty")

    sha256 = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document).where(Document.collection_id == collection.id, Document.sha256 == sha256)):
        raise HTTPException(status_code=409, detail="This file is already in the collection")

    document = Document(
        collection_id=collection.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256=sha256,
        status="processing",
        uploaded_by=user.id,
    )
    db.add(document)
    db.flush()  # assigns document.id so we can name the file
    storage.save_file(document.id, data)
    db.commit()

    background.add_task(ingest_document, document.id)
    logger.info("document uploaded", extra={"document_id": document.id, "size_bytes": len(data)})
    return document


@router.get("/collections/{collection_id}/documents", response_model=list[DocumentOut])
def list_documents(collection_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    collection = access.get_collection(db, user, collection_id)
    return db.scalars(
        select(Document).where(Document.collection_id == collection.id).order_by(Document.created_at.desc())
    ).all()


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return access.get_document(db, user, document_id)


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reindex_document(
    document_id: int,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run chunking + embedding, e.g. after changing the chunk size or embedding model."""
    document = access.get_document(db, user, document_id)
    if document.status == "processing":
        raise HTTPException(status_code=409, detail="Document is already being processed")
    document.status, document.error = "processing", None
    db.commit()
    background.add_task(ingest_document, document.id)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = access.get_document(db, user, document_id)
    db.delete(document)  # chunks are removed by ON DELETE CASCADE
    db.commit()
    storage.delete_file(document_id)
    logger.info("document deleted", extra={"document_id": document_id})
