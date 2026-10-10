import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


def _sqlalchemy_url(url: str) -> str:
    # Supabase and most providers hand out "postgresql://..." URLs; tell SQLAlchemy to use psycopg 3.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


engine = create_engine(_sqlalchemy_url(settings.database_url), pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 5) -> None:
    """Create the pgvector extension and tables. Retries so the API survives a slow-starting database."""
    from app import models  # noqa: F401  (registers the tables on Base)

    for attempt in range(1, retries + 1):
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(engine)
            return
        except Exception:
            if attempt == retries:
                raise
            logger.warning("database not ready, retrying", extra={"attempt": attempt})
            time.sleep(2 * attempt)
