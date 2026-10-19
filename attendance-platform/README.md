# AI-Powered Attendance Management Platform

Employees **punch in/out**. Admins manage **users, shifts and attendance**, see **trends and absenteeism reports**, and review an **audit log**.
A **chatbot** answers attendance questions in plain English ("Who was absent yesterday?"), with **role-based access** and **PII masking**.

- **Backend:** FastAPI · PostgreSQL · SQLAlchemy
- **AI:** Agent Router (Axon) `deepseek-v4-flash` with tool calling
- **UI:** Streamlit (employee view + admin view with charts)
- **Ops:** Docker Compose · JSON logs with request ids · `/health` · pytest

Architecture, diagrams and trade-offs: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Features

| Requirement | How |
|---|---|
| Punch in / out | One record per employee per work day (enforced by a unique constraint). Late = after shift start + grace minutes, in the company timezone. Night shifts punch out correctly across midnight. |
| Admin: users, shifts, attendance | Create/edit users (deactivate, never delete), CRUD shifts, view everyone's attendance, correct records (e.g. a forgotten punch-out) |
| Role-based access | `employee`: own data only. `admin`: everything. Enforced on every endpoint *and* inside the chatbot. Role and active flag are re-checked from the DB on each request, so a deactivated user is locked out immediately. |
| Chatbot | The LLM can only call fixed, read-only **tools** (e.g. `get_absentees(day)`); it never writes SQL. Employees are only offered `get_my_attendance`. |
| PII masking | Emails/phones are masked before anything goes to the LLM, in audit-log details, and in app logs (`j***@acme.com`, `******3210`). Reports never include contact details. |
| Audit log | Logins (and failed logins), user/shift changes, punches, corrections (with before/after) and chatbot questions, with who/when/IP. Written in the same transaction as the change. |
| Trend analytics | Daily present / late / absent over any date range (dashboard line chart) |
| Absenteeism reporting | Per employee: working days, absent days, late days, absence rate %, worst first. Absences count only on working days, from the join date, never in the future. |

## Run it

### Option A: Docker (recommended)

```bash
cp .env.example .env              # set AXON_API_KEY (Agent Router)
docker compose up --build
docker compose exec api python -m app.seed      # optional: demo data
```

- UI: http://localhost:8502
- API docs (Swagger): http://localhost:8001/docs

### Option B: Without Docker (e.g. with Supabase)

1. Create a free Supabase project. Copy **Project Settings → Database → Connection string → Session pooler** into `DATABASE_URL` in `.env`. Use a separate Supabase project for each of the two apps, because both have a `users` table.
2. Install and run (Python 3.11+):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed                          # optional: demo data
uvicorn app.main:app --port 8001            # terminal 1
streamlit run ui/app.py --server.port 8502  # terminal 2
```

### Logins

| Who | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `admin12345` (set `ADMIN_EMAIL` / `ADMIN_PASSWORD`) |
| Demo employees (after seeding) | `aarav.sharma@acme.com`, `rohan.gupta@acme.com`, … | `password123` |

The seed creates 2 shifts, 8 employees in 4 departments and 6 weeks of realistic attendance (some people absent or late more often), so the dashboard and chatbot have something to show.

## Try it in 1 minute

1. Log in as **admin**. The **Dashboard** shows the trend chart and absenteeism table.
2. **Assistant** tab: try "Who was absent on the last working day?", "Top 3 absentees in the last 30 days", "Who was late most often last week?".
3. Log out, log in as **rohan.gupta@acme.com**, press **Punch in**, then ask "How many days was I late this month?".
4. As Rohan, ask "Show me Priya's attendance". It refuses: employees only have access to their own data.
5. Back as admin, open the **Audit log** to see every action above.

## API overview

Full interactive docs at `/docs`. Everything except `/health` and `/auth/login` needs `Authorization: Bearer <token>`.

| Method | Path | Who | What it does |
|---|---|---|---|
| POST | `/auth/login` | anyone | Get a JWT (form fields `username`=email, `password`) |
| GET | `/auth/me` | any user | Current user |
| POST | `/attendance/punch-in` | any user | Punch in (once per day) |
| POST | `/attendance/punch-out` | any user | Punch out |
| GET | `/attendance/me` | any user | Own records (`start_date`, `end_date`, default last 30 days) |
| GET | `/attendance` | admin | Everyone's records (filter `user_id`, dates) |
| PATCH | `/attendance/{id}` | admin | Correct punch times / notes (audited, before + after) |
| POST / GET / GET / PATCH | `/users`, `/users/{id}` | admin | Create, list, get, update or deactivate users |
| POST / GET / PUT / DELETE | `/shifts`, `/shifts/{id}` | admin | Manage shifts |
| GET | `/reports/daily` | admin | Trend: present / late / absent per working day |
| GET | `/reports/absenteeism` | admin | Per-employee absence report |
| GET | `/reports/absentees?day=` | admin | Who was absent on a day |
| GET | `/reports/late-arrivals` | admin | Late punch-ins in a range |
| GET | `/audit-logs` | admin | Audit trail (filter `action`, `actor_id`; paginated) |
| POST | `/chat` | any user | Ask a question: `{"message": "..."}` → `{"answer", "tools_used"}` |
| GET | `/health` | anyone | Liveness + database check |

## Configuration

All settings are environment variables (see [.env.example](.env.example) and [app/config.py](app/config.py)).

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local Postgres | Any Postgres (Supabase works) |
| `JWT_SECRET` | placeholder | **Set a long random value in production** |
| `AXON_BASE_URL` / `AXON_API_KEY` / `LLM_MODEL` | `https://agentrouter.org` / – / `deepseek-v4-flash` | `LLM_BASE_URL` and `LLM_API_KEY` aliases supported |
| `TIMEZONE` | `Asia/Kolkata` | Punch times and lateness are judged in this timezone |
| `WORK_DAYS` | `[0,1,2,3,4]` | Days that count for absence (Mon=0 … Sun=6) |

## Tests

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/attendance_test pytest -q
```

The LLM is replaced with a scripted fake, so no API key is needed. Without `TEST_DATABASE_URL` only the unit tests run.
They cover: PII masking (and that dates are *not* masked), lateness and grace period, working days, login, RBAC on every admin endpoint, validation, punch in/out rules, deactivation lockout, admin corrections plus audit (with masked PII), report maths, the chatbot's tool loop and PII masking, employees blocked from admin tools, and the LLM-outage response.

## Project structure

```
app/
  main.py              app setup, request logging middleware, startup (tables + admin)
  config.py            settings from env vars
  db.py, models.py     database connection and tables
  schemas.py           request/response validation
  security.py          password hashing, JWT, current user, admin check
  pii.py               masking of emails / phone numbers
  llm.py               OpenAI-compatible client (tool calling)
  seed.py              demo data
  routers/             HTTP endpoints (auth, attendance, users, shifts, reports, audit, chat, health)
  services/
    attendance.py      punch in/out rules, lateness
    reports.py         trend, absenteeism, absentees, late arrivals
    chatbot.py         tools, role-based tool access, tool-calling loop
    audit.py           writes audit entries
ui/app.py              Streamlit UI
tests/                 pytest
docs/ARCHITECTURE.md   diagrams, design decisions, trade-offs
```
