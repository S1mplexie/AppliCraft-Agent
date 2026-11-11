"""用户自带大模型 Key（BYOK）：加密、隔离、脱敏、优先级、配额与接口回归。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import deps
from app.api.deps import check_quota, get_current_user, get_db, get_llm
from app.config import get_settings
from app.db.models import Base, User, UserLLMSetting
from app.llm import user_settings as us
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.main import app

PERSONAL_KEY = "sk-personal-abcdefghijklmnop1234"
PERSONAL_URL = "https://api.example-llm.com/v1"
PERSONAL_MODEL = "my-custom-model"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """独立 SQLite + 独立加密密钥目录，避免污染真实 data/ 或全局单例缓存。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "allow_personal_llm_keys", True)
    monkeypatch.setattr(settings, "require_personal_llm_key", False)
    monkeypatch.setattr(settings, "llm_api_key", "sk-system-key-9999")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.system-llm.com/v1")
    monkeypatch.setattr(settings, "llm_model", "system-model")
    us._fernet.cache_clear()
    deps._system_llm.cache_clear()

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    user_a = User(id="user_a", email="a@example.com", password_hash="x", daily_quota=2)
    user_b = User(id="user_b", email="b@example.com", password_hash="x", daily_quota=2)
    session.add_all([user_a, user_b])
    session.commit()
    yield {"settings": settings, "db": session, "user_a": user_a, "user_b": user_b}
    session.close()
    deps._llm_registry._items.clear()
    deps._llm_registry._evicted.clear()
    deps._system_llm.cache_clear()
    us._fernet.cache_clear()
    app.dependency_overrides.clear()


def _client(ctx, user_key: str = "user_a"):
    app.dependency_overrides[get_db] = lambda: ctx["db"]
    app.dependency_overrides[get_current_user] = lambda: ctx[user_key]
    return TestClient(app)


# ------------------------------------------------------------------ 加密与校验
def test_encrypt_roundtrip_and_mask(ctx):
    cipher = us._encrypt(PERSONAL_KEY)
    assert PERSONAL_KEY not in cipher
    assert us._decrypt(cipher) == PERSONAL_KEY
    assert us.mask_key(PERSONAL_KEY) == "***1234"
    assert PERSONAL_KEY not in us.mask_key(PERSONAL_KEY)


def test_validate_input_rejects_bad_values(ctx):
    with pytest.raises(us.UserLLMError):
        us.validate_input(base_url="ftp://evil.com/v1", model="m", api_key="k")
    with pytest.raises(us.UserLLMError):
        us.validate_input(base_url="javascript:alert(1)", model="m", api_key="k")
    with pytest.raises(us.UserLLMError):
        us.validate_input(base_url=PERSONAL_URL, model="bad model name!", api_key="k")
    with pytest.raises(us.UserLLMError):
        us.validate_input(base_url=PERSONAL_URL, model="", api_key="k")
    url, model, key = us.validate_input(base_url=PERSONAL_URL + "/", model=" gpt-4o ", api_key=" sk ")
    assert (url, model, key) == (PERSONAL_URL, "gpt-4o", "sk")


# ------------------------------------------------------------------ 存储与隔离
def test_save_read_delete_is_per_user(ctx):
    db = ctx["db"]
    result = us.save_config(db, "user_a", base_url=PERSONAL_URL, model=PERSONAL_MODEL, api_key=PERSONAL_KEY)
    assert result["has_key"] is True
    assert result["api_key_hint"] == "***1234"
    assert PERSONAL_KEY not in str(result)

    # 密文确实落在库里，而不是明文
    row = db.get(UserLLMSetting, "user_a")
    assert PERSONAL_KEY not in row.api_key_cipher
    assert us._decrypt(row.api_key_cipher) == PERSONAL_KEY

    # 另一用户完全看不到
    assert us.public_config(db, "user_b")["has_key"] is False
    assert us.secret_config(db, "user_b") is None

    assert us.delete_config(db, "user_a") is True
    assert us.public_config(db, "user_a")["has_key"] is False
    assert us.delete_config(db, "user_a") is False


def test_empty_key_keeps_existing_secret(ctx):
    db = ctx["db"]
    us.save_config(db, "user_a", base_url=PERSONAL_URL, model=PERSONAL_MODEL, api_key=PERSONAL_KEY)
    us.save_config(db, "user_a", base_url=PERSONAL_URL, model="another-model", api_key="")
    secret = us.secret_config(db, "user_a")
    assert secret["api_key"] == PERSONAL_KEY
    assert secret["model"] == "another-model"


def test_empty_key_without_existing_raises(ctx):
    with pytest.raises(us.UserLLMError):
        us.save_config(ctx["db"], "user_b", base_url=PERSONAL_URL, model="m", api_key="")


# ------------------------------------------------------------------ 生效配置优先级
def test_resolve_personal_wins_and_keeps_global_runtime_settings(ctx):
    settings = ctx["settings"]
    personal = {"api_key": PERSONAL_KEY, "base_url": PERSONAL_URL, "model": PERSONAL_MODEL}
    effective = us.resolve_effective_llm(settings, personal)
    assert effective.source == "personal"
    assert effective.settings.llm_api_key == PERSONAL_KEY
    assert effective.settings.llm_model == PERSONAL_MODEL
    assert effective.settings.llm_base_url == PERSONAL_URL
    # 超时 / 重试 / temperature 等运行参数仍继承全局
    assert effective.settings.llm_timeout == settings.llm_timeout
    assert settings.llm_api_key == "sk-system-key-9999"  # 未污染全局单例


def test_resolve_system_fallback_and_require_personal(ctx):
    settings = ctx["settings"]
    assert us.resolve_effective_llm(settings, None).source == "system"
    settings.require_personal_llm_key = True
    with pytest.raises(us.UserLLMError, match="自己的 API Key"):
        us.resolve_effective_llm(settings, None)


def test_resolve_raises_when_no_key_at_all(ctx):
    blank = ctx["settings"].model_copy(update={"llm_api_key": "", "require_personal_llm_key": False})
    with pytest.raises(LLMNotConfiguredError):
        us.resolve_effective_llm(blank, None)


def test_disabled_feature_falls_back_to_system(ctx):
    settings = ctx["settings"]
    settings.allow_personal_llm_keys = False
    personal = {"api_key": PERSONAL_KEY, "base_url": PERSONAL_URL, "model": PERSONAL_MODEL}
    assert us.resolve_effective_llm(settings, personal).source == "system"


def test_get_llm_returns_personal_client_with_source(ctx, monkeypatch):
    us.save_config(ctx["db"], "user_a", base_url=PERSONAL_URL, model=PERSONAL_MODEL, api_key=PERSONAL_KEY)
    client = get_llm(user=ctx["user_a"], db=ctx["db"], settings=ctx["settings"])
    assert isinstance(client, LLMClient)
    assert client.source == "personal"
    assert client.settings.llm_api_key == PERSONAL_KEY
    assert client.settings.llm_model == PERSONAL_MODEL
    # 同一配置复用同一个客户端，避免每次请求新建连接池
    assert get_llm(user=ctx["user_a"], db=ctx["db"], settings=ctx["settings"]) is client


def test_get_llm_raises_when_personal_required(ctx):
    ctx["settings"].require_personal_llm_key = True
    with pytest.raises(HTTPException) as exc:
        get_llm(user=ctx["user_b"], db=ctx["db"], settings=ctx["settings"])
    assert exc.value.status_code == 400


# ------------------------------------------------------------------ 配额豁免
class _FullQuotaDB:
    def scalar(self, *args, **kwargs):
        return 999


def test_byok_skips_system_daily_quota(ctx, monkeypatch):
    monkeypatch.setattr(deps, "quota_used", lambda db, uid: 999)
    personal = type("L", (), {"source": "personal"})()
    system = type("L", (), {"source": "system"})()
    check_quota(_FullQuotaDB(), ctx["user_a"], personal)  # 不抛
    with pytest.raises(HTTPException) as exc:
        check_quota(_FullQuotaDB(), ctx["user_a"], system)
    assert exc.value.status_code == 429
    with pytest.raises(HTTPException):
        check_quota(_FullQuotaDB(), ctx["user_a"], None)  # 测试桩无 source 时按系统处理


# ------------------------------------------------------------------ HTTP 接口
def test_http_get_put_delete(ctx):
    client = _client(ctx)
    resp = client.get("/api/me/llm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_key"] is False
    assert body["effective_source"] == "system"
    assert body["effective_model"] == "system-model"

    resp = client.put("/api/me/llm", json={
        "base_url": PERSONAL_URL, "model": PERSONAL_MODEL, "api_key": PERSONAL_KEY,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_key"] is True
    assert body["api_key_hint"] == "***1234"
    assert body["effective_source"] == "personal"
    assert body["effective_model"] == PERSONAL_MODEL
    assert PERSONAL_KEY not in resp.text

    assert client.delete("/api/me/llm").json()["effective_source"] == "system"


def test_http_other_user_cannot_see_or_delete(ctx):
    us.save_config(ctx["db"], "user_a", base_url=PERSONAL_URL, model=PERSONAL_MODEL, api_key=PERSONAL_KEY)
    client = _client(ctx, "user_b")
    assert client.get("/api/me/llm").json()["has_key"] is False
    client.delete("/api/me/llm")
    assert us.secret_config(ctx["db"], "user_a")["api_key"] == PERSONAL_KEY  # A 的配置没被动过


def test_http_feature_disabled_blocks_edits(ctx):
    ctx["settings"].allow_personal_llm_keys = False
    client = _client(ctx)
    assert client.put("/api/me/llm", json={
        "base_url": PERSONAL_URL, "model": "m", "api_key": PERSONAL_KEY,
    }).status_code == 403
    assert client.get("/api/me/llm").json()["allow_personal_llm_keys"] is False


def test_http_bad_input_returns_400(ctx):
    client = _client(ctx)
    resp = client.put("/api/me/llm", json={
        "base_url": "not-a-url", "model": "m", "api_key": PERSONAL_KEY,
    })
    assert resp.status_code == 400
    assert PERSONAL_KEY not in resp.text


def test_http_test_endpoint_never_leaks_key(ctx, monkeypatch):
    """连通性测试用桩替换真实客户端：成功/失败都不回显完整 Key。"""
    class ProbeLLM:
        def __init__(self, settings, source="system"):
            self.settings = settings
            self.source = source
            self.calls = []

        async def complete(self, **kwargs):
            self.calls.append(kwargs)
            return "OK"

        async def aclose(self):
            pass

    monkeypatch.setattr("app.api.routes_llm.LLMClient", ProbeLLM)
    client = _client(ctx)
    resp = client.post("/api/me/llm/test", json={
        "base_url": PERSONAL_URL, "model": PERSONAL_MODEL, "api_key": PERSONAL_KEY,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert PERSONAL_KEY not in resp.text

    class FailingLLM(ProbeLLM):
        async def complete(self, **kwargs):
            raise RuntimeError(f"401 invalid key {self.settings.llm_api_key}")

    monkeypatch.setattr("app.api.routes_llm.LLMClient", FailingLLM)
    resp = client.post("/api/me/llm/test", json={
        "base_url": PERSONAL_URL, "model": PERSONAL_MODEL, "api_key": PERSONAL_KEY,
    })
    assert resp.json()["ok"] is False
    assert PERSONAL_KEY not in resp.text


def test_config_endpoint_exposes_switches(ctx):
    client = _client(ctx)
    body = client.get("/api/config").json()
    assert body["allow_personal_llm_keys"] is True
    assert body["require_personal_llm_key"] is False
