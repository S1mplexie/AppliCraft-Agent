"""开放注册策略：默认开放、非空库仍可注册、新账号不带管理员权限。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import User
from app.db.session import SessionLocal, init_db
from app.main import app

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _email(tag: str = "open") -> str:
    return f"{tag}_{uuid4().hex[:10]}@example.com"


def test_registration_defaults_to_open():
    """类字段默认值不受测试环境变量影响，验证产品默认策略本身。"""
    assert Settings.model_fields["allow_registration"].default is True
    assert Settings.model_fields["register_max_attempts"].default == 10


def test_config_reports_open_registration_with_existing_users():
    client = TestClient(app)
    first = client.post(
        "/api/auth/register", json={"email": _email("first"), "password": PASSWORD}
    )
    assert first.status_code == 201, first.text
    cfg = client.get("/api/config").json()
    assert cfg["allow_registration"] is True
    assert cfg["system_key_daily_limit"] == 3


def test_new_visitor_registers_without_admin_privileges():
    """开放注册不能把新账号变成管理员，且沿用每天 3 次系统 Key 免费额度。"""
    client = TestClient(app)
    email = _email("newcomer")
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "新用户"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["quota"]["source"] == "system"
    assert body["quota"]["unlimited"] is False
    assert body["quota"]["system_key_remaining"] == 3

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert bool(user.is_admin) is False


def test_registered_account_can_login_and_read_me():
    email = _email("login")
    creator = TestClient(app)
    assert creator.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    ).status_code == 201

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert client.get("/api/auth/me").json()["user"]["email"] == email


def test_miniprogram_token_register_works_when_users_exist():
    """非空库时小程序自助注册也可用（旧版只允许空库建首个账号）。"""
    client = TestClient(app)
    response = client.post(
        "/api/auth/token-register",
        json={"email": _email("wx"), "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200, me.text
