"""参考文档库服务：用户上传材料的文本抽取与上下文装配，以及系统项目信息解析。

设计边界
--------
- 用户上传的参考文档是其本人提供的补充素材（项目说明、研究陈述、课程大纲等），
  只在生成时作为「补充背景」注入，使用守则明确：不得与申请人事实清单冲突、
  不得把第三方信息当成申请人自身成就、清单外的事实一律 [TO CONFIRM] 占位。
- 系统项目信息来自知识库 chunks.jsonl，按 program_id 聚合，只读、全局共享，
  用于让用户直观看到系统已覆盖哪些港新项目（也便于核对官方资料）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from app.resume.parser import MAX_UPLOAD_BYTES, ALLOWED_EXTENSIONS, extract_text  # noqa: F401 复用约束常量
from app.storage.filestore import FileStore

# 注入提示词的参考文档文本预算：用户上传可能很多，超出部分截断，避免撑爆上下文。
REFERENCE_MAX_CHARS = 4000


class LibraryError(ValueError):
    """参考文档库的可预期用户级错误（上传超限 / 格式不支持等）。"""


def extract_reference_text(content: bytes, filename: str) -> str:
    """抽取上传参考文档的纯文本，直接复用简历解析的文本抽取能力。"""
    return extract_text(content, filename)


def build_reference_context(
    store: FileStore,
    reference_doc_ids: list[str] | None,
    max_chars: int = REFERENCE_MAX_CHARS,
) -> tuple[str, list[dict[str, Any]]]:
    """按勾选的文档 id 装配生成用上下文（提示词段落）与来源清单。

    缺失 / 已删除的文档安全跳过，不报错；没有任何有效文档时返回 ("", [])。
    返回 (context_block, meta_list)，context_block 已是可直接拼进提示词的完整段落，
    由提示词层负责生成，这里只做预算截断与来源收集。
    """
    ids = [str(x).strip() for x in (reference_doc_ids or []) if str(x).strip()]
    if not ids:
        return "", []

    meta_list: list[dict[str, Any]] = []
    parts: list[str] = []
    used = 0
    for ref_id in ids:
        ref = store.get_reference(ref_id)
        if not ref:
            # 已删除 / 不存在的文档：列入来源但不注入，对用户透明。
            meta_list.append(
                {
                    "id": ref_id,
                    "name": "",
                    "filename": "",
                    "included": False,
                    "missing": True,
                }
            )
            continue
        text = (ref.get("text") or "").strip()
        if not text:
            meta_list.append(
                {
                    "id": ref_id,
                    "name": ref.get("name", ""),
                    "filename": ref.get("filename", ""),
                    "included": False,
                }
            )
            continue
        if used and used + len(text) > max_chars:
            # 预算已满：仍把这份文档列入来源（用户勾选了），但不再注入正文。
            meta_list.append(
                {
                    "id": ref_id,
                    "name": ref.get("name", ""),
                    "filename": ref.get("filename", ""),
                    "included": False,
                }
            )
            continue
        if not used and len(text) > max_chars:
            # 唯一超长文档：截断到预算内注入，总比完全没有上下文好。
            text = text[:max_chars]
        parts.append(f"### {ref.get('name', ref.get('filename', ref_id))}\n{text}")
        used += len(text)
        meta_list.append(
            {
                "id": ref_id,
                "name": ref.get("name", ""),
                "filename": ref.get("filename", ""),
                "included": True,
            }
        )

    if not parts:
        return "", meta_list
    return "\n\n".join(parts), meta_list


def list_system_programs(settings: Settings) -> list[dict[str, Any]]:
    """聚合知识库 chunks.jsonl，按 program_id 返回系统已覆盖的港新项目清单。

    每个项目包含学校、项目名（中英）、学院、地区、入学批次、官方链接与已覆盖资料板块，
    供前端「参考文档库」页展示系统自带的官方项目信息，也便于用户核对。
    """
    path = settings.knowledge_dir / "chunks.jsonl"
    programs: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = __import__("json").loads(line)
            except Exception:  # noqa: BLE001 - 单行损坏不影响整体
                continue
            meta = obj.get("meta") or {}
            pid = meta.get("program_id")
            if not pid:
                continue
            entry = programs.setdefault(
                pid,
                {
                    "program_id": pid,
                    "school_id": meta.get("school_id", ""),
                    "school_name_zh": meta.get("school_name_zh", ""),
                    "program_name_en": meta.get("program_name_en", ""),
                    "program_name_zh": meta.get("program_name_zh", ""),
                    "faculty": meta.get("faculty", ""),
                    "region": meta.get("region", ""),
                    "intake": meta.get("intake", ""),
                    "official_urls": list(meta.get("official_urls") or []),
                    "fields": [],
                },
            )
            field_label = meta.get("field_label") or meta.get("field")
            if field_label and field_label not in entry["fields"]:
                entry["fields"].append(field_label)
            for url in meta.get("official_urls") or []:
                if url and url not in entry["official_urls"]:
                    entry["official_urls"].append(url)

    return sorted(
        programs.values(),
        key=lambda p: (p.get("school_name_zh", ""), p.get("program_name_en", "")),
    )
