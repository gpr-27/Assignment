import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.pii import mask_email
from app.schemas import TokenOut, UserOut
from app.security import create_access_token, get_current_user, verify_password
from app.services import audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Standard OAuth2 password form: `username` is the email. Accounts are created by admins."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.password_hash) or not user.is_active:
        audit.record(db, request, user, "auth.login_failed", "user", user.id if user else None,
                     {"email": form.username})
        db.commit()
        logger.warning("login failed", extra={"email": mask_email(form.username)})
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    audit.record(db, request, user, "auth.login", "user", user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
