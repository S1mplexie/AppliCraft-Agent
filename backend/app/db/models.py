"""ORM 模型。

归属隔离有两层保障：数据库记录带 user_id；文书正文由 FileStore 按用户分目录存放。
即使某处查询漏写归属条件，也读不到别的用户目录下的文件。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def naive_utc() -> datetime:
    # 统一存朴素 UTC 时间，避免 PostgreSQL TIMESTAMPTZ 与 SQLite 比较时出错。
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow() -> datetime:
    return naive_utc()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 管理员可无限使用系统默认 Key，不受每日免费次数限制。
    # 由 .env 的 APPLICRAFT_BOOTSTRAP_EMAIL 在迁移 / sync-admin 时对齐。
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_quota: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "is_admin": bool(self.is_admin),
            "daily_quota": self.daily_quota,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class UserLLMSetting(Base):
    """用户自带大模型 Key（BYOK），一人一条，物理上与其他用户的数据隔离。

    API Key 以 Fernet 密文落库，服务端只在生成时解密进内存；任何接口都不会回传明文，
    只返回末尾四位提示。base_url / model 允许用户接任意 OpenAI 兼容端点。
    """

    __tablename__ = "user_llm_settings"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    api_key_cipher: Mapped[str] = mapped_column(Text, default="")
    api_key_hint: Mapped[str] = mapped_column(String(16), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SessionToken(Base):
    """存 token 的哈希而非明文；吊销会话只需置 revoked。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WechatIdentity(Base):
    """微信 openid 与本地账号的绑定关系。

    openid 只在同一个 AppID 下唯一，因此用 (appid, openid) 做联合唯一约束；
    session_key 属于解密密钥，不落库、不下发，code2session 用完即丢。
    """

    __tablename__ = "wechat_identities"
    __table_args__ = (UniqueConstraint("appid", "openid", name="uq_wechat_appid_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    appid: Mapped[str] = mapped_column(String(64))
    openid: Mapped[str] = mapped_column(String(128), index=True)
    unionid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GenerationLog(Base):
    """生成审计：同时用于每日配额计数与成本追踪。

    llm_source 标记这次生成扣的是谁的额度：system（系统默认 Key）/ personal（用户自带 Key）。
    只有 status='ok' 且 llm_source='system' 的记录才计入「系统 Key 每日免费次数」，
    失败调用与自带 Key 都不占用免费额度。
    """

    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    llm_source: Mapped[str] = mapped_column(String(16), default="system")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class KnowledgeChunk(Base):
    """RAG 预留：本阶段只建表，不写入、不参与生成。

    user_id 是硬约束——检索时必须同时带向量相似度与 user_id 条件，
    否则会把别人的申请材料片段召回进当前用户的文书。
    向量维度暂固定 1536；更换 embedding 模型时需要迁移该列。
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
    # PostgreSQL 下是 pgvector 列（可建 HNSW 索引）；SQLite 下退化为 JSON，
    # 让本机在无数据库服务时也能跑通完整业务链路。
    embedding: Mapped[list[float] | None] = mapped_column(
        JSON().with_variant(Vector(1536), "postgresql"), nullable=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
