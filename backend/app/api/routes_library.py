"""参考文档库接口：用户上传 / 管理自己的项目参考材料，并查看系统自带的港新项目信息。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_current_user, get_user_store
from app.config import Settings, get_settings
from app.db.models import User
from app.library.service import LibraryError, extract_reference_text, list_system_programs
from app.models.schemas import ReferenceDocUpdate
from app.resume.parser import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES
from app.storage.filestore import FileStore, StorageError

router = APIRouter(prefix="/library", tags=["library"])
logger = logging.getLogger(__name__)


@router.get("/references")
def list_references(store: FileStore = Depends(get_user_store)):
    """列出当前用户上传的全部参考文档（不含正文文本，仅供列表展示）。"""
    return {"items": store.list_references()}


@router.post("/references")
async def upload_reference(
    file: UploadFile,
    name: str | None = Form(None),
    store: FileStore = Depends(get_user_store),
):
    """上传一份参考文档（PDF / DOCX / TXT / MD），服务端仅抽取纯文本用于生成上下文。

    隐私：原始文件仅保存在用户隔离目录内供本人下载核对，绝不外传或上传第三方。
    """
    filename = file.filename or "untitled"
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式：{ext or '未知'}。仅支持 PDF / DOCX / TXT / MD。",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{len(content) // 1024} KB），上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB。",
        )
    try:
        text = extract_reference_text(content, filename)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 解析失败给用户可懂提示
        raise HTTPException(status_code=400, detail=f"参考文档解析失败：{exc}") from exc

    meta = store.save_reference(
        filename=filename,
        name=(name or "").strip(),
        content=content,
        text=text,
        ext=ext,
    )
    return meta


@router.get("/references/{ref_id}/download")
def download_reference(ref_id: str, store: FileStore = Depends(get_user_store)):
    """下载用户上传的原始文件（用于核对）。"""
    path = store.reference_file_path(ref_id)
    if not path:
        raise HTTPException(status_code=404, detail="参考文档不存在")
    meta = store.get_reference(ref_id) or {}
    download_name = meta.get("filename") or f"{ref_id}{meta.get('ext') or ''}"
    return FileResponse(path, filename=download_name)


@router.patch("/references/{ref_id}")
def rename_reference(
    ref_id: str,
    payload: ReferenceDocUpdate,
    store: FileStore = Depends(get_user_store),
):
    """导入成功后由弹窗补充文档标题（也支持事后重新编辑）。

    不触碰上传文件与已抽取文本，也不改变 uploaded_at 导入时间。
    """
    try:
        meta = store.update_reference(ref_id, name=payload.name)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not meta:
        raise HTTPException(status_code=404, detail="参考文档不存在")
    return meta


@router.delete("/references/{ref_id}")
def delete_reference(ref_id: str, store: FileStore = Depends(get_user_store)):
    if not store.delete_reference(ref_id):
        raise HTTPException(status_code=404, detail="参考文档不存在")
    return {"deleted": True}


@router.get("/system-programs")
def system_programs(
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """系统自带的港新项目官方信息（来自知识库），只读、全站共享，供用户查看与核对。"""
    try:
        return {"items": list_system_programs(settings)}
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
