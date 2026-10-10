import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.logging_config import request_id_var, setup_logging
from app.models import User
from app.routers import auth, chat, documents, health, namespaces
from app.security import hash_password

logger = logging.getLogger("app")


def create_admin_if_missing() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == settings.admin_email.lower())):
            db.add(User(email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password), role="admin"))
            db.commit()
            logger.info("admin user created", extra={"email": settings.admin_email})


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    init_db()
    create_admin_if_missing()
    logger.info("application started")
    yield


app = FastAPI(
    title="Enterprise RAG Assistant",
    description="Upload documents into namespaces and collections, then chat with them. Answers stream back with citations.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Gives every request an id, logs method/path/status/duration, and hides internal errors from clients."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_var.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error")
        response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


for router in (health.router, auth.router, namespaces.router, documents.router, chat.router):
    app.include_router(router)
