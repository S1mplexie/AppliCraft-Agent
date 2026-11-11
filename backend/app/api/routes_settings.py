"""本地部署版专属：管理「我的大模型 API」配置（单用户、落盘 data/local_llm.json）。

网页版（多租户）走 routes_llm 的 BYOK（数据库 + Fernet 加密）；本地版没有数据库，
因此用一份明文 JSON 保存用户自己的 Key。本路由只在 standalone 模式下被挂载。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.llm.local_config import (
    LocalLLMConfig,
    load_local_llm_config,
    mask_key,
    save_local_llm_config,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class LocalLLMPayload(BaseModel):
    # 三个字段都允许为空：空 base_url / model 表示沿用已保存或 .env 默认值；
    # 空 api_key 表示「继续用已保存的 Key，只改地址或模型名」。
    base_url: str = ""
    api_key: str = Field(default="", max_length=2000)
    model: str = ""


def _effective(settings: Settings, cfg: LocalLLMConfig) -> Settings:
    return settings.model_copy(
        update={
            "llm_api_key": cfg.api_key,
            "llm_base_url": cfg.base_url or settings.llm_base_url,
            "llm_model": cfg.model or settings.llm_model,
        }
    )


@router.get("/llm")
def get_llm_config(settings: Settings = Depends(get_settings)):
    cfg = load_local_llm_config()
    return {
        "base_url": cfg.base_url or settings.llm_base_url,
        "api_key_hint": mask_key(cfg.api_key),
        "model": cfg.model or settings.llm_model,
        "configured": bool(cfg.api_key.strip()),
    }


@router.post("/llm/test")
async def test_llm(payload: LocalLLMPayload, settings: Settings = Depends(get_settings)):
    """用给定配置做一次极小的补全，确认地址 / Key / 模型可用。"""
    cfg = load_local_llm_config()
    api_key = payload.api_key if payload.api_key.strip() else cfg.api_key
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="请先填写 API Key 再做连接测试")
    candidate = LocalLLMConfig(
        base_url=payload.base_url or cfg.base_url,
        api_key=api_key,
        model=payload.model or cfg.model,
    )
    effective = _effective(settings, candidate)
    try:
        client = LLMClient(effective, source="personal")
        await client.complete(
            task="ping", system="用最简短的话回复 ok", user="测试", max_tokens=8
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 连接/鉴权错误直接回传文案
        return {"ok": False, "message": f"连接失败：{exc}", "model": effective.llm_model}
    return {"ok": True, "message": f"连接成功（模型 {effective.llm_model}）", "model": effective.llm_model}


@router.put("/llm")
def save_llm(payload: LocalLLMPayload, settings: Settings = Depends(get_settings)):
    """保存大模型配置；会先实例化客户端校验可用性（与生成时同一套校验）。"""
    cfg = load_local_llm_config()
    api_key = payload.api_key if payload.api_key.strip() else cfg.api_key
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Key")
    candidate = LocalLLMConfig(
        base_url=payload.base_url or cfg.base_url,
        api_key=api_key,
        model=payload.model or cfg.model,
    )
    effective = _effective(settings, candidate)
    try:
        LLMClient(effective, source="personal")
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_local_llm_config(candidate)
    return {
        "base_url": candidate.base_url or settings.llm_base_url,
        "api_key_hint": mask_key(candidate.api_key),
        "model": candidate.model or settings.llm_model,
        "configured": True,
    }
