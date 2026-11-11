"""参考文档库：存储、上下文装配、系统项目解析与接口的回归测试。"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_user_store
from app.library.service import build_reference_context, list_system_programs
from app.main import app
from app.models.schemas import GenerateRequest
from app.storage.filestore import FileStore, StorageError


class FakeUser:
    id = "user_library_test"
    daily_quota = 20
    is_active = True


class FakeDB:
    def scalar(self, *args, **kwargs):
        return 0

    def get(self, *args, **kwargs):
        # 用户级模型配置查询：桩用户没有自带 Key
        return None


def _save_reference(store: FileStore, name: str, text: str) -> str:
    meta = store.save_reference(
        filename=f"{name}.txt", name=name, content=text.encode("utf-8"),
        text=text, ext=".txt",
    )
    return meta["id"]


def test_store_save_list_get_delete(tmp_path):
    store = FileStore(tmp_path)
    assert store.list_references() == []
    ref_id = _save_reference(store, "项目说明", "这是我的项目背景资料")
    items = store.list_references()
    assert len(items) == 1
    assert items[0]["id"] == ref_id
    assert items[0]["char_count"] == len("这是我的项目背景资料")

    ref = store.get_reference(ref_id)
    assert ref["text"] == "这是我的项目背景资料"
    assert store.reference_file_path(ref_id) is not None

    assert store.delete_reference(ref_id) is True
    assert store.list_references() == []
    assert store.get_reference(ref_id) is None


def test_build_reference_context_assembles_and_skips_missing(tmp_path):
    store = FileStore(tmp_path)
    a = _save_reference(store, "文档A", "A 的内容")
    b = _save_reference(store, "文档B", "B 的内容")
    ctx, meta = build_reference_context(store, [a, b, "missing-id"])
    assert "A 的内容" in ctx and "B 的内容" in ctx
    # 来源清单包含已存在的两个与缺失的一个（标注未注入）。
    ids = {m["id"] for m in meta}
    assert {a, b, "missing-id"} == ids
    included = {m["id"] for m in meta if m["included"]}
    assert {a, b} == included


def test_build_reference_context_budget_truncation(tmp_path):
    store = FileStore(tmp_path)
    a = _save_reference(store, "文档A", "A" * 3000)
    b = _save_reference(store, "文档B", "B" * 3000)
    ctx, meta = build_reference_context(store, [a, b], max_chars=4000)
    # 第一篇注入；第二篇超出剩余预算，仅列入来源而不注入正文。
    assert meta[0]["included"] is True
    assert meta[1]["included"] is False
    assert "A" in ctx and "B" not in ctx
    assert len(ctx.replace("### 文档A\n", "")) == 3000


def test_build_reference_context_empty_ids(tmp_path):
    store = FileStore(tmp_path)
    ctx, meta = build_reference_context(store, [], max_chars=4000)
    assert ctx == "" and meta == []


def test_list_system_programs_groups_by_program(tmp_path, monkeypatch):
    # 用一个临时知识库目录验证聚合逻辑。
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    chunks = [
        {
            "meta": {
                "program_id": "hkust-msc-cs", "school_id": "HKUST",
                "school_name_zh": "香港科技大学", "program_name_en": "MSc in Computer Science",
                "program_name_zh": "计算机科学理学硕士", "faculty": "School of Engineering",
                "region": "HK", "intake": "2027/28", "field": "overview",
                "field_label": "项目概览", "official_urls": ["https://hkust.example/cs"],
                "suitable_for_writing": True,
            }
        },
        {
            "meta": {
                "program_id": "hkust-msc-cs", "school_id": "HKUST",
                "school_name_zh": "香港科技大学", "program_name_en": "MSc in Computer Science",
                "program_name_zh": "计算机科学理学硕士", "faculty": "School of Engineering",
                "region": "HK", "intake": "2027/28", "field": "curriculum",
                "field_label": "课程体系", "official_urls": ["https://hkust.example/cs"],
                "suitable_for_writing": True,
            }
        },
    ]
    (knowledge_dir / "chunks.jsonl").write_text(
        "\n".join(__import__("json").dumps(c, ensure_ascii=False) for c in chunks),
        encoding="utf-8",
    )
    from app.config import Settings

    settings = Settings(knowledge_dir=knowledge_dir)
    programs = list_system_programs(settings)
    assert len(programs) == 1
    p = programs[0]
    assert p["program_id"] == "hkust-msc-cs"
    assert p["school_name_zh"] == "香港科技大学"
    assert set(p["fields"]) == {"项目概览", "课程体系"}
    assert p["official_urls"] == ["https://hkust.example/cs"]


def test_reference_upload_list_delete_endpoints(tmp_path):
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        # 上传（文本需超过抽取下限 30 字符）
        resp = client.post(
            "/api/library/references",
            files={"file": ("note.txt", ("我的项目背景文字，包含较为详细的研究经历与项目说明，用于生成文书时作为补充背景参考材料。" * 2).encode("utf-8"), "text/plain")},
            data={"name": "项目说明"},
        )
        assert resp.status_code == 200, resp.text
        ref = resp.json()
        assert ref["name"] == "项目说明"
        ref_id = ref["id"]

        # 列表
        listing = client.get("/api/library/references").json()
        assert len(listing["items"]) == 1
        assert listing["items"][0]["id"] == ref_id

        # 下载原始文件
        dl = client.get(f"/api/library/references/{ref_id}/download")
        assert dl.status_code == 200
        assert "项目背景".encode("utf-8") in dl.content

        # 删除
        assert client.delete(f"/api/library/references/{ref_id}").status_code == 200
        assert client.get("/api/library/references").json()["items"] == []
        assert client.get(f"/api/library/references/{ref_id}/download").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_reference_upload_rejects_bad_extension(tmp_path):
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/library/references",
            files={"file": ("note.png", b"x", "image/png")},
        )
        assert resp.status_code == 400
        assert "格式" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_system_programs_endpoint_returns_items(tmp_path):
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        resp = client.get("/api/library/system-programs")
        assert resp.status_code == 200
        # 知识库 chunks.jsonl 已包含多个港新项目，至少应聚合出若干项目。
        assert len(resp.json()["items"]) > 0
    finally:
        app.dependency_overrides.clear()


class StubLLMAll:
    """覆盖 outline / draft / verify / revise 调用的桩，使整条生成链路可离线跑通。"""
    async def complete(self, *, task, system, user, **kwargs):
        # 若提示词里注入了参考文档内容，则回显到草稿，便于断言已注入。
        if task in ("draft", "revise"):
            if "项目背景资料" in (user or ""):
                return "本文书参考了申请人提供的项目背景资料，并涉及 [TO CONFIRM: target programme]。"
            return "Draft mentions target programme [TO CONFIRM: target programme]."
        return "polished"

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


def test_generate_injects_selected_reference_into_trace(tmp_path, monkeypatch):
    """端到端：勾选的参考文档应被注入并在生成 trace 的 references 中记录。"""
    from app.api import routes_generate
    from app.api.deps import get_llm

    monkeypatch.setattr(routes_generate, "_log_generation", lambda *a, **k: None)

    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile_for_gen())
    ref_id = _save_reference(store, "项目说明", "这是申请人自己写的项目背景资料，包含独特的研究细节。")

    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    app.dependency_overrides[get_llm] = lambda: StubLLMAll()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/generate",
            json=GenerateRequest(
                profile_id=profile["id"], doc_type="ps",
                reference_doc_ids=[ref_id],
            ).model_dump(),
        )
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["id"]
        detail = client.get(f"/api/documents/{doc_id}").json()
        # trace 应记录勾选的参考文档，且标记已注入。
        refs = detail["trace"]["references"]
        assert len(refs) == 1
        assert refs[0]["id"] == ref_id
        assert refs[0]["included"] is True
        # 草稿确实回显了参考文档内容，证明提示词里已注入。
        assert "项目背景资料" in detail["markdown"]
        # 未勾选时不应注入。
        resp2 = client.post(
            "/api/generate",
            json=GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump(),
        )
        assert resp2.status_code == 200
        detail2 = client.get(f"/api/documents/{resp2.json()['id']}").json()
        assert detail2["trace"]["references"] == []
    finally:
        app.dependency_overrides.clear()


def _base_profile_for_gen() -> dict:
    from app.models.profile import ApplicantProfile
    return ApplicantProfile(
        basics={"name_en": "Test User", "email": "t@example.com"},
        target_programs=[{"university": "HKU", "program": "MSc in Computer Science", "degree_type": "Taught Master"}],
    ).model_dump()


# ------------------------------------------- 导入后弹窗命名（2026-11-10）
def test_store_update_reference_only_changes_name(tmp_path):
    store = FileStore(tmp_path)
    text = "可参考的项目背景与研究经历描述。" * 8
    ref_id = _save_reference(store, "旧标题", text)
    before = store.list_references()[0]

    meta = store.update_reference(ref_id, name="  课程大纲  ")
    assert meta["name"] == "课程大纲"
    assert meta["uploaded_at"] == before["uploaded_at"]
    assert meta["char_count"] == before["char_count"]
    # 原始文件与已抽取文本都不受影响。
    assert store.get_reference(ref_id)["text"] == text
    assert store.reference_file_path(ref_id) is not None

    fallback = store.update_reference(ref_id, name="")
    assert fallback["name"] == "旧标题.txt"
    assert store.update_reference("deadbeef1234", name="X") is None
    with pytest.raises(StorageError):
        store.update_reference("../evil", name="X")


def test_reference_import_then_name_dialog_endpoint(tmp_path):
    """真实前端链路：导入时不带名称 → 弹窗 PATCH 补名称 → 列表同步、正文仍可注入。"""
    store = FileStore(tmp_path)
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        text = "我的项目背景文字，包含较为详细的研究经历与项目说明，用于生成文书时作为补充背景参考材料。" * 2
        resp = client.post(
            "/api/library/references",
            files={"file": ("note.txt", text.encode("utf-8"), "text/plain")},
        )
        assert resp.status_code == 200, resp.text
        ref = resp.json()
        assert ref["name"] == "note.txt"  # 未填名称时以文件名兜底
        assert ref["uploaded_at"]

        updated = client.patch(
            f"/api/library/references/{ref['id']}", json={"name": "NUS 项目课程大纲"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "NUS 项目课程大纲"
        assert updated.json()["uploaded_at"] == ref["uploaded_at"]
        listing = client.get("/api/library/references").json()["items"]
        assert listing[0]["name"] == "NUS 项目课程大纲"
        ctx, meta = build_reference_context(store, [ref["id"]])
        assert "项目背景" in ctx and meta[0]["included"] is True

        # 留空回退文件名 / 不存在 404 / 非法 id 400 / 超长 422。
        assert client.patch(
            f"/api/library/references/{ref['id']}", json={"name": ""}
        ).json()["name"] == "note.txt"
        assert client.patch(
            "/api/library/references/deadbeef1234", json={"name": "X"}
        ).status_code == 404
        assert client.patch(
            "/api/library/references/bad%20id", json={"name": "X"}
        ).status_code == 400
        assert client.patch(
            f"/api/library/references/{ref['id']}", json={"name": "X" * 121}
        ).status_code == 422
    finally:
        app.dependency_overrides.clear()
