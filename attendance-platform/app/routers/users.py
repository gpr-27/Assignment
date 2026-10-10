"""User administration (admins only). Users are deactivated, never deleted."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Shift, User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import hash_password, require_admin
from app.services import audit

router = APIRouter(prefix="/users", tags=["users (admin)"])


def _check_shift(db: Session, shift_id: int | None) -> None:
    if shift_id is not None and db.get(Shift, shift_id) is None:
        raise HTTPException(status_code=400, detail="Shift not found")


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(or_(User.email == email, User.employee_code == body.employee_code))):
        raise HTTPException(status_code=409, detail="A user with this email or employee code already exists")
    _check_shift(db, body.shift_id)
    user = User(**body.model_dump(exclude={"password", "email"}), email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.record(db, request, admin, "user.create", "user", user.id, body.model_dump(exclude={"password"}))
    db.commit()
    return user


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.employee_code)).all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    user = get_user(user_id, admin, db)
    changes = body.model_dump(exclude_unset=True)
    if "shift_id" in changes:
        _check_shift(db, changes["shift_id"])
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("role") == "employee"):
        raise HTTPException(status_code=400, detail="You can't deactivate or demote yourself")

    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
        changes["password"] = "changed"  # recorded in the audit log, value masked
    for field, value in changes.items():
        if field != "password":
            setattr(user, field, value)
    audit.record(db, request, admin, "user.update", "user", user.id, changes)
    db.commit()
    return user
