from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import require_admin
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports (admin)"])


@router.get("/daily")
def daily_summary(start_date: date, end_date: date, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Attendance trend: present / late / absent per working day."""
    return reports.daily_summary(db, start_date, end_date)


@router.get("/absenteeism")
def absenteeism(start_date: date, end_date: date, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Per employee absence and lateness, worst first."""
    return reports.absenteeism(db, start_date, end_date)


@router.get("/absentees")
def absentees(day: date, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Who was absent on a given day."""
    return reports.absentees_on(db, day)


@router.get("/late-arrivals")
def late_arrivals(start_date: date, end_date: date, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return reports.late_arrivals(db, start_date, end_date)
