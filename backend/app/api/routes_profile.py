"""申请人档案的增删改查。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_llm, get_user_store
from app.models.profile import ApplicantProfile, new_id, utcnow
from app.resume.parser import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    ResumeParseError,
    extract_text,
    merge_profile,
    parse_resume_text,
)
from app.storage.filestore import FileStore, StorageError

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("")
def list_profiles(store: FileStore = Depends(get_user_store)):
    return {"items": store.list_profiles()}


@router.post("", status_code=201)
def create_profile(profile: ApplicantProfile, store: FileStore = Depends(get_user_store)):
    data = profile.model_dump()
    # 前端新建空白档案时会带空的 id / created_at 占位，覆盖掉模型默认值；
    # 创建接口统一补齐，否则存储层的 ID 校验会直接拒绝（400 非法 ID）。
    # 非空 id 仍按原样交给存储层校验，避免放宽非法输入的约束。
    if not str(data.get("id") or "").strip():
        data["id"] = new_id()
    if not str(data.get("created_at") or "").strip():
        data["created_at"] = utcnow()
    try:
        return store.save_profile(data)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{profile_id}")
def read_profile(profile_id: str, store: FileStore = Depends(get_user_store)):
    data = store.get_profile(profile_id)
    if not data:
        raise HTTPException(status_code=404, detail="档案不存在")
    return data


@router.put("/{profile_id}")
def update_profile(profile_id: str, profile: ApplicantProfile, store: FileStore = Depends(get_user_store)):
    if not store.get_profile(profile_id):
        raise HTTPException(status_code=404, detail="档案不存在")
    data = profile.model_dump()
    data["id"] = profile_id
    return store.save_profile(data)


@router.delete("/{profile_id}")
def delete_profile(profile_id: str, store: FileStore = Depends(get_user_store)):
    if not store.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="档案不存在")
    return {"deleted": True}


@router.post("/{profile_id}/parse-resume")
async def parse_resume(
    profile_id: str,
    file: UploadFile = File(...),
    store: FileStore = Depends(get_user_store),
    llm=Depends(get_llm),
):
    """上传简历（PDF/DOCX/TXT/MD），解析后以「只覆盖出现的信息」语义合并进档案。

    文件仅在内存中抽取纯文本，不上传第三方、不落盘；解析结果直接覆盖写入档案，
    并返回变更清单供前端展示。LLM 未配置时由 get_llm 依赖返回 503。
    """
    data = store.get_profile(profile_id)
    if not data:
        raise HTTPException(status_code=404, detail="档案不存在")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，请上传不超过 10 MB 的简历。")

    filename = file.filename or ""
    if "." not in filename or "." + filename.rsplit(".", 1)[-1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。仅支持：{', '.join(sorted(ALLOWED_EXTENSIONS))}。",
        )

    try:
        resume_text = extract_text(content, filename)
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        patch = await parse_resume_text(resume_text, llm)
        merged, changes = merge_profile(data, patch)
    except Exception as exc:  # noqa: BLE001 - 归一化 LLM / 解析层错误为 502
        raise HTTPException(status_code=502, detail=f"简历解析失败：{exc}") from exc

    saved = store.save_profile(merged)
    return {"profile": saved, "changes": changes}
