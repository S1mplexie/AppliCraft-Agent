"""简历上传解析：文本抽取、LLM 解析、覆盖合并与接口的回归测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import routes_profile
from app.api.deps import get_current_user, get_db, get_llm, get_user_store
from app.main import app
from app.models.profile import ApplicantProfile
from app.resume.parser import (
    ResumeParseError,
    extract_text,
    merge_profile,
    parse_resume_text,
)
from app.storage.filestore import FileStore


class FakeUser:
    id = "user_resume_test"
    daily_quota = 20
    is_active = True


class FakeDB:
    def scalar(self, *args, **kwargs):
        return 0

    def get(self, *args, **kwargs):
        # 用户级模型配置查询：桩用户没有自带 Key
        return None


class StubLLM:
    """返回一份确定的解析 patch，便于断言覆盖合并效果。"""

    async def complete(self, *, task, system, user, **kwargs):
        return "ignored"

    async def complete_json(self, *, task, system, user, **kwargs):
        assert task == "parse_resume"
        return {
            "basics": {
                "name_en": "Yiran Chen",
                "email": "yiran@example.com",
                "phone": "+86 138 0000 0000",
            },
            "education": [
                {
                    "school": "Example University",
                    "degree": "Bachelor",
                    "major": "Computer Science",
                    "gpa": "3.7",
                    "start_date": "2022-09",
                    "end_date": "2026-06",
                }
            ],
            "experiences": [
                {"type": "research", "org": "Data Lab", "role": "RA", "bullets": ["Built a pipeline"]}
            ],
            "skill_groups": [{"category": "Programming", "items": ["Python", "PyTorch"]}],
            "test_scores": [{"kind": "IELTS", "total": "7.0"}],
        }


def _base_profile() -> dict:
    return ApplicantProfile(
        basics={"name_en": "Old Name", "phone": "000"},
        education=[{"school": "Old School", "major": "Math"}],
        experiences=[{"org": "Old Org", "role": "Intern"}],
        skill_groups=[{"category": "Languages", "items": ["English"]}],
        test_scores=[{"kind": "TOEFL", "total": "100"}],
    ).model_dump()


def test_merge_overwrites_only_present_and_replaces_lists():
    base = _base_profile()
    patch = StubLLM()
    # 直接构造 ResumePatch 以验证 merge 语义；这里用手工 dict 走 merge_profile。
    from app.resume.parser import ResumePatch

    parsed = ResumePatch(
        basics={"name_en": "Yiran Chen", "email": "yiran@example.com", "phone": "+86 138 0000 0000"},
        education=[{"school": "Example University", "major": "Computer Science"}],
        experiences=[{"org": "Data Lab", "role": "RA", "bullets": ["Built a pipeline"]}],
        skill_groups=[{"category": "Programming", "items": ["Python"]}],
        test_scores=[{"kind": "IELTS", "total": "7.0"}],
    )
    merged, changes = merge_profile(base, parsed)

    # 基本信息：只覆盖出现的字段，phone 被覆盖，其余保留。
    assert merged["basics"]["name_en"] == "Yiran Chen"
    assert merged["basics"]["email"] == "yiran@example.com"
    assert merged["basics"]["phone"] == "+86 138 0000 0000"
    # 列表：有内容则整体替换为解析结果（id 由模型生成，非旧值）。
    assert len(merged["education"]) == 1
    assert merged["education"][0]["school"] == "Example University"
    assert merged["education"][0]["id"] != base["education"][0]["id"]
    assert merged["experiences"][0]["org"] == "Data Lab"
    assert merged["skill_groups"][0]["category"] == "Programming"
    assert merged["test_scores"][0]["kind"] == "IELTS"
    # 变更清单应包含这几类覆盖说明。
    assert any("基本信息" in c for c in changes)
    assert any("教育经历" in c for c in changes)
    assert any("技能组" in c for c in changes)


def test_merge_does_not_clobber_when_patch_list_empty():
    base = _base_profile()
    from app.resume.parser import ResumePatch

    parsed = ResumePatch(basics={"name_en": ""}, education=[], experiences=[])
    merged, changes = merge_profile(base, parsed)
    # 空列表不覆盖；空 basics 字段也不覆盖。
    assert merged["education"] == base["education"]
    assert merged["experiences"] == base["experiences"]
    assert merged["basics"]["name_en"] == "Old Name"
    assert changes == []


def _resume_text() -> str:
    return (
        "Yiran Chen\nyiran@example.com | +86 138 0000 0000\n"
        "Education: Example University, BSc in Computer Science, GPA 3.7/4.0\n"
        "Experience: Research Assistant at Data Intelligence Lab, built an OCR pipeline.\n"
    )


def test_extract_text_txt_and_docx():
    txt = extract_text(_resume_text().encode("utf-8"), "resume.txt")
    assert "Yiran Chen" in txt

    docx_bytes = _make_docx(_resume_text())
    docx = extract_text(docx_bytes, "resume.docx")
    assert "Yiran Chen" in docx and "Example University" in docx


def test_extract_text_rejects_unsupported_format():
    try:
        extract_text(b"hello", "resume.png")
        raise AssertionError("应当拒绝不支持的格式")
    except ResumeParseError:
        pass


def test_extract_text_corrupted_docx_returns_friendly_error():
    # 损坏的 docx（非法 zip）应抛 ResumeParseError（接口层转为 400），而非 500。
    try:
        extract_text(b"PK\x03\x04" + b"\x00" * 500, "resume.docx")
        raise AssertionError("损坏的 docx 应当抛出 ResumeParseError")
    except ResumeParseError as exc:
        assert "DOCX" in str(exc) or "损坏" in str(exc)


def test_extract_text_corrupted_pdf_returns_friendly_error():
    try:
        extract_text(b"%PDF-1.4 " + b"\x00" * 200 + _resume_text().encode("utf-8"), "resume.pdf")
        raise AssertionError("损坏的 PDF 应当抛出 ResumeParseError")
    except ResumeParseError as exc:
        assert "PDF" in str(exc) or "解析失败" in str(exc)


def _make_docx(text: str) -> bytes:
    from docx import Document
    from io import BytesIO

    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_resume_endpoint(tmp_path):
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())

    app.dependency_overrides[get_llm] = lambda: StubLLM()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/profiles/{profile['id']}/parse-resume",
            files={"file": ("resume.txt", _resume_text().encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["changes"]
        # 服务端已落盘，重新读取档案应反映覆盖结果。
        saved = store.get_profile(profile["id"])
        assert saved["basics"]["name_en"] == "Yiran Chen"
        assert saved["education"][0]["school"] == "Example University"
    finally:
        app.dependency_overrides.clear()


def test_parse_resume_rejects_bad_extension(tmp_path):
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())

    app.dependency_overrides[get_llm] = lambda: StubLLM()
    app.dependency_overrides[get_user_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    app.dependency_overrides[get_db] = lambda: FakeDB()
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/profiles/{profile['id']}/parse-resume",
            files={"file": ("resume.png", b"x", "image/png")},
        )
        assert response.status_code == 400
        assert "格式" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
