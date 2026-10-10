"""Analytics: daily trend, absenteeism, absentees on a day, late arrivals.

"Absent" = a working day (see settings.work_days) with no punch-in, counted only from the day the
employee joined and never for future days. Only active employees are included.
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Attendance, User
from app.services.attendance import now, tz


def validate_range(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if (end - start).days + 1 > settings.max_report_days:
        raise HTTPException(status_code=400, detail=f"Date range can be at most {settings.max_report_days} days")


def working_days(start: date, end: date) -> list[date]:
    end = min(end, now().date())  # the future can't have absences
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() in settings.work_days]


def _joined(user: User) -> date:
    return user.created_at.astimezone(tz()).date()


def _employees(db: Session) -> list[User]:
    return list(db.scalars(
        select(User).where(User.role == "employee", User.is_active.is_(True)).order_by(User.employee_code)
    ))


def _records(db: Session, start: date, end: date, user_ids: list[int] | None = None) -> dict:
    stmt = select(Attendance).where(Attendance.work_date.between(start, end))
    if user_ids is not None:
        stmt = stmt.where(Attendance.user_id.in_(user_ids))
    return {(r.user_id, r.work_date): r for r in db.scalars(stmt)}


def _person(user: User) -> dict:
    # Names and codes only: contact details are never part of a report.
    return {"employee_code": user.employee_code, "full_name": user.full_name, "department": user.department}


def daily_summary(db: Session, start: date, end: date) -> list[dict]:
    """One row per working day: how many were present, late and absent."""
    validate_range(start, end)
    employees, records = _employees(db), _records(db, start, end)
    rows = []
    for day in working_days(start, end):
        expected = [e for e in employees if _joined(e) <= day]
        present = [records[(e.id, day)] for e in expected if (e.id, day) in records]
        rows.append({
            "date": day.isoformat(),
            "total": len(expected),
            "present": len(present),
            "late": sum(r.is_late for r in present),
            "absent": len(expected) - len(present),
        })
    return rows


def absenteeism(db: Session, start: date, end: date, users: list[User] | None = None) -> list[dict]:
    """Per employee: working days, days present/absent/late and absence rate. Worst first."""
    validate_range(start, end)
    users = _employees(db) if users is None else users
    records = _records(db, start, end, [u.id for u in users])
    days = working_days(start, end)
    rows = []
    for user in users:
        expected = [d for d in days if d >= _joined(user)]
        present = [records[(user.id, d)] for d in expected if (user.id, d) in records]
        absent = len(expected) - len(present)
        rows.append({
            **_person(user),
            "working_days": len(expected),
            "present_days": len(present),
            "absent_days": absent,
            "late_days": sum(r.is_late for r in present),
            "absence_rate_pct": round(100 * absent / len(expected), 1) if expected else 0.0,
        })
    return sorted(rows, key=lambda r: (-r["absent_days"], r["employee_code"]))


def absentees_on(db: Session, day: date) -> list[dict]:
    if day.weekday() not in settings.work_days or day > now().date():
        return []
    present = {user_id for user_id, _ in _records(db, day, day)}
    return [_person(e) for e in _employees(db) if e.id not in present and _joined(e) <= day]


def late_arrivals(db: Session, start: date, end: date) -> list[dict]:
    validate_range(start, end)
    rows = db.execute(
        select(User, Attendance).join(Attendance, Attendance.user_id == User.id)
        .where(Attendance.work_date.between(start, end), Attendance.is_late.is_(True))
        .order_by(Attendance.work_date, User.employee_code)
    ).all()
    return [
        {**_person(u), "date": a.work_date.isoformat(), "punch_in": a.punch_in.astimezone(tz()).strftime("%H:%M")}
        for u, a in rows
    ]


def employee_attendance(db: Session, user: User, start: date, end: date) -> dict:
    """One person's records plus their summary numbers."""
    validate_range(start, end)
    records =sorted(_records(db, start, end, [user.id]).values(), key=lambda r: r.work_date)
    return {
        "summary": absenteeism(db, start, end, [user])[0],
        "records": [
            {
                "date": r.work_date.isoformat(),
                "punch_in": r.punch_in.astimezone(tz()).strftime("%H:%M"),
                "punch_out": r.punch_out.astimezone(tz()).strftime("%H:%M") if r.punch_out else None,
                "late": r.is_late,
            }
            for r in records
        ],
    }
