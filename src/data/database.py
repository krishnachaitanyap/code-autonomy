"""
Database engine, session factory, and initialization.

Defaults to SQLite at ``~/.code-autonomy/autonomy.db``.
Override with ``DATABASE_URL`` environment variable for PostgreSQL.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.data.models import Base

_DEFAULT_DB_PATH = Path.home() / ".code-autonomy" / "autonomy.db"
_DEFAULT_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

_engine = None
_SessionFactory = None


def get_database_url() -> str:
    """Resolve the database URL from environment or default."""
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def get_engine(url: str = ""):
    """Get or create the SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        db_url = url or get_database_url()
        # Ensure parent directory exists for SQLite
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(db_url, connect_args=connect_args, echo=False)
    return _engine


def get_session_factory(url: str = "") -> sessionmaker:
    """Get or create the session factory (singleton)."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine(url)
        _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionFactory


def init_db(url: str = "") -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    engine = get_engine(url)
    Base.metadata.create_all(engine)

    # Migrate existing DBs
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if 'sessions' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('sessions')]
        if 'log' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN log JSON DEFAULT '[]'"))
    if 'test_runs' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('test_runs')]
        if 'branch' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE test_runs ADD COLUMN branch VARCHAR(256) DEFAULT 'main'"))


@contextmanager
def get_session(url: str = "") -> Generator[Session, None, None]:
    """Context manager yielding a SQLAlchemy session with auto-commit/rollback."""
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Reset the global engine and session factory (for testing)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
