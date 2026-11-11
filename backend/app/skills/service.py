"""Skill 市场服务层。

设计边界
--------
- 内置技能来自 `skills/builtin.json`（由 grad-writing-skills 技能包生成），
  全站只读共享；每个技能保存完整方法论 `content` 与示例 `examples` 供用户查看，
  但注入提示词时只用精炼过的 `instructions`，避免示例与流程说明稀释正文要求。
- 用户导入的技能保存在其隔离目录；支持单个 Markdown/文本，或包含多个
  `SKILL.md` 的 zip 技能包。导入内容只作为「写法约束」注入，绝不当成申请人事实。
- 所有技能都只是方法论：提示词层明确要求事实清单优先、占位符不得落地、
  与生成要求（字数/语言/文书类型）冲突时以生成要求为准。
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from app.storage.filestore import FileStore

BUILTIN_JSON = Path(__file__).with_name("builtin.json")

# 注入提示词的技能总预算；单个用户技能最多注入的字符数。
SKILL_MAX_CHARS = 6000
USER_INJECT_CHARS = 2500
# 上传限制：单个技能文件、整次上传、单次导入技能数、每用户技能总数。
USER_SKILL_MAX_BYTES = 200_000
SKILL_UPLOAD_MAX_BYTES = 1_000_000
MAX_SKILLS_PER_UPLOAD = 20
MAX_USER_SKILLS = 50
SKILL_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
SKILL_UPLOAD_EXTENSIONS = SKILL_TEXT_EXTENSIONS | {".zip"}

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_PUBLIC_FIELDS = (
    "id", "key", "origin", "name", "name_en", "description", "category",
    "doc_types", "tags", "char_count", "imported_at", "filename",
)


class SkillError(ValueError):
    """技能导入 / 解析的可预期用户级错误。"""


@lru_cache(maxsize=1)
def _builtin_items() -> tuple[dict[str, Any], ...]:
    if not BUILTIN_JSON.is_file():
        return ()
    data = json.loads(BUILTIN_JSON.read_text(encoding="utf-8"))
    return tuple(data.get("items") or [])


def public_skill(item: dict[str, Any]) -> dict[str, Any]:
    """列表用视图：剔除 content / examples / instructions 等大字段。"""
    return {key: item.get(key) for key in _PUBLIC_FIELDS if key in item}


def builtin_skills() -> list[dict[str, Any]]:
    return [public_skill(item) for item in _builtin_items()]


def _builtin_full(skill_id: str) -> dict[str, Any] | None:
    for item in _builtin_items():
        if item.get("id") == skill_id:
            return dict(item)
    return None


def get_skill_detail(store: FileStore, skill_id: str) -> dict[str, Any] | None:
    """技能详情（含完整方法论与示例）；内置只读，用户技能来自隔离目录。"""
    if skill_id.startswith("builtin:"):
        return _builtin_full(skill_id)
    if skill_id.startswith("user:"):
        return store.get_skill(skill_id[5:])
    return None


def resolve_skill(store: FileStore, skill_id: str) -> dict[str, Any] | None:
    """生成时按 id 取技能（内置优先，用户技能带 origin 标记）。"""
    detail = get_skill_detail(store, skill_id)
    if detail is None:
        return None
    detail.setdefault("origin", "builtin" if skill_id.startswith("builtin:") else "user")
    return detail


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 SKILL.md 顶部的 YAML 风格 frontmatter（只取简单 key: value）。"""
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text.strip()
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip().strip('"').strip("'")
    return fields, text[match.end():].strip()


def _decode(content: bytes, label: str) -> str:
    if not content or len(content) > USER_SKILL_MAX_BYTES:
        raise SkillError(f"技能文件「{label}」为空或超过 200 KB 上限")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillError(f"技能文件「{label}」不是有效的 UTF-8 文本") from exc


def _first_paragraph(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if len(line) >= 8 and not line.startswith(("|", "---", "```")):
            return line[:140]
    return ""


def _make_skill(
    *,
    filename: str,
    body: str,
    frontmatter: dict[str, str],
    name: str = "",
    description: str = "",
    examples: str = "",
) -> dict[str, Any]:
    _, content = parse_frontmatter(body) if body.startswith("---") else ({}, body.strip())
    if len(content) < 20:
        raise SkillError(f"技能「{filename}」正文过短（至少 20 个字符）")
    stem = PurePosixPath(filename).stem
    parent = PurePosixPath(filename).parent.name
    heading = next(
        (line.lstrip("#").strip() for line in content.splitlines() if line.startswith("# ")),
        "",
    )
    label = (name or "").strip() or frontmatter.get("title", "") or heading or (
        parent if parent and parent not in {".", ""} else frontmatter.get("name", "") or stem
    )
    desc = (description or "").strip() or frontmatter.get("description", "") or _first_paragraph(content)
    return {
        "name": label[:80],
        "name_en": (frontmatter.get("name") or stem)[:80],
        "description": desc[:300],
        "content": content,
        "examples": examples.strip(),
        "char_count": len(content),
        "filename": filename,
        "doc_types": [],
        "tags": [],
        "category": "我导入的",
    }


def parse_skill_upload(
    filename: str, content: bytes, *, name: str = "", description: str = ""
) -> list[dict[str, Any]]:
    """把上传文件解析为一组待保存技能；支持 .md/.txt 单文件与 .zip 技能包。

    只把 zip 内容读进内存、从不落盘解压，天然规避路径穿越；仍显式拒绝
    含 `..` 或绝对路径的成员，避免把伪装文件当成技能。
    """
    filename = filename or "skill.md"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in SKILL_UPLOAD_EXTENSIONS:
        raise SkillError(f"不支持的文件格式：{ext or '未知'}。请上传 .md / .txt / .zip 技能包。")
    if len(content) > SKILL_UPLOAD_MAX_BYTES:
        raise SkillError("技能包过大（上限 1 MB）")

    if ext == ".zip":
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise SkillError("不是有效的 zip 技能包") from exc
        with archive:
            members = []
            for info in archive.infolist():
                member = info.filename.replace("\\", "/")
                path = PurePosixPath(member)
                if info.is_dir() or path.is_absolute() or ".." in path.parts:
                    continue
                if path.suffix.lower() not in SKILL_TEXT_EXTENSIONS:
                    continue
                members.append((member, info))
            # 技能包优先按 SKILL.md 识别；否则退化为包内所有 md/txt（排除 README）。
            skill_files = [(m, i) for m, i in members if PurePosixPath(m).name.lower() == "skill.md"]
            if not skill_files:
                skill_files = [
                    (m, i) for m, i in members
                    if PurePosixPath(m).name.upper() != "README.MD"
                ]
            if not skill_files:
                raise SkillError("zip 包里没有找到 SKILL.md 或 .md / .txt 技能文件")
            if len(skill_files) > MAX_SKILLS_PER_UPLOAD:
                raise SkillError(f"单次最多导入 {MAX_SKILLS_PER_UPLOAD} 个技能")
            names = {m for m, _ in members}
            result = []
            for member, info in skill_files:
                body = _decode(archive.read(info), member)
                fm, _ = parse_frontmatter(body)
                example_member = str(PurePosixPath(member).parent / "references" / "examples.md")
                examples = ""
                if example_member in names:
                    try:
                        examples = _decode(archive.read(example_member), example_member)
                    except SkillError:
                        examples = ""
                result.append(
                    _make_skill(
                        filename=member, body=body, frontmatter=fm,
                        examples=examples,
                    )
                )
            return result

    body = _decode(content, filename)
    fm, _ = parse_frontmatter(body)
    return [
        _make_skill(
            filename=filename, body=body, frontmatter=fm,
            name=name, description=description,
        )
    ]


def build_skill_context(
    store: FileStore,
    skill_ids: list[str] | None,
    max_chars: int = SKILL_MAX_CHARS,
) -> tuple[str, list[dict[str, Any]]]:
    """按勾选顺序装配技能指令与来源清单；缺失 / 超预算技能对用户透明标注。

    返回 (context, meta)。context 是纯指令文本，由 prompts.skill_block 加守则后注入。
    """
    ids = [str(x).strip() for x in (skill_ids or []) if str(x).strip()]
    if not ids:
        return "", []
    meta_list: list[dict[str, Any]] = []
    parts: list[str] = []
    used = 0
    for skill_id in ids:
        skill = resolve_skill(store, skill_id)
        if not skill:
            meta_list.append(
                {"id": skill_id, "name": "", "included": False, "missing": True, "origin": ""}
            )
            continue
        name = skill.get("name") or skill.get("name_en") or skill_id
        origin = skill.get("origin", "")
        instructions = (skill.get("instructions") or "").strip()
        if not instructions:
            # 用户导入的技能没有精炼版：取正文前若干字符作为写法约束。
            instructions = (skill.get("content") or "").strip()[:USER_INJECT_CHARS]
        if not instructions:
            meta_list.append(
                {"id": skill_id, "name": name, "included": False, "origin": origin}
            )
            continue
        header = f"### 技能：{name}\n"
        budget = max_chars - used - len(header)
        if budget <= 60:
            meta_list.append(
                {"id": skill_id, "name": name, "included": False,
                 "truncated": True, "origin": origin}
            )
            continue
        truncated = len(instructions) > budget
        body = instructions[:budget].rstrip() + ("\n…（技能内容按字数预算截断）" if truncated else "")
        block = header + body
        parts.append(block)
        used += len(block)
        meta_list.append(
            {"id": skill_id, "name": name, "included": True,
             "truncated": truncated, "origin": origin}
        )
    return "\n\n".join(parts), meta_list
