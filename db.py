import os
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.base import Base

engine = None
SessionLocal = None

_dirty = False
db_file_path = None


def _create_memory_engine():
    """Create an in-memory SQLite engine with StaticPool so all connections share one DB."""
    global engine, SessionLocal
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    SessionLocal = sessionmaker(bind=engine)


def _stamp_alembic_head():
    """Stamp the in-memory DB with the current alembic head revision."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    with engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.stamp(alembic_cfg, "head")
        conn.commit()


def _init_fresh_db(path: str | None = None):
    """Create a fresh in-memory DB with all tables, optionally remembering a file path."""
    global db_file_path
    db_file_path = os.path.abspath(path) if path else None
    _create_memory_engine()
    Base.metadata.create_all(engine)
    _stamp_alembic_head()


def init_memory_db():
    """Create a fresh in-memory DB with all tables. No file path remembered."""
    _init_fresh_db()


def load_db_from_file(path: str):
    """Copy an existing SQLite file into an in-memory DB."""
    global db_file_path
    db_file_path = os.path.abspath(path)
    _create_memory_engine()

    # Copy file DB into the in-memory DB
    file_conn = sqlite3.connect(path)
    mem_conn = engine.raw_connection()
    file_conn.backup(mem_conn.driver_connection)
    file_conn.close()


def init_new_db(path: str):
    """Create a fresh in-memory DB, remembering path for later :w."""
    _init_fresh_db(path)


def save_to_file(path: str | None = None):
    """Save the in-memory DB to disk using sqlite3.backup() + atomic swap."""
    global db_file_path, _dirty

    target = path or db_file_path
    if target is None:
        raise ValueError("No file path specified")

    target = os.path.abspath(target)
    swp_path = target + ".swp"

    mem_conn = engine.raw_connection()
    try:
        swp_conn = sqlite3.connect(swp_path)
        mem_conn.driver_connection.backup(swp_conn)
        swp_conn.close()
        os.rename(swp_path, target)
    except Exception:
        # Clean up swap file on failure
        if os.path.exists(swp_path):
            os.remove(swp_path)
        raise
    finally:
        mem_conn.close()

    db_file_path = target
    _dirty = False


def mark_dirty():
    global _dirty
    _dirty = True


def is_dirty():
    return _dirty


def clear_dirty():
    global _dirty
    _dirty = False


def has_pending_migrations() -> bool:
    """Check if the loaded DB has unapplied alembic migrations."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.migration import MigrationContext

    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current = ctx.get_current_revision()

    return current != head


def run_migrations():
    """Apply pending alembic migrations to the in-memory DB."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    with engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.upgrade(alembic_cfg, "head")
        conn.commit()
    mark_dirty()
