from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Attendance, Shift, User
from app.schemas import AttendanceOut, AttendanceUpdate
from app.security import get_current_user, require_admin
from app.services import attendance, audit
from app.services.reports import validate_range

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _default_range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or attendance.now().date()
    start = start or end - timedelta(days=29)
    validate_range(start, end)
    return start, end


@router.post("/punch-in", response_model=AttendanceOut, status_code=201)
def punch_in(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = attendance.punch_in(db, user)
    try:
        db.flush()
    except IntegrityError:  # two punch-ins at the same moment: the unique constraint catches it
        db.rollback()
        raise HTTPException(status_code=409, detail="You have already punched in today")
    audit.record(db, request, user, "attendance.punch_in", "attendance", record.id, {"late": record.is_late})
    db.commit()
    return record


@router.post("/punch-out", response_model=AttendanceOut)
def punch_out(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = attendance.punch_out(db, user)
    audit.record(db, request, user, "attendance.punch_out", "attendance", record.id)
    db.commit()
    return record


@router.get("/me", response_model=list[AttendanceOut])
def my_attendance(
    start_date: date | None = None,
    end_date: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Your own records. Defaults to the last 30 days."""
    start, end = _default_range(start_date, end_date)
    return db.scalars(
        select(Attendance).where(Attendance.user_id == user.id, Attendance.work_date.between(start, end))
        .order_by(Attendance.work_date.desc())
    ).all()


@router.get("", response_model=list[AttendanceOut])
def list_attendance(
    user_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Everyone's records (admins only). Defaults to the last 30 days."""
    start, end = _default_range(start_date, end_date)
    stmt = select(Attendance).where(Attendance.work_date.between(start, end))
    if user_id is not None:
        stmt = stmt.where(Attendance.user_id == user_id)
    return db.scalars(stmt.order_by(Attendance.work_date.desc(), Attendance.user_id)).all()


@router.patch("/{record_id}", response_model=AttendanceOut)
def correct_attendance(
    record_id: int,
    body: AttendanceUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin correction, e.g. a forgotten punch-out. The change is audit-logged with old and new values."""
    record = db.get(Attendance, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    changes = body.model_dump(exclude_unset=True)
    punch_in = changes.get("punch_in", record.punch_in)
    punch_out = changes.get("punch_out", record.punch_out)
    if punch_out is not None and punch_out <= punch_in:
        raise HTTPException(status_code=400, detail="punch_out must be after punch_in")

    before = {field: str(getattr(record, field)) for field in changes}
    for field, value in changes.items():
        setattr(record, field, value)
    if "punch_in" in changes:
        employee = db.get(User, record.user_id)
        record.is_late = attendance.is_late(record.punch_in, db.get(Shift, employee.shift_id) if employee.shift_id else None)
    record.updated_by = admin.id
    audit.record(db, request, admin, "attendance.correct", "attendance", record.id,
                 {"before": before, "after": {field: str(value) for field, value in changes.items()}})
    db.commit()
    return record
