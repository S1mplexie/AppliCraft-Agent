"""用户反馈：登录用户可提交，仅管理员可查看；未登录与越权访问必须被拒绝。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import SessionLocal, init_db
from app.main import app

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _register(client: TestClient, prefix: str) -> str:
    email = f"{prefix}_{uuid4().hex[:10]}@example.com"
    resp = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return email


def _promote_to_admin(email: str) -> None:
    """测试里把注册用户提升为管理员（与 sync-admin 的落库语义一致）。"""
    with SessionLocal() as db:  # type: Session
        user = db.query(User).filter_by(email=email).first()
        assert user is not None
        user.is_admin = True
        db.commit()


def test_submit_feedback_ok():
    client = TestClient(app)
    _register(client, "fb_ok")
    resp = client.post("/api/feedback", json={"content": "  希望支持导出 PDF，并且保留行间距设置。  "})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] > 0
    # 提交内容被 trim，避免把纯空格当成有效反馈。
    assert data["content"].startswith("希望支持导出")
    assert data["created_at"]


def test_submit_feedback_requires_login():
    client = TestClient(app)
    resp = client.post("/api/feedback", json={"content": "匿名反馈不应被接受"})
    assert resp.status_code == 401


def test_submit_feedback_empty_rejected():
    client = TestClient(app)
    _register(client, "fb_empty")
    resp = client.post("/api/feedback", json={"content": "      "})
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_feedback_list_admin_only():
    client = TestClient(app)
    user_email = _register(client, "fb_user")
    resp = client.post("/api/feedback", json={"content": "第一次使用，建议生成页加个示例。"})
    assert resp.status_code == 201

    # 普通用户不能查看任何人的反馈列表。
    denied = client.get("/api/feedback")
    assert denied.status_code == 403

    # 管理员可查看，且能看到提交者信息与原始内容。
    admin_client = TestClient(app)
    admin_email = _register(admin_client, "fb_admin")
    _promote_to_admin(admin_email)
    listing = admin_client.get("/api/feedback")
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert items, "管理员至少能看到一条反馈"
    assert items[0]["user_email"] == user_email
    assert "示例" in items[0]["content"]


def test_feedback_content_over_limit_rejected():
    client = TestClient(app)
    _register(client, "fb_long")
    resp = client.post("/api/feedback", json={"content": "超" * 2001})
    assert resp.status_code == 422