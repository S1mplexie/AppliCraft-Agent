"""简历解析：文本抽取 → LLM 结构化 → 字段级覆盖合并。

设计约束：
- 隐私优先：上传文件只在内存中抽取纯文本，绝不落盘、绝不上传第三方。
- 覆盖语义：只覆盖简历里确实出现的信息；列表类字段（教育/经历/奖项/技能/成绩/
  目标项目）仅当解析结果非空时才整体替换，避免误删用户已有的手工录入。
- 不臆造：LLM 只做事实抽取；推荐人等简历通常不含量，刻意不纳入解析 schema，
  防止把模型「补出来」的内容写进档案。
"""
from __future__ import annotations

import io
import re
from typing import Any

from pydantic import BaseModel, Field

from app.models.profile import (
    ApplicantProfile,
    Award,
    Basics,
    Education,
    Experience,
    SkillGroup,
    TargetProgram,
    TestScore,
)

# 上传文件约束：允许的扩展名与最大体积（10 MB，足以容纳图文混排简历）。
ALLOWED_EXTENSIONS = frozenset({".txt", ".md", ".docx", ".pdf"})
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# LLM 可见的简历纯文本上限，防止超长简历撑爆上下文。
MAX_RESUME_TEXT_CHARS = 16000


class ResumeParseError(ValueError):
    """简历解析过程中可预期的用户级错误（文本为空 / 格式不支持等）。"""


# --------------------------------------------------------------------------- 文本抽取

def extract_text(content: bytes, filename: str) -> str:
    """根据扩展名抽取简历纯文本；不支持的格式或空内容抛出 ResumeParseError。"""
    ext = (filename or "").lower()
    if "." in ext:
        ext = "." + ext.rsplit(".", 1)[-1]
    if ext not in ALLOWED_EXTENSIONS:
        raise ResumeParseError(
            f"不支持的文件格式：{ext or '未知'}。仅支持 PDF / DOCX / TXT / MD。"
        )

    if ext in (".txt", ".md"):
        text = content.decode("utf-8", errors="ignore")
    elif ext == ".docx":
        text = _extract_docx(content)
    elif ext == ".pdf":
        text = _extract_pdf(content)
    else:  # pragma: no cover - 上面已拦截
        raise ResumeParseError("不支持的文件格式。")

    text = _normalize_whitespace(text)
    if len(text.strip()) < 30:
        raise ResumeParseError("未能从文件中解析出足够的文字内容，请确认文件未损坏或是否为图片版简历。")
    return text


def _normalize_whitespace(text: str) -> str:
    # 合并多余空行与首尾空白，保留段落分隔。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_docx(content: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - python-docx 已在依赖中
        raise ResumeParseError("服务端缺少 docx 解析依赖，请联系管理员。") from exc
    try:
        document = Document(io.BytesIO(content))
        parts: list[str] = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001 - 损坏的 zip/非 docx 内容都会在此暴露
        raise ResumeParseError(f"DOCX 解析失败（文件可能已损坏）：{exc}") from exc


def _extract_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf 已在依赖中
        raise ResumeParseError("服务端缺少 PDF 解析依赖，请联系管理员。") from exc
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - PDF 损坏 / 加密都会在此暴露
        raise ResumeParseError(f"PDF 解析失败（可能已加密或损坏）：{exc}") from exc
    return "\n".join(pages)


# --------------------------------------------------------------------------- LLM 解析

PARSE_SYSTEM = """你是一名严谨的简历信息抽取引擎。你会收到一份简历纯文本，请从中抽取结构化信息，\
严格按下面的 JSON Schema 输出，只返回 JSON 对象，不要任何解释或代码块。

抽取规则：
1. 只抽取简历里明确出现的事实，绝不臆造、补全或推断不存在的信息。
2. 字段在简历中未出现时留空字符串或空数组，不要填占位符。
3. 日期统一为 YYYY-MM 或 YYYY-MM ~ YYYY-MM 形式（如 2022-09、2024-06 ~ 2025-12）。
4. 经历 type 只能是以下之一：research（科研）/ internship（实习）/ work（全职）/ project（项目）/ volunteer（志愿）/ competition（竞赛）。
5. 标化成绩 kind 只能是以下之一：IELTS / TOEFL / GRE / GMAT / other。
6. 目标项目 degree_type 按简历推断，如 Taught Master / Research Master / PhD，不确定留空。
7. 列表字段（education / experiences / awards / skill_groups / test_scores / target_programs）
   中每一项的字段请尽量填全；skill_groups 按类别分组（如 Programming、Languages）。

JSON Schema：
{
  "basics": {
    "name_en": "", "name_zh": "", "email": "", "phone": "", "location": "",
    "linkedin": "", "github": "", "personal_site": ""
  },
  "education": [
    {"school": "", "degree": "", "major": "", "gpa": "", "gpa_scale": "4.0",
     "ranking": "", "start_date": "", "end_date": "", "relevant_courses": [], "thesis": "", "highlights": ""}
  ],
  "experiences": [
    {"type": "", "org": "", "role": "", "location": "", "start_date": "", "end_date": "",
     "bullets": [], "tags": []}
  ],
  "publications": ["每行一条完整引用"],
  "awards": [{"title": "", "issuer": "", "date": "", "detail": ""}],
  "skill_groups": [{"category": "", "items": []}],
  "test_scores": [{"kind": "", "total": "", "breakdown": "", "date": ""}],
  "target_programs": [
    {"university": "", "program": "", "degree_type": "", "region": "", "intake": "",
     "deadline": "", "language_requirement": "", "curriculum_notes": "", "faculty_notes": "", "why_fit": "", "notes": ""}
  ],
  "career_goal": "",
  "additional_notes": ""
}"""


class ResumePatch(BaseModel):
    """LLM 解析结果的结构化形态；复用档案子模型以获得一致的字段与默认 id。"""

    basics: Basics = Field(default_factory=Basics)
    education: list[Education] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    test_scores: list[TestScore] = Field(default_factory=list)
    target_programs: list[TargetProgram] = Field(default_factory=list)
    career_goal: str = ""
    additional_notes: str = ""


def _normalize_raw_patch(raw: dict[str, Any]) -> dict[str, Any]:
    """对 LLM 输出做少量容错：常见异名字段归一到规范 schema。"""
    if not isinstance(raw, dict):
        return {}
    norm = dict(raw)
    # 技能字段别名兼容
    if not norm.get("skill_groups"):
        for alias in ("skills", "skillGroups", "skill_list"):
            val = norm.get(alias)
            if isinstance(val, list) and val:
                norm["skill_groups"] = val
                break
    # 目标项目别名兼容
    if not norm.get("target_programs"):
        for alias in ("programs", "targets", "target_programs"):
            val = norm.get(alias)
            if isinstance(val, list) and val:
                norm["target_programs"] = val
                break
    return norm


async def parse_resume_text(resume_text: str, llm: Any) -> ResumePatch:
    """调用 LLM 把简历文本解析为 ResumePatch。"""
    truncated = resume_text[:MAX_RESUME_TEXT_CHARS]
    data = await llm.complete_json(
        task="parse_resume",
        system=PARSE_SYSTEM,
        user=f"以下是一份简历的纯文本内容，请抽取结构化信息：\n\n{truncated}",
        temperature=0.0,
    )
    return ResumePatch.model_validate(_normalize_raw_patch(data))


# --------------------------------------------------------------------------- 覆盖合并

def merge_profile(base: dict[str, Any], patch: ResumePatch) -> tuple[dict[str, Any], list[str]]:
    """把解析结果按「只覆盖确实出现的信息」语义合并进 base 档案，返回 (合并后档案, 变更清单)。"""
    merged = dict(base)
    changes: list[str] = []

    # 基本信息：逐字段覆盖非空值。
    base_basics = dict(base.get("basics") or {})
    for field, value in patch.basics.model_dump().items():
        if isinstance(value, str) and value.strip():
            if base_basics.get(field) != value:
                base_basics[field] = value
                label = _BASICS_LABELS.get(field, field)
                changes.append(f"基本信息·{label}：{value}")
    merged["basics"] = base_basics

    # 列表类字段：解析结果非空才整体替换（并保留模型生成的 id）。
    _merge_list(merged, changes, "education", patch.education, "教育经历", "段")
    _merge_list(merged, changes, "experiences", patch.experiences, "研究/实习/项目经历", "条")
    _merge_list(merged, changes, "awards", patch.awards, "奖项与荣誉", "项")
    _merge_list(merged, changes, "skill_groups", patch.skill_groups, "技能组", "组")
    _merge_list(merged, changes, "test_scores", patch.test_scores, "标化成绩", "项")
    _merge_list(merged, changes, "target_programs", patch.target_programs, "目标项目", "个")

    # 论文：字符串数组，非空才替换。
    if patch.publications:
        merged["publications"] = list(patch.publications)
        changes.append(f"论文/出版物：{len(patch.publications)} 条")

    # 职业目标 / 补充说明：非空才覆盖。
    if patch.career_goal.strip():
        merged["career_goal"] = patch.career_goal.strip()
        changes.append("职业目标：已更新")
    if patch.additional_notes.strip():
        existing = (merged.get("additional_notes") or "").strip()
        merged["additional_notes"] = (
            f"{existing}\n{patch.additional_notes.strip()}" if existing else patch.additional_notes.strip()
        )
        changes.append("补充说明：已补充简历备注")

    return merged, changes


def _merge_list(
    merged: dict[str, Any],
    changes: list[str],
    key: str,
    items: list[Any],
    label: str,
    unit: str,
) -> None:
    if not items:
        return
    merged[key] = [item.model_dump() for item in items]
    changes.append(f"{label}：以简历内容覆盖，共 {len(items)} {unit}")


_BASICS_LABELS: dict[str, str] = {
    "name_en": "英文姓名",
    "name_zh": "中文姓名",
    "email": "邮箱",
    "phone": "电话",
    "location": "所在地",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "personal_site": "个人主页",
}


def build_merged_profile(base: ApplicantProfile, patch: ResumePatch) -> tuple[dict[str, Any], list[str]]:
    """便利封装：直接吃 ApplicantProfile 对象，返回合并后的 dict 与变更清单。"""
    return merge_profile(base.model_dump(), patch)
