from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session


def ensure_conversation_columns(target_engine=None) -> None:
    """Additive columns for databases created before they existed.

    SQLite and PostgreSQL both accept ADD COLUMN with a constant default, so no
    migration framework is needed for these additive columns.
    """
    target = target_engine or engine
    inspector = inspect(target)
    if "conversations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("conversations")}
    with target.begin() as connection:
        if "client_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN client_id VARCHAR(64) NOT NULL DEFAULT ''")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_conversations_client_id ON conversations (client_id)")
        if "title" not in columns:
            connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN title VARCHAR(120)")
        if "pinned" not in columns:
            # FALSE 而不是 0：PostgreSQL 的 BOOLEAN 默认值不接受整数（SQLite 两者皆可）
            connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE")
