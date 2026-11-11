"""用户自带大模型 Key（BYOK）的存取、加密与生效配置解析。

安全边界：
- API Key 以 Fernet 密文落库，明文只在单次生成请求的内存里存在；
- 加密主密钥保存在 data/.byok_key（首次启动随机生成、权限 600、随数据卷持久化），
  不进镜像、不进仓库、不与系统 Key 耦合（改系统 Key 不会让已存的用户 Key 失效）；
- 任何对外接口都不返回完整 Key，只返回末尾四位提示。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import UserLLMSetting

MAX_KEY_LEN = 300
MAX_URL_LEN = 500
MAX_MODEL_LEN = 120
_MODEL_RE = re.compile(r"^[\w.\-/:]+$", re.ASCII)


class UserLLMError(ValueError):
    """配置校验或加解密失败，可直接转成 400 返回给用户。"""


@lru_cache
def _fernet() -> Fernet:
    """取得（必要时创建）进程级 Fernet 实例。

    用 O_EXCL 独占创建避免多进程同时写密钥文件；文件随 data 卷持久化，
    容器重建不会丢失。若该文件被删除或替换，旧密文将无法解密，
    此时会提示用户重新填写 Key，而不是静默回退到系统 Key。
    """
    from app.config import get_settings

    path = get_settings().data_dir / ".byok_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        raw = Fernet.generate_key()
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
        except FileExistsError:
            pass  # 另一个进程刚创建好，下面直接读取即可
    raw = path.read_bytes().strip()
    if not raw:
        raise UserLLMError("加密密钥文件为空，请联系管理员检查 data/.byok_key")
    return Fernet(raw)


def _encrypt(key: str) -> str:
    return _fernet().encrypt(key.encode("utf-8")).decode("ascii")


def _decrypt(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise UserLLMError(
            "已保存的 API Key 无法解密（服务端的加密密钥文件可能已被更换）。请重新填写一次 API Key。"
        ) from exc


def mask_key(key: str) -> str:
    """只暴露末四位，用于设置页回显与状态展示，绝不返回完整明文。"""
    value = (key or "").strip()
    return f"***{value[-4:]}" if len(value) > 4 else "***"


def validate_input(*, base_url: str, model: str, api_key: str) -> tuple[str, str, str]:
    """规范化并校验用户输入；返回 (base_url, model, api_key)。"""
    url = (base_url or "").strip().rstrip("/")
    name = (model or "").strip()
    key = (api_key or "").strip()
    if not url.startswith(("https://", "http://")):
        raise UserLLMError("接口地址必须以 https:// 或 http:// 开头")
    if len(url) > MAX_URL_LEN:
        raise UserLLMError(f"接口地址过长（上限 {MAX_URL_LEN} 字符）")
    if " " in url or "\n" in url:
        raise UserLLMError("接口地址不能包含空格或换行")
    if not name or len(name) > MAX_MODEL_LEN or not _MODEL_RE.match(name):
        raise UserLLMError(f"模型名称不合法（仅允许字母数字与 . - _ / : ，上限 {MAX_MODEL_LEN} 字符）")
    if len(key) > MAX_KEY_LEN or "\n" in key:
        raise UserLLMError(f"API Key 格式不合法（上限 {MAX_KEY_LEN} 字符且不能含换行）")
    return url, name, key


def get_row(db: Session, user_id: str) -> UserLLMSetting | None:
    return db.get(UserLLMSetting, user_id)


def public_config(db: Session, user_id: str) -> dict[str, Any]:
    """脱敏后的个人配置，可直接返回给前端。"""
    row = get_row(db, user_id)
    if not row or not row.api_key_cipher:
        return {"has_key": False, "api_key_hint": "", "base_url": "", "model": "", "updated_at": ""}
    return {
        "has_key": True,
        "api_key_hint": row.api_key_hint or "***",
        "base_url": row.base_url,
        "model": row.model,
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def save_config(db: Session, user_id: str, *, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    """新建或更新个人配置。api_key 传空表示沿用已保存的 Key（便于只改模型/地址）。"""
    url, name, key = validate_input(base_url=base_url, model=model, api_key=api_key)
    row = get_row(db, user_id)
    if not key:
        if not row or not row.api_key_cipher:
            raise UserLLMError("请先填写 API Key")
        key = _decrypt(row.api_key_cipher)
    cipher = _encrypt(key)
    hint = mask_key(key)
    if row is None:
        row = UserLLMSetting(user_id=user_id)
        db.add(row)
    row.base_url = url
    row.model = name
    row.api_key_cipher = cipher
    row.api_key_hint = hint
    db.commit()
    return public_config(db, user_id)


def delete_config(db: Session, user_id: str) -> bool:
    row = get_row(db, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def secret_config(db: Session, user_id: str) -> dict[str, str] | None:
    """读取解密后的完整配置，仅供服务端构造 LLM 客户端使用。"""
    row = get_row(db, user_id)
    if not row or not row.api_key_cipher:
        return None
    return {
        "api_key": _decrypt(row.api_key_cipher),
        "base_url": row.base_url,
        "model": row.model,
    }


@dataclass(frozen=True)
class EffectiveLLM:
    """本次请求真正生效的模型配置。source 决定是否计入系统配额、错误如何提示。"""

    settings: Settings
    source: Literal["personal", "system"]


def resolve_effective_llm(settings: Settings, personal: dict[str, str] | None) -> EffectiveLLM:
    """个人 Key 优先，系统 Key 兜底；强制 BYOK 时拒绝回退。"""
    if personal and personal.get("api_key") and settings.allow_personal_llm_keys:
        effective = settings.model_copy(
            update={
                "llm_api_key": personal["api_key"],
                "llm_base_url": personal.get("base_url") or settings.llm_base_url,
                "llm_model": personal.get("model") or settings.llm_model,
            }
        )
        return EffectiveLLM(effective, "personal")
    if settings.require_personal_llm_key:
        raise UserLLMError(
            "管理员已要求每位用户使用自己的 API Key。请在「设置 → 我的大模型 API」中配置后重试。"
        )
    if not settings.llm_configured:
        from app.llm.client import LLMNotConfiguredError

        raise LLMNotConfiguredError(
            "尚未配置可用的大模型 API Key。请在「设置 → 我的大模型 API」填入自己的 Key，"
            "或由管理员在 .env 中设置 APPLICRAFT_LLM_API_KEY。"
        )
    return EffectiveLLM(settings, "system")
