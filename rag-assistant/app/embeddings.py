"""Turns text into vectors with a small local model (fastembed / ONNX, no GPU or API key needed)."""

from functools import lru_cache

from fastembed import TextEmbedding

from app.config import settings


@lru_cache
def _model() -> TextEmbedding:
    # Loaded once on first use (downloaded on first run, baked into the Docker image).
    return TextEmbedding(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _model().embed(texts, batch_size=32)]


def embed_query(text: str) -> list[float]:
    # query_embed adds the model's "search query" prefix, which improves retrieval.
    return next(iter(_model().query_embed(text))).tolist()
