# RAG Assistant: Architecture

## 1. High-level architecture

```mermaid
flowchart LR
    U[User / Browser] --> UI[Streamlit UI]
    UI -->|REST + SSE, JWT| API[FastAPI backend]
    API --> PG[(PostgreSQL + pgvector)]
    API --> FS[(File storage<br/>original uploads)]
    API --> EMB[Embedding model<br/>bge-small, local]
    API -->|OpenAI-compatible API| LLM[LLM<br/>Axon deepseek-v4-flash]
```

The UI is a thin client: everything goes through the API, so any other client (mobile, Slack bot, curl) gets the same behaviour and the same security checks.

## 2. Deployment

```mermaid
flowchart TB
    subgraph Host["Docker host (docker compose)"]
        UI["ui container<br/>streamlit :8501"]
        API["api container<br/>uvicorn :8000<br/>embedding model baked into the image"]
        DB["db container<br/>pgvector/pgvector:pg16 :5432"]
        V1[("volume: pgdata")]
        V2[("volume: uploads")]
        UI --> API --> DB
        DB --- V1
        API --- V2
    end
    API -->|HTTPS| Axon["Agent Router / Axon (external)"]
    Browser --> UI
```

- **Health checks:** `db` uses `pg_isready`. `api` uses `GET /health`, and `ui` only starts once `api` is healthy.
- **Restart policy:** `unless-stopped`. On startup the API retries the database connection with backoff.
- **Swap to managed services:** set `DATABASE_URL` to Supabase (or RDS) and drop the `db` container. The API is stateless apart from the uploads folder, which would move to S3 in a multi-instance setup (see trade-offs).

## 3. Components

```mermaid
flowchart TB
    subgraph routers["routers (HTTP layer)"]
        R1[auth]
        R2[namespaces]
        R3[documents]
        R4[chat]
        R5[health]
    end
    subgraph services["services (business logic)"]
        S1[access<br/>ownership checks]
        S2[ingestion<br/>extract, chunk, embed]
        S3[retrieval<br/>vector search]
        S4[chat<br/>prompt, stream, citations]
    end
    subgraph infra["infrastructure"]
        I1[db / models]
        I2[security<br/>bcrypt + JWT]
        I3[llm]
        I4[embeddings]
        I5[storage]
        I6[config / logging]
    end
    R2 --> S1
    R3 --> S1
    R4 --> S1
    R3 --> S2
    R4 --> S3
    R4 --> S4
    S2 --> I4
    S2 --> I5
    S2 --> I1
    S3 --> I4
    S3 --> I1
    S4 --> I3
    S4 --> I1
    R1 --> I2
```

Routers only handle HTTP: they parse input, call services, and shape the response. Services contain the logic and can be tested on their own. `llm`, `embeddings` and `storage` are small wrappers, so the provider can be swapped (OpenAI, Ollama or S3) in one file.

## 4. Database (ER diagram)

```mermaid
erDiagram
    users ||--o{ namespaces : owns
    namespaces ||--o{ collections : contains
    collections ||--o{ documents : contains
    documents ||--o{ chunks : "split into"
    users ||--o{ chat_sessions : starts
    namespaces ||--o{ chat_sessions : "searched by"
    chat_sessions ||--o{ chat_messages : contains

    users {
        int id PK
        string email UK
        string password_hash
        string role "user | admin"
    }
    namespaces {
        int id PK
        string name "unique per owner"
        int owner_id FK
    }
    collections {
        int id PK
        int namespace_id FK
        string name "unique per namespace"
        text description
    }
    documents {
        int id PK
        int collection_id FK
        string filename
        string sha256 "unique per collection"
        string status "processing | ready | failed"
        text error
        int num_chunks
        int uploaded_by FK
    }
    chunks {
        int id PK
        int document_id FK
        int chunk_index
        int page
        text content
        vector embedding "384-dim, HNSW index"
    }
    chat_sessions {
        int id PK
        int user_id FK
        int namespace_id FK
        string title
    }
    chat_messages {
        int id PK
        int session_id FK
        string role "user | assistant"
        text content
        jsonb citations
    }
```

Design notes:
- **`ON DELETE CASCADE`** all the way down. Deleting a namespace removes its collections, documents, chunks and chats in one statement, so nothing is left orphaned.
- **Unique constraints** enforce the rules in the database itself: no duplicate names, and no duplicate files in one collection.
- **HNSW index** (`vector_cosine_ops`) on `chunks.embedding` keeps similarity search fast as the table grows. Foreign-key columns are indexed for the joins.
- Citations are stored as **JSONB** on the message, so chat history shows the same sources later even if the document has since been deleted.

## 5. Sequence diagrams

### Upload and indexing

```mermaid
sequenceDiagram
    actor U as User
    participant API
    participant DB as Postgres
    participant FS as File storage
    participant BG as Background task
    participant E as Embedding model

    U->>API: POST /collections/{id}/documents (file)
    API->>API: check owner, type, size, SHA-256 duplicate
    API->>DB: INSERT document (status=processing)
    API->>FS: save file
    API-->>U: 202 Accepted {status: processing}
    API->>BG: ingest_document(id)
    BG->>FS: read file
    BG->>BG: extract text per page, split into chunks
    BG->>E: embed chunks (batches of 32)
    BG->>DB: replace chunks, status=ready (one transaction)
    Note over BG,DB: on any error: status=failed, error=reason
    U->>API: GET /documents/{id}
    API-->>U: {status: ready, num_chunks: 12}
```

### Asking a question (streaming + memory + citations)

```mermaid
sequenceDiagram
    actor U as User
    participant API
    participant DB as Postgres
    participant E as Embedding model
    participant L as LLM (Axon)

    U->>API: POST /chat/sessions/{id}/ask {question}
    API->>DB: check session belongs to user
    API->>DB: load last 6 messages (memory)
    API->>E: embed (previous question + question)
    API->>DB: top-5 chunks by cosine distance (namespace, ready docs only)
    API->>DB: save user message
    API->>L: system rules + history + numbered sources + question (stream=true)
    loop as tokens arrive
        L-->>API: token
        API-->>U: event: token
    end
    API->>API: find [n] citations in the answer
    API->>DB: save assistant message + citations
    API-->>U: event: citations, event: done
```

### Request flow (every request)

```mermaid
flowchart LR
    A[Request] --> B[Middleware: assign request id, start timer]
    B --> C{JWT valid?}
    C -- no --> X[401]
    C -- yes --> D{Owner or admin?}
    D -- no --> Y[404, don't reveal it exists]
    D -- yes --> E[Pydantic validation]
    E -- invalid --> Z[422 with field errors]
    E -- ok --> F["Router → service → DB / LLM"]
    F --> G[Response + X-Request-ID header]
    G --> H[JSON log line: method, path, status, duration_ms]
    F -- unexpected exception --> I[Log stack trace, 500 with request_id]
```

## 6. Non-functional requirements

| Area | What's done |
|---|---|
| **Security** | bcrypt hashes; signed JWTs with expiry; every query is scoped to the owner (other users' resources return 404); input validation; upload type/size limits; filenames are never used as paths (files are stored by id); the container runs as a non-root user; secrets live only in env vars |
| **Scalability** | The API is stateless (JWT, no server sessions), so you can run more containers behind a load balancer. Uses DB connection pooling and an HNSW vector index. Indexing runs after the response, so uploads return immediately. |
| **Observability** | Structured JSON logs with request id, latency and status on every request, plus events (indexed, failed, streamed) with ids. `/health` for probes. `X-Request-ID` is returned so users can quote it in bug reports. |
| **Resilience** | LLM client has a timeout and retries (2, with backoff, on 429/5xx). An LLM failure becomes a clean SSE `error` event. A failed document is marked `failed` with the reason and can be re-indexed. Startup retries the DB. `pool_pre_ping` drops dead connections. |
| **Maintainability** | Same layered layout in both projects; small single-purpose modules; providers behind one-file wrappers; config only via env; tests for the main flows |
| **Performance** | Embeddings run locally (no network hop); chunks are embedded in batches; the embedding model is loaded once and baked into the image; answers are streamed, so the first words appear in under a second |

## 7. Design decisions and trade-offs

| Decision | Why | Trade-off / what I'd do at larger scale |
|---|---|---|
| **pgvector instead of a separate vector DB** | One database for everything: transactions, joins for access control, cascade deletes, one backup | A dedicated vector DB (Qdrant, Pinecone) scales further at hundreds of millions of vectors. With many tenants in one HNSW index, filtered search can return fewer than k results; fix with pgvector iterative scans or per-tenant partitions. |
| **Local embeddings (fastembed, bge-small)** | Free, no rate limits, no data leaves the server, fast on CPU | Lower quality than large hosted embedding models. Switching model means changing `EMBEDDING_MODEL`/`EMBEDDING_DIM` and re-indexing. |
| **Agent Router (Axon) via an OpenAI-compatible client** | Single provider endpoint; model fixed to `deepseek-v4-flash` for consistency. | Depends on Agent Router availability and quotas; top-k and history are kept small to limit token use. |
| **FastAPI `BackgroundTasks` for indexing** | No extra infrastructure; upload returns immediately | Work is lost if the process dies mid-index (the document stays `processing`, and you can re-index it). At scale, use a queue (Celery/RQ/SQS) with retries. |
| **Character-based chunking with overlap and boundary snapping** | Simple, predictable, no tokenizer dependency | Not structure-aware (headings, tables). Could add semantic or heading-based splitting. |
| **Follow-up handling: retrieve with previous question + current question** | Cheap and works for most follow-ups, with no extra LLM call | An LLM "rewrite the question" step is more accurate but doubles LLM calls. |
| **Citations: the model writes `[n]`, the server keeps only cited sources** | Users see exactly which sources back the answer | Relies on the model following instructions. Some models use full-width `【n】` instead of `[n]`; both are handled. |
| **Files on local disk / volume** | Simplest. Isolated behind `storage.py` | Multiple API instances need shared storage. Swap `storage.py` for S3. |
| **`create_all` instead of migrations** | Fewer moving parts for a first version | Schema changes after launch need Alembic migrations. |
| **Sync SQLAlchemy + sync endpoints** | Easier to read and debug; FastAPI runs them in a thread pool | Async would handle more concurrent slow requests per process. Adding workers (`--workers`) is the simple fix. |
| **Namespace = owned by one user, admin sees all** | Clear and easy to reason about | Team sharing would need a `namespace_members` table with roles. |
