"""工作流拓扑的离线单元测试。

StubLLM 仅供 pytest 使用的测试替身，不是运行时的兜底方案：
应用始终调用真实的 OpenAI 兼容端点。
"""
from __future__ import annotations

import asyncio

from app.config import Settings
from app.graph.workflow import build_graph, initial_state
from app.models.profile import ApplicantProfile
from app.models.schemas import GenerateRequest


class StubLLM:
    def __init__(self, issues=None, fail_first_verify=False, long_draft=False):
        self.issues = issues or []
        self.fail_first_verify = fail_first_verify
        self.long_draft = long_draft
        self.verify_calls = 0
        self.tasks: list[str] = []
        self.prompts: list[str] = []

    async def complete(self, *, task, system, user, **kwargs):
        self.tasks.append(task)
        self.prompts.append(user)
        if task == "cv_polish":
            return "## Education\n\n**X University** — Bachelor in CS\n\n## Skills\n\n- Python"
        if self.long_draft:
            return "word " * 1200
        return "## Draft\n\nThis draft is derived strictly from the supplied fact sheet."

    async def complete_json(self, *, task, system, user, **kwargs):
        self.tasks.append(task)
        self.prompts.append(user)
        if task == "outline":
            return {"sections": [{"title": "Opening", "goal": "Motivation", "evidence_ids": ["E1"]}]}
        self.verify_calls += 1
        if self.fail_first_verify and self.verify_calls > 1:
            return {"passed": True, "issues": [], "summary": "stub audit clean"}
        return {"passed": not self.issues, "issues": self.issues, "summary": "stub audit"}


def _profile() -> dict:
    return ApplicantProfile(
        basics={"name_en": "Test Applicant"},
        education=[{"school": "X University", "major": "Computer Science"}],
        experiences=[{"org": "Lab", "role": "RA", "bullets": ["Built a pipeline"]}],
    ).model_dump()


def test_all_document_types_reach_finalize():
    profile = _profile()
    for doc_type in ("ps", "recommendation", "cv"):
        request = GenerateRequest(profile_id=profile["id"], doc_type=doc_type).model_dump()
        result = asyncio.run(build_graph(StubLLM(), Settings()).ainvoke(initial_state(profile, request)))
        visited = [event["node"] for event in result["events"]]
        assert result["final"].strip()
        assert "verify" in visited and "finalize" in visited
        if doc_type == "cv":
            assert "cv_render" in visited and "outline" not in visited
        else:
            assert "outline" in visited and "draft" in visited


def test_issues_trigger_revision():
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    issue = {"quote": "invented", "type": "fabrication", "reason": "not in facts", "fix": "remove"}
    stub = StubLLM(issues=[issue])
    # 显式限制一轮：默认 max_revisions 已提高到 2，意见持续存在时会修满两轮。
    result = asyncio.run(build_graph(stub, Settings(max_revisions=1)).ainvoke(initial_state(profile, request)))
    visited = [event["node"] for event in result["events"]]
    assert "revise" in visited
    assert result["revision_count"] == 1
    assert "revise" in stub.tasks


def test_first_revision_focuses_on_fact_issues():
    """第一轮自修复只把事实类意见交给模型，文风类意见留待后续轮次。"""
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    fact_issue = {"quote": "invented fact", "type": "fabrication", "reason": "not in facts", "fix": "remove"}
    style_issue = {"quote": "AI tone phrase", "type": "style", "reason": "cliché", "fix": "rewrite"}
    stub = StubLLM(issues=[fact_issue, style_issue], fail_first_verify=True)
    result = asyncio.run(build_graph(stub, Settings()).ainvoke(initial_state(profile, request)))
    revise_prompts = [u for t, u in zip(stub.tasks, stub.prompts) if t == "revise"]
    assert len(revise_prompts) == 1
    assert "invented fact" in revise_prompts[0]        # 事实类意见已传给模型
    assert "AI tone phrase" not in revise_prompts[0]   # 文风类意见第一轮不传
    assert result["revision_count"] == 1


def test_reverify_receives_previous_issues():
    """复检提示必须带上修订前的意见清单，做「已解决/仍存在」对照。"""
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    issue = {"quote": "invented", "type": "fabrication", "reason": "not in facts", "fix": "remove"}
    stub = StubLLM(issues=[issue], fail_first_verify=True)
    asyncio.run(build_graph(stub, Settings()).ainvoke(initial_state(profile, request)))
    verify_prompts = [u for t, u in zip(stub.tasks, stub.prompts) if t == "verify"]
    assert len(verify_prompts) == 2
    # 初审没有上一轮对照块（注意区分 VERIFY_JSON_HINT 里对 revision_check 的说明文字）
    assert "上一轮校验意见（修订前版本的问题清单）" not in verify_prompts[0]
    assert "上一轮校验意见（修订前版本的问题清单）" in verify_prompts[1]


def test_word_limit_overflow_reported():
    """初稿超出目标篇幅 ±15% 时，verify 注入字数类 style 意见驱动压缩。"""
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    stub = StubLLM(long_draft=True)
    result = asyncio.run(build_graph(stub, Settings()).ainvoke(initial_state(profile, request)))
    verify_events = [e for e in result["events"] if e["node"] == "verify"]
    assert verify_events, "必须产生 verify 事件"
    first_issues = verify_events[0].get("issues") or []
    assert first_issues, "超长初稿必须报出字数意见"
    assert first_issues[0]["type"] == "style"
    assert "超出目标篇幅" in first_issues[0]["reason"]

def test_self_repair_reverifies_before_finalize():
    """自我修复一轮后必须复检：复检通过直接定稿，不进入人工复核。"""
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    issue = {"quote": "invented", "type": "fabrication", "reason": "not in facts", "fix": "remove"}
    stub = StubLLM(issues=[issue], fail_first_verify=True)
    result = asyncio.run(build_graph(stub, Settings()).ainvoke(initial_state(profile, request)))
    visited = [event["node"] for event in result["events"]]
    assert result["revision_count"] == 1
    assert visited.count("revise") == 1
    assert visited.count("verify") == 2  # 初检 + 修复后复检
    assert result["critique"]["passed"] is True
    assert not result["critique"]["issues"]
    assert result["final"].strip()
    finalize_events = [e for e in result["events"] if e["node"] == "finalize"]
    assert "复检通过" in finalize_events[0]["summary"]


def test_self_repair_exhausted_hands_over_to_human():
    """复检始终不通过时修满 max_revisions 轮，剩余意见转人工复核。"""
    profile = _profile()
    request = GenerateRequest(profile_id=profile["id"], doc_type="ps").model_dump()
    issue = {"quote": "invented", "type": "fabrication", "reason": "not in facts", "fix": "remove"}
    stub = StubLLM(issues=[issue])
    settings = Settings(max_revisions=2)
    result = asyncio.run(build_graph(stub, settings).ainvoke(initial_state(profile, request)))
    visited = [event["node"] for event in result["events"]]
    assert result["revision_count"] == 2
    assert visited.count("revise") == 2
    assert visited.count("verify") == 3  # 初检 + 两轮复检
    assert result["critique"]["passed"] is False
    assert result["critique"]["issues"]  # 剩余意见保留，等待人工审核建议
    finalize_events = [e for e in result["events"] if e["node"] == "finalize"]
    assert "转人工复核" in finalize_events[0]["summary"]
