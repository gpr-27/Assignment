"""Audit trail. Every change is recorded in the same transaction as the change itself,
so a change can never be saved without its audit entry (or the other way round)."""

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.pii import mask_dict


def record(
    db: Session,
    request: Request | None,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: int | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=mask_dict(details) if details else None,
            ip_address=request.client.host if request and request.client else None,
        )
    )
