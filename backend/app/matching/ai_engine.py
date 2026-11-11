"""AI 选校评估引擎：调用 LLM 结合申请人档案与项目官方要求，给出每个项目的适配等级。

与前端 tier 字段一致：
- gap   硬性缺口：明显不满足官方硬性门槛（语言未达标 / 背景完全不相关且无弥补）
- reach 冲刺：满足硬性要求但竞争激烈、背景边际，录取概率低
- match 稳妥：满足硬性要求且匹配度良好，录取概率中等偏上
- safety 保底：满足硬性要求且背景明显强于项目典型录取水平

说明：本模块仅负责把档案与项目要求组装成提示词、调用 LLM、并把模型返回的等级
映射回前端需要的统一结构；不调用任何规则引擎，也不做确定性兜底（未配置 Key 或
模型调用失败会直接报错，由路由层转为友好 HTTP 错误）。
"""
from __future__ import annotations

import re
from typing import Any

from app.llm.client import LLMCallError, LLMClient

_TIER_ORDER = ["gap", "reach", "match", "safety"]
_TIER_LABELS = {"gap": "硬性缺口", "reach": "冲刺", "match": "稳妥", "safety": "保底"}
_VALID_TIERS = set(_TIER_ORDER)

_SYSTEM_PROMPT = """你是一位资深的香港与新加坡授课型 / 研究型硕士留学选校顾问。
任务：根据申请人档案，以及给定的每个硕士项目的官方硬性要求，结合项目竞争激烈程度与申请人综合背景，判断每个项目的适配等级。

等级定义（每个项目只能取其一）：
- "gap"（硬性缺口）：申请人明显不满足官方硬性门槛（如语言总分或单项未达标、背景完全不相关且无弥补空间）。不建议作为申请目标。
- "reach"（冲刺）：满足硬性要求，但项目竞争激烈、申请人背景处于边际，录取概率较低，值得冲刺。
- "match"（稳妥）：满足硬性要求，申请人背景与项目匹配度良好，录取概率中等偏上。
- "safety"（保底）：满足硬性要求，且申请人背景明显强于项目典型录取水平，录取概率高。

判断准则：
1. 语言是否达标以项目给定的官方要求为准（ielts_total_min / ielts_subtest_min / toefl_min）。若申请人语言成绩未达标（含单项），该项目必须判为 "gap"，并在 gaps 中具体说明（例如「雅思写作 6.0 低于单项要求 6.5」）。
2. 在满足硬性门槛的前提下，综合 GPA / 均分、专业与课程匹配度、科研 / 实习 / 项目经历、院校背景等给出 reach / match / safety 判断。
3. reasons 给出 2-3 条简明判断依据；gaps 列出申请人相对该项目的主要短板或需补强项（没有则为空数组）。
4. 只使用给定信息，不要编造项目未提供的官方数据。若信息不足，宁可保守（偏向 reach / match）。
5. 若输入包含 "preferences"（申请人的择校与项目偏好，均为可选）：
   - priority_regions 是优先地区（如 ["SG"] 优先新加坡、"HK" 优先香港）：符合偏好地区的项目，在 reasons 中明确呼应（例如「符合优先新加坡的择校偏好」），并在同级评估中给予倾向；
   - preferred_fields 是优先的专业方向关键词：与项目名称 / 培养方向吻合时，在 reasons 中呼应（例如「项目方向符合优先计算机相关专业的偏好」）；
   - 偏好不改变硬性门槛判定（语言未达标仍是 "gap"），只影响 reach / match / safety 之间的倾向与理由侧重。

输出要求：只返回一个 JSON 数组，不要任何解释文字、不要使用代码块。数组每个元素形如：
{"program_id": "项目id", "tier": "gap|reach|match|safety", "reasons": ["依据1", "依据2"], "gaps": ["短板1"]}
reasons 每条不超过 30 字、gaps 尽量精简，紧凑输出；必须覆盖输入 programs 中的全部 program_id（共 30 个），不可遗漏任何一项。"""


def _first_number(text: Any) -> float | None:
    if text is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(text))
    return float(m.group()) if m else None


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    education = []
    for ed in profile.get("education") or []:
        education.append({
            "school": ed.get("school"),
            "degree": ed.get("degree"),
            "major": ed.get("major"),
            "gpa": ed.get("gpa"),
            "gpa_scale": ed.get("gpa_scale"),
            "gpa_average": ed.get("gpa_average"),
            "relevant_courses": ed.get("relevant_courses") or [],
            "thesis": ed.get("thesis"),
            "highlights": ed.get("highlights"),
        })
    test_scores = [
        {"kind": t.get("kind"), "total": t.get("total"), "breakdown": t.get("breakdown")}
        for t in (profile.get("test_scores") or [])
    ]
    experiences = [
        {"type": e.get("type"), "org": e.get("org"), "role": e.get("role"),
         "bullets": (e.get("bullets") or [])[:4]}
        for e in (profile.get("experiences") or [])
    ]
    return {
        "education": education,
        "test_scores": test_scores,
        "experiences": experiences,
        "publications": profile.get("publications") or [],
        "awards": [{"title": a.get("title"), "issuer": a.get("issuer")} for a in (profile.get("awards") or [])],
        "skills": [{"category": s.get("category"), "items": s.get("items") or []} for s in (profile.get("skill_groups") or [])],
        "career_goal": profile.get("career_goal"),
        "additional_notes": profile.get("additional_notes"),
    }


def _programs_payload(requirements: dict[str, Any], index_data: dict[str, Any]) -> list[dict[str, Any]]:
    meta = {str(p.get("id")): p for p in (index_data.get("programs") or []) if p.get("id")}
    payload: list[dict[str, Any]] = []
    for pid, req in (requirements.get("programs") or {}).items():
        m = meta.get(pid) or {}
        payload.append({
            "program_id": pid,
            "school": m.get("school_name_zh") or "",
            "name_en": m.get("name_en") or "",
            "name_zh": m.get("name_zh") or "",
            "region": m.get("region") or "",
            "requirements": {
                "ielts_total_min": req.get("ielts_total_min"),
                "ielts_subtest_min": req.get("ielts_subtest_min"),
                "toefl_min": req.get("toefl_min"),
                "preferred_background": req.get("preferred_background") or [],
                "language_note": req.get("language_note") or "",
            },
        })
    return payload


def _snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    ielts = toefl = None
    for t in (profile.get("test_scores") or []):
        kind = str(t.get("kind") or "").lower()
        total = _first_number(t.get("total"))
        if total is None:
            continue
        if "ielts" in kind or "雅思" in kind:
            ielts = total
        elif "toefl" in kind or "托福" in kind:
            toefl = total
    edu = profile.get("education") or []
    first = edu[0] if edu else {}
    return {
        "gpa": first.get("gpa") or "",
        "gpa_average": first.get("gpa_average") or "",
        "ielts_total": ielts,
        "toefl_total": toefl,
        "notes": [],
        "watermark_note": "由大模型结合档案与项目官方要求评估；语言硬性门槛以官方要求为准，最终请以官网最新信息为准。",
    }


async def ai_evaluate_profile(
    profile: dict[str, Any],
    requirements: dict[str, Any],
    index_data: dict[str, Any],
    llm: LLMClient,
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用 LLM 评估全部候选项目的适配等级，返回与前端契约一致的结构。

    preferences 为可选的择校 / 项目偏好（priority_regions / preferred_fields），
    非空时会进入提示词，让模型在 reasons 中呼应偏好；为空时行为与既往一致。
    失败时抛出 LLMCallError（模型调用失败 / 未返回合规 JSON），由路由层转成 HTTP 错误。
    """
    summary = _profile_summary(profile)
    programs = _programs_payload(requirements, index_data)
    payload_obj: dict[str, Any] = {"profile": summary, "programs": programs}
    cleaned = {k: v for k, v in (preferences or {}).items() if v}
    if cleaned:
        payload_obj["preferences"] = cleaned
    user_content = _json_dumps(payload_obj)

    data = await llm.complete_json(
        task="选校评估",
        system=_SYSTEM_PROMPT,
        user=user_content,
        max_tokens=8192,
        temperature=0.2,
    )
    if not isinstance(data, list):
        raise LLMCallError("选校评估：模型未返回合规的 JSON 数组")

    meta = {str(p.get("id")): p for p in (index_data.get("programs") or []) if p.get("id")}
    target_keys = {
        (str(t.get("university") or ""), str(t.get("program") or ""))
        for t in profile.get("target_programs") or []
    }
    by_id = {str(item.get("program_id")): item for item in data if isinstance(item, dict)}

    results: list[dict[str, Any]] = []
    for pid, req in (requirements.get("programs") or {}).items():
        m = meta.get(pid) or {}
        ai = by_id.get(pid) or {}
        tier = str(ai.get("tier") or "").strip().lower()
        if tier not in _VALID_TIERS:
            tier = "match"
            reasons = list(ai.get("reasons") or []) or ["模型未给出明确等级，已按稳妥保守处理"]
        else:
            reasons = list(ai.get("reasons") or [])
        gaps = list(ai.get("gaps") or [])
        school = m.get("school_name_zh") or ""
        name_en = m.get("name_en") or ""
        in_target = (school, name_en) in target_keys
        results.append({
            "program_id": pid,
            "school_name_zh": school,
            "name_en": name_en,
            "name_zh": m.get("name_zh") or "",
            "region": m.get("region") or "",
            "intake": m.get("tuition_intake") or "",
            "deadline": (m.get("deadlines") or [""])[0],
            "tier": tier,
            "tier_label": _TIER_LABELS[tier],
            "reasons": reasons,
            "gaps": gaps,
            "language_note": req.get("language_note") or "",
            "in_target": in_target,
        })

    results.sort(key=lambda x: (_TIER_ORDER.index(x["tier"]), x["school_name_zh"], x["name_en"]))
    return {
        "results": results,
        "profile_snapshot": _snapshot(profile),
        "tier_order": _TIER_ORDER,
        "tier_labels": _TIER_LABELS,
        "preferences_applied": bool(cleaned),
    }


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
