"""真实数据库下的注册、登录与跨用户隔离测试。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import init_db
from app.main import app


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _client_with_account() -> tuple[TestClient, str]:
    client = TestClient(app)
    email = f"user_{uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "test-password-123", "display_name": "测试用户"},
    )
    assert response.status_code == 201, response.text
    return client, email


def test_register_login_and_current_user():
    client, email = _client_with_account()
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email
    assert me.json()["quota"]["limit"] >= 1

    other = TestClient(app)
    login = other.post("/api/auth/login", json={"email": email, "password": "test-password-123"})
    assert login.status_code == 200
    assert other.get("/api/auth/me").status_code == 200

    bad = TestClient(app)
    assert bad.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_profiles_are_invisible_to_other_users():
    alice, _ = _client_with_account()
    bob, _ = _client_with_account()

    created = alice.post("/api/profiles", json={"label": "Alice 的档案", "basics": {"name_en": "Alice"}})
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    assert [item["id"] for item in alice.get("/api/profiles").json()["items"]] == [profile_id]
    assert bob.get("/api/profiles").json()["items"] == []
    assert bob.get(f"/api/profiles/{profile_id}").status_code == 404
    assert bob.put(f"/api/profiles/{profile_id}", json={"label": "篡改"}).status_code == 404
    assert bob.delete(f"/api/profiles/{profile_id}").status_code == 404
    assert bob.get("/api/documents").json()["items"] == []


def test_quota_blocks_generation():
    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import SessionLocal

    client, email = _client_with_account()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        user.daily_quota = 0
        db.commit()

    profile = client.post("/api/profiles", json={"label": "配额测试"}).json()
    response = client.post(
        "/api/generate", json={"profile_id": profile["id"], "doc_type": "ps"}
    )
    assert response.status_code == 429, response.text
