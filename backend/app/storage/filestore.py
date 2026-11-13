"""无第三方依赖的文件存储：每份档案一个 JSON，每篇文书一个目录。

data_dir 下的目录结构：
    profiles/{profile_id}.json
    projects/{project_id}.json
    documents/{doc_id}/meta.json
    documents/{doc_id}/current.md
    documents/{doc_id}/trace.json
    documents/{doc_id}/versions/v1.md, v2.md, ...
    exports/{doc_id}_{version}.docx
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models.schemas import DOC_TYPE_LABELS

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class StorageError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _count_words(text: str) -> int:
    # 兼顾中英文：拉丁单词按词计数，中日韩字符按字计数。
    latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return latin + cjk


def _strip_zh_blocks(text: str) -> str:
    """移除中英对照文档里的 `> 译：...` 翻译块，得到纯英文正文（用于字数统计与导出）。"""
    lines = (text or "").splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if re.match(r"^\s*>\s*译[:：]", line):
            skipping = True
            continue
        if skipping and re.match(r"^\s*>", line):
            continue
        skipping = False
        out.append(line)
    return "\n".join(out).strip() + "\n"


class FileStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.profiles_dir = self.root / "profiles"
        self.projects_dir = self.root / "projects"
        self.documents_dir = self.root / "documents"
        self.exports_dir = self.root / "exports"
        for directory in (self.profiles_dir, self.projects_dir, self.documents_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def for_user(self, user_id: str) -> "FileStore":
        """返回该用户专属的存储实例；目录隔离是归属校验之外的第二道防线。"""
        return FileStore(self.root / "users" / self.check_id(user_id))

    @staticmethod
    def check_id(value: str) -> str:
        if not _ID_RE.match(value or ""):
            raise StorageError(f"非法 ID: {value!r}")
        return value

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _read_json(path: Path, default: Any = None) -> Any:
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageError(f"数据文件损坏: {path}") from exc

    # ------------------------------------------------------------------ 档案
    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        pid = self.check_id(profile.get("id", ""))
        profile["id"] = pid
        profile["updated_at"] = _now()
        self._write_json(self.profiles_dir / f"{pid}.json", profile)
        return profile

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        return self._read_json(self.profiles_dir / f"{self.check_id(profile_id)}.json")

    def list_profiles(self) -> list[dict[str, Any]]:
        items = []
        for path in self.profiles_dir.glob("*.json"):
            data = self._read_json(path)
            if data:
                items.append(
                    {
                        "id": data.get("id", path.stem),
                        "label": data.get("label", "未命名档案"),
                        "updated_at": data.get("updated_at", ""),
                        "name": (data.get("basics") or {}).get("name_en", ""),
                    }
                )
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def delete_profile(self, profile_id: str) -> bool:
        path = self.profiles_dir / f"{self.check_id(profile_id)}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True

    # ----------------------------------------------------------------- 文书
    def _doc_dir(self, doc_id: str) -> Path:
        return self.documents_dir / self.check_id(doc_id)

    def save_document(
        self,
        *,
        profile_id: str,
        doc_type: str,
        markdown: str,
        trace: dict[str, Any],
        model: str,
        language: str,
        subject: str = "",
        bilingual: bool = False,
    ) -> dict[str, Any]:
        doc_id = uuid4().hex[:12]
        doc_dir = self._doc_dir(doc_id)
        now = _now()
        label = DOC_TYPE_LABELS.get(doc_type, doc_type)
        title = f"{label} · {subject or '通用'} · {now[:10]}"
        # 双语文档：字数只统计英文正文（剥离译块），避免中文翻译虚增词数。
        count_md = _strip_zh_blocks(markdown) if bilingual else markdown
        meta: dict[str, Any] = {
            "id": doc_id,
            "profile_id": self.check_id(profile_id),
            "doc_type": doc_type,
            "doc_type_label": label,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "model": model,
            "language": language,
            "bilingual": bilingual,
            "word_count": _count_words(count_md),
            "passed_verification": bool(trace.get("passed_verification", False)),
            "issue_count": len(trace.get("issues", []) or []),
        }
        self._write_text(doc_dir / "current.md", markdown)
        self._write_text(doc_dir / "versions" / "v1.md", markdown)
        self._write_json(doc_dir / "trace.json", trace)
        self._write_json(doc_dir / "meta.json", meta)
        return meta

    def update_document(
        self, doc_id: str, markdown: str, trace: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """保存新版本；trace 非空时一并更新轨迹与核验状态（按建议重生成用）。"""
        doc_dir = self._doc_dir(doc_id)
        meta = self._read_json(doc_dir / "meta.json")
        if not meta:
            return None
        version = int(meta.get("version", 1)) + 1
        meta["version"] = version
        meta["updated_at"] = _now()
        # 双语文档沿用 meta 里的 bilingual 标志，字数只统计英文正文。
        count_md = _strip_zh_blocks(markdown) if meta.get("bilingual") else markdown
        meta["word_count"] = _count_words(count_md)
        if trace is not None:
            self._write_json(doc_dir / "trace.json", trace)
            meta["passed_verification"] = bool(trace.get("passed_verification", False))
            meta["issue_count"] = len(trace.get("issues", []) or [])
        self._write_text(doc_dir / "current.md", markdown)
        self._write_text(doc_dir / "versions" / f"v{version}.md", markdown)
        self._write_json(doc_dir / "meta.json", meta)
        return meta

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        doc_dir = self._doc_dir(doc_id)
        meta = self._read_json(doc_dir / "meta.json")
        if not meta:
            return None
        current = doc_dir / "current.md"
        versions = []
        for path in sorted(doc_dir.glob("versions/v*.md"), key=lambda p: int(p.stem[1:])):
            versions.append({"name": path.stem, "markdown": path.read_text(encoding="utf-8")})
        return {
            "meta": meta,
            "markdown": current.read_text(encoding="utf-8") if current.is_file() else "",
            "trace": self._read_json(doc_dir / "trace.json", {}),
            "versions": versions,
        }

    def list_documents(
        self, profile_id: str | None = None, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        """文书列表：profile_id 按档案过滤；project_id 再按申请项目过滤（None=不过滤，
        "ungrouped"=只看未归组文书）。"""
        items = []
        for path in self.documents_dir.glob("*/meta.json"):
            meta = self._read_json(path)
            if not meta:
                continue
            if profile_id and meta.get("profile_id") != profile_id:
                continue
            if project_id == "ungrouped":
                if meta.get("project_id"):
                    continue
            elif project_id and meta.get("project_id") != project_id:
                continue
            items.append(meta)
        return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)

    def delete_document(self, doc_id: str) -> bool:
        doc_dir = self._doc_dir(doc_id)
        if not doc_dir.is_dir():
            return False
        shutil.rmtree(doc_dir)
        return True

    def document_markdown(self, doc_id: str, version: str | None = None) -> str | None:
        doc_dir = self._doc_dir(doc_id)
        if version:
            if not re.fullmatch(r"v\d+", version):
                raise StorageError("非法版本号")
            path = doc_dir / "versions" / f"{version}.md"
        else:
            path = doc_dir / "current.md"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def export_dir(self) -> Path:
        return self.exports_dir

    # ----------------------------------------------------------------- 申请项目
    def save_project(self, project: dict[str, Any]) -> dict[str, Any]:
        pid = self.check_id(project.get("id", ""))
        project["id"] = pid
        project["updated_at"] = _now()
        self._write_json(self.projects_dir / f"{pid}.json", project)
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._read_json(self.projects_dir / f"{self.check_id(project_id)}.json")

    def list_projects(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        """按更新时间倒序列出申请项目；profile_id 给定时只返回该档案的项目。

        一并统计各项目名下文书数，供项目卡片直接展示。
        """
        counts: dict[str, int] = {}
        for path in self.documents_dir.glob("*/meta.json"):
            meta = self._read_json(path)
            if meta and meta.get("project_id"):
                counts[meta["project_id"]] = counts.get(meta["project_id"], 0) + 1
        items = []
        for path in self.projects_dir.glob("*.json"):
            data = self._read_json(path)
            if not data:
                continue
            if profile_id and data.get("profile_id") != profile_id:
                continue
            item = dict(data)
            item["document_count"] = counts.get(item["id"], 0)
            items.append(item)
        return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)

    def delete_project(self, project_id: str) -> bool:
        path = self.projects_dir / f"{self.check_id(project_id)}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True

    def set_document_project(
        self, doc_id: str, project_id: str | None
    ) -> dict[str, Any] | None:
        """把文书归入项目（project_id 为 None 表示移出，回到未分组）。

        项目存在性与档案归属校验由路由层完成；这里只负责安全写入 meta.json
        并返回更新后的 meta，文书不存在返回 None。
        """
        doc_dir = self._doc_dir(doc_id)
        meta = self._read_json(doc_dir / "meta.json")
        if not meta:
            return None
        meta = dict(meta)
        if project_id is None:
            meta.pop("project_id", None)
        else:
            meta["project_id"] = self.check_id(project_id)
        self._write_json(doc_dir / "meta.json", meta)
        return meta

    # ----------------------------------------------------- 参考文档库（用户上传）
    def _references_dir(self) -> Path:
        directory = self.root / "references"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _reference_files_dir(self) -> Path:
        directory = self._references_dir() / "files"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def save_reference(
        self,
        *,
        filename: str,
        name: str,
        content: bytes,
        text: str,
        ext: str,
    ) -> dict[str, Any]:
        """保存一份用户上传的参考文档：元数据 + 提取文本 + 原始文件。

        返回元数据 dict（id/name/filename/size/char_count/uploaded_at）。
        原始文件保留以便用户下载核对，文本用于生成时作为补充上下文注入。
        """
        ref_id = uuid4().hex[:12]
        size = len(content)
        meta: dict[str, Any] = {
            "id": ref_id,
            "name": name or filename or "未命名参考文档",
            "filename": filename or "",
            "ext": ext or "",
            "size": size,
            "char_count": len(text),
            "uploaded_at": _now(),
        }
        self._write_json(self._references_dir() / f"{ref_id}.json", meta)
        # 原始文件：加 ref_id 前缀避免同名覆盖。
        if size:
            file_path = self._reference_files_dir() / f"{ref_id}{ext or ''}"
            file_path.write_bytes(content)
        # 提取文本单独存盘，生成时只读文本即可，不必每次重抽。
        self._write_text(self._references_dir() / f"{ref_id}.txt", text)
        return meta

    def list_references(self) -> list[dict[str, Any]]:
        items = []
        for path in self._references_dir().glob("*.json"):
            data = self._read_json(path)
            if data:
                # 早期上传的文档可能没有时间戳：用元数据文件的修改时间兜底，
                # 保证每份文档都能显示各自的导入时间。
                uploaded_at = data.get("uploaded_at", "")
                if not uploaded_at:
                    try:
                        uploaded_at = datetime.fromtimestamp(
                            path.stat().st_mtime, timezone.utc
                        ).isoformat(timespec="seconds")
                    except OSError:
                        uploaded_at = ""
                items.append(
                    {
                        "id": data.get("id", path.stem),
                        "name": data.get("name", "未命名参考文档"),
                        "filename": data.get("filename", ""),
                        "ext": data.get("ext", ""),
                        "size": data.get("size", 0),
                        "char_count": data.get("char_count", 0),
                        "uploaded_at": uploaded_at,
                    }
                )
        return sorted(items, key=lambda item: item.get("uploaded_at", ""), reverse=True)

    def get_reference(self, ref_id: str) -> dict[str, Any] | None:
        ref_id = self.check_id(ref_id)
        meta = self._read_json(self._references_dir() / f"{ref_id}.json")
        if not meta:
            return None
        meta = dict(meta)
        text_path = self._references_dir() / f"{ref_id}.txt"
        meta["text"] = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
        return meta

    def reference_file_path(self, ref_id: str) -> Path | None:
        """返回原始上传文件（若存在）；仅用于下载。"""
        ref_id = self.check_id(ref_id)
        meta = self._read_json(self._references_dir() / f"{ref_id}.json")
        if not meta:
            return None
        ext = meta.get("ext") or ""
        path = self._reference_files_dir() / f"{ref_id}{ext}"
        return path if path.is_file() else None

    def delete_reference(self, ref_id: str) -> bool:
        ref_id = self.check_id(ref_id)
        meta_path = self._references_dir() / f"{ref_id}.json"
        text_path = self._references_dir() / f"{ref_id}.txt"
        file_path = self.reference_file_path(ref_id)
        if not meta_path.is_file():
            return False
        meta_path.unlink()
        if text_path.is_file():
            text_path.unlink()
        if file_path and file_path.is_file():
            file_path.unlink()
        return True

    def update_reference(self, ref_id: str, *, name: str) -> dict[str, Any] | None:
        """导入后补充/修改文档标题；返回列表视图元数据，不存在返回 None。

        只改元数据，不动已抽取的文本与原始文件，也不重置 uploaded_at。
        名称留空时回退到原始文件名，保证列表始终有可读标题。
        """
        ref_id = self.check_id(ref_id)
        path = self._references_dir() / f"{ref_id}.json"
        meta = self._read_json(path)
        if not meta:
            return None
        meta = dict(meta)
        meta["name"] = (name or "").strip() or meta.get("filename") or "未命名参考文档"
        self._write_json(path, meta)
        return next((x for x in self.list_references() if x["id"] == ref_id), None)

    # ----------------------------------------------------- Skill 市场（用户导入）
    def _skills_dir(self) -> Path:
        directory = self.root / "skills"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def save_skill(
        self,
        *,
        name: str,
        name_en: str = "",
        description: str = "",
        content: str,
        examples: str = "",
        filename: str = "",
        category: str = "我导入的",
        tags: list[str] | None = None,
        doc_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """保存一份用户导入的技能：元数据 + 正文 + 可选示例，均在用户隔离目录。"""
        skill_id = uuid4().hex[:12]
        meta: dict[str, Any] = {
            "id": "user:" + skill_id,
            "origin": "user",
            "name": name or filename or "未命名技能",
            "name_en": name_en or "",
            "description": description or "",
            "category": category,
            "doc_types": doc_types or [],
            "tags": tags or [],
            "filename": filename or "",
            "char_count": len(content),
            "has_examples": bool(examples),
            "imported_at": _now(),
        }
        self._write_json(self._skills_dir() / f"{skill_id}.json", meta)
        self._write_text(self._skills_dir() / f"{skill_id}.md", content)
        if examples:
            self._write_text(self._skills_dir() / f"{skill_id}.examples.md", examples)
        return meta

    def list_skills(self) -> list[dict[str, Any]]:
        items = []
        for path in self._skills_dir().glob("*.json"):
            data = self._read_json(path)
            if not data:
                continue
            imported_at = data.get("imported_at", "")
            if not imported_at:
                try:
                    imported_at = datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc
                    ).isoformat(timespec="seconds")
                except OSError:
                    imported_at = ""
            item = dict(data)
            item["imported_at"] = imported_at
            items.append(item)
        return sorted(items, key=lambda item: item.get("imported_at", ""), reverse=True)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        skill_id = self.check_id(skill_id)
        meta = self._read_json(self._skills_dir() / f"{skill_id}.json")
        if not meta:
            return None
        meta = dict(meta)
        text_path = self._skills_dir() / f"{skill_id}.md"
        example_path = self._skills_dir() / f"{skill_id}.examples.md"
        meta["content"] = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
        meta["examples"] = (
            example_path.read_text(encoding="utf-8") if example_path.is_file() else ""
        )
        return meta

    def update_skill(
        self, skill_id: str, *, name: str, description: str
    ) -> dict[str, Any] | None:
        """导入后补充/修改技能名称与简介；返回列表视图元数据，不存在返回 None。

        只改元数据，不动方法论正文、示例、导入时间；名称留空回退到文件名。
        """
        skill_id = self.check_id(skill_id)
        path = self._skills_dir() / f"{skill_id}.json"
        meta = self._read_json(path)
        if not meta:
            return None
        meta = dict(meta)
        meta["name"] = (name or "").strip() or meta.get("filename") or "未命名技能"
        meta["description"] = (description or "").strip()
        self._write_json(path, meta)
        return next(
            (x for x in self.list_skills() if x["id"] == "user:" + skill_id), None
        )

    def delete_skill(self, skill_id: str) -> bool:
        skill_id = self.check_id(skill_id)
        meta_path = self._skills_dir() / f"{skill_id}.json"
        if not meta_path.is_file():
            return False
        meta_path.unlink()
        for path in (
            self._skills_dir() / f"{skill_id}.md",
            self._skills_dir() / f"{skill_id}.examples.md",
        ):
            if path.is_file():
                path.unlink()
        return True
