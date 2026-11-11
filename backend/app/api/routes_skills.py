"""Skill 市场接口：查看内置技能、导入自己的技能包、生成时勾选使用。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile

from app.api.deps import get_user_store
from app.models.schemas import SkillUpdate
from app.skills.service import (
    MAX_USER_SKILLS,
    SkillError,
    builtin_skills,
    get_skill_detail,
    parse_skill_upload,
)
from app.storage.filestore import FileStore, StorageError

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
def list_skills(store: FileStore = Depends(get_user_store)):
    """系统内置技能 + 当前用户导入的技能；均只返回列表字段，不含正文。"""
    return {"items": builtin_skills() + store.list_skills()}


@router.post("", status_code=201)
async def import_skill(
    file: UploadFile,
    name: str | None = Form(None),
    description: str | None = Form(None),
    store: FileStore = Depends(get_user_store),
):
    """导入 .md / .txt 单个技能，或含多个 SKILL.md 的 .zip 技能包。"""
    content = await file.read()
    try:
        parsed = parse_skill_upload(
            file.filename or "",
            content,
            name=(name or "").strip(),
            description=(description or "").strip(),
        )
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(store.list_skills()) + len(parsed) > MAX_USER_SKILLS:
        raise HTTPException(
            status_code=400,
            detail=f"每个账号最多保存 {MAX_USER_SKILLS} 个导入技能，请先删除部分再导入。",
        )
    saved = [
        store.save_skill(
            name=item["name"],
            name_en=item.get("name_en", ""),
            description=item.get("description", ""),
            content=item["content"],
            examples=item.get("examples", ""),
            filename=item.get("filename", ""),
            category=item.get("category", "我导入的"),
            tags=item.get("tags", []),
            doc_types=item.get("doc_types", []),
        )
        for item in parsed
    ]
    return {"items": saved, "imported": len(saved)}


@router.get("/detail")
def skill_detail(
    skill_id: str = Query(..., description="builtin:xxx 或 user:xxx"),
    store: FileStore = Depends(get_user_store),
):
    """查看技能完整方法论与示例（只读，不参与生成）。"""
    try:
        detail = get_skill_detail(store, skill_id)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not detail:
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
    return detail


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, store: FileStore = Depends(get_user_store)):
    """仅可删除自己导入的技能；内置技能全站只读。"""
    if not skill_id.startswith("user:"):
        raise HTTPException(status_code=400, detail="系统内置技能不可删除")
    try:
        deleted = store.delete_skill(skill_id[5:])
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"deleted": True}


@router.patch("/{skill_id}")
def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    store: FileStore = Depends(get_user_store),
):
    """导入成功后由弹窗补充名称 / 简介（也支持事后重新编辑）。

    仅可修改自己导入的技能；方法论正文、示例与 imported_at 不变。
    """
    if not skill_id.startswith("user:"):
        raise HTTPException(status_code=400, detail="系统内置技能不可修改")
    try:
        meta = store.update_skill(
            skill_id[5:], name=payload.name, description=payload.description
        )
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not meta:
        raise HTTPException(status_code=404, detail="技能不存在")
    return meta
