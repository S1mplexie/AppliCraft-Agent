"""数据库引擎、会话依赖与初始化。"""
from __future__ import annotations

import logging
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

logger = logging.getLogger(__name__)

settings = get_settings()
_db_url = settings.db_url
if _db_url.startswith("sqlite"):
    from pathlib import Path

    Path(_db_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
_options: dict = {"pool_pre_ping": True}
if _db_url.startswith("postgresql"):
    _options.update(pool_size=5, max_overflow=10)
engine = create_engine(_db_url, **_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    # 本地部署版（standalone）没有数据库：yield None，让路由在 standalone 分支里跳过 DB 操作。
    if get_settings().standalone:
        yield None  # type: ignore[misc]
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_schema() -> None:
    """给已有库补列并回填管理员标记。

    create_all 只建新表、不会给旧表加列，因此线上升级必须走这里。
    全部语句幂等，重复启动不会重复加列或覆盖数据。
    """
    is_pg = engine.dialect.name == "postgresql"
    false_sql, true_sql = ("false", "true") if is_pg else ("0", "1")

    def columns(table: str) -> set[str]:
        inspector = inspect(engine)
        if table not in inspector.get_table_names():
            return set()
        return {col["name"] for col in inspector.get_columns(table)}

    with engine.begin() as conn:
        if "is_admin" not in columns("users"):
            conn.execute(
                text(f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT {false_sql}")
            )
            logger.info("数据库迁移：users 增加 is_admin 列")
        if "llm_source" not in columns("generation_logs"):
            conn.execute(
                text("ALTER TABLE generation_logs ADD COLUMN llm_source VARCHAR(16) NOT NULL DEFAULT 'system'")
            )
            logger.info("数据库迁移：generation_logs 增加 llm_source 列")

        # .env 里的默认管理员即为「当前使用的账号」；只做授予、不撤销已有管理员，
        # 避免误把人工设置的其他管理员锁在系统 Key 限流里。
        email = settings.bootstrap_email.strip()
        if email:
            conn.execute(
                text(f"UPDATE users SET is_admin = {true_sql} WHERE lower(email) = lower(:email)"),
                {"email": email},
            )


def init_db() -> None:
    """建表、执行结构迁移；仅 PostgreSQL 额外建 vector 扩展与 HNSW 索引。"""
    is_pg = engine.dialect.name == "postgresql"
    if is_pg:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _migrate_schema()
    if is_pg:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding "
                    "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
                )
            )
    logger.info("数据库初始化完成（%s）", "PostgreSQL" if is_pg else "SQLite")


def db_healthy() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - 数据库不可达时仅用于健康检查
        return False
