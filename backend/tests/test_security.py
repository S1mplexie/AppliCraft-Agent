"""账号密码制的安全策略测试：注册收敛、限流、同源校验与命令行建号。"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import routes_auth
from app.auth.guards import SlidingLimiter, registration_open
from app.db.models import User
from app.db.session import SessionLocal, init_db
from app.main import app


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _policy(allow: bool, bootstrap: bool) -> SimpleNamespace:
    # 注册策略只依赖这两个字段，用轻量替身即可覆盖全部组合。
    return SimpleNamespace(allow_registration=allow, bootstrap_first_user=bootstrap)


def test_registration_policy():
    closed = _policy(False, True)
    assert registration_open(0, closed) is True       # 空库允许自助创建首个账号
    assert registration_open(1, closed) is False      # 有了账号立刻关闭
    assert registration_open(0, _policy(False, False)) is False
    assert registration_open(9, _policy(True, False)) is True


def test_closed_registration_is_rejected(monkeypatch):
    monkeypatch.setattr(routes_auth.settings, "allow_registration", False)
    monkeypatch.setattr(routes_auth.settings, "bootstrap_first_user", False)
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={"email": f"blocked_{uuid4().hex[:8]}@example.com", "password": "some-password-123"},
    )
    assert response.status_code == 403, response.text
    assert client.get("/api/config").json()["allow_registration"] is False


def test_sliding_limiter():
    limiter = SlidingLimiter(max_attempts=2, window_seconds=60)
    assert limiter.check("ip") is True
    limiter.hit("ip")
    limiter.hit("ip")
    assert limiter.check("ip") is False
    limiter.reset("ip")
    assert limiter.check("ip") is True


def test_login_failure_rate_limit(monkeypatch):
    monkeypatch.setattr(routes_auth, "_login_limiter", SlidingLimiter(2, 600))
    client = TestClient(app)
    payload = {"email": f"lock_{uuid4().hex[:8]}@example.com", "password": "wrong-password"}
    assert client.post("/api/auth/login", json=payload).status_code == 401
    assert client.post("/api/auth/login", json=payload).status_code == 401
    limited = client.post("/api/auth/login", json=payload)
    assert limited.status_code == 429, limited.text


def test_csrf_rejects_cross_site_writes():
    client = TestClient(app)
    payload = {"email": "nobody@example.com", "password": "wrong-password"}
    evil = client.post("/api/auth/login", json=payload, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403, evil.text
    # 同源请求与无来源头的服务端脚本都应正常进入业务逻辑。
    same = client.post("/api/auth/login", json=payload, headers={"Origin": "http://testserver"})
    assert same.status_code != 403
    script = client.post("/api/auth/login", json=payload)
    assert script.status_code != 403
    assert client.get("/api/health").status_code == 200


def test_cli_creates_and_resets_account(monkeypatch):
    from app import cli

    email = f"cli_{uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(
        sys, "argv",
        ["app.cli", "create-user", email, "--password", "cli-password-123", "--name", "命令行用户"],
    )
    assert cli.main() == 0
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.display_name == "命令行用户"
        old_hash = user.password_hash

    monkeypatch.setattr(
        sys, "argv",
        ["app.cli", "reset-password", email, "--password", "replaced-password-456"],
    )
    assert cli.main() == 0
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == email)).password_hash != old_hash
