"""简历上传解析：文本抽取、LLM 解析、覆盖合并、接口与计费的回归测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes_generate
from app.api.deps import get_current_user, get_db, get_llm, get_user_store
from app.config import get_settings
from app.db.models import Base, GenerationLog, naive_utc
from app.main import app
from app.models.profile import ApplicantProfile
from app.resume.parser import (
    ResumeParseError,
    extract_text,
    merge_profile,
    parse_resume_text,
)
from app.storage.filestore import FileStore


@pytest.fixture(autouse=True)
def audit_db(tmp_path, monkeypatch):
    """把生成审计日志隔离到临时 sqlite，避免测试污染真实额度库。

    _log_generation 内部使用 routes_generate.SessionLocal 而非请求注入的 db，
    因此这里同时替换请求依赖与审计 Session，让断言看到同一份数据。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'resume-audit.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(routes_generate, "SessionLocal", session_factory)
    yield session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def _seed_log(session_factory, user_id: str, *, status: str = "ok", source: str = "system", count: int = 1):
    with session_factory() as db:
        for _ in range(count):
            db.add(
                GenerationLog(
                    user_id=user_id, doc_type="ps", status=status,
                    llm_source=source, created_at=naive_utc(),
                )
            )
        db.commit()


def _log_rows(session_factory, user_id: str):
    with session_factory() as db:
        return list(db.query(GenerationLog).filter(GenerationLog.user_id == user_id).all())



class FakeUser:
    id = "user_resume_test"
    daily_quota = 20
    is_active = True
    is_admin = False


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


# ------------------------------------------------------------------ 额度计费
def _parse_request(client, profile_id: str):
    return client.post(
        f"/api/profiles/{profile_id}/parse-resume",
        files={"file": ("resume.txt", _resume_text().encode("utf-8"), "text/plain")},
    )


def test_parse_resume_consumes_system_quota(tmp_path, audit_db, monkeypatch):
    """成功解析写一条 resume_parse 日志，用完免费额度后返回 429。"""
    monkeypatch.setattr(get_settings(), "system_key_daily_limit", 2)
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())
    user = FakeUser()

    with audit_db() as db:
        app.dependency_overrides[get_llm] = lambda: StubLLM()
        app.dependency_overrides[get_user_store] = lambda: store
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        assert _parse_request(client, profile["id"]).status_code == 200
        assert _parse_request(client, profile["id"]).status_code == 200
        blocked = _parse_request(client, profile["id"])
        assert blocked.status_code == 429
        assert "免费额度" in blocked.json()["detail"]

    logs = _log_rows(audit_db, user.id)
    assert len(logs) == 2
    assert all(
        row.doc_type == "resume_parse" and row.status == "ok" and row.llm_source == "system"
        for row in logs
    )


def test_parse_resume_failure_does_not_consume_quota(tmp_path, audit_db, monkeypatch):
    """解析失败只记 error 日志，不占免费次数；紧接着仍可成功解析。"""
    monkeypatch.setattr(get_settings(), "system_key_daily_limit", 2)
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())
    user = FakeUser()

    class FailingLLM(StubLLM):
        async def complete_json(self, *, task, system, user, **kwargs):
            raise RuntimeError("模型临时不可用")

    with audit_db() as db:
        app.dependency_overrides[get_llm] = lambda: FailingLLM()
        app.dependency_overrides[get_user_store] = lambda: store
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        assert _parse_request(client, profile["id"]).status_code == 502

        app.dependency_overrides[get_llm] = lambda: StubLLM()
        assert _parse_request(client, profile["id"]).status_code == 200
        assert _parse_request(client, profile["id"]).status_code == 200
        # 第三次才因额度用尽被拦截，说明失败的第一次没有扣次数。
        assert _parse_request(client, profile["id"]).status_code == 429

    logs = _log_rows(audit_db, user.id)
    assert sum(1 for row in logs if row.status == "error") == 1
    assert sum(1 for row in logs if row.status == "ok") == 2


def test_parse_resume_personal_key_bypasses_quota(tmp_path, audit_db, monkeypatch):
    """额度已满但用户自带 Key：仍可解析，日志记为 personal 不占系统额度。"""
    monkeypatch.setattr(get_settings(), "system_key_daily_limit", 1)
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())
    user = FakeUser()
    _seed_log(audit_db, user.id, count=1)

    class PersonalLLM(StubLLM):
        source = "personal"

    with audit_db() as db:
        app.dependency_overrides[get_llm] = lambda: PersonalLLM()
        app.dependency_overrides[get_user_store] = lambda: store
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        assert _parse_request(client, profile["id"]).status_code == 200

    logs = _log_rows(audit_db, user.id)
    assert len(logs) == 2
    assert logs[-1].doc_type == "resume_parse" and logs[-1].llm_source == "personal"


def test_parse_resume_admin_unlimited(tmp_path, audit_db, monkeypatch):
    """管理员额度已满仍可解析：闸门放行，日志来源仍按 Key 归属记为 system。"""
    monkeypatch.setattr(get_settings(), "system_key_daily_limit", 1)
    store = FileStore(tmp_path)
    profile = store.save_profile(_base_profile())
    admin = FakeUser()
    admin.is_admin = True
    _seed_log(audit_db, admin.id, count=1)

    with audit_db() as db:
        app.dependency_overrides[get_llm] = lambda: StubLLM()
        app.dependency_overrides[get_user_store] = lambda: store
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        assert _parse_request(client, profile["id"]).status_code == 200

    logs = _log_rows(audit_db, admin.id)
    assert logs[-1].doc_type == "resume_parse" and logs[-1].llm_source == "system"
