"""Punch in / punch out rules."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Attendance, Shift, User


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def now() -> datetime:
    return datetime.now(tz())


def is_late(punch_in: datetime, shift: Shift | None) -> bool:
    """Late = punched in after the shift's start time plus the grace period (in local time)."""
    if shift is None:
        return False
    local = punch_in.astimezone(tz())
    deadline = datetime.combine(local.date(), shift.start_time, tzinfo=tz()) + timedelta(minutes=shift.grace_minutes)
    return local > deadline


def punch_in(db: Session, user: User, at: datetime | None = None) -> Attendance:
    at = at or now()
    work_date = at.astimezone(tz()).date()
    if db.scalar(select(Attendance).where(Attendance.user_id == user.id, Attendance.work_date == work_date)):
        raise HTTPException(status_code=409, detail="You have already punched in today")
    shift = db.get(Shift, user.shift_id) if user.shift_id else None
    record = Attendance(user_id=user.id, work_date=work_date, punch_in=at, is_late=is_late(at, shift))
    db.add(record)
    return record


def punch_out(db: Session, user: User, at: datetime | None = None) -> Attendance:
    # The latest open record, so a night shift that crosses midnight still punches out correctly.
    record = db.scalar(
        select(Attendance)
        .where(Attendance.user_id == user.id, Attendance.punch_out.is_(None))
        .order_by(Attendance.punch_in.desc())
    )
    if record is None:
        raise HTTPException(status_code=409, detail="You are not punched in")
    record.punch_out = at or now()
    return record
