"""SSE 生成链路与多用户归属隔离的接口测试。

此处的 StubLLM 仅供 pytest 使用，通过 FastAPI 的 dependency_overrides 注入。
运行中的应用绝不会使用它：生产环境始终调用配置好的 OpenAI 兼容端点。
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import routes_generate
from app.api.deps import get_current_user, get_db, get_llm, get_user_store
from app.main import app
from app.models.profile import ApplicantProfile
from app.storage.filestore import FileStore


class StubLLM:
    async def complete(self, *, task, system, user, **kwargs):
        if task == "cv_polish":
            return "## Education\n\n**Example University** — Bachelor in CS\n"
        return "## Statement of Purpose\n\nA grounded paragraph derived from the fact sheet."

    async def complete_json(self, *, task, system, user, **kwargs):
        if task == "outline":
            return {"sections": [{"title": "Opening", "goal": "Motivation", "evidence_ids": ["E1"]}]}
        return {"passed": True, "issues": [], "summary": "clean"}


class FakeUser:
    id = "user_test_a"
    daily_quota = 20
    is_active = True


class FakeDB:
    """只满足配额计数所需的最小接口，避免单元测试依赖真实数据库。"""

    def scalar(self, *args, **kwargs):
        return 0

    def get(self, *args, **kwargs):
        # 用户级模型配置查询：桩用户没有自带 Key
        return None


def _done_document_id(sse_text: str) -> str:
    for block in sse_text.split("\n\n"):
        if "event: done" not in block:
            continue
        for line in block.split("\n"):
            if line.startswith("data:"):
                return json.loads(line[5:].strip())["document"]["id"]
    raise AssertionError("SSE 流没有推送 done 事件")


def _profile_data() -> dict:
    return ApplicantProfile(
        basics={"name_en": "Test Applicant"},
        education=[{"school": "Example University", "major": "Computer Science"}],
        experiences=[{"org": "Lab", "role": "RA", "bullets": ["Built a pipeline"]}],
    ).model_dump()


def test_stream_generate_and_export(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    profile = store.save_profile(_profile_data())
    monkeypatch.setattr(routes_generate, "_log_generation", lambda *args, **kwargs: None)

    app.dependency_overrides[get_llm] = lambda: StubLLM()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/generate/stream",
            json={"profile_id": profile["id"], "doc_type": "ps", "language": "en"},
        )
        assert response.status_code == 200
        assert "event: start" in response.text
        assert "event: node" in response.text
        assert "verify" in response.text  # 校验节点已执行并推送
        doc_id = _done_document_id(response.text)

        detail = client.get(f"/api/documents/{doc_id}").json()
        assert detail["markdown"].strip()
        assert detail["meta"]["passed_verification"] is True
        assert len(detail["versions"]) == 1
        assert detail["trace"]["outline"]

        updated = client.put(
            f"/api/documents/{doc_id}", json={"markdown": "## Revised\n\nHuman edited text."}
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        assert len(client.get(f"/api/documents/{doc_id}").json()["versions"]) == 2

        docx = client.get(f"/api/documents/{doc_id}/download?format=docx")
        assert docx.status_code == 200
        assert docx.content[:2] == b"PK"

        listing = client.get(f"/api/documents?profile_id={profile['id']}").json()
        assert any(item["id"] == doc_id for item in listing["items"])
    finally:
        app.dependency_overrides.clear()


def test_user_directories_are_isolated(tmp_path):
    root = FileStore(tmp_path)
    alice = root.for_user("user_alice")
    bob = root.for_user("user_bob")
    profile = alice.save_profile(_profile_data())
    assert alice.get_profile(profile["id"])
    assert bob.get_profile(profile["id"]) is None
    assert bob.list_profiles() == []
    assert bob.list_documents() == []


def test_business_endpoints_require_login():
    client = TestClient(app)
    assert client.get("/api/profiles").status_code == 401
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
