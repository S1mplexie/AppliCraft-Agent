"""「我的大模型 API」：用户自带 Key 的查看、保存、清除与连通性测试。

所有接口都绑定当前登录用户，配置按 user_id 隔离；API Key 只进不出，
任何响应里最多出现末四位提示。生成时由 deps.get_llm 自动选用这里的配置。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, quota_info
from app.config import Settings, get_settings
from app.db.models import User
from app.llm.client import LLMClient
from app.llm.user_settings import (
    UserLLMError,
    delete_config,
    public_config,
    save_config,
    secret_config,
    validate_input,
)
from app.models.schemas import UserLLMConfigIn, UserLLMConfigOut, UserLLMTestIn, UserLLMTestOut

router = APIRouter(prefix="/me/llm", tags=["llm"])
logger = logging.getLogger(__name__)


def _status(db: Session, user: User, settings: Settings) -> UserLLMConfigOut:
    cfg = public_config(db, user.id)
    has_personal = bool(cfg["has_key"]) and settings.allow_personal_llm_keys
    # 管理员不受「强制自带 Key」限制，始终能用系统默认 Key。
    admin_can_use_system = bool(getattr(user, "is_admin", False))
    if has_personal:
        source = "personal"
        model = cfg["model"]
        base_url = cfg["base_url"]
    elif (not settings.require_personal_llm_key or admin_can_use_system) and settings.llm_configured:
        source = "system"
        model = settings.llm_model
        base_url = settings.llm_base_url
    else:
        source = "none"
        model = ""
        base_url = ""
    return UserLLMConfigOut(
        **cfg,
        effective_source=source,
        effective_model=model,
        effective_base_url=base_url,
        allow_personal_llm_keys=settings.allow_personal_llm_keys,
        require_personal_llm_key=settings.require_personal_llm_key,
        system_llm_configured=settings.llm_configured,
        **_billing_fields(db, user, settings),
    )


def _billing_fields(db: Session, user: User, settings: Settings) -> dict:
    """把当前账号的免费额度口径一并回显，设置页无需再发一次请求。"""
    q = quota_info(db, user, settings=settings)
    return {
        "is_admin": bool(getattr(user, "is_admin", False)),
        "unlimited": bool(q["unlimited"]),
        "system_key_daily_limit": int(q["system_key_limit"]),
        "system_key_remaining": int(q["system_key_remaining"]),
    }


def _editable(settings: Settings) -> None:
    if not settings.allow_personal_llm_keys:
        raise HTTPException(status_code=403, detail="管理员已关闭「用户自带 API Key」功能")


@router.get("", response_model=UserLLMConfigOut)
def get_my_llm(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _status(db, user, settings)


@router.put("", response_model=UserLLMConfigOut)
def put_my_llm(
    payload: UserLLMConfigIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _editable(settings)
    try:
        save_config(
            db,
            user.id,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
        )
    except UserLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _status(db, user, settings)


@router.delete("")
def delete_my_llm(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """清除个人 Key，之后回退到系统 Key（若管理员关闭了兜底则会要求重新配置）。"""
    _editable(settings)
    removed = delete_config(db, user.id)
    return {"deleted": removed, **_status(db, user, settings).model_dump()}


@router.post("/test", response_model=UserLLMTestOut)
async def test_my_llm(
    payload: UserLLMTestIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """发一个极小的请求验证 Key / 地址 / 模型名是否可用，不写入任何配置。

    使用短超时且不重试，避免无效 Key 把请求挂住；错误信息已脱敏，不含完整 Key。
    """
    _editable(settings)
    stored = None
    try:
        stored = secret_config(db, user.id)
    except UserLLMError as exc:
        if not payload.api_key.strip():
            return UserLLMTestOut(ok=False, message=str(exc))

    url = payload.base_url.strip() or (stored or {}).get("base_url", "") or settings.llm_base_url
    model = payload.model.strip() or (stored or {}).get("model", "") or settings.llm_model
    key = payload.api_key.strip() or (stored or {}).get("api_key", "")
    try:
        url, model, key = validate_input(base_url=url, model=model, api_key=key)
    except UserLLMError as exc:
        return UserLLMTestOut(ok=False, message=str(exc))
    if not key:
        return UserLLMTestOut(ok=False, message="请先填写 API Key 再测试")

    probe = settings.model_copy(
        update={
            "llm_api_key": key,
            "llm_base_url": url,
            "llm_model": model,
            "llm_timeout": 15.0,
            "llm_max_retries": 0,
        }
    )
    client: LLMClient | None = None
    try:
        client = LLMClient(probe, source="personal")
        await client.complete(
            task="connectivity_check",
            system="You are a connectivity probe. Reply with the single word OK.",
            user="ping",
            temperature=0.0,
            max_tokens=8,
        )
        return UserLLMTestOut(ok=True, message=f"连接成功，模型 {model} 可正常调用", model=model)
    except Exception as exc:  # noqa: BLE001 - 探测失败要给用户可读结论而非 500
        # 客户端构造/依赖层抛出的异常没经过 LLMClient 的脱敏，这里再兜一层。
        message = str(exc)
        if key and key in message:
            message = message.replace(key, f"***{key[-4:]}")
        return UserLLMTestOut(ok=False, message=f"连接失败：{message}", model=model)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover
                pass
