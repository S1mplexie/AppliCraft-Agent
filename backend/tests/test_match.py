"""选校评估（AI 驱动，standalone）：偏好进入提示词与 API 权限。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.db.session import init_db
from app.main import app


class StubMatchLLM:
    """AI 评估测试替身：捕获提示词，返回覆盖全部项目的分档结果数组。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete_json(self, *, task: str, system: str, user: str, **kwargs):
        self.prompts.append(user)
        payload = json.loads(user)
        return [
            {
                "program_id": p["program_id"],
                "tier": "safety" if p.get("region") == "SG" else "match",
                "reasons": ["stub 依据"],
                "gaps": [],
            }
            for p in payload["programs"]
        ]


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def teardown_module():
    app.dependency_overrides.clear()


def _client() -> TestClient:
    client = TestClient(app)
    # 本地部署版单用户免登录，直接进入工作台。
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    return client


def _stub() -> StubMatchLLM:
    stub = StubMatchLLM()
    app.dependency_overrides[get_llm] = lambda: stub
    return stub


def _profile_id(client: TestClient) -> str:
    """取本地版已有档案的 id；没有则创建一个（评估必须指向真实档案）。"""
    resp = client.get("/api/profiles")
    items = resp.json()["items"]
    if items:
        return items[0]["id"]
    return client.post("/api/profiles", json={"label": "评估测试档案"}).json()["id"]


def test_prompt_includes_preferences():
    """带偏好评估时，择校 / 项目偏好必须进入提示词供模型参考。"""
    client = _client()
    stub = _stub()
    pid = _profile_id(client)
    resp = client.post(f"/api/match/{pid}", json={
        "preferences": {"priority_regions": ["SG"], "preferred_fields": ["计算机", "人工智能"]},
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences_applied"] is True
    prompt = stub.prompts[0]
    assert '"priority_regions"' in prompt and "SG" in prompt
    assert "计算机" in prompt and "人工智能" in prompt


def test_prompt_without_preferences_stays_clean():
    """不带偏好评估时，提示词不应出现 preferences 块（行为与既往一致）。"""
    client = _client()
    stub = _stub()
    pid = _profile_id(client)
    resp = client.post(f"/api/match/{pid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences_applied"] is False
    assert '"preferences"' not in stub.prompts[0]


def test_match_response_structure():
    client = _client()
    stub = _stub()
    pid = _profile_id(client)
    resp = client.post(f"/api/match/{pid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == 39
    item = data["results"][0]
    assert {"tier", "tier_label", "reasons", "gaps", "in_target", "program_id"} <= set(item.keys())
    assert item["tier"] in {"gap", "reach", "match", "safety"}


def test_match_stub_called_for_all_programs():
    """stub 捕获的提示词必须覆盖全部 30 个项目 id（与知识库一致）。"""
    client = _client()
    stub = _stub()
    pid = _profile_id(client)
    client.post(f"/api/match/{pid}")
    assert len(stub.prompts) == 1
    assert stub.prompts[0].count('"program_id"') >= 30