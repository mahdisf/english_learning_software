"""Database engine and session management."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from english_coach.config import Settings


class DatabaseNotInitializedError(RuntimeError):
    """Raised when the database file does not exist yet."""


def _sqlalchemy_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def get_engine(settings: Settings, *, create_parent: bool = False) -> Engine:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    db_path = settings.database_path
    if create_parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(_sqlalchemy_url(db_path), future=True, poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def require_database(settings: Settings) -> None:
    if not settings.database_path.is_file():
        raise DatabaseNotInitializedError(
            f"Database not found at {settings.database_path}. "
            "Run 'english-coach init' first."
        )


def get_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = get_engine(settings)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """Provide a transactional scope. Commits on success, rolls back on error."""
    require_database(settings)
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
