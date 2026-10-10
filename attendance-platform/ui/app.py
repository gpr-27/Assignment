"""Streamlit front end. It only talks to the API over HTTP. What you see depends on your role."""

import os
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8001")

st.set_page_config(page_title="Attendance", page_icon="🕘", layout="wide")


def api(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {st.session_state.token}"} if "token" in st.session_state else {}
    try:
        response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=60, **kwargs)
    except requests.ConnectionError:
        st.error(f"Cannot reach the API at {API_URL}")
        st.stop()
    if response.status_code == 401 and "token" in st.session_state:
        del st.session_state.token
        st.rerun()
    return response


def show_result(response, success: str) -> None:
    if response.ok:
        st.success(success)
    else:
        detail = response.json().get("detail", response.text)
        st.error(detail if isinstance(detail, str) else "; ".join(e["msg"] for e in detail))


def date_range(key: str, days: int = 30) -> tuple[date, date]:
    col1, col2 = st.columns(2)
    start = col1.date_input("From", date.today() - timedelta(days=days - 1), key=f"{key}_from")
    end = col2.date_input("To", date.today(), key=f"{key}_to")
    return start, end


def fmt_time(value: str | None) -> str:
    return datetime.fromisoformat(value).strftime("%H:%M") if value else "—"


def attendance_table(records: list[dict], names: dict[int, str] | None = None) -> None:
    if not records:
        st.info("No records in this period.")
        return
    rows = [{
        **({"Employee": names.get(r["user_id"], r["user_id"])} if names else {}),
        "Date": r["work_date"], "In": fmt_time(r["punch_in"]), "Out": fmt_time(r["punch_out"]),
        "Hours": r["hours_worked"], "Late": "⚠️" if r["is_late"] else "", "Notes": r["notes"] or "", "ID": r["id"],
    } for r in records]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def assistant(examples: list[str]) -> None:
    st.caption("Ask in plain English, e.g. " + " · ".join(f"“{e}”" for e in examples))
    history = st.session_state.setdefault("chat", [])
    for role, text in history:
        st.chat_message(role).markdown(text)
    if question := st.chat_input("Ask about attendance"):
        st.chat_message("user").markdown(question)
        with st.chat_message("assistant"), st.spinner("Thinking…"):
            r = api("POST", "/chat", json={"message": question})
            answer = r.json()["answer"] if r.ok else f"⚠️ {r.json().get('detail')}"
            st.markdown(answer)
        history += [("user", question), ("assistant", answer)]


# ---------- Login ----------
if "token" not in st.session_state:
    st.title("🕘 Attendance Portal")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            r = api("POST", "/auth/login", data={"username": email, "password": password})
            if r.ok:
                st.session_state.token = r.json()["access_token"]
                st.rerun()
            st.error("Incorrect email or password")
    st.stop()

me = api("GET", "/auth/me").json()
with st.sidebar:
    st.write(f"**{me['full_name']}** ({me['employee_code']})")
    st.caption(f"Role: {me['role']}")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()


# ---------- Employee view ----------
def employee_view() -> None:
    st.title("🕘 My Attendance")
    today = [r for r in api("GET", "/attendance/me").json() if r["work_date"] == date.today().isoformat()]
    record = today[0] if today else None
    col1, col2, col3 = st.columns(3)
    col1.metric("Punched in", fmt_time(record["punch_in"]) if record else "—")
    col2.metric("Punched out", fmt_time(record["punch_out"]) if record else "—")
    with col3:
        if record is None and st.button("✅ Punch in", type="primary", width="stretch"):
            show_result(api("POST", "/attendance/punch-in"), "Punched in")
            st.rerun()
        if record and not record["punch_out"] and st.button("🏁 Punch out", type="primary", width="stretch"):
            show_result(api("POST", "/attendance/punch-out"), "Punched out")
            st.rerun()
        if record and record["punch_out"]:
            st.success("Done for today 🎉")

    history_tab, chat_tab = st.tabs(["📅 History", "💬 Assistant"])
    with history_tab:
        start, end = date_range("mine")
        attendance_table(api("GET", "/attendance/me", params={"start_date": start, "end_date": end}).json())
    with chat_tab:
        assistant(["How many days was I late this month?", "Did I miss any day last week?"])


# ---------- Admin view ----------
def admin_view() -> None:
    st.title("🕘 Attendance Admin")
    users = api("GET", "/users").json()
    shifts = api("GET", "/shifts").json()
    names = {u["id"]: f"{u['full_name']} ({u['employee_code']})" for u in users}
    shift_names = {s["id"]: s["name"] for s in shifts}

    dash, people, shift_tab, records_tab, audit_tab, chat_tab = st.tabs(
        ["📊 Dashboard", "👥 Users", "⏰ Shifts", "📅 Attendance", "🧾 Audit log", "💬 Assistant"])

    with dash:
        start, end = date_range("dash")
        daily = api("GET", "/reports/daily", params={"start_date": start, "end_date": end})
        if not daily.ok:
            show_result(daily, "")
        elif daily.json():
            df = pd.DataFrame(daily.json()).set_index("date")
            last = df.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Employees", int(last["total"]))
            c2.metric(f"Present ({df.index[-1]})", int(last["present"]))
            c3.metric("Late", int(last["late"]))
            c4.metric("Avg. attendance", f"{100 * df['present'].sum() / max(df['total'].sum(), 1):.0f}%")
            st.subheader("Daily trend")
            st.line_chart(df[["present", "late", "absent"]])
            st.subheader("Absenteeism (worst first)")
            report = api("GET", "/reports/absenteeism", params={"start_date": start, "end_date": end}).json()
            st.dataframe(pd.DataFrame(report), hide_index=True, width="stretch")
        else:
            st.info("No working days in this range.")

    with people:
        st.dataframe(pd.DataFrame(users).assign(shift=lambda d: d["shift_id"].map(shift_names)).drop(columns="shift_id"),
                     hide_index=True, width="stretch")
        with st.expander("➕ Add user"), st.form("add_user", clear_on_submit=True):
            c1, c2 = st.columns(2)
            body = {
                "employee_code": c1.text_input("Employee code"), "full_name": c2.text_input("Full name"),
                "email": c1.text_input("Email"), "phone": c2.text_input("Phone") or None,
                "department": c1.text_input("Department") or None,
                "role": c2.selectbox("Role", ["employee", "admin"]),
                "password": c1.text_input("Initial password", type="password"),
                "shift_id": c2.selectbox("Shift", [None, *shift_names], format_func=lambda s: shift_names.get(s, "None")),
            }
            if st.form_submit_button("Create"):
                show_result(api("POST", "/users", json=body), "User created")
        with st.expander("✏️ Edit user"):
            user = st.selectbox("User", users, format_func=lambda u: names[u["id"]])
            with st.form("edit_user"):
                c1, c2 = st.columns(2)
                department = c1.text_input("Department", user["department"] or "")
                shift_id = c2.selectbox("Shift", [None, *shift_names], format_func=lambda s: shift_names.get(s, "None"),
                                        index=[None, *shift_names].index(user["shift_id"]))
                role = c1.selectbox("Role", ["employee", "admin"], index=["employee", "admin"].index(user["role"]))
                active = c2.checkbox("Active", user["is_active"])
                if st.form_submit_button("Save"):
                    show_result(api("PATCH", f"/users/{user['id']}", json={
                        "department": department or None, "shift_id": shift_id, "role": role, "is_active": active,
                    }), "User updated")

    with shift_tab:
        st.dataframe(pd.DataFrame(shifts), hide_index=True, width="stretch")
        with st.form("add_shift", clear_on_submit=True):
            st.write("**Add shift**")
            c1, c2, c3, c4 = st.columns(4)
            body = {"name": c1.text_input("Name"), "start_time": c2.time_input("Start").isoformat(),
                    "end_time": c3.time_input("End").isoformat(), "grace_minutes": c4.number_input("Grace (min)", 0, 120, 10)}
            if st.form_submit_button("Create"):
                show_result(api("POST", "/shifts", json=body), "Shift created")

    with records_tab:
        start, end = date_range("records", days=7)
        records = api("GET", "/attendance", params={"start_date": start, "end_date": end}).json()
        attendance_table(records, names)
        with st.expander("✏️ Correct a record"), st.form("correct"):
            st.caption("Use the ID from the table above. Times are in the company timezone.")
            c1, c2, c3 = st.columns(3)
            record_id = c1.number_input("Record ID", min_value=1, step=1)
            punch_out = c2.text_input("Punch out (YYYY-MM-DDTHH:MM+05:30)")
            notes = c3.text_input("Notes")
            if st.form_submit_button("Save correction"):
                body = {k: v for k, v in {"punch_out": punch_out, "notes": notes}.items() if v}
                show_result(api("PATCH", f"/attendance/{int(record_id)}", json=body), "Record corrected")

    with audit_tab:
        logs = api("GET", "/audit-logs", params={"limit": 200}).json()
        st.dataframe(pd.DataFrame([{**log, "actor": names.get(log["actor_id"], "—")} for log in logs]),
                     hide_index=True, width="stretch")

    with chat_tab:
        assistant(["Who was absent yesterday?", "Top 3 absentees this month", "Who was late most often last week?"])


if me["role"] == "admin":
    admin_view()
else:
    employee_view()
