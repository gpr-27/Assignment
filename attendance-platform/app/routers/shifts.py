from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Shift, User
from app.schemas import ShiftIn, ShiftOut
from app.security import require_admin
from app.services import audit

router = APIRouter(prefix="/shifts", tags=["shifts (admin)"])


def _get(db: Session, shift_id: int) -> Shift:
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    return shift


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A shift with this name already exists")


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(body: ShiftIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    shift = Shift(**body.model_dump())
    db.add(shift)
    db.flush()
    audit.record(db, request, admin, "shift.create", "shift", shift.id, body.model_dump(mode="json"))
    _commit(db)
    return shift


@router.get("", response_model=list[ShiftOut])
def list_shifts(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(Shift).order_by(Shift.start_time)).all()


@router.put("/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: int, body: ShiftIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    shift = _get(db, shift_id)
    for field, value in body.model_dump().items():
        setattr(shift, field, value)
    audit.record(db, request, admin, "shift.update", "shift", shift.id, body.model_dump(mode="json"))
    _commit(db)
    return shift


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(shift_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    shift = _get(db, shift_id)
    db.delete(shift)  # users on this shift get shift_id = NULL (ON DELETE SET NULL)
    audit.record(db, request, admin, "shift.delete", "shift", shift_id, {"name": shift.name})
    db.commit()
