"""Skill 市场：内置技能、导入解析、上下文装配、接口与生成注入测试。"""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_user_store
from app.graph import prompts
from app.main import app
from app.models.schemas import GenerateRequest
from app.skills.service import (
    SkillError,
    build_skill_context,
    builtin_skills,
    get_skill_detail,
    parse_frontmatter,
    parse_skill_upload,
)
from app.storage.filestore import FileStore

SKILL_MD = """---
name: demo-skill
description: 演示用写作技能
agent_created: true
---

# 演示技能

## 规则
每条经历都要写动作、结果和可核查数值，禁止空话与无支撑形容词。
所有缺失的信息标注待确认，绝不估计后提交。
"""


class FakeUser:
    id = "user_skills_test"
    daily_quota = 20
    is_active = True


class FakeDB:
    def scalar(self, *args, **kwargs):
        return 0

    def get(self, *args, **kwargs):
        return None


def _zip_package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("alpha/SKILL.md", SKILL_MD)
        archive.writestr("alpha/references/examples.md", "# 示例\n空话 → 改写对照表内容")
        archive.writestr("beta/SKILL.md", SKILL_MD.replace("演示技能", "第二个技能"))
        archive.writestr("README.md", "# 技能包说明")
        archive.writestr("../evil.md", "不该被导入的路径穿越文件")
    return buffer.getvalue()


def test_builtin_catalog_is_readonly_and_complete(tmp_path):
    items = builtin_skills()
    assert len(items) == 4
    assert "builtin:grad-sop-writing" in {item["id"] for item in items}
    # 列表不返回大字段，详情才返回完整方法论与示例。
    assert all("content" not in item and "instructions" not in item for item in items)
    detail = get_skill_detail(FileStore(tmp_path), "builtin:grad-sop-writing")
    assert "结构骨架" in detail["content"]
    assert "禁止" in detail["instructions"]
    assert detail["examples"]
    assert get_skill_detail(FileStore(tmp_path), "builtin:missing") is None


def test_parse_frontmatter():
    fm, body = parse_frontmatter(SKILL_MD)
    assert fm["name"] == "demo-skill"
    assert fm["description"] == "演示用写作技能"
    assert body.startswith("# 演示技能")


def test_parse_markdown_upload():
    items = parse_skill_upload(
        "my-skill.md", SKILL_MD.encode("utf-8"),
        name="我的技能", description="自定义描述",
    )
    assert len(items) == 1
    assert items[0]["name"] == "我的技能"
    assert items[0]["description"] == "自定义描述"
    assert "frontmatter" not in items[0]["content"]
    assert "禁止空话" in items[0]["content"]


def test_parse_zip_package_and_ignore_unsafe_members():
    items = parse_skill_upload("skills.zip", _zip_package())
    assert len(items) == 2  # README 与路径穿越成员均被忽略
    assert {item["name"] for item in items} == {"演示技能", "第二个技能"}
    with_examples = [item for item in items if item["examples"]]
    assert len(with_examples) == 1
    assert "空话" in with_examples[0]["examples"]


def test_parse_upload_rejects_bad_input():
    with pytest.raises(SkillError):
        parse_skill_upload("skill.exe", b"binary")
    with pytest.raises(SkillError):
        parse_skill_upload("skill.md", b"\xff\xfe\x00not-utf8")
    with pytest.raises(SkillError, match="过短"):
        parse_skill_upload("skill.md", b"# short")
    with pytest.raises(SkillError):
        parse_skill_upload("skill.zip", b"not-a-zip")
    with pytest.raises(SkillError):
        parse_skill_upload("skill.md", b"x" * 1_100_000)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes/readme.txt", "只有说明，没有技能文件")
    # 包内唯一的 txt 会被当作技能，但正文过短时应被拒绝。
    with pytest.raises(SkillError):
        parse_skill_upload("skills.zip", buffer.getvalue())


def test_skill_store_crud(tmp_path):
    store = FileStore(tmp_path)
    saved = store.save_skill(
        name="自定义技能", content="用动词开头；给出可核查数值。", examples="示例文本",
        filename="custom.md",
    )
    assert saved["id"].startswith("user:")
    assert saved["imported_at"]
    listed = store.list_skills()
    assert len(listed) == 1 and listed[0]["has_examples"] is True
    detail = store.get_skill(saved["id"][5:])
    assert detail["content"].startswith("用动词开头")
    assert detail["examples"] == "示例文本"
    assert store.delete_skill(saved["id"][5:]) is True
    assert store.list_skills() == []


def test_build_skill_context_assembles_builtin_user_and_missing(tmp_path):
    store = FileStore(tmp_path)
    skill_id = store.save_skill(
        name="自定义技能", content="每条经历都要写动作、结果和可核查数值。"
    )["id"]
    ctx, meta = build_skill_context(
        store, ["builtin:grad-sop-writing", skill_id, "builtin:missing"]
    )
    assert "禁止童年热情" in ctx         # 内置技能用精炼版指令
    assert "可核查数值" in ctx          # 用户技能用正文
    assert {m["included"] for m in meta} == {True, False}
    assert meta[0]["origin"] == "builtin"
    assert meta[1]["origin"] == "user"
    assert meta[2]["missing"] is True


def test_build_skill_context_budget_truncation(tmp_path):
    store = FileStore(tmp_path)
    other = store.save_skill(name="另一个技能", content="另外一条规则" * 50)["id"]
    ctx, meta = build_skill_context(
        store, ["builtin:grad-sop-writing", other], max_chars=300
    )
    assert meta[0]["included"] is True and meta[0]["truncated"] is True
    assert meta[1]["included"] is False
    assert "按字数预算截断" in ctx


def test_prompt_skill_block_guardrails():
    assert prompts.skill_block("", []) == ""
    block = prompts.skill_block(
        "### 技能：X\n规则", [{"included": True, "name": "X"}]
    )
    assert "事实清单" in block and "[TO CONFIRM" in block
    assert "不是申请人事实" in block
    assert "已启用技能：\n- X" in block


def _override(store: FileStore) -> None:
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()


def test_skills_api_import_detail_and_delete(tmp_path):
    _override(FileStore(tmp_path))
    try:
        client = TestClient(app)
        catalog = client.get("/api/skills").json()["items"]
        assert len(catalog) == 4

        resp = client.post(
            "/api/skills",
            files={"file": ("demo.md", SKILL_MD.encode("utf-8"), "text/markdown")},
            data={"name": "导入技能"},
        )
        assert resp.status_code == 201, resp.text
        skill_id = resp.json()["items"][0]["id"]
        assert skill_id.startswith("user:")

        detail = client.get("/api/skills/detail", params={"skill_id": skill_id})
        assert detail.status_code == 200
        assert "禁止空话" in detail.json()["content"]

        builtin_detail = client.get(
            "/api/skills/detail", params={"skill_id": "builtin:grad-sop-writing"}
        )
        assert builtin_detail.status_code == 200
        assert builtin_detail.json()["examples"]

        assert client.delete(f"/api/skills/{skill_id}").json()["deleted"] is True
        assert client.get("/api/skills/detail", params={"skill_id": skill_id}).status_code == 404
        assert client.delete("/api/skills/builtin:grad-sop-writing").status_code == 400
    finally:
        app.dependency_overrides.clear()


class StubLLM:
    """草稿阶段回显技能标记，验证提示词确实注入了技能段落。"""

    async def complete(self, *, task, system, user, **kwargs):
        if task in ("draft", "revise") and "禁止童年热情" in (user or ""):
            return "遵循技能规则的草稿 [TO CONFIRM: target programme]."
        return "Draft [TO CONFIRM: target programme]."

    async def complete_json(self, *, task, system, user, **kwargs):
        if task == "outline":
            return {"sections": [{"title": "开篇", "goal": "动机", "evidence_ids": []}]}
        if task == "verify":
            return {
                "passed": True, "score": 90,
                "dimensions": {"factual_safety": 5, "program_fit": 5, "specificity": 5,
                               "structure": 5, "tone_register": 5, "language_quality": 5},
                "issues": [], "summary": "ok",
            }
        return {}


def test_generate_injects_selected_skill_into_trace(tmp_path, monkeypatch):
    from app.api import routes_generate
    from app.api.deps import get_llm

    monkeypatch.setattr(routes_generate, "_log_generation", lambda *a, **k: None)
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())
    app.dependency_overrides[get_llm] = lambda: StubLLM()
    _override(store)
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/generate",
            json=GenerateRequest(
                profile_id=profile["id"], doc_type="ps",
                skill_ids=["builtin:grad-sop-writing"],
            ).model_dump(),
        )
        assert resp.status_code == 200, resp.text
        detail = client.get(f"/api/documents/{resp.json()['id']}").json()
        skills = detail["trace"]["skills"]
        assert len(skills) == 1 and skills[0]["included"] is True
        assert skills[0]["name"] == "个人陈述 / SOP 写作"
        assert "遵循技能规则" in detail["markdown"]

        plain = client.post(
            "/api/generate",
            json=GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump(),
        )
        assert plain.status_code == 200
        detail2 = client.get(f"/api/documents/{plain.json()['id']}").json()
        assert detail2["trace"]["skills"] == []
    finally:
        app.dependency_overrides.clear()


def test_reference_uploaded_at_falls_back_to_file_mtime(tmp_path):
    """旧数据没有时间戳时，也能显示各自的导入时间。"""
    store = FileStore(tmp_path)
    directory = store._references_dir()
    (directory / "legacy.json").write_text(
        json.dumps({"id": "legacy", "name": "早期文档", "char_count": 10}),
        encoding="utf-8",
    )
    (directory / "legacy.txt").write_text("legacy text", encoding="utf-8")
    items = store.list_references()
    assert len(items) == 1
    assert items[0]["uploaded_at"].startswith("20")


def _base_profile() -> dict:
    from app.models.profile import ApplicantProfile
    return ApplicantProfile(
        basics={"name_en": "Test User", "email": "t@example.com"},
        target_programs=[{"university": "HKU", "program": "MSc in Computer Science",
                          "degree_type": "Taught Master"}],
    ).model_dump()


# --------------------------------------- 导入后弹窗填写名称 / 简介（2026-11-10）
def test_store_update_skill_only_changes_metadata(tmp_path):
    store = FileStore(tmp_path)
    content = "每条经历都要写动作、结果和可核查数值。" * 12
    full_id = store.save_skill(
        name="原名", description="旧简介", content=content,
        examples="示例文本", filename="demo.md",
    )["id"]
    skill_id = full_id[5:]
    before = store.list_skills()[0]

    meta = store.update_skill(skill_id, name=" 我的写法规范 ", description=" 约束段落长度 ")
    assert meta["name"] == "我的写法规范"
    assert meta["description"] == "约束段落长度"
    assert meta["imported_at"] == before["imported_at"]
    assert meta["char_count"] == before["char_count"]
    detail = store.get_skill(skill_id)
    assert detail["content"] == content
    assert detail["examples"] == "示例文本"

    cleared = store.update_skill(skill_id, name="", description="")
    assert cleared["name"] == "demo.md"
    assert cleared["description"] == ""
    assert store.update_skill("deadbeef1234", name="X", description="") is None


def test_skills_import_then_naming_dialog_endpoint(tmp_path):
    """导入时不带名称/简介 → 弹窗 PATCH 补写 → 列表与详情同步，内置技能只读。"""
    _override(FileStore(tmp_path))
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/skills",
            files={"file": ("demo.md", SKILL_MD.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 201, resp.text
        skill = resp.json()["items"][0]
        skill_id = skill["id"]
        assert skill["name"] and skill["imported_at"]

        updated = client.patch(
            f"/api/skills/{skill_id}",
            json={"name": "我的 PS 写法规范", "description": "段落短、以事实清单为准"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "我的 PS 写法规范"
        assert updated.json()["description"] == "段落短、以事实清单为准"
        assert updated.json()["imported_at"] == skill["imported_at"]
        detail = client.get("/api/skills/detail", params={"skill_id": skill_id})
        assert "禁止空话" in detail.json()["content"]
        listing = [x for x in client.get("/api/skills").json()["items"] if x["id"] == skill_id]
        assert listing[0]["name"] == "我的 PS 写法规范"

        assert client.patch(
            "/api/skills/builtin:grad-sop-writing",
            json={"name": "篡改", "description": ""},
        ).status_code == 400
        assert client.patch(
            "/api/skills/user:deadbeef1234",
            json={"name": "X", "description": ""},
        ).status_code == 404
        assert client.patch(
            f"/api/skills/{skill_id}",
            json={"name": "X" * 81, "description": ""},
        ).status_code == 422
    finally:
        app.dependency_overrides.clear()
