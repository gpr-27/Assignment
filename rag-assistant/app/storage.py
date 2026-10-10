"""Original uploaded files live on disk (a Docker volume), named by document id.

Kept behind these three functions so swapping to S3 later only touches this file.
"""

from pathlib import Path

from app.config import settings


def file_path(document_id: int) -> Path:
    return Path(settings.storage_dir) / str(document_id)


def save_file(document_id: int, data: bytes) -> None:
    path = file_path(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def delete_file(document_id: int) -> None:
    file_path(document_id).unlink(missing_ok=True)
