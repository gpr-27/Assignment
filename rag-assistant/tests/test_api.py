"""End-to-end API tests: auth -> namespace -> collection -> upload -> chat (streaming + citations)."""

import json

from tests.conftest import register_and_login

POLICY = b"Leave policy. Every employee gets 24 days of paid leave per year.\n\nThe office opens at 9 am."


def setup_collection(client, headers):
    ns = client.post("/namespaces", json={"name": "acme"}, headers=headers).json()
    col = client.post(f"/namespaces/{ns['id']}/collections", json={"name": "hr"}, headers=headers).json()
    return ns, col


def upload(client, headers, collection_id, content=POLICY, name="policy.txt"):
    return client.post(
        f"/collections/{collection_id}/documents", files={"file": (name, content, "text/plain")}, headers=headers
    )


def parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_auth_flow(client):
    assert client.post("/auth/register", json={"email": "a@x.com", "password": "password123"}).status_code == 201
    assert client.post("/auth/register", json={"email": "a@x.com", "password": "password123"}).status_code == 409
    assert client.post("/auth/register", json={"email": "bad", "password": "password123"}).status_code == 422
    assert client.post("/auth/login", data={"username": "a@x.com", "password": "nope"}).status_code == 401
    headers = register_and_login(client, "a@x.com")
    assert client.get("/auth/me", headers=headers).json()["email"] == "a@x.com"
    assert client.get("/auth/me").status_code == 401


def test_document_lifecycle(client):
    headers = register_and_login(client, "owner@x.com")
    _, col = setup_collection(client, headers)

    response = upload(client, headers, col["id"])
    assert response.status_code == 202
    doc_id = response.json()["id"]

    # background indexing has run by the time TestClient returns
    doc = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert doc["status"] == "ready" and doc["num_chunks"] >= 1

    assert upload(client, headers, col["id"]).status_code == 409  # duplicate
    assert upload(client, headers, col["id"], name="virus.exe").status_code == 400
    assert upload(client, headers, col["id"], content=b"", name="empty.txt").status_code == 400

    assert client.post(f"/documents/{doc_id}/reindex", headers=headers).status_code == 202
    assert client.get(f"/documents/{doc_id}", headers=headers).json()["status"] == "ready"

    assert client.delete(f"/documents/{doc_id}", headers=headers).status_code == 204
    assert client.get(f"/documents/{doc_id}", headers=headers).status_code == 404


def test_users_cannot_see_each_others_data(client):
    owner = register_and_login(client, "owner@x.com")
    other = register_and_login(client, "other@x.com")
    ns, col = setup_collection(client, owner)

    assert client.get(f"/namespaces/{ns['id']}/collections", headers=other).status_code == 404
    assert upload(client, other, col["id"]).status_code == 404
    assert client.get("/namespaces", headers=other).json() == []

    admin = {"Authorization": "Bearer " + client.post(
        "/auth/login", data={"username": "admin@example.com", "password": "admin12345"}
    ).json()["access_token"]}
    assert len(client.get("/namespaces", headers=admin).json()) == 1


def test_chat_streams_answer_with_citations_and_remembers_history(client, fake_ai):
    headers = register_and_login(client, "owner@x.com")
    ns, col = setup_collection(client, headers)
    upload(client, headers, col["id"])
    session = client.post("/chat/sessions", json={"namespace_id": ns["id"]}, headers=headers).json()

    response = client.post(f"/chat/sessions/{session['id']}/ask", json={"question": "How many leave days?"}, headers=headers)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e for e, _ in events] == ["token", "token", "citations", "done"]
    citations = events[2][1]
    assert citations[0]["filename"] == "policy.txt" and "24 days" in citations[0]["snippet"]

    # the retrieved document text was sent to the model
    assert "24 days of paid leave" in fake_ai[0][-1]["content"]

    # second question: previous turn is included as memory
    client.post(f"/chat/sessions/{session['id']}/ask", json={"question": "And when does the office open?"}, headers=headers)
    roles = [m["role"] for m in fake_ai[1]]
    assert roles == ["system", "user", "assistant", "user"]

    messages = client.get(f"/chat/sessions/{session['id']}/messages", headers=headers).json()
    assert len(messages) == 4 and messages[1]["citations"][0]["number"] == 1


def test_chat_without_documents_does_not_call_llm(client, fake_ai):
    headers = register_and_login(client, "owner@x.com")
    ns, _ = setup_collection(client, headers)
    session = client.post("/chat/sessions", json={"namespace_id": ns["id"]}, headers=headers).json()
    events = parse_sse(client.post(f"/chat/sessions/{session['id']}/ask", json={"question": "hi"}, headers=headers).text)
    assert "couldn't find" in events[0][1]["text"]
    assert fake_ai == []
