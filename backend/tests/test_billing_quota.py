"""系统默认 Key 的按账号计费策略：管理员无限、普通账号每日 3 次、BYOK 豁免。

覆盖：旧库列迁移与管理员回填、免费次数计数口径、429 引导文案、
quota_info 字段、日志来源写入、/api/config 与 /api/me/llm 的字段暴露。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.api import deps, routes_generate
from app.api.deps import (
    billing_source,
    check_quota,
    get_current_user,
    get_db,
    get_llm,
    quota_info,
    system_key_used,
)
from app.config import get_settings
from app.db import session as db_session
from app.db.models import Base, GenerationLog, User, UserLLMSetting, naive_utc
from app.main import app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "system_key_daily_limit", 3)
    monkeypatch.setattr(settings, "allow_personal_llm_keys", True)
    monkeypatch.setattr(settings, "require_personal_llm_key", False)
    monkeypatch.setattr(settings, "llm_api_key", "sk-system-key-9999")

    engine = create_engine(f"sqlite:///{tmp_path / 'billing.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    admin = User(id="admin", email="admin@example.com", password_hash="x",
                 is_admin=True, daily_quota=999)
    normal = User(id="normal", email="normal@example.com", password_hash="x",
                  is_admin=False, daily_quota=999)
    byok = User(id="byok", email="byok@example.com", password_hash="x",
                is_admin=False, daily_quota=999)
    db.add_all([admin, normal, byok])
    db.commit()
    yield {
        "settings": settings, "db": db, "engine": engine, "Session": Session,
        "admin": admin, "normal": normal, "byok": byok,
    }
    db.close()
    app.dependency_overrides.clear()


def _log(ctx, user_id: str, *, status: str = "ok", source: str = "system") -> None:
    ctx["db"].add(
        GenerationLog(
            user_id=user_id, doc_type="ps", status=status, llm_source=source,
            created_at=naive_utc(),
        )
    )
    ctx["db"].commit()


def _system_stub():
    return type("L", (), {"source": "system"})()


def _personal_stub():
    return type("L", (), {"source": "personal"})()


# ------------------------------------------------------------------ 旧库迁移
def test_migration_adds_columns_and_marks_bootstrap_admin(tmp_path, monkeypatch):
    """模拟升级前的旧表结构：create_all 不会补列，必须靠 _migrate_schema。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(32) NOT NULL PRIMARY KEY, email VARCHAR(255))"))
        conn.execute(text(
            "CREATE TABLE generation_logs (id INTEGER NOT NULL PRIMARY KEY, "
            "user_id VARCHAR(32), status VARCHAR(16), created_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO users (id, email) VALUES ('a', 'Admin@Example.com')"))
        conn.execute(text("INSERT INTO users (id, email) VALUES ('b', 'other@example.com')"))

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(
        db_session, "settings",
        SimpleNamespace(bootstrap_email="admin@example.com"),
    )
    db_session._migrate_schema()
    db_session._migrate_schema()  # 幂等：重复执行不能报错或重复加列

    insp = inspect(engine)
    assert "is_admin" in {c["name"] for c in insp.get_columns("users")}
    assert "llm_source" in {c["name"] for c in insp.get_columns("generation_logs")}
    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, is_admin FROM users")).fetchall())
        default = conn.execute(text("SELECT llm_source FROM generation_logs LIMIT 1")).scalar()
    assert rows == {"a": 1, "b": 0}, rows
    assert default in (None, "system")


# ------------------------------------------------------------------ 计费来源判定
def test_billing_source_priority(ctx):
    s = ctx["settings"]
    assert billing_source(ctx["admin"], s, llm=_system_stub()) == "admin"
    assert billing_source(ctx["admin"], s, llm=_personal_stub()) == "admin"
    assert billing_source(ctx["normal"], s, llm=_personal_stub()) == "personal"
    assert billing_source(ctx["normal"], s, llm=_system_stub()) == "system"
    assert billing_source(ctx["normal"], s, personal_key=True) == "personal"
    assert billing_source(ctx["normal"], s, personal_key=False) == "system"


# ------------------------------------------------------------------ 免费次数闸门
def test_admin_uses_system_key_without_limit(ctx):
    for _ in range(30):
        _log(ctx, "admin")
    assert system_key_used(ctx["db"], "admin") == 30
    check_quota(ctx["db"], ctx["admin"], _system_stub(), ctx["settings"])  # 不抛


def test_normal_user_blocked_after_three_free_generations(ctx):
    for _ in range(2):
        _log(ctx, "normal")
    check_quota(ctx["db"], ctx["normal"], _system_stub(), ctx["settings"])  # 第 3 次仍可用
    _log(ctx, "normal")
    assert system_key_used(ctx["db"], "normal") == 3
    with pytest.raises(HTTPException) as exc:
        check_quota(ctx["db"], ctx["normal"], _system_stub(), ctx["settings"])
    assert exc.value.status_code == 429
    detail = exc.value.detail
    assert "3 次免费额度" in detail
    assert "我的大模型 API" in detail


def test_personal_key_bypasses_free_limit(ctx):
    for _ in range(30):
        _log(ctx, "byok")
    check_quota(ctx["db"], ctx["byok"], _personal_stub(), ctx["settings"])  # 不抛


def test_admin_keeps_system_key_even_when_byok_is_forced(ctx):
    """开启「强制自带 Key」时普通用户被拦，管理员仍可无限用系统 Key。"""
    s = ctx["settings"]
    s.require_personal_llm_key = True
    deps._system_llm.cache_clear()
    with pytest.raises(HTTPException) as exc:
        deps.get_llm(user=ctx["normal"], db=ctx["db"], settings=s)
    assert exc.value.status_code == 400
    client = deps.get_llm(user=ctx["admin"], db=ctx["db"], settings=s)
    assert client.source == "system"
    deps._system_llm.cache_clear()

    app.dependency_overrides[get_db] = lambda: ctx["db"]
    app.dependency_overrides[get_current_user] = lambda: ctx["admin"]
    status = TestClient(app).get("/api/me/llm").json()
    assert status["effective_source"] == "system"
    assert status["is_admin"] is True and status["unlimited"] is True


def test_failed_and_personal_calls_do_not_consume_free_quota(ctx):
    _log(ctx, "normal", status="error")
    _log(ctx, "normal", source="personal")
    assert system_key_used(ctx["db"], "normal") == 0
    check_quota(ctx["db"], ctx["normal"], _system_stub(), ctx["settings"])


def test_zero_limit_disables_system_key_for_normal_users(ctx):
    ctx["settings"].system_key_daily_limit = 0
    with pytest.raises(HTTPException) as exc:
        check_quota(ctx["db"], ctx["normal"], _system_stub(), ctx["settings"])
    assert "配置自己的 API Key" in exc.value.detail
    check_quota(ctx["db"], ctx["admin"], _system_stub(), ctx["settings"])  # 管理员仍可用


def test_http_generate_returns_guidance_when_free_quota_exhausted(ctx):
    """端到端：普通账号次数用尽时，生成接口直接 429 并给出配置引导。"""
    for _ in range(3):
        _log(ctx, "normal")
    app.dependency_overrides[get_db] = lambda: ctx["db"]
    app.dependency_overrides[get_current_user] = lambda: ctx["normal"]
    app.dependency_overrides[get_llm] = _system_stub
    client = TestClient(app)
    resp = client.post("/api/generate", json={
        "profile_id": "whatever", "doc_type": "ps", "language": "en", "word_limit": 150,
    })
    assert resp.status_code == 429, resp.text
    assert "我的大模型 API" in resp.json()["detail"]


# ------------------------------------------------------------------ quota_info 字段
def test_quota_info_reports_billing_fields(ctx):
    s = ctx["settings"]
    _log(ctx, "normal")
    q = quota_info(ctx["db"], ctx["normal"], _system_stub(), s)
    assert q["source"] == "system" and q["unlimited"] is False
    assert q["system_key_limit"] == 3 and q["system_key_used"] == 1
    assert q["system_key_remaining"] == 2
    assert q["limit"] == ctx["normal"].daily_quota  # 旧字段语义不变

    admin_q = quota_info(ctx["db"], ctx["admin"], _system_stub(), s)
    assert admin_q["source"] == "admin" and admin_q["unlimited"] is True

    personal_q = quota_info(ctx["db"], ctx["byok"], _personal_stub(), s)
    assert personal_q["source"] == "personal" and personal_q["unlimited"] is True


def test_quota_info_detects_saved_personal_key(ctx):
    ctx["db"].add(UserLLMSetting(
        user_id="normal", base_url="https://api.example.com/v1", model="m",
        api_key_cipher="cipher", api_key_hint="***1234",
    ))
    ctx["db"].commit()
    q = quota_info(ctx["db"], ctx["normal"], settings=ctx["settings"])
    assert q["source"] == "personal" and q["unlimited"] is True


# ------------------------------------------------------------------ 日志来源写入
def test_generation_log_records_llm_source(ctx, monkeypatch):
    monkeypatch.setattr(routes_generate, "SessionLocal", ctx["Session"])
    routes_generate._log_generation("normal", "ps", llm_source="personal")
    routes_generate._log_generation("normal", "ps", llm_source="system", status="error")
    rows = ctx["db"].query(GenerationLog).order_by(GenerationLog.id).all()
    assert [(r.llm_source, r.status) for r in rows] == [("personal", "ok"), ("system", "error")]
    assert system_key_used(ctx["db"], "normal") == 0


# ------------------------------------------------------------------ 接口字段
def test_config_and_me_llm_expose_billing(ctx):
    app.dependency_overrides[get_db] = lambda: ctx["db"]
    app.dependency_overrides[get_current_user] = lambda: ctx["normal"]
    client = TestClient(app)

    cfg = client.get("/api/config").json()
    assert cfg["system_key_daily_limit"] == 3

    _log(ctx, "normal")
    mine = client.get("/api/me/llm").json()
    assert mine["is_admin"] is False
    assert mine["unlimited"] is False
    assert mine["system_key_daily_limit"] == 3
    assert mine["system_key_remaining"] == 2

    app.dependency_overrides[get_current_user] = lambda: ctx["admin"]
    admin_mine = client.get("/api/me/llm").json()
    assert admin_mine["is_admin"] is True and admin_mine["unlimited"] is True
