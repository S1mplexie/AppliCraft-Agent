"""申请项目：以项目为中心组织文书。

每个项目挂在档案之下，两种来源：
- imported：从知识库（system-programs，39 个港新项目官方信息）导入，快照官方字段；
- custom：用户自定义新建（学校/专业/学位/入学季/备注）。

文书归组写入文书 meta 的 project_id 字段；未归组文书标为「未分组」，
删除项目时名下文书自动回到未分组，不删除文书本身。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session  # noqa: F401 - 保持与既有路由一致的导入风格

from app.api.deps import get_user_store
from app.config import Settings, get_settings
from app.library.service import LibraryError, list_system_programs
from app.models.profile import new_id, utcnow
from app.models.schemas import (
    ApplicationProjectCreate,
    ApplicationProjectPatch,
    DocumentAssign,
)
from app.storage.filestore import FileStore, StorageError

router = APIRouter(prefix="/profiles/{profile_id}/projects", tags=["projects"])


def _require_profile(store: FileStore, profile_id: str) -> dict:
    data = store.get_profile(profile_id)
    if not data:
        raise HTTPException(status_code=404, detail="档案不存在")
    return data


def _require_project(store: FileStore, profile_id: str, project_id: str) -> dict:
    project = store.get_project(project_id)
    if not project or project.get("profile_id") != profile_id:
        raise HTTPException(status_code=404, detail="申请项目不存在")
    return project


@router.get("")
def list_projects(profile_id: str, store: FileStore = Depends(get_user_store)):
    _require_profile(store, profile_id)
    return {"items": store.list_projects(profile_id)}


@router.post("", status_code=201)
def create_project(
    profile_id: str,
    payload: ApplicationProjectCreate,
    store: FileStore = Depends(get_user_store),
    settings: Settings = Depends(get_settings),
):
    _require_profile(store, profile_id)
    now = utcnow()
    project: dict = {
        "id": new_id(),
        "profile_id": profile_id,
        "name": payload.name.strip(),
        "source": "custom",
        "system_program_id": "",
        "university": payload.university.strip(),
        "program": payload.program.strip(),
        "program_name_en": "",
        "faculty": "",
        "degree_type": payload.degree_type.strip(),
        "region": payload.region.strip(),
        "intake": payload.intake.strip(),
        "notes": payload.notes.strip(),
        "official_urls": [],
        "deadline": "",
        "materials": {},
        "created_at": now,
        "updated_at": now,
    }
    if payload.system_program_id:
        # 从知识库导入：快照官方字段，后续知识库更新不影响已导入的项目。
        try:
            programs = list_system_programs(settings)
        except LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        program = next(
            (p for p in programs if p.get("program_id") == payload.system_program_id),
            None,
        )
        if not program:
            raise HTTPException(status_code=404, detail="知识库中不存在该项目")
        project["source"] = "imported"
        project["system_program_id"] = program.get("program_id", "")
        project["university"] = program.get("school_name_zh", "")
        project["program"] = program.get("program_name_zh", "")
        project["program_name_en"] = program.get("program_name_en", "")
        project["faculty"] = program.get("faculty", "")
        project["region"] = program.get("region", "")
        project["intake"] = program.get("intake", "")
        project["official_urls"] = program.get("official_urls", [])
    try:
        return store.save_project(project)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{project_id}")
def update_project(
    profile_id: str,
    project_id: str,
    payload: ApplicationProjectPatch,
    store: FileStore = Depends(get_user_store),
):
    _require_project(store, profile_id, project_id)
    project = store.get_project(project_id) or {}
    if payload.name.strip():
        project["name"] = payload.name.strip()
    if payload.notes.strip():
        project["notes"] = payload.notes.strip()
    # 截止日期：null=不修改；""=清空；其余按原样保存（前端统一用 YYYY-MM-DD）。
    if payload.deadline is not None:
        project["deadline"] = payload.deadline.strip()
    # 材料清单：与已有值合并（只覆盖本次提交的键），保留其它键的勾选状态。
    if payload.materials is not None:
        existing = dict(project.get("materials") or {})
        existing.update(payload.materials)
        project["materials"] = existing
    try:
        return store.save_project(project)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{project_id}")
def delete_project(
    profile_id: str, project_id: str, store: FileStore = Depends(get_user_store)
):
    _require_project(store, profile_id, project_id)
    # 名下文书回到未分组：先清 meta 的 project_id 再删项目文件。
    for meta in store.list_documents(profile_id):
        if meta.get("project_id") == project_id:
            store.set_document_project(meta["id"], None)
    if not store.delete_project(project_id):
        raise HTTPException(status_code=404, detail="申请项目不存在")
    return {"deleted": True}


@router.post("/{project_id}/assign")
def assign_document(
    profile_id: str,
    project_id: str,
    payload: DocumentAssign,
    store: FileStore = Depends(get_user_store),
):
    """把一篇文书归入项目；文书必须属于当前档案。"""
    _require_project(store, profile_id, project_id)
    doc = store.get_document(payload.doc_id)
    if not doc or doc["meta"].get("profile_id") != profile_id:
        raise HTTPException(status_code=404, detail="文书不存在")
    try:
        meta = store.set_document_project(payload.doc_id, project_id)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not meta:
        raise HTTPException(status_code=404, detail="文书不存在")
    return meta


@router.post("/{project_id}/unassign")
def unassign_document(
    profile_id: str,
    project_id: str,
    payload: DocumentAssign,
    store: FileStore = Depends(get_user_store),
):
    """把文书移出项目，回到「未分组」。"""
    _require_project(store, profile_id, project_id)
    doc = store.get_document(payload.doc_id)
    if not doc or doc["meta"].get("profile_id") != profile_id:
        raise HTTPException(status_code=404, detail="文书不存在")
    try:
        meta = store.set_document_project(payload.doc_id, None)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not meta:
        raise HTTPException(status_code=404, detail="文书不存在")
    return meta