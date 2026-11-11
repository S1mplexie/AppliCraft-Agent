"""微信小程序一键登录：配置开关、账号绑定、免密登录与自动建号。

code2session 用可控桩替换，测试不打真实微信接口、也不需要 AppSecret。
"""
from __future__ import annotations

import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth
from app.auth import wechat as wechat_module
from app.auth.wechat import WechatIdentityInfo, WechatLoginError
from app.db.session import init_db
from app.main import app

PASSWORD = "test-password-123"
APPID = "wxtest0000001"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


@pytest.fixture
def wechat(monkeypatch):
    """开启微信登录，并把换取 openid 的过程替换成按 code 查表的桩。"""
    monkeypatch.setattr(routes_auth.settings, "wechat_appid", APPID)
    monkeypatch.setattr(routes_auth.settings, "wechat_secret", "test-secret")
    monkeypatch.setattr(routes_auth.settings, "wechat_auto_register", False)
    codes: dict[str, WechatIdentityInfo] = {}

    def fake_exchange(code, settings):
        if code in codes:
            return codes[code]
        raise WechatLoginError("微信登录凭证无效或已过期，请退出小程序重新进入再试")

    monkeypatch.setattr(routes_auth, "exchange_code", fake_exchange)
    return codes


def _code(wechat: dict, openid: str | None = None) -> str:
    code = "code-" + uuid4().hex[:10]
    wechat[code] = WechatIdentityInfo(openid=openid or "openid-" + uuid4().hex[:8])
    return code


def _account() -> str:
    email = f"wx_{uuid4().hex[:10]}@example.com"
    response = TestClient(app).post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return email


def test_config_flag_and_disabled_endpoint(monkeypatch):
    """未配置 AppID / AppSecret 时入口隐藏，接口明确报 503 而不是假登录。"""
    monkeypatch.setattr(routes_auth.settings, "wechat_appid", "")
    monkeypatch.setattr(routes_auth.settings, "wechat_secret", "")
    client = TestClient(app)
    assert client.get("/api/config").json()["wechat_login_enabled"] is False
    assert client.post("/api/auth/wechat-login", json={"code": "any"}).status_code == 503


def test_config_flag_enabled_when_credentials_present(wechat):
    assert TestClient(app).get("/api/config").json()["wechat_login_enabled"] is True


def test_first_login_needs_binding_then_passwordless_login(wechat):
    email = _account()
    code = _code(wechat)
    client = TestClient(app)

    first = client.post("/api/auth/wechat-login", json={"code": code})
    assert first.status_code == 200, first.text
    assert first.json()["need_bind"] is True

    bound = client.post(
        "/api/auth/wechat-bind",
        json={"code": code, "email": email, "password": PASSWORD},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["user"]["email"] == email
    token = bound.json()["token"]
    assert token

    # 同一微信号再次进入直接拿到 token，且仍是原来那个账号、原来的数据。
    second = client.post("/api/auth/wechat-login", json={"code": code})
    assert second.status_code == 200, second.text
    assert second.json()["user"]["email"] == email
    assert TestClient(app, headers={"Authorization": f"Bearer {token}"}).get("/api/auth/me").status_code == 200


def test_bind_rejects_wrong_password(wechat):
    email = _account()
    response = TestClient(app).post(
        "/api/auth/wechat-bind",
        json={"code": _code(wechat), "email": email, "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_invalid_code_maps_to_readable_error(wechat):
    response = TestClient(app).post("/api/auth/wechat-login", json={"code": "unknown-code"})
    assert response.status_code == 400
    assert "凭证" in response.json()["detail"]


def test_auto_register_creates_one_wechat_only_account(wechat, monkeypatch):
    monkeypatch.setattr(routes_auth.settings, "wechat_auto_register", True)
    code = _code(wechat)
    client = TestClient(app)
    first = client.post("/api/auth/wechat-login", json={"code": code})
    assert first.status_code == 200, first.text
    assert "token" in first.json()
    assert first.json()["user"]["email"].endswith("@wechat.local")
    second = client.post("/api/auth/wechat-login", json={"code": code})
    assert second.json()["user"]["id"] == first.json()["user"]["id"]


def test_one_openid_cannot_bind_two_accounts(wechat):
    email_a, email_b = _account(), _account()
    code = _code(wechat)
    client = TestClient(app)
    assert client.post(
        "/api/auth/wechat-bind", json={"code": code, "email": email_a, "password": PASSWORD}
    ).status_code == 200
    conflict = client.post(
        "/api/auth/wechat-bind", json={"code": code, "email": email_b, "password": PASSWORD}
    )
    assert conflict.status_code == 409


def test_exchange_code_maps_wechat_errcode(monkeypatch):
    """真实解析逻辑：微信错误码不透传 errmsg，映射成中文提示。"""
    monkeypatch.setattr(routes_auth.settings, "wechat_appid", APPID)
    monkeypatch.setattr(routes_auth.settings, "wechat_secret", "test-secret")

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        wechat_module,
        "urlopen",
        lambda request, timeout: FakeResponse(b'{"errcode":40029,"errmsg":"invalid code"}'),
    )
    with pytest.raises(WechatLoginError) as exc:
        wechat_module.exchange_code("some-code", routes_auth.settings)
    assert "凭证" in exc.value.message
    assert "invalid code" not in exc.value.message
