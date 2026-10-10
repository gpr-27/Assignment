# Enterprise Multi-Document RAG Assistant

Upload documents (PDF, TXT, MD) into **namespaces** and **collections**, then chat with them.
Answers **stream** back token by token, with **citations** (file + page) and **conversational memory**.

- **Backend:** FastAPI · PostgreSQL + pgvector · SQLAlchemy
- **AI:** any OpenAI-compatible LLM (Groq `gpt-oss-120b` by default, free tier) · local embeddings (`bge-small-en-v1.5` via fastembed, no API key)
- **UI:** Streamlit
- **Ops:** Docker Compose · JSON logs with request ids · `/health` · pytest

Architecture, diagrams and trade-offs: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Features

| Requirement | How |
|---|---|
| Namespaces & collections | `Namespace` (workspace, owned by a user) → `Collection` → `Document` |
| Document lifecycle | upload → `processing` → `ready` / `failed` (with reason) → re-index → delete. Duplicate files are rejected (SHA-256). |
| Retrieval | Text split into ~1000-character overlapping chunks, embedded, stored in pgvector with an HNSW index, searched by cosine similarity |
| Citations | Model is told to cite `[n]`; only sources it actually cited are returned (filename, page, snippet) |
| Streaming | Server-Sent Events: `token` … `citations` → `done` (or `error`) |
| Conversational memory | Chat sessions and messages saved in Postgres; the last 6 messages go into each prompt, and the previous question is used to help retrieval of follow-ups |
| Authentication | Register / login, bcrypt password hashes, JWT bearer tokens. Users only see their own namespaces; admins see all. |
| Validation & errors | Pydantic on every input; file type/size checks; consistent JSON errors; unexpected errors return `500` with a `request_id` instead of a stack trace |
| Logging & monitoring | One JSON log line per request (method, path, status, duration, request id); `GET /health` checks the database |

## Run it

### Option A: Docker (recommended)

```bash
cp .env.example .env          # put your LLM_API_KEY in it (free key: https://console.groq.com)
docker compose up --build
```

- UI: http://localhost:8501
- API docs (Swagger): http://localhost:8000/docs

Compose starts its own Postgres + pgvector, so `DATABASE_URL` in `.env` is ignored here.

### Option B: Without Docker (e.g. with Supabase)

1. Create a free Supabase project. Copy **Project Settings → Database → Connection string → Session pooler** into `DATABASE_URL` in `.env`. Use a separate Supabase project for each of the two apps, because both have a `users` table. pgvector is enabled automatically on startup.
2. Install and run (Python 3.11+):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000          # terminal 1
streamlit run ui/app.py                   # terminal 2
```

The first start downloads the embedding model (~70 MB, once).

**Default admin:** `admin@example.com` / `admin12345`. Change it with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## Try it in 1 minute

1. Open the UI, register (or log in as admin).
2. Sidebar: create a namespace (e.g. `acme`) and a collection (e.g. `hr`).
3. **Documents** tab: upload a PDF. It shows 🟡 processing, then 🟢 ready (press Refresh).
4. **Chat** tab: **New chat**, ask a question. The answer streams in, with a **Sources** box underneath.
5. Ask a follow-up ("and what about sick leave?"). The previous turn is remembered.

## API overview

Full interactive docs at `/docs`. All endpoints except `/health`, `/auth/register` and `/auth/login` need `Authorization: Bearer <token>`.

| Method | Path | What it does |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get a JWT (form fields `username`=email, `password`) |
| GET | `/auth/me` | Current user |
| POST / GET | `/namespaces` | Create / list namespaces |
| DELETE | `/namespaces/{id}` | Delete namespace and everything in it |
| POST / GET | `/namespaces/{id}/collections` | Create / list collections |
| DELETE | `/collections/{id}` | Delete a collection |
| POST | `/collections/{id}/documents` | Upload a file (multipart). Returns `202` with status `processing` |
| GET | `/collections/{id}/documents` | List documents with status |
| GET | `/documents/{id}` | Document status / error |
| POST | `/documents/{id}/reindex` | Re-chunk and re-embed |
| DELETE | `/documents/{id}` | Delete document, its chunks and file |
| POST / GET | `/chat/sessions` | Start / list your chat sessions (a session searches one namespace) |
| GET | `/chat/sessions/{id}/messages` | Chat history with citations |
| POST | `/chat/sessions/{id}/ask` | Ask a question. Streams SSE. Optional `collection_ids` to narrow the search |
| DELETE | `/chat/sessions/{id}` | Delete a chat |
| GET | `/health` | Liveness + database check |

Example with curl:

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login -d 'username=admin@example.com&password=admin12345' | jq -r .access_token)
curl -N -X POST localhost:8000/chat/sessions/1/ask -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"question": "How many leave days do employees get?"}'
# event: token      data: {"text": "Employees get "}
# event: token      data: {"text": "24 days [1]."}
# event: citations  data: [{"number": 1, "filename": "handbook.pdf", "page": 1, "snippet": "..."}]
# event: done       data: {"message_id": 2}
```

## Configuration

All settings are environment variables (see [.env.example](.env.example) and [app/config.py](app/config.py)).

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local Postgres | Postgres with pgvector (Supabase works) |
| `JWT_SECRET` | placeholder | **Set a long random value in production** |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | Groq / – / `openai/gpt-oss-120b` | Any OpenAI-compatible API |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model (384-dim) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1000 / 150 | Characters per chunk / overlap |
| `TOP_K` | 5 | Chunks retrieved per question |
| `HISTORY_MESSAGES` | 6 | Past messages sent as memory |
| `MAX_UPLOAD_MB` | 10 | Upload size limit |
| `STORAGE_DIR` | `./data/uploads` | Where original files are kept |

## Tests

Tests use a real Postgres (pgvector can't be faked). The LLM and embedding model are replaced with fakes, so tests are fast and need no API key.

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rag_test pytest -q
```

Without `TEST_DATABASE_URL` only the unit tests run (the database tests are skipped).
They cover: auth, validation, upload → index → re-index → delete, duplicate/invalid files, users isolated from each other, streaming + citations, chat memory, and the "no documents" case.

## Project structure

```
app/
  main.py              app setup, request logging middleware, startup (tables + admin)
  config.py            settings from env vars
  db.py, models.py     database connection and tables
  schemas.py           request/response validation
  security.py          password hashing, JWT, current user
  llm.py               OpenAI-compatible client (streaming)
  embeddings.py        local embedding model
  storage.py           where uploaded files are kept
  routers/             HTTP endpoints (auth, namespaces, documents, chat, health)
  services/
    access.py          who can see what
    ingestion.py       extract text -> chunk -> embed -> save
    retrieval.py       vector search
    chat.py            prompt building, SSE streaming, citations
ui/app.py              Streamlit UI
tests/                 pytest
docs/ARCHITECTURE.md   diagrams, design decisions, trade-offs
```
