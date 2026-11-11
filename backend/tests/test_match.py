"""选校评估：规则引擎的确定性比对、配额扣减与 API 权限。"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import GenerationLog, User
from app.db.session import SessionLocal, init_db
from app.main import app
from app.matching.engine import evaluate_profile, load_index, load_requirements, parse_ielts_breakdown

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def _client() -> TestClient:
    client = TestClient(app)
    email = f"match_{uuid4().hex[:10]}@example.com"
    resp = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return client


REQ = {
    "programs": {
        "hku-msc-ai": {
            "ielts_total_min": 6.0, "ielts_subtest_min": 5.5, "toefl_min": 80,
            "language_note": "HKU 校级", "gpa_reference": None, "gpa_reference_scale": None,
            "preferred_background": ["计算机"],
        },
        "nus-msba": {
            "ielts_total_min": None, "ielts_subtest_min": None, "toefl_min": None,
            "language_note": "无需语言成绩", "gpa_reference": None, "gpa_reference_scale": None,
            "preferred_background": [],
        },
    }
}
INDEX = {
    "programs": [
        {"id": "hku-msc-ai", "school_name_zh": "香港大学", "name_en": "MSc in AI",
         "name_zh": "人工智能硕士", "region": "HK", "tuition_intake": "2027/28",
         "deadlines": ["2027-01-31"]},
    ]
}


def _profile(ielts: dict | None = None, gpa_average: str = "88 / 100", target_programs: list | None = None) -> dict:
    return {
        "education": [{
            "id": "ed1", "school": "X University", "degree": "Bachelor", "major": "Computer Science",
            "gpa": "3.7", "gpa_scale": "4.0", "gpa_average": gpa_average, "ranking": "",
            "start_date": "", "end_date": "", "relevant_courses": [], "thesis": "", "highlights": "",
        }],
        "test_scores": [ielts] if ielts else [],
        "target_programs": target_programs or [],
    }


def test_parse_ielts_breakdown_variants():
    std = parse_ielts_breakdown("L 7.5 / R 7.5 / W 6.5 / S 6.5")
    assert std == {"L": 7.5, "R": 7.5, "W": 6.5, "S": 6.5}
    colon = parse_ielts_breakdown("R:7.5, L:8.0, W:6.0, S:6.0")
    assert colon == {"L": 8.0, "R": 7.5, "W": 6.0, "S": 6.0}
    assert parse_ielts_breakdown("") == {}


def test_subtest_gap_reports_writing():
    """总分达标但单项不满足 → 硬性缺口，文案具体到分项（用户示例场景）。"""
    profile = _profile(ielts={"kind": "IELTS", "total": "6.5", "breakdown": "L 7.5 / R 7.5 / W 5.0 / S 6.0"})
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "hku-msc-ai")
    assert item["tier"] == "gap"
    assert any("写作 5.0" in g and "5.5" in g for g in item["gaps"])


def test_language_pass_with_high_average_is_safety():
    profile = _profile(ielts={"kind": "IELTS", "total": "7.0", "breakdown": "L 7.5 / R 7.5 / W 6.5 / S 6.5"})
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "hku-msc-ai")
    assert item["tier"] == "safety"
    assert any("达到该项目要求" in r for r in item["reasons"])
    assert item["gaps"] == []


def test_low_average_is_reach():
    profile = _profile(ielts={"kind": "IELTS", "total": "6.5", "breakdown": "L 6.5 / R 6.5 / W 6.0 / S 6.0"}, gpa_average="75 / 100")
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "hku-msc-ai")
    assert item["tier"] == "reach"


def test_missing_language_scores_is_gap():
    profile = _profile()
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "hku-msc-ai")
    assert item["tier"] == "gap"
    assert item["gaps"][0].startswith("档案未提供语言成绩")


def test_program_without_language_requirement_passes():
    """NUS MSBA 官网明确无需语言成绩 → 不产生语言缺口。"""
    profile = _profile()
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "nus-msba")
    assert any("无需提交语言成绩" in r for r in item["reasons"])
    assert not any("语言" in g for g in item["gaps"])


def test_in_target_flag():
    profile = _profile(target_programs=[{"university": "香港大学", "program": "MSc in AI"}])
    result = evaluate_profile(profile, REQ, INDEX)
    item = next(r for r in result["results"] if r["program_id"] == "hku-msc-ai")
    assert item["in_target"] is True


def test_requirements_cover_all_index_programs():
    """match-requirements 必须覆盖 index.json 的全部项目，防止 id 拼错漏项。"""
    knowledge = Path(__file__).resolve().parents[2] / "knowledge"
    index_ids = {p["id"] for p in load_index(knowledge)["programs"]}
    req_ids = set((load_requirements(knowledge).get("programs") or {}).keys())
    assert index_ids == req_ids, f"缺失要求：{index_ids - req_ids}；多余：{req_ids - index_ids}"


def test_api_match_endpoint():
    client = _client()
    created = client.post("/api/profiles", json={"label": "评估档案"})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    resp = client.post(f"/api/match/{pid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["results"]
    assert {"tier", "reasons", "gaps", "in_target"} <= set(data["results"][0].keys())
    assert data["billing_source"] == "system"
    # 免费额度口径：system 来源的评估计入 system_key_used；总量护栏 used 同步 +1。
    assert data["quota"]["system_key_used"] == 1
    assert data["quota"]["used"] == 1
    missing = client.post("/api/match/nonexistent")
    assert missing.status_code == 404


def test_api_match_requires_login():
    client = TestClient(app)
    resp = client.post("/api/match/whatever")
    assert resp.status_code == 401


def test_match_consumes_free_quota_once_per_call():
    """每次评估扣 1 次免费额度（写入 GenerationLog，与生成共用每日配额池）。"""
    client = _client()
    pid = client.post("/api/profiles", json={"label": "配额档案"}).json()["id"]
    assert client.post(f"/api/match/{pid}").status_code == 200
    assert client.post(f"/api/match/{pid}").status_code == 200
    me = client.get("/api/auth/me").json()
    # 免费额度口径：两次评估均使用系统 Key，system_key_used 计 2；总量护栏 used 同步。
    assert me["quota"]["system_key_used"] == 2
    assert me["quota"]["used"] == 2


def _fill_free_quota(email: str, count: int) -> None:
    """预置今日已消耗的免费额度记录（llm_source='system'，创建于今天）。"""
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).first()
        assert user is not None
        for _ in range(count):
            db.add(GenerationLog(user_id=user.id, doc_type="generate", status="ok", llm_source="system"))
        db.commit()


def test_match_blocked_when_quota_exhausted():
    """免费额度（system_key_daily_limit）耗尽的系统用户不能再评估（403）。"""
    client = _client()
    email = client.get("/api/auth/me").json()["user"]["email"]
    _fill_free_quota(email, get_settings().system_key_daily_limit)
    pid = client.post("/api/profiles", json={"label": "耗尽档案"}).json()["id"]
    resp = client.post(f"/api/match/{pid}")
    assert resp.status_code == 403
    assert "免费额度" in resp.json()["detail"]


def test_match_admin_not_billed():
    """管理员评估不占用免费额度（system_key_used 不变）；总量护栏 used 仅作审计口径。"""
    client = _client()
    email = client.get("/api/auth/me").json()["user"]["email"]
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).first()
        assert user is not None
        user.is_admin = True
        db.commit()
    pid = client.post("/api/profiles", json={"label": "管理员评估档案"}).json()["id"]
    resp = client.post(f"/api/match/{pid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["billing_source"] == "admin"
    quota = client.get("/api/auth/me").json()["quota"]
    assert (quota.get("system_key_used") or 0) == 0
    assert quota["used"] == 1  # 总量护栏记录本次评估（审计口径，非免费额度）