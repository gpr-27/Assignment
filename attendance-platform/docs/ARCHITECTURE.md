# Attendance Platform: Architecture

## 1. High-level architecture

```mermaid
flowchart LR
    E[Employee] --> UI[Streamlit UI]
    A[Admin] --> UI
    UI -->|REST, JWT| API[FastAPI backend]
    API --> PG[(PostgreSQL)]
    API -->|tool use, PII-masked data only| LLM[LLM<br/>Claude Sonnet]
```

The UI is a thin client. All rules (roles, punch rules, masking, auditing) live in the API, so they apply to every client.

## 2. Deployment

```mermaid
flowchart TB
    subgraph Host["Docker host (docker compose)"]
        UI["ui container<br/>streamlit :8502"]
        API["api container<br/>uvicorn :8001"]
        DB["db container<br/>postgres:16 :5432"]
        V1[("volume: pgdata")]
        UI --> API --> DB
        DB --- V1
    end
    API -->|HTTPS| Anthropic["Anthropic API (external)"]
    Browser --> UI
```

- **Health checks:** `db` uses `pg_isready`. `api` uses `GET /health`, and `ui` waits for a healthy `api`.
- **Restart policy:** `unless-stopped`. The API retries the DB connection on startup.
- The API is fully stateless (JWT auth, all data in Postgres), so you can run more replicas behind a load balancer, or point `DATABASE_URL` at Supabase/RDS and drop the `db` container.

## 3. Components

```mermaid
flowchart TB
    subgraph routers["routers (HTTP layer)"]
        R1[auth]
        R2[attendance]
        R3[users]
        R4[shifts]
        R5[reports]
        R6[audit]
        R7[chat]
    end
    subgraph services["services (business logic)"]
        S1[attendance<br/>punch rules, lateness]
        S2[reports<br/>trend, absenteeism]
        S3[chatbot<br/>tools + RBAC + loop]
        S4[audit<br/>write audit entries]
    end
    subgraph infra["infrastructure"]
        I1[db / models]
        I2[security<br/>bcrypt, JWT, require_admin]
        I3[pii<br/>masking]
        I4[llm]
    end
    R2 --> S1
    R5 --> S2
    R7 --> S3
    S3 --> S2
    S3 --> I4
    S3 --> I3
    R1 --> S4
    R2 --> S4
    R3 --> S4
    R4 --> S4
    R7 --> S4
    S4 --> I3
    S1 --> I1
    S2 --> I1
    R1 --> I2
```

The chatbot does not have its own data access. Its tools call the same `reports` functions the admin dashboard uses, so the bot and the dashboard always agree.

## 4. Database (ER diagram)

```mermaid
erDiagram
    shifts ||--o{ users : "assigned to"
    users ||--o{ attendance : has
    users ||--o{ audit_logs : "performed"

    shifts {
        int id PK
        string name UK
        time start_time
        time end_time
        int grace_minutes
    }
    users {
        int id PK
        string employee_code UK
        string full_name
        string email UK
        string phone "PII"
        string department
        string role "employee | admin"
        string password_hash
        int shift_id FK "SET NULL on shift delete"
        bool is_active
        timestamptz created_at "join date for absence maths"
    }
    attendance {
        int id PK
        int user_id FK
        date work_date "unique with user_id"
        timestamptz punch_in
        timestamptz punch_out
        bool is_late
        text notes
        int updated_by FK "admin who corrected"
    }
    audit_logs {
        int id PK
        int actor_id FK
        string action "e.g. user.update"
        string entity
        int entity_id
        jsonb details "PII-masked"
        string ip_address
        timestamptz created_at
    }
```

Design notes:
- **`UNIQUE(user_id, work_date)`** guarantees one record per person per day, even if two punch-in requests race. It also serves as the index for per-user lookups. A separate index on `work_date` speeds up date-range reports.
- **Absence is derived, not stored.** "Absent" means a working day with no row. This avoids nightly jobs that write absent rows, and the numbers are always consistent with the punches.
- **Users are deactivated, never deleted**, so attendance and audit history stay complete. Audit `actor_id` uses `SET NULL`, so audit rows survive anyway.
- **Timestamps are `timestamptz`** (stored in UTC); `work_date` and lateness are computed in the configured company timezone.
- **Audit `details` is JSONB**, so each action can store its own shape (e.g. before/after for corrections).

## 5. Sequence diagrams

### Punch in

```mermaid
sequenceDiagram
    actor E as Employee
    participant API
    participant DB as Postgres
    E->>API: POST /attendance/punch-in (JWT)
    API->>DB: load user (must be active)
    API->>DB: already a record for today (local date)?
    alt already punched in
        API-->>E: 409 Already punched in today
    else
        API->>DB: load shift, compute is_late (start + grace)
        API->>DB: INSERT attendance + INSERT audit_log (one transaction)
        API-->>E: 201 {punch_in, is_late}
    end
```

### Chatbot question (tool calling with RBAC and PII masking)

```mermaid
sequenceDiagram
    actor U as User
    participant API
    participant BOT as chatbot service
    participant L as LLM (Anthropic)
    participant R as reports service
    participant DB as Postgres

    U->>API: POST /chat {"message": "Who was absent yesterday?"}
    API->>BOT: answer(user, message)
    BOT->>BOT: mask PII in message, pick tools for the user's role
    BOT->>L: system prompt (today's date, role) + message + allowed tools
    L-->>BOT: tool call get_absentees(day=2026-10-09)
    BOT->>BOT: is this tool allowed for this role? (else return an error to the LLM)
    BOT->>R: absentees_on(2026-10-09)
    R->>DB: SELECT ...
    R-->>BOT: [{employee_code, full_name, department}]
    BOT->>L: tool result (PII-masked JSON)
    L-->>BOT: final answer text
    BOT-->>API: answer, tools_used
    API->>DB: audit_log chat.query (masked question)
    API-->>U: {"answer": "...", "tools_used": ["get_absentees"]}
```

### Admin correction

```mermaid
sequenceDiagram
    actor A as Admin
    participant API
    participant DB as Postgres
    A->>API: PATCH /attendance/{id} {punch_out, notes}
    API->>API: require_admin, validate (timezone required, out after in)
    API->>DB: update record, recompute is_late if punch_in changed, set updated_by
    API->>DB: audit_log attendance.correct {before, after} (same transaction)
    API-->>A: 200 updated record
```

### How "absent" is decided

```mermaid
flowchart TD
    A[For each active employee and each day in range] --> B{Is it a working day?<br/>WORK_DAYS}
    B -- no --> S[Skip]
    B -- yes --> C{Day is in the future?}
    C -- yes --> S
    C -- no --> D{Day is before the employee joined?}
    D -- yes --> S
    D -- no --> E{Attendance row exists?}
    E -- yes --> P[Present, late if is_late]
    E -- no --> X[Absent]
```

## 6. Non-functional requirements

| Area | What's done |
|---|---|
| **Security** | bcrypt hashes; signed JWTs with expiry; `require_admin` on every admin route; role and active status re-read from the DB on every request; you can't deactivate or demote yourself; Pydantic validation (email, phone format, password length, timezone-aware datetimes, date-range limit); the LLM only sees masked data and can't run arbitrary queries; non-root container; secrets in env vars only |
| **Auditability** | Every change and every login (including failures) is in `audit_logs` with actor, action, entity, IP, time and masked details. It's written in the same transaction as the change, so a change can never be saved without its audit row. |
| **Scalability** | Stateless API (scale horizontally); connection pooling; indexed date-range queries; date ranges capped at 366 days so reports stay bounded |
| **Observability** | JSON logs with request id, status and latency on every request; chatbot tool calls are logged; `/health`; `X-Request-ID` response header |
| **Resilience** | LLM timeout and 2 retries with backoff; an LLM outage returns a clean `503` while the rest of the app keeps working; tool errors go back to the LLM as data instead of crashing; the unique constraint handles punch races; DB retry on startup; `pool_pre_ping` |
| **Maintainability** | Same layout as the RAG project; the chatbot reuses the report functions; adding a chatbot capability means adding one tool definition and one `if` branch |
| **Performance** | Reports load each date range's rows in one query and compute in memory (no N+1 queries); the chatbot is capped at 4 tool rounds |

## 7. Design decisions and trade-offs

| Decision | Why | Trade-off / what I'd do at larger scale |
|---|---|---|
| **Chatbot uses fixed tools, not text-to-SQL** | Safe (no SQL injection or data leaks through the LLM), RBAC is easy to enforce, and the answers match the dashboard | Can only answer what the tools cover. New questions need a new tool, which is a small change. |
| **RBAC applied twice for the chatbot** (tool list per role + a check before running) | Even if the model "invents" an admin tool call, the server refuses it | None worth mentioning |
| **PII policy: contact details never reach the LLM; names do (admins only)** | Names are needed to answer "who was absent?", and admins are already allowed to see them. Emails/phones are never needed. | Stricter setups could pseudonymise names (E003 → "Employee A") and map them back after the LLM replies. |
| **Absence computed on the fly** | Always correct; no scheduled jobs | Reports compute in Python: O(employees × days), which is fine for thousands of employees. At much larger scale, use SQL `generate_series` aggregation or a nightly summary table. |
| **One attendance row per day** (single punch in/out) | Matches the brief; simple rules | Breaks or multiple sessions per day would need a `punches` table. |
| **Deactivated employees are excluded from reports** | Reports reflect the current workforce | Historic reports for people who left would need a `left_at` date. |
| **Lateness stored at punch time** (`is_late`) | Fast reports; history doesn't change if a shift is edited later | Changing a shift doesn't re-grade old days. That's intentional, but worth knowing. |
| **`create_all` instead of migrations** | Fewer moving parts for a first version | Use Alembic once the schema needs to change in production. |
| **Anthropic Messages API (`anthropic` SDK)** | Tool use via Claude; `ANTHROPIC_API_KEY` and model in env | Depends on Anthropic availability and quotas. |
| **Sync SQLAlchemy** | Simple and readable | Add uvicorn workers for more throughput; async if needed. |
