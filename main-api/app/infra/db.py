from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(settings.postgres_dsn, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)


def apply_schema(engine: Engine) -> None:
    schema_file = Path(__file__).resolve().parents[2] / "migrations" / "001_init.sql"
    sql = schema_file.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))


@contextmanager
def transactional_session(session_factory: sessionmaker[Session]):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
