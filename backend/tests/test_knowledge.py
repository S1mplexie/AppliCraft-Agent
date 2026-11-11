"""知识库检索（RAG 召回层）与生成流程注入的测试。"""
from __future__ import annotations

import asyncio

from app.config import Settings
from app.graph.workflow import build_graph, initial_state
from app.knowledge.retriever import KnowledgeRetriever, get_retriever
from app.models.profile import ApplicantProfile
from app.models.schemas import GenerateRequest


HKU_CS = {
    "id": "hku-msc-cs",
    "university": "The University of Hong Kong",
    "program": "MSc in Computer Science",
    "degree_type": "Taught Master",
    "region": "Hong Kong, China",
    "intake": "2027 Fall",
    "deadline": "",
    "language_requirement": "",
    "curriculum_notes": "",
    "faculty_notes": "",
    "why_fit": "",
    "notes": "",
}


def test_retriever_known_program():
    r = get_retriever(Settings())
    ref = r.retrieve(HKU_CS, {"doc_type": "ps", "emphasis": []}, "reliable ML systems")
    assert ref.enabled and ref.context
    assert ref.sources
    # 学校感知 + 学科归一化：应命中港大 CS（即使官方长名是 Master of Science in
    # Computer Science (MSc(CompSc))），而非同名的香港中文大学项目。
    assert "Computer Science" in ref.matched_program
    assert all(s["school"] == "香港大学" for s in ref.sources)
    assert any("Computer Science" in s["program"] for s in ref.sources)
    # 不得混入其它学校（如香港中文大学）的同名项目。
    assert not any(s["school"] == "香港中文大学" for s in ref.sources)


def test_retriever_school_disambiguation():
    # 港大与中文大学都有 MSc in Computer Science；按 university 字段应能区分，
    # 不得把另一所学校同名项目的官方资料串味注入。
    cuhk_cs = {
        "university": "The Chinese University of Hong Kong",
        "program": "MSc in Computer Science",
        "degree_type": "Taught Master",
    }
    r = get_retriever(Settings())
    ref = r.retrieve(cuhk_cs, {"doc_type": "ps", "emphasis": []}, "")
    assert ref.enabled and ref.context
    assert all(s["school"] == "香港中文大学" for s in ref.sources)
    assert not any(s["school"] == "香港大学" for s in ref.sources)


def test_retriever_unknown_program_safe_noop():
    r = get_retriever(Settings())
    ref = r.retrieve(
        {"program": "MSc in Advanced CS", "university": "University of Oxford", "degree_type": "Taught Master"},
        {"doc_type": "ps", "emphasis": []},
        "",
    )
    assert ref.enabled and not ref.context
    assert "不在知识库覆盖范围内" in ref.note


def test_retriever_no_target_safe_noop():
    r = get_retriever(Settings())
    ref = r.retrieve(None, {"doc_type": "ps", "emphasis": []}, "")
    assert ref.enabled and not ref.context
    assert "未指定目标项目" in ref.note


def test_retriever_disabled():
    r = KnowledgeRetriever(knowledge_dir=Settings().knowledge_dir, enabled=False)
    ref = r.retrieve(HKU_CS, {"doc_type": "ps", "emphasis": []}, "")
    assert not ref.enabled and not ref.context


class _StubLLM:
    async def complete(self, *, task, system, user, **kwargs):
        if task == "cv_polish":
            return "## Education\n\n**X University** — Bachelor in CS"
        return "## Draft\n\nThis draft is derived strictly from the supplied fact sheet."

    async def complete_json(self, *, task, system, user, **kwargs):
        if task == "outline":
            return {"sections": [{"title": "Opening", "goal": "Motivation", "evidence_ids": ["E1"]}]}
        return {"passed": True, "issues": [], "summary": "stub", "dimensions": {}, "score": None}


def _profile_with_target() -> dict:
    return ApplicantProfile(
        basics={"name_en": "Test Applicant"},
        education=[{"school": "X University", "major": "Computer Science"}],
        experiences=[{"org": "Lab", "role": "RA", "bullets": ["Built a pipeline"]}],
        target_programs=[HKU_CS],
    ).model_dump()


def test_rag_injects_knowledge_into_graph():
    profile = _profile_with_target()
    request = GenerateRequest(
        profile_id=profile["id"], doc_type="ps", target_program_id="hku-msc-cs"
    ).model_dump()
    result = asyncio.run(
        build_graph(_StubLLM(), Settings()).ainvoke(initial_state(profile, request))
    )
    assert result["final"].strip()
    knowledge = result["knowledge"]
    assert knowledge.get("enabled")
    assert knowledge.get("sources")
    # 学校感知 + 学科归一化后应命中港大 CS，而非同名的中大项目。
    assert "Computer Science" in (knowledge.get("matched_program") or "")
    assert all(s["school"] == "香港大学" for s in knowledge.get("sources", []))
    assert result["knowledge_context"].strip()
    # 注入资料应出现在 intake 节点产生的 knowledge 字段中（供前端展示）。
    assert any(ev["node"] == "intake" for ev in result["events"])
