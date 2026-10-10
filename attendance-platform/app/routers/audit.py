from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogOut
from app.security import require_admin

router = APIRouter(prefix="/audit-logs", tags=["audit (admin)"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    action: str | None = None,
    actor_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Newest first. Filter by action (e.g. "user.update") or by who did it."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    return db.scalars(stmt).all()
