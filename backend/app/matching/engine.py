"""选校评估规则引擎：档案硬指标与项目要求的确定性比对（不调用 LLM）。

比对口径与诚实边界：
- 语言要求（IELTS/TOEFL 总分与单项）是官方硬性标准 → 不满足进入硬性缺口清单。
- GPA/均分：多数港新项目不公布硬线，分级中的学术水位（87/82 分界）是通用经验
  参考，输出文案会明确标注；4.0 制 GPA 按线性折算并注明「仅供参考」。
- 本科背景匹配是软参考（关键词命中才加分），不构成缺口或负评。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 通用水位线（百分制口径；4.0 制 GPA 线性折算后使用同一分界）。
AVG_SAFETY = 87.0
AVG_MATCH = 82.0

_TIER_ORDER = ["gap", "reach", "match", "safety"]
_TIER_LABELS = {"gap": "硬性缺口", "reach": "冲刺", "match": "稳妥", "safety": "保底"}
_SUBTEST_NAMES = {"L": "听力", "R": "阅读", "W": "写作", "S": "口语"}


def load_requirements(knowledge_dir: Path) -> dict[str, Any]:
    path = Path(knowledge_dir) / "match-requirements.json"
    if not path.exists():
        return {"programs": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(knowledge_dir: Path) -> dict[str, Any]:
    path = Path(knowledge_dir) / "index.json"
    if not path.exists():
        return {"programs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _first_number(text: Any) -> float | None:
    if text is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(text))
    return float(m.group()) if m else None


def parse_ielts_breakdown(text: str | None) -> dict[str, float]:
    """解析分项自由文本：L 7.5 / R 7.5 / W 6.5 / S 6.5（含 R:7.5、中文 听读写说 变体）。"""
    out: dict[str, float] = {}
    mapping = {"L": "L", "R": "R", "W": "W", "S": "S", "听": "L", "读": "R", "写": "W", "说": "S"}
    for m in re.finditer(r"([LRWS听读写说])\s*[:：]?\s*(\d(?:\.\d)?)", (text or ""), re.IGNORECASE):
        raw = m.group(1)
        key = mapping.get(raw.upper() if raw.isascii() else raw)
        if key and key not in out:
            out[key] = float(m.group(2))
    return out


def _pick_language_scores(test_scores: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """取 IELTS 与 TOEFL 各自的最佳成绩记录（总分可解析且最高者）。"""
    ielts = toefl = None
    ielts_best = toefl_best = -1.0
    for item in test_scores or []:
        kind = str(item.get("kind") or "").lower()
        total = _first_number(item.get("total"))
        if total is None:
            continue
        if ("ielts" in kind or "雅思" in kind) and total > ielts_best:
            ielts, ielts_best = item, total
        if ("toefl" in kind or "托福" in kind) and total > toefl_best:
            toefl, toefl_best = item, total
    return ielts, toefl


def _check_one_exam(
    exam: dict[str, Any] | None,
    total_min: float,
    subtest_min: float | None,
    name: str,
) -> tuple[bool | None, list[str], list[str]]:
    """单考试判定：返回 (passed, reasons, gaps)。passed=None 表示没有可判定数据。"""
    if not exam:
        return None, [], []
    total = _first_number(exam.get("total"))
    if total is None:
        return None, [], []
    reasons: list[str] = []
    gaps: list[str] = []
    passed = total >= total_min
    if passed:
        reasons.append(f"{name} 总分 {total} 达到该项目要求 {total_min}")
    else:
        gaps.append(f"{name} 总分 {total} 低于该项目要求 {total_min}")
    if subtest_min is not None:
        sub = parse_ielts_breakdown(exam.get("breakdown")) if name == "IELTS" else {}
        if sub:
            weak = {k: v for k, v in sub.items() if v < subtest_min}
            if weak:
                for k, v in sorted(weak.items()):
                    gaps.append(f"{name} {_SUBTEST_NAMES.get(k, k)} {v} 低于单项要求 {subtest_min}")
                passed = False
            else:
                reasons.append(f"{name} 各单项均不低于 {subtest_min}，满足单项要求")
        elif passed:
            reasons.append(f"未提供 {name} 分项成绩，单项要求 ≥{subtest_min} 无法核对（总分已达标）")
    return passed, reasons, gaps


def _check_language(
    req: dict[str, Any],
    ielts: dict[str, Any] | None,
    toefl: dict[str, Any] | None,
) -> tuple[list[str], list[str], bool | None]:
    """返回 (reasons, gaps, lang_satisfied)。任一考试达标即满足。"""
    ielts_min = req.get("ielts_total_min")
    subtest_min = req.get("ielts_subtest_min")
    toefl_min = req.get("toefl_min")
    if ielts_min is None and toefl_min is None:
        return ["该项目官网明确无需提交语言成绩"], [], True

    reasons: list[str] = []
    gaps: list[str] = []
    satisfied: bool | None = None
    if ielts_min is not None:
        passed, r, g = _check_one_exam(ielts, float(ielts_min), float(subtest_min) if subtest_min is not None else None, "IELTS")
        reasons += r
        gaps += g
        if passed is not None:
            satisfied = True if passed else satisfied
    if toefl_min is not None:
        passed, r, g = _check_one_exam(toefl, float(toefl_min), None, "TOEFL")
        reasons += r
        gaps += g
        if passed is not None:
            satisfied = True if passed else satisfied
    if satisfied is None:
        req_desc = f"IELTS ≥ {ielts_min or '—'}"
        if toefl_min is not None:
            req_desc += f" / TOEFL ≥ {toefl_min}"
        gaps.insert(0, f"档案未提供语言成绩（该项目要求 {req_desc}）")
    return reasons, gaps, satisfied


def _academic_state(education: list[dict[str, Any]]) -> tuple[float | None, list[str]]:
    """取档案中最高的百分制均分；无均分时用 4.0 制 GPA 线性折算（注明仅供参考）。"""
    notes: list[str] = []
    best: float | None = None
    for item in education or []:
        avg = _first_number(item.get("gpa_average"))
        if avg is not None:
            best = avg if best is None else max(best, avg)
            continue
        gpa = _first_number(item.get("gpa"))
        scale = _first_number(item.get("gpa_scale")) or 4.0
        if gpa is not None and scale == 4.0:
            conv = round(gpa / 4.0 * 100, 1)
            best = conv if best is None else max(best, conv)
            note = f"GPA {gpa}/4.0 按线性折算约 {conv}/100（折算仅供参考，建议直接填写百分制均分）"
            if note not in notes:
                notes.append(note)
    return best, notes


def _academic_verdict(avg: float | None) -> tuple[str, str]:
    if avg is None:
        return "match", "档案未提供 GPA / 均分，无法进行学术水位比对"
    if avg >= AVG_SAFETY:
        return "safety", f"均分 {avg:g}/100 高于常见录取水位（≥{AVG_SAFETY:g} 竞争力较充足）"
    if avg >= AVG_MATCH:
        return "match", f"均分 {avg:g}/100 处于常见录取区间（{AVG_MATCH:g}-{AVG_SAFETY:g}）"
    return "reach", f"均分 {avg:g}/100 低于常见录取水位（<{AVG_MATCH:g}），按冲刺评估，建议以软实力补足"


def _background_match(req: dict[str, Any], education: list[dict[str, Any]]) -> str | None:
    preferred = req.get("preferred_background") or []
    if not preferred or not education:
        return None
    haystack = " ".join(
        f"{item.get('major') or ''} {' '.join(item.get('relevant_courses') or [])}".lower()
        for item in education
    )
    hits = [k for k in preferred if k.lower() in haystack]
    if not hits:
        return None
    major = (education[0].get("major") or "").strip()
    where = f"本科专业（{major}）" if major else "本科背景"
    return f"{where}与项目偏好背景匹配（命中关键词：{'、'.join(hits[:3])}）"


def evaluate_profile(
    profile: dict[str, Any],
    requirements: dict[str, Any],
    index_data: dict[str, Any],
) -> dict[str, Any]:
    education = profile.get("education") or []
    ielts, toefl = _pick_language_scores(profile.get("test_scores") or [])
    avg, acad_notes = _academic_state(education)
    acad_tier, acad_reason = _academic_verdict(avg)

    ielts_total = _first_number(ielts.get("total")) if ielts else None
    toefl_total = _first_number(toefl.get("total")) if toefl else None
    snapshot = {
        "gpa": (education or [{}])[0].get("gpa") or "",
        "gpa_average": (education[0].get("gpa_average") or "") if education else "",
        "ielts_total": ielts_total,
        "toefl_total": toefl_total,
        "notes": acad_notes,
        "watermark_note": "语言要求为官方硬性标准；学术水位（保底/稳妥/冲刺分界）为通用经验参考，多数港新项目不公布 GPA 硬线。",
    }

    meta = {str(p.get("id")): p for p in (index_data.get("programs") or []) if p.get("id")}
    target_keys = {
        (str(t.get("university") or ""), str(t.get("program") or ""))
        for t in profile.get("target_programs") or []
    }

    results: list[dict[str, Any]] = []
    for pid, req in (requirements.get("programs") or {}).items():
        m = meta.get(pid) or {}
        school = m.get("school_name_zh") or ""
        name_en = m.get("name_en") or ""
        reasons, gaps, lang_satisfied = _check_language(req, ielts, toefl)
        bg = _background_match(req, education)
        if bg:
            reasons.append(bg)
        tier = "gap" if gaps else acad_tier
        reasons.append(acad_reason)
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

    # 缺口最优先，其余按 保底→稳妥→冲刺 展示，同级按校名分组可读性更好。
    results.sort(key=lambda x: (_TIER_ORDER.index(x["tier"]), x["school_name_zh"], x["name_en"]))
    return {
        "results": results,
        "profile_snapshot": snapshot,
        "tier_order": _TIER_ORDER,
        "tier_labels": _TIER_LABELS,
    }