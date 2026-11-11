"""小程序 Bearer Token 通道测试：与网页版 Cookie 会话共用账号、配额与数据。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import init_db
from app.main import app

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _new_account() -> tuple[TestClient, str]:
    """用网页版注册建号，再返回网页客户端与邮箱。"""
    client = TestClient(app)
    email = f"mp_{uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "小程序用户"},
    )
    assert response.status_code == 201, response.text
    return client, email


def _token(email: str) -> str:
    response = TestClient(app).post("/api/auth/token-login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert token and len(token) > 20
    assert "user" in response.json() and "quota" in response.json()
    return token


def test_token_login_grants_access_to_api():
    _, email = _new_account()
    client = TestClient(app, headers={"Authorization": f"Bearer {_token(email)}"})
    assert client.get("/api/auth/me").json()["user"]["email"] == email
    created = client.post("/api/profiles", json={"label": "小程序档案", "basics": {"name_en": "Mini"}})
    assert created.status_code == 201, created.text
    assert [p["id"] for p in client.get("/api/profiles").json()["items"]] == [created.json()["id"]]


def test_token_login_rejects_wrong_password():
    _, email = _new_account()
    bad = TestClient(app).post("/api/auth/token-login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401
    assert "token" not in bad.json()


def test_token_logout_revokes_only_that_session():
    web, email = _new_account()
    token_a, token_b = _token(email), _token(email)
    a = TestClient(app, headers={"Authorization": f"Bearer {token_a}"})
    b = TestClient(app, headers={"Authorization": f"Bearer {token_b}"})
    assert a.post("/api/auth/token-logout").status_code == 200
    assert a.get("/api/auth/me").status_code == 401
    # 另一条小程序会话和网页 Cookie 都不受影响。
    assert b.get("/api/auth/me").status_code == 200
    assert web.get("/api/auth/me").status_code == 200


def test_bearer_requests_bypass_csrf_guard():
    """小程序不发送浏览器同源头；显式携带 token 的写请求不应被当成 CSRF。"""
    _, email = _new_account()
    token = _token(email)
    cross_site = {"Origin": "https://evil.example"}
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert client.post("/api/profiles", json={"label": "跨站 Bearer"}, headers=cross_site).status_code == 201
    # 回归：依赖 Cookie 的跨站写请求仍然必须被拒绝。
    assert TestClient(app).post(
        "/api/profiles", json={"label": "跨站 Cookie"}, headers=cross_site
    ).status_code == 403


def test_token_and_cookie_share_the_same_data():
    web, email = _new_account()
    profile = web.post("/api/profiles", json={"label": "网页建的档案", "basics": {"name_en": "Shared"}}).json()
    mp = TestClient(app, headers={"Authorization": f"Bearer {_token(email)}"})
    assert mp.get(f"/api/profiles/{profile['id']}").json()["label"] == "网页建的档案"
    assert mp.get("/api/auth/me").json()["quota"]["limit"] >= 1


def test_token_register_returns_usable_token():
    email = f"mpreg_{uuid4().hex[:10]}@example.com"
    response = TestClient(app).post(
        "/api/auth/token-register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/auth/me").json()["user"]["email"] == email
