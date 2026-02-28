from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = None
SessionLocal = None


def init_db(db_path: str):
    """Initialize the database engine and session factory for the given path."""
    global engine, SessionLocal
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, echo=False)
    SessionLocal = sessionmaker(bind=engine)

@contextmanager
def get_db_session():
    """Context manager for DB sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()