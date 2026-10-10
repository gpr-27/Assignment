"""API tests: auth, role-based access, punch in/out, admin corrections, reports, audit log, chatbot."""

from datetime import date, datetime, time, timedelta

from app import llm
from app.services.attendance import now, tz
from tests.conftest import final_answer, login, tool_call


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_login(client):
    assert client.post("/auth/login", data={"username": "admin@example.com", "password": "wrong"}).status_code == 401
    headers = login(client, "admin@example.com", "admin12345")
    assert client.get("/auth/me", headers=headers).json()["role"] == "admin"


def test_employees_cannot_use_admin_endpoints(client, employee):
    for path in ("/users", "/shifts", "/attendance", "/audit-logs", "/reports/absentees?day=2026-10-09"):
        assert client.get(path, headers=employee).status_code == 403, path
    assert client.get("/attendance/me", headers=employee).status_code == 200


def test_validation_errors(client, admin):
    bad_user = {"employee_code": "E1", "full_name": "X", "email": "not-an-email", "password": "short"}
    assert client.post("/users", json=bad_user, headers=admin).status_code == 422
    assert client.get("/reports/daily?start_date=2026-10-10&end_date=2026-10-01", headers=admin).status_code == 400


def test_punch_in_and_out(client, employee):
    response = client.post("/attendance/punch-in", headers=employee)
    assert response.status_code == 201
    assert client.post("/attendance/punch-in", headers=employee).status_code == 409  # only once a day

    out = client.post("/attendance/punch-out", headers=employee).json()
    assert out["punch_out"] is not None and out["hours_worked"] is not None
    assert client.post("/attendance/punch-out", headers=employee).status_code == 409  # not punched in

    assert len(client.get("/attendance/me", headers=employee).json()) == 1


def test_deactivated_user_is_locked_out(client, admin, employee):
    user_id = client.get("/auth/me", headers=employee).json()["id"]
    client.patch(f"/users/{user_id}", json={"is_active": False}, headers=admin)
    assert client.get("/auth/me", headers=employee).status_code == 401
    assert client.post("/auth/login", data={"username": "emp@acme.com", "password": "password123"}).status_code == 401


def test_admin_correction_is_audited_and_pii_masked(client, admin, employee):
    record = client.post("/attendance/punch-in", headers=employee).json()
    late_in = datetime.combine(now().date(), time(11, 0), tzinfo=tz()).isoformat()
    corrected = client.patch(f"/attendance/{record['id']}", json={"punch_in": late_in, "notes": "late train"},
                             headers=admin).json()
    assert corrected["is_late"] is True

    logs = client.get("/audit-logs", headers=admin).json()
    actions = [log["action"] for log in logs]
    assert {"attendance.correct", "attendance.punch_in", "user.create", "shift.create", "auth.login"} <= set(actions)

    user_create = next(log for log in logs if log["action"] == "user.create")
    assert user_create["details"]["email"] == "e***@acme.com"
    assert user_create["details"]["phone"] == "******3210"
    assert "password" not in user_create["details"]


def test_reports_count_absences_on_working_days_only(client, admin, employee):
    client.post("/attendance/punch-in", headers=employee)
    today = now().date()
    rows = client.get(f"/reports/daily?start_date={today}&end_date={today}", headers=admin).json()
    if today.weekday() < 5:
        assert rows == [{"date": today.isoformat(), "total": 1, "present": 1, "late": rows[0]["late"], "absent": 0}]
    else:
        assert rows == []

    # The employee joined today, so earlier days are not counted as absences.
    week_ago = today - timedelta(days=7)
    report = client.get(f"/reports/absenteeism?start_date={week_ago}&end_date={today}", headers=admin).json()
    assert report[0]["absent_days"] == 0


def test_chatbot_uses_tools_and_masks_pii(client, admin, monkeypatch):
    sent = []
    replies = iter([tool_call("get_absentees", '{"day": "%s"}' % date.today()), final_answer("Nobody was absent.")])

    def fake_chat(messages, tools):
        sent.append([dict(m) for m in messages])
        return next(replies)

    monkeypatch.setattr(llm, "chat", fake_chat)
    response = client.post("/chat", json={"message": "Who was absent today? My number is 9876543210"}, headers=admin)
    assert response.json() == {"answer": "Nobody was absent.", "tools_used": ["get_absentees"]}
    assert "9876543210" not in str(sent) and "******3210" in sent[0][1]["content"]
    assert sent[1][-1]["role"] == "tool"  # tool result was sent back to the model


def test_chatbot_employee_cannot_use_admin_tools(client, employee, monkeypatch):
    seen_tools, sent = [], []
    replies = iter([tool_call("get_absenteeism_report", '{"start_date": "2026-10-01", "end_date": "2026-10-09"}'),
                    final_answer("I can't share that.")])

    def fake_chat(messages, tools):
        seen_tools.append([t["function"]["name"] for t in tools])
        sent.append(messages[-1])
        return next(replies)

    monkeypatch.setattr(llm, "chat", fake_chat)
    client.post("/chat", json={"message": "Show everyone's absences"}, headers=employee)
    assert seen_tools[0] == ["get_my_attendance"]  # only their own data is offered
    assert "permission" in sent[1]["content"]  # and a forced call is refused


def test_chatbot_reports_llm_outage(client, admin, monkeypatch):
    def broken_chat(messages, tools):
        raise llm.LLMError("timeout")

    monkeypatch.setattr(llm, "chat", broken_chat)
    assert client.post("/chat", json={"message": "hi"}, headers=admin).status_code == 503
