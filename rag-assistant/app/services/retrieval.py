"""Finds the chunks most similar to a question, using pgvector cosine distance."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import embeddings
from app.models import Chunk, Collection, Document


@dataclass
class Source:
    number: int  # the [n] the model uses to cite it
    document_id: int
    filename: str
    page: int | None
    content: str
    score: float  # cosine similarity, 1.0 = identical

    def as_citation(self) -> dict:
        return {
            "number": self.number,
            "document_id": self.document_id,
            "filename": self.filename,
            "page": self.page,
            "snippet": self.content[:300],
        }


def search(
    db: Session, namespace_id: int, query: str, collection_ids: list[int] | None, top_k: int
) -> list[Source]:
    query_vector = embeddings.embed_query(query)
    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(Chunk, Document.filename, distance)
        .join(Document, Chunk.document_id == Document.id)
        .join(Collection, Document.collection_id == Collection.id)
        .where(Collection.namespace_id == namespace_id, Document.status == "ready")
        .order_by(distance)
        .limit(top_k)
    )
    if collection_ids:
        stmt = stmt.where(Collection.id.in_(collection_ids))

    return [
        Source(
            number=i,
            document_id=chunk.document_id,
            filename=filename,
            page=chunk.page,
            content=chunk.content,
            score=round(1 - dist, 4),
        )
        for i, (chunk, filename, dist) in enumerate(db.execute(stmt).all(), start=1)
    ]
