# AI Engineering Assessment

Two production-style projects, built the same way (FastAPI · PostgreSQL · Streamlit · Docker · pytest) so each is easy to follow once you know the other.

| Project | What it does | Docs |
|---|---|---|
| [**1. RAG Assistant**](rag-assistant/) | Upload documents into namespaces/collections and chat with them. Streaming answers with citations, chat memory, auth, document lifecycle. | [README](rag-assistant/README.md) · [Architecture](rag-assistant/docs/ARCHITECTURE.md) |
| [**2. Attendance Platform**](attendance-platform/) | Punch in/out, admin management of users/shifts/attendance, trend + absenteeism reports, audit log, and an attendance chatbot with RBAC and PII masking. | [README](attendance-platform/README.md) · [Architecture](attendance-platform/docs/ARCHITECTURE.md) |

## Before you run: what to set

Each project has its own `.env`. Copy the template and fill in **one required value**:

```bash
cd rag-assistant        # or attendance-platform
cp .env.example .env
```

| Variable | Required? | What to put |
|---|---|---|
| `LLM_API_KEY` | **Yes** | Free Groq key: sign up at https://console.groq.com → **API Keys** → *Create API Key* (starts with `gsk_`) |
| `DATABASE_URL` | Only without Docker | Supabase: **Project Settings → Database → Connection string → Session pooler** (port 5432). Docker Compose provides its own database and ignores this. |
| `JWT_SECRET` | Yes for any real deployment | A long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Optional | The first admin account, created on startup. Default `admin@example.com` / `admin12345` |
| `LLM_BASE_URL` / `LLM_MODEL` | Optional | Defaults to Groq `openai/gpt-oss-120b`. Any OpenAI-compatible provider works (OpenAI, Ollama, …). |

> **Use a separate database for each project.** Both have a `users` table with different columns. On Supabase's free tier, create **two projects** (one per app) and use each one's connection string.

`.env` is git-ignored. Never commit real keys.

## Run

**With Docker** (each project, from its folder):
```bash
docker compose up --build
```

| | API docs | UI |
|---|---|---|
| RAG Assistant | http://localhost:8000/docs | http://localhost:8501 |
| Attendance Platform | http://localhost:8001/docs | http://localhost:8502 |

For attendance demo data: `docker compose exec api python -m app.seed`

**Without Docker** (Python 3.11+, `DATABASE_URL` pointing at Supabase or any Postgres): see "Option B" in each project's README.

## Tests

```bash
cd rag-assistant && TEST_DATABASE_URL=postgresql://... pytest -q          # 10 tests
cd attendance-platform && TEST_DATABASE_URL=postgresql://... pytest -q    # 16 tests
```

Use an empty database for tests. The tables are dropped and recreated. The LLM and embeddings are faked in tests, so no API key is needed.

## Where to find each deliverable

| Deliverable | Location |
|---|---|
| High-level architecture diagram | `*/docs/ARCHITECTURE.md` §1 |
| Deployment diagram | `*/docs/ARCHITECTURE.md` §2 |
| Component diagram | `*/docs/ARCHITECTURE.md` §3 |
| Database ER diagram | `*/docs/ARCHITECTURE.md` §4 |
| Sequence diagrams & flowcharts | `*/docs/ARCHITECTURE.md` §5 |
| Non-functional requirements (security, scalability, observability, resilience, maintainability, performance) | `*/docs/ARCHITECTURE.md` §6 |
| Trade-off analysis | `*/docs/ARCHITECTURE.md` §7 |
| API documentation | Each README's "API overview", plus live Swagger at `/docs` |
| README | This file + one per project |

Diagrams are written in Mermaid, which GitHub renders automatically.

## Shared design choices (both projects)

- **Layered code:** `routers/` (HTTP) → `services/` (logic) → `models.py` (DB). Small wrappers for the LLM, embeddings and storage, so providers can be swapped in one file.
- **Config** only from environment variables (`pydantic-settings`).
- **Auth:** bcrypt + JWT; roles checked on the server for every request.
- **Logging:** one JSON line per request with request id, status and latency; `X-Request-ID` header; unexpected errors return `500` + request id, never a stack trace.
- **Resilience:** LLM timeouts + retries; LLM failures return a clean error while the rest of the app keeps working; DB connection retry on startup; Docker health checks and restart policies.
- **LLM:** Groq's free tier through the standard OpenAI client. Any OpenAI-compatible API works by changing `.env`.

What's intentionally *not* included (bonus items, out of scope): CI/CD, caching, metrics dashboards, cloud deployment, job queues, DB migrations. Each project's trade-off section says how these would be added.
