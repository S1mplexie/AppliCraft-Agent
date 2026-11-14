"""LangGraph 各节点：素材锁定 -> 大纲/起草或简历渲染 -> 事实校验 -> 修订 -> 定稿。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.graph import prompts
from app.graph.state import GraphState
from app.knowledge.retriever import get_retriever
from app.llm.client import LLMClient

OUTLINE_SYSTEM = "你是研究生申请文书的结构规划师。请依据事实清单规划段落，只返回合法的 JSON。"

# 事实安全硬错误：只有这类问题才驱动多轮自动修订。
# style / missing 等质量建议只给首轮一次机会，避免模型每轮复检都挑出新文风意见而空转。
FATAL_ISSUE_TYPES = frozenset({"fabrication", "contradiction", "unsupported", "program_fit"})

# 大纲模型调用失败时的兜底结构；标题与目标会展示在界面上，故使用中文。
FALLBACK_OUTLINES: dict[str, list[dict[str, Any]]] = {
    "ps": [
        {"title": "开篇：一个具体问题", "goal": "把动机落在真实存在的学术问题上", "evidence_ids": []},
        {"title": "学术准备", "goal": "呈现最相关的课程与技能", "evidence_ids": ["ED1"]},
        {"title": "科研 / 实习经历一", "goal": "写明贡献、结果与反思的论据段落", "evidence_ids": ["E1"]},
        {"title": "科研 / 实习经历二", "goal": "第二个论据段落，体现不同能力", "evidence_ids": ["E2"]},
        {"title": "为什么选择这个项目", "goal": "只用已提供的目标项目信息做定制", "evidence_ids": []},
        {"title": "职业规划与收尾", "goal": "把职业目标与本项目衔接起来", "evidence_ids": []},
    ],
    "recommendation": [
        {"title": "推荐意向", "goal": "说明推荐结论与背景", "evidence_ids": []},
        {"title": "关系与观察场景", "goal": "交代推荐人的观察立场", "evidence_ids": []},
        {"title": "具体观察一", "goal": "有事实支撑的具体事例", "evidence_ids": ["E1"]},
        {"title": "具体观察二", "goal": "第二个事例与有分寸的横向评价", "evidence_ids": ["E2"]},
        {"title": "匹配度与署名", "goal": "说明项目匹配度、明确推荐并附署名块", "evidence_ids": []},
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _event(node: str, summary: str, **payload: Any) -> dict[str, Any]:
    return {"node": node, "summary": summary, "at": _now(), **payload}


def _clean_markdown(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _numeric_warnings(draft: str, facts_text: str) -> list[str]:
    """标记初稿中出现、但事实清单里没有的小数与百分比。"""
    candidates = set(re.findall(r"\b\d+\.\d+\b|\b\d{1,3}%", draft))
    return [
        f"文中出现事实清单里没有的数字「{number}」，请人工核对。"
        for number in sorted(candidates)
        if number not in facts_text
    ][:5]


async def intake(state: GraphState, *, settings: Settings, **_: Any) -> dict[str, Any]:
    profile = state["profile"]
    request = state["request"]
    facts, facts_text = prompts.render_facts(profile, request)
    warnings: list[str] = []

    if request["doc_type"] == "ps" and not facts.get("target"):
        warnings.append("未设置目标项目：PS 的 why-this-programme 段落将使用 [TO CONFIRM] 占位符。")
    if request["doc_type"] == "recommendation" and not facts.get("recommender"):
        warnings.append("未设置推荐人：推荐信的身份与签名信息将使用 [TO CONFIRM] 占位符。")
    if not profile.get("experiences"):
        warnings.append("档案里没有经历条目，文书会缺少具体事例支撑。")
    if not (profile.get("basics") or {}).get("name_en"):
        warnings.append("档案里没有英文姓名，文书抬头将使用占位符。")

    # RAG：按目标项目检索官方资料，作为 why-this-programme / 职业规划的背景参考。
    ref = get_retriever(settings).retrieve(
        facts.get("target"), request, profile.get("career_goal", "")
    )
    knowledge_context = prompts.knowledge_block(ref.context, ref.sources, ref.matched_program)
    if facts.get("target") and not knowledge_context and ref.note:
        warnings.append(ref.note)
    knowledge_summary = {
        "sources": ref.sources,
        "matched_program": ref.matched_program,
        "context_chars": ref.context_chars,
        "enabled": ref.enabled,
        "note": ref.note,
    }

    rag_note = f"，已注入 {len(ref.sources)} 份目标项目官方资料" if knowledge_context else ""

    # 目标项目缺学校名时，用知识库匹配到的校名补全事实清单，避免文书出现
    # [TO CONFIRM: university name] 而 verify 又因未指明学校扣分（占位符死锁）。
    target = facts.get("target") or {}
    if target and not str(target.get("university") or "").strip():
        school = next((str(s.get("school") or "").strip() for s in ref.sources if s.get("school")), "")
        if school:
            facts["target"] = {**target, "university": school}
            facts_text = facts_text.replace("- 学校：（未提供）", f"- 学校：{school}", 1)
            warnings.append(
                f"档案里目标项目未填学校名，已按知识库匹配补全为「{school}」，请人工核对。"
            )

    return {
        "facts": facts,
        "facts_text": facts_text,
        "system_prompt": prompts.build_system(request),
        "outline": [],
        "draft": "",
        "critique": {},
        "final": "",
        "revision_count": 0,
        "knowledge_context": knowledge_context,
        "knowledge_sources": ref.sources,
        "knowledge": knowledge_summary,
        "warnings": warnings,
        "events": [
            _event(
                "intake",
                f"已锁定 {len(facts['education'])} 条教育经历、{len(facts['experiences'])} 段经历、"
                f"{len(facts['awards'])} 项奖项作为唯一事实来源{rag_note}",
                warning_count=len(warnings),
            )
        ],
    }


def route_by_doc_type(state: GraphState) -> str:
    return "cv" if state["request"]["doc_type"] == "cv" else "narrative"


async def outline(state: GraphState, *, llm: LLMClient, **_: Any) -> dict[str, Any]:
    request = state["request"]
    fallback = FALLBACK_OUTLINES.get(request["doc_type"], FALLBACK_OUTLINES["ps"])
    warnings: list[str] = []
    try:
        data = await llm.complete_json(
            task="outline",
            system=OUTLINE_SYSTEM + "\n" + prompts.OUTLINE_JSON_HINT,
            user=prompts.outline_user(
                state["facts_text"], request, knowledge=state.get("knowledge_context", ""),
                reference=state.get("reference_context", ""),
                skill=state.get("skill_context", ""),
            ),
        )
        sections = data.get("sections") if isinstance(data, dict) else None
        if not isinstance(sections, list) or not sections:
            raise ValueError("outline 缺少 sections")
        sections = [
            {
                "title": str(item.get("title", "")),
                "goal": str(item.get("goal", "")),
                "evidence_ids": list(item.get("evidence_ids") or []),
                "specifics": str(item.get("specifics", "")),
            }
            for item in sections
            if isinstance(item, dict)
        ][:8]
    except Exception as exc:  # noqa: BLE001 - 失败时回退到确定性的内置大纲
        sections = fallback
        warnings.append(f"大纲规划未成功，已使用内置结构：{exc}")

    return {
        "outline": sections,
        "warnings": warnings,
        "events": [_event("outline", f"已规划 {len(sections)} 个段落及对应素材", sections=sections)],
    }


async def draft(state: GraphState, *, llm: LLMClient, **_: Any) -> dict[str, Any]:
    request = state["request"]
    text = await llm.complete(
        task="draft",
        system=state["system_prompt"],
        user=prompts.draft_user(
            state["facts_text"],
            state.get("outline") or [],
            request,
            knowledge=state.get("knowledge_context", ""),
            reference=state.get("reference_context", ""),
            skill=state.get("skill_context", ""),
        ),
        # 事实文书用偏低温度：默认 0.5 偏发散，容易引入清单外的数字与细节。
        temperature=0.35,
        max_tokens=max(2048, min(6000, request.get("word_limit", 900) * 4)),
    )
    words = len(re.findall(r"\b[\w'-]+\b", text)) + len(re.findall(r"[\u4e00-\u9fff]", text))
    return {
        "draft": _clean_markdown(text),
        "events": [_event("draft", f"初稿完成，约 {words} 词", word_count=words)],
    }


async def cv_render(state: GraphState, *, llm: LLMClient, **_: Any) -> dict[str, Any]:
    skeleton = prompts.render_cv_skeleton(state["facts"])
    warnings: list[str] = []
    try:
        polished = _clean_markdown(
            await llm.complete(
                task="cv_polish",
                system=state["system_prompt"],
                user=prompts.cv_user(
                    skeleton, state["facts_text"], state["request"],
                    skill=state.get("skill_context", ""),
                ),
                temperature=0.2,
            )
        )
        if len(polished) < len(skeleton) * 0.5:
            polished = skeleton
            warnings.append("模型返回的简历过短，已回退到事实骨架（未做任何虚构补充）。")
    except Exception as exc:  # noqa: BLE001
        polished = skeleton
        warnings.append(f"简历润色调用失败，已使用事实骨架：{exc}")

    return {
        "draft": polished,
        "warnings": warnings,
        "events": [_event("cv_render", "已按事实骨架渲染简历并润色表述", section_count=polished.count("## "))],
    }


async def verify(state: GraphState, *, llm: LLMClient, **_: Any) -> dict[str, Any]:
    request = state["request"]
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    summary = ""
    dimensions: dict[str, int] = {}
    score: int | None = None
    llm_score: int | None = None
    revision_check: list[dict[str, Any]] = []
    previous_issues = state.get("previous_issues") or []
    # 按建议重生成时，把用户已裁决的待核项传给复检，避免把已确认/要求保留的
    # 内容反复重新挑出（事实安全级别的硬错误仍会照常报出）。
    resolved = state.get("issue_feedback") or []
    resolved_feedback = resolved if any(
        str(item.get("suggestion") or "").strip() for item in resolved
    ) else None

    try:
        data = await llm.complete_json(
            task="verify",
            system=prompts.VERIFY_SYSTEM + "\n" + prompts.VERIFY_JSON_HINT,
            user=prompts.verify_user(
                state["facts_text"], state["draft"], request,
                knowledge=state.get("knowledge_context", ""),
                reference=state.get("reference_context", ""),
                skill=state.get("skill_context", ""),
                previous_issues=previous_issues or None,
                resolved_feedback=resolved_feedback,
            ),
            # 评审含主观判断，温度 0 会让六维评分坍缩到同一组数字（线上曾全部输出 62 分）；
            # 0.3 允许评分与措辞有合理波动，事实比对部分由锚点与事实清单约束。
            temperature=0.3,
        )
        if isinstance(data, dict):
            raw_issues = data.get("issues") or []
            issues = [item for item in raw_issues if isinstance(item, dict)][:8]
            summary = str(data.get("summary") or "")
            raw_dims = data.get("dimensions") or {}
            dimensions = {
                str(k): max(1, min(5, int(v)))
                for k, v in raw_dims.items()
                if isinstance(v, (int, float))
            }
            raw_score = data.get("score")
            if isinstance(raw_score, (int, float)):
                llm_score = max(0, min(100, int(raw_score)))
            raw_check = data.get("revision_check")
            if isinstance(raw_check, list):
                revision_check = [item for item in raw_check if isinstance(item, dict)]
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"事实校验调用失败，请把初稿视为未审核：{exc}")

    # 字数纪律：超出目标篇幅 ±15% 由系统注入一条 style 意见，驱动 revise 修剪篇幅。
    words = len(re.findall(r"\b[\w'-]+\b", state["draft"])) + len(re.findall(r"[\u4e00-\u9fff]", state["draft"]))
    limit = request.get("word_limit", 900)
    if words > limit * 1.15:
        issues.insert(0, {
            "quote": f"全文约 {words} 词",
            "type": "style",
            "reason": f"超出目标篇幅 {limit} 词的 15%",
            "fix": f"压缩到 {int(limit * 0.9)}-{int(limit * 1.1)} 词：优先删冗余修饰、重复论据与总结性段落",
        })

    # 总分一律由六维均值换算（score = 六维平均 × 20），保证总分可解释、与六维一致、
    # 跨轮稳定可比；模型直接给的 score 仅在其未返回维度时兜底。
    score = round(sum(dimensions.values()) / len(dimensions) / 5 * 100) if dimensions else llm_score

    hard_issues = [item for item in issues if item.get("type") in FATAL_ISSUE_TYPES]
    soft_issues = [item for item in issues if item.get("type") not in FATAL_ISSUE_TYPES]
    number_warnings = _numeric_warnings(state["draft"], state["facts_text"])
    # 三态结论：事实风险 / 建议复核 / 已核验。数字待核对只降到「建议复核」。
    if hard_issues:
        verdict = "factual_risk"
    elif soft_issues or number_warnings:
        verdict = "needs_review"
    else:
        verdict = "passed"
    passed = not hard_issues
    if hard_issues and score is not None:
        score = min(score, 70)

    # 分数历史用于自修复收敛判断：连续两轮没有提升就停止自动改写。
    history = list(state.get("score_history") or [])
    if score is not None:
        history.append(score)
    critique = {
        "passed": passed,
        "verdict": verdict,
        "score": score,
        "dimensions": dimensions,
        "issues": issues,
        "hard_issue_count": len(hard_issues),
        "soft_issue_count": len(soft_issues),
        "summary": summary,
        "numeric_warnings": number_warnings,
        "word_count": words,
        "revision_check": revision_check,
    }
    # 数字待核对只进 critique（每轮复检覆盖更新），不进全局 warnings：
    # 自修复循环会多轮 verify，全局 warnings 是累加通道，把数字警告放进去会产生重复与过时提示。
    phase = "复检" if state.get("revision_count", 0) else "初审"
    resolved_note = ""
    if previous_issues and revision_check:
        resolved = sum(1 for item in revision_check if item.get("status") == "resolved")
        resolved_note = f"，上一轮 {len(previous_issues)} 条意见已解决 {resolved} 条"
    word_note = f"、当前约 {words} 词（目标 {limit}）" if words > limit * 1.15 else ""
    return {
        "critique": critique,
        "score_history": history,
        "warnings": warnings,
        "events": [
            _event(
                "verify",
                f"{phase}完成：质量分 {score if score is not None else '—'}/100，"
                f"{len(hard_issues)} 条事实风险、{len(soft_issues)} 条质量建议、"
                f"{len(number_warnings)} 处数字待核对{word_note}{resolved_note}",
                issues=issues,
                passed=passed,
                verdict=verdict,
                score=score,
                dimensions=dimensions,
                numeric_warnings=number_warnings,
                word_count=words,
            )
        ],
    }


def should_revise(state: GraphState, *, settings: Settings, **_: Any) -> str:
    issues = (state.get("critique") or {}).get("issues") or []
    if not issues or state.get("revision_count", 0) >= settings.max_revisions:
        return "finalize"
    hard = [item for item in issues if item.get("type") in FATAL_ISSUE_TYPES]
    if hard:
        # 事实安全硬错误继续修，但连续两轮分数没有提升就停手。
        history = state.get("score_history") or []
        if len(history) >= 2 and history[-1] <= history[-2]:
            return "finalize"
        return "revise"
    # 纯质量建议（含本地版字数纪律注入的超篇幅意见）只给首轮一次改写机会。
    if state.get("revision_count", 0) == 0:
        return "revise"
    return "finalize"


async def revise(state: GraphState, *, llm: LLMClient, **_: Any) -> dict[str, Any]:
    issues = (state.get("critique") or {}).get("issues") or []
    feedback = state.get("feedback") or ""
    issue_feedback = state.get("issue_feedback") or []
    rounds = state.get("revision_count", 0)

    # 分轮聚焦：两类修改混在轮内互相打架是自修复无效的主因之一。
    # 第一轮只修事实类；后续轮优先文风/结构/篇幅并清残留事实类；
    # 用户建议轮（feedback / issue_feedback）最高优先级，全部意见照办。
    if issue_feedback or feedback.strip():
        focus_issues = issues
        focus_note = ""
        focus_label = "用户建议轮"
    elif rounds == 0:
        fatal_types = {"fabrication", "contradiction", "unsupported", "program_fit"}
        focus_issues = [i for i in issues if i.get("type") in fatal_types] or issues
        focus_note = ("第一轮只处理事实类问题（fabrication / contradiction / unsupported / "
                      "program_fit）；文风、结构与篇幅问题本轮不动，留给后续轮次。")
        focus_label = "事实类聚焦"
    else:
        focus_issues = issues
        focus_note = ("本轮优先处理文风、结构、篇幅与语言问题；"
                      "前一轮遗留的事实类问题一并修正。")
        focus_label = "文风与收尾"

    text = await llm.complete(
        task="revise",
        system=state["system_prompt"],
        user=prompts.revise_user(
            state["facts_text"],
            state["draft"],
            focus_issues,
            state["request"],
            feedback=feedback,
            issue_feedback=issue_feedback,
            focus_note=focus_note,
        ),
        temperature=0.3,
        max_tokens=max(2048, min(6000, state["request"].get("word_limit", 900) * 4)),
    )
    advised = sum(1 for item in issue_feedback if str(item.get("suggestion") or "").strip())
    if advised:
        summary = f"已按 {advised} 条逐项审核建议与 {len(focus_issues)} 条校验意见修订全文"
    elif feedback.strip():
        summary = f"已按 {len(focus_issues)} 条校验意见与整体补充说明修订全文"
    else:
        summary = f"自我修复（{focus_label}）：处理 {len(focus_issues)}/{len(issues)} 条意见，待复检确认"
    return {
        "draft": _clean_markdown(text),
        "revision_count": rounds + 1,
        # 记录修订前的完整意见清单（未按轮次过滤），供下一轮复检做"已解决/仍存在"对照。
        "previous_issues": issues,
        "events": [_event("revise", summary, resolved=len(focus_issues), focus=focus_label)],
    }


async def finalize(state: GraphState, **_: Any) -> dict[str, Any]:
    final = _clean_markdown(state.get("draft") or "")
    if not final:
        raise RuntimeError("生成结果为空，未生成文档")
    words = len(re.findall(r"\b[\w'-]+\b", final)) + len(re.findall(r"[\u4e00-\u9fff]", final))
    # 定稿文案区分「用户按审核建议重生成」与「系统自修复」两种链路。
    critique = state.get("critique") or {}
    rounds = state.get("revision_count", 0)
    remaining = len(critique.get("issues") or [])
    level = critique.get("verdict") or ("passed" if critique.get("passed") else "needs_review")
    user_driven = bool((state.get("feedback") or "").strip()) or any(
        str(item.get("suggestion") or "").strip()
        for item in (state.get("issue_feedback") or [])
    )
    if user_driven:
        if level == "passed":
            verdict = "已按审核建议修订并复检通过"
        elif level == "factual_risk":
            verdict = f"已按审核建议修订，仍有 {remaining} 条事实风险待人工确认"
        else:
            verdict = f"已按审核建议修订，复检仍有 {remaining} 条建议待复核"
    elif rounds == 0:
        verdict = "初审通过，无需修复"
    elif level == "passed":
        verdict = f"自我修复 {rounds} 轮后复检通过"
    else:
        verdict = f"自我修复 {rounds} 轮后仍有 {remaining} 条待核项，转人工复核"
    return {
        "final": final,
        "events": [_event("finalize", f"{verdict}，约 {words} 词", word_count=words, verdict=verdict)],
    }
