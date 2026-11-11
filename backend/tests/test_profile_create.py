"""新建档案：网页与小程序会带空 id 占位，创建接口必须自动分配合法 ID。"""
from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import init_db
from app.main import app

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _client() -> TestClient:
    """每个用例用独立账号，避免档案列表互相干扰。"""
    client = TestClient(app)
    email = f"profile_{uuid4().hex[:10]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def _blank_profile() -> dict:
    """模拟前端 emptyProfile() 提交的空白档案。"""
    return {"id": "", "label": "我的申请档案", "created_at": "", "updated_at": "", "basics": {}}


def test_create_profile_with_blank_id_assigns_server_id():
    client = _client()
    response = client.post("/api/profiles", json=_blank_profile())
    assert response.status_code == 201, response.text
    data = response.json()
    assert re.fullmatch(r"[0-9a-f]{12}", data["id"])
    assert data["created_at"]
    assert data["label"] == "我的申请档案"


def test_create_profile_without_id_field_works():
    client = _client()
    response = client.post("/api/profiles", json={"label": "无 ID 档案"})
    assert response.status_code == 201, response.text
    assert re.fullmatch(r"[0-9a-f]{12}", response.json()["id"])


def test_blank_id_creates_distinct_profiles():
    client = _client()
    first = client.post("/api/profiles", json=_blank_profile())
    second = client.post("/api/profiles", json=_blank_profile())
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    listed = [item["id"] for item in client.get("/api/profiles").json()["items"]]
    assert first.json()["id"] in listed and second.json()["id"] in listed


def test_create_profile_still_rejects_illegal_nonblank_id():
    client = _client()
    response = client.post("/api/profiles", json={"id": "非法 ID!", "label": "不合法"})
    assert response.status_code == 400
    assert "非法 ID" in response.json()["detail"]
