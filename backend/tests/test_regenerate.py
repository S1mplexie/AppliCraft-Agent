"""按审核建议重新生成：提示词、接口与版本/轨迹落盘的回归测试。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import routes_documents, routes_generate
from app.api.deps import get_current_user, get_db, get_llm, get_user_store
from app.graph import prompts
from app.main import app
from app.models.profile import ApplicantProfile
from app.storage.filestore import FileStore


class StubLLM:
    """revise 返回带标记的修订稿；verify 返回通过且带评分，便于断言落盘。"""

    async def complete(self, *, task, system, user, **kwargs):
        if task == "revise":
            self.last_user = user
            assert "审核建议" in user or "整体补充说明" in user, "revise 提示词应包含用户建议块"
            return "## Statement of Purpose\n\nRevised by user feedback."
        return "## Statement of Purpose\n\nOriginal draft."

    async def complete_json(self, *, task, system, user, **kwargs):
        return {
            "passed": True,
            "score": 88,
            "dimensions": {"factual_safety": 5},
            "issues": [],
            "summary": "clean",
        }


class FakeUser:
    id = "user_regen"
    daily_quota = 20
    is_active = True


class FakeDB:
    def scalar(self, *args, **kwargs):
        return 0

    def get(self, *args, **kwargs):
        # 用户级模型配置查询：桩用户没有自带 Key
        return None


def _profile_data() -> dict:
    return ApplicantProfile(
        basics={"name_en": "Test Applicant"},
        education=[{"school": "Example University", "major": "Computer Science"}],
        experiences=[{"org": "Lab", "role": "RA", "bullets": ["Built a pipeline"]}],
    ).model_dump()


def _create_document(store: FileStore) -> dict:
    """直接落盘一份带完整 trace 的文档，模拟一次已完成的生成。"""
    request = {
        "profile_id": "p1",
        "doc_type": "ps",
        "target_program_id": None,
        "recommender_id": None,
        "language": "en",
        "word_limit": 900,
        "tone": "professional",
        "emphasis": [],
        "extra_instructions": "",
    }
    facts, facts_text = prompts.render_facts(_profile_data(), request)
    trace = {
        "request": request,
        "model": "stub",
        "facts": facts,
        "facts_text": facts_text,
        "outline": [],
        "critique": {
            "passed": False,
            "score": 60,
            "dimensions": {"specificity": 3},
            "issues": [{"type": "specificity", "reason": "太笼统", "quote": "x", "fix": "加细节"}],
            "summary": "needs work",
            "numeric_warnings": [],
        },
        "issues": [{"type": "specificity", "reason": "太笼统"}],
        "passed_verification": False,
        "events": [{"node": "intake", "summary": "原始生成"}],
        "warnings": [],
        "revision_count": 0,
    }
    return store.save_document(
        profile_id="p1",
        doc_type="ps",
        markdown="## Statement of Purpose\n\nOriginal draft.",
        trace=trace,
        model="stub",
        language="en",
        subject="Example University",
    )


def test_regenerate_saves_new_version_and_trace(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    store.save_profile({**_profile_data(), "id": "p1", "label": "档案"})
    monkeypatch.setattr(routes_generate, "_log_generation", lambda *a, **k: None)

    app.dependency_overrides[get_llm] = lambda: StubLLM()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        meta = _create_document(store)

        response = client.post(
            f"/api/documents/{meta['id']}/regenerate",
            json={"feedback": "请加强动机段的具体性，删掉空泛表述"},
        )
        assert response.status_code == 200
        text = response.text
        assert "event: start" in text
        assert "event: node" in text
        assert "event: done" in text

        # done 事件携带新版本 meta
        for block in text.split("\n\n"):
            if "event: done" in block:
                done = json.loads(block.split("data:")[1].strip())
                assert done["document"]["version"] == 2

        # 落盘校验：新版本内容 + 轨迹更新（复审通过、事件追加、feedback 记录）
        doc = store.get_document(meta["id"])
        assert doc["markdown"].strip().endswith("Revised by user feedback.")
        assert len(doc["versions"]) == 2
        assert doc["meta"]["version"] == 2
        assert doc["meta"]["passed_verification"] is True
        assert doc["trace"]["passed_verification"] is True
        assert doc["trace"]["critique"]["score"] == 88
        assert doc["trace"]["feedback"] == "请加强动机段的具体性，删掉空泛表述"
        nodes_in_events = [e["node"] for e in doc["trace"]["events"]]
        assert nodes_in_events[0] == "intake"  # 原始事件保留
        assert "regenerate" in nodes_in_events
        assert "revise" in nodes_in_events
        assert doc["trace"]["revision_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_regenerate_requires_any_suggestion(tmp_path):
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        meta = _create_document(store)
        # 既没有逐项建议、也没有整体说明 → 422
        response = client.post(f"/api/documents/{meta['id']}/regenerate", json={"feedback": "  "})
        assert response.status_code == 422
        # 逐项建议不能是空白
        response = client.post(
            f"/api/documents/{meta['id']}/regenerate",
            json={"feedback": "", "issue_feedback": [{"index": 0, "suggestion": "   "}]},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_regenerate_with_per_issue_suggestions(tmp_path, monkeypatch):
    """逐项建议应按编号落实到提示词，并写入 trace。"""
    store = FileStore(tmp_path)
    store.save_profile({**_profile_data(), "id": "p1", "label": "档案"})
    monkeypatch.setattr(routes_generate, "_log_generation", lambda *a, **k: None)

    llm = StubLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        meta = _create_document(store)
        response = client.post(
            f"/api/documents/{meta['id']}/regenerate",
            json={
                "feedback": "",
                "issue_feedback": [{"index": 0, "suggestion": "保留原句，只把空泛词换成具体指标"}],
            },
        )
        assert response.status_code == 200
        assert "event: done" in response.text

        # 提示词按编号 + 原文 + 用户意见落实
        prompt = llm.last_user
        assert "逐项审核建议" in prompt
        assert "1." in prompt
        assert "保留原句" in prompt
        assert "原文「x」" in prompt or "太笼统" in prompt

        doc = store.get_document(meta["id"])
        assert doc["trace"]["issue_feedback"][0]["index"] == 0
        assert doc["trace"]["issue_feedback"][0]["suggestion"] == "保留原句，只把空泛词换成具体指标"
        # 逐项建议仍要按事实边界走
        assert "TO CONFIRM" in prompt
    finally:
        app.dependency_overrides.clear()


def test_regenerate_accepts_camel_case_issue_feedback(tmp_path, monkeypatch):
    """前端按 JS 习惯发 issueFeedback（驼峰）也必须生效，不能被静默丢弃返回 422。"""
    store = FileStore(tmp_path)
    store.save_profile({**_profile_data(), "id": "p1", "label": "档案"})
    monkeypatch.setattr(routes_generate, "_log_generation", lambda *a, **k: None)

    app.dependency_overrides[get_llm] = lambda: StubLLM()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        meta = _create_document(store)
        response = client.post(
            f"/api/documents/{meta['id']}/regenerate",
            json={"feedback": "", "issueFeedback": [{"index": 0, "suggestion": "换成具体指标"}]},
        )
        assert response.status_code == 200, response.text
        doc = store.get_document(meta["id"])
        assert doc["trace"]["issue_feedback"][0]["suggestion"] == "换成具体指标"
    finally:
        app.dependency_overrides.clear()


def test_regenerate_document_not_found(tmp_path):
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        response = client.post("/api/documents/missing/regenerate", json={"feedback": "x"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_regenerate_legacy_doc_without_request(tmp_path):
    """旧版文档 trace 里没有 request：应返回 400 友好提示而不是 500。"""
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        meta = store.save_document(
            profile_id="p1", doc_type="ps", markdown="old doc",
            trace={}, model="stub", language="en",
        )
        response = client.post(f"/api/documents/{meta['id']}/regenerate", json={"feedback": "改一下"})
        assert response.status_code == 400
        assert "重新生成" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_revise_prompt_includes_per_issue_and_overall_blocks():
    request = {"doc_type": "ps", "word_limit": 900}
    issues = [{"type": "specificity", "quote": "显著提升", "reason": "太模糊", "fix": "换成数字"}]
    text = prompts.revise_user(
        "facts", "draft", issues, request,
        feedback="结尾更克制",
        issue_feedback=[{"index": 0, "suggestion": "保留原意，只换成具体指标", **issues[0]}],
    )
    assert "逐项审核建议" in text
    assert "整体补充说明" in text
    assert "保留原意，只换成具体指标" in text
    assert "结尾更克制" in text
    assert "最高优先级" in text
    # 无任何建议时不出现这两个块
    plain = prompts.revise_user("facts", "draft", [], request)
    assert "逐项审核建议" not in plain and "整体补充说明" not in plain
