"""Test setup.

Tests run against a real Postgres (pgvector needs it). Point TEST_DATABASE_URL at an empty database:
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rag_test pytest
Without it, database tests are skipped and only the pure unit tests run.

The embedding model and the LLM are replaced with fakes, so tests are fast, free and deterministic.
"""

import hashlib
import math
import os
import re
import tempfile

import pytest

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://invalid:invalid@127.0.0.1:1/none")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
os.environ["LOG_LEVEL"] = "WARNING"

from app import embeddings, llm  # noqa: E402
from app.config import settings  # noqa: E402


def fake_embed(text: str) -> list[float]:
    """Bag-of-words vector: texts that share words are similar, which is enough to test retrieval."""
    vector = [0.0] * settings.embedding_dim
    for word in re.findall(r"\w+", text.lower()):
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % settings.embedding_dim] += 1
    norm = math.sqrt(sum(v * v for v in vector)) or 1
    return [v / norm for v in vector]


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    calls = []

    def fake_stream_chat(messages):
        calls.append(messages)
        return iter(["Employees get 24 days ", "of leave [1]."])

    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: [fake_embed(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", fake_embed)
    monkeypatch.setattr(llm, "stream_chat", fake_stream_chat)
    return calls


@pytest.fixture
def client():
    if "TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TEST_DATABASE_URL not set")
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:  # runs startup: creates tables + admin
        yield test_client


def register_and_login(client, email: str, password: str = "password123") -> dict:
    client.post("/auth/register", json={"email": email, "password": password})
    token = client.post("/auth/login", data={"username": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
