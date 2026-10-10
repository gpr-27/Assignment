"""Test setup.

Tests run against a real Postgres. Point TEST_DATABASE_URL at an empty database:
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/attendance_test pytest
Without it, database tests are skipped and only the pure unit tests run.
The LLM is replaced with a scripted fake, so tests are fast, free and deterministic.
"""

import os
from types import SimpleNamespace

import pytest

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://invalid:invalid@127.0.0.1:1/none")
os.environ["LOG_LEVEL"] = "WARNING"

ADMIN = {"username": "admin@example.com", "password": "admin12345"}


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


def login(client, username: str, password: str) -> dict:
    token = client.post("/auth/login", data={"username": username, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client):
    return login(client, **ADMIN)


@pytest.fixture
def employee(client, admin):
    """Creates employee E100 on a 09:30 shift and returns their auth headers."""
    shift = client.post("/shifts", json={"name": "Day", "start_time": "09:30", "end_time": "18:30"}, headers=admin).json()
    client.post("/users", headers=admin, json={
        "employee_code": "E100", "full_name": "Test Employee", "email": "emp@acme.com",
        "phone": "+91 98765 43210", "department": "Engineering", "password": "password123", "shift_id": shift["id"],
    })
    return login(client, "emp@acme.com", "password123")


def tool_call(name: str, arguments: str):
    """Builds an object shaped like an OpenAI assistant message that requests one tool call."""
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(content=None, tool_calls=[call])


def final_answer(text: str):
    return SimpleNamespace(content=text, tool_calls=None)
