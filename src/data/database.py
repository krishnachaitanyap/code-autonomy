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
    if 'workflows' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('workflows')]
        if 'token_budget' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE workflows ADD COLUMN token_budget INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE workflows ADD COLUMN total_tokens_used INTEGER DEFAULT 0"))
    if 'custom_migration_recipes' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('custom_migration_recipes')]
        if 'tool_ids' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE custom_migration_recipes ADD COLUMN tool_ids JSON DEFAULT '[]'"))

    # Backfill TestProject.repo_id → ensure every project points to a valid Repo
    _backfill_test_project_repos(engine)


def _backfill_test_project_repos(engine) -> None:
    """Ensure every TestProject has a valid repo_id pointing to an existing Repo."""
    from sqlalchemy import text

    with engine.begin() as conn:
        # Find test_projects with NULL repo_id or repo_id not in repos table
        rows = conn.execute(text(
            "SELECT tp.id, tp.repo_id, tp.repo_url, tp.local_path "
            "FROM test_projects tp "
            "LEFT JOIN repos r ON tp.repo_id = r.id "
            "WHERE tp.repo_id IS NULL OR r.id IS NULL"
        )).fetchall()

        if not rows:
            return

        from src.agent.knowledge import compute_repo_id

        for row in rows:
            tp_id, old_repo_id, repo_url, local_path = row
            new_repo_id = compute_repo_id(local_path or "", repo_url or "")

            # Create Repo record if it doesn't exist
            existing = conn.execute(
                text("SELECT id FROM repos WHERE id = :rid"),
                {"rid": new_repo_id},
            ).fetchone()

            if not existing:
                platform = "local"
                url = repo_url or ""
                if "github.com" in url:
                    platform = "github"
                elif "bitbucket" in url:
                    platform = "bitbucket"
                conn.execute(text(
                    "INSERT INTO repos (id, url, local_path, platform, created_at, updated_at) "
                    "VALUES (:id, :url, :lp, :platform, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": new_repo_id, "url": url, "lp": local_path or "", "platform": platform})

            # Update the test_project to point to the valid repo
            conn.execute(text(
                "UPDATE test_projects SET repo_id = :rid WHERE id = :tid"
            ), {"rid": new_repo_id, "tid": tp_id})


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
