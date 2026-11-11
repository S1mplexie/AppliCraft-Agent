"""小程序 token 通道的 CSRF 回归测试。

真机与模拟器里的 wx.request 会固定带上 servicewechat.com 的 Referer，
登录前又没有 Bearer token；若沿用网页版同源校验，小程序会直接 403 无法登录。
本测试同时守住「网页版 Cookie 通道仍必须拒绝跨站写请求」这条底线。
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import init_db
from app.main import app

PASSWORD = "test-password-123"
# 微信开发者工具模拟器的真实 Referer 形态
MP_REFERER = {
    "Referer": "https://servicewechat.com/wx14c6a873042c0570/devtools/page-frame.html"
}


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _account() -> str:
    email = f"csrf_{uuid4().hex[:10]}@example.com"
    response = TestClient(app).post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return email


def test_token_login_accepts_miniprogram_referer():
    """核心回归：小程序登录不再被同源校验拦下。"""
    email = _account()
    response = TestClient(app).post(
        "/api/auth/token-login",
        json={"email": email, "password": PASSWORD},
        headers=MP_REFERER,
    )
    assert response.status_code == 200, response.text
    assert response.json()["token"]


def test_token_register_accepts_miniprogram_referer():
    email = f"csrfreg_{uuid4().hex[:10]}@example.com"
    response = TestClient(app).post(
        "/api/auth/token-register",
        json={"email": email, "password": PASSWORD},
        headers=MP_REFERER,
    )
    assert response.status_code == 201, response.text
    assert response.json()["token"]


def test_wechat_login_with_miniprogram_referer_is_not_csrf_blocked():
    """未配置凭证时应报 503（业务提示），而不是 403（来源不合法）。"""
    response = TestClient(app).post(
        "/api/auth/wechat-login", json={"code": "any"}, headers=MP_REFERER
    )
    assert response.status_code != 403, response.text
    assert response.status_code in (400, 401, 422, 503), response.text


def test_web_cookie_channel_still_rejects_cross_site_writes():
    """回归：网页版依赖 Cookie 的跨站写请求依旧必须被拒绝。"""
    cross_site = {"Origin": "https://evil.example"}
    assert TestClient(app).post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
        headers=cross_site,
    ).status_code == 403
    assert TestClient(app).post(
        "/api/profiles", json={"label": "跨站 Cookie"}, headers=cross_site
    ).status_code == 403


def test_token_channel_does_not_bypass_authentication():
    """豁免同源校验不等于豁免鉴权：密码错误仍 401。"""
    email = _account()
    response = TestClient(app).post(
        "/api/auth/token-login",
        json={"email": email, "password": "wrong-password"},
        headers=MP_REFERER,
    )
    assert response.status_code == 401, response.text
