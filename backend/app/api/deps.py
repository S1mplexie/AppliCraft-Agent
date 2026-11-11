"""FastAPI 公共依赖：当前用户、按用户隔离的存储、配额与模型客户端。"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.security import COOKIE_NAME, hash_token
from app.config import Settings, get_settings
from app.db.models import GenerationLog, SessionToken, User, UserLLMSetting, naive_utc
from app.db.session import get_db
from app.llm.client import LLMClient, LLMNotConfiguredError
from app.llm.user_settings import (
    UserLLMError,
    resolve_effective_llm,
    secret_config,
)
from app.storage.filestore import FileStore

logger = logging.getLogger(__name__)


class _LocalUser:
    """本地部署版（standalone）的虚拟单用户：不需要登录，也不落库。

    仅提供生成链路需要的几个属性；routes 里用到 user 的地方只用 user.id。
    """

    id = "local"
    is_admin = False
    is_active = True
    daily_quota = 10_000_000
    email = "local@local"
    display_name = "本地用户"
    created_at = ""


@lru_cache
def _root_store() -> FileStore:
    return FileStore(get_settings().data_dir)


class _LLMRegistry:
    """按 (用户, 配置指纹) 复用 LLM 客户端，避免每次请求都新建 HTTP 连接池。

    更新个人配置会立刻改变指纹，旧客户端被淘汰并在服务关闭时统一释放；
    因此不会出现「改了 Key 却还在用旧 Key」的缓存陈旧问题。
    """

    def __init__(self, maxsize: int = 128):
        self._items: OrderedDict[tuple[str, str], LLMClient] = OrderedDict()
        self._evicted: list[LLMClient] = []
        self._lock = threading.Lock()
        self.maxsize = maxsize

    def get(self, key: tuple[str, str], factory: Callable[[], LLMClient]) -> LLMClient:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            client = factory()
            self._items[key] = client
            while len(self._items) > self.maxsize:
                _, old = self._items.popitem(last=False)
                self._evicted.append(old)
            return client

    async def aclose_all(self) -> None:
        with self._lock:
            clients = list(self._items.values()) + self._evicted
            self._items.clear()
            self._evicted.clear()
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - 关停阶段尽力而为
                pass


_llm_registry = _LLMRegistry()


@lru_cache
def _system_llm() -> LLMClient:
    """系统 .env 里的 Key 全站共用一个客户端。"""
    return LLMClient(get_settings(), source="system")


async def close_llm_clients() -> None:
    """应用关停时释放所有模型客户端的连接池。"""
    await _llm_registry.aclose_all()
    try:
        await _system_llm().aclose()
    except Exception:  # pragma: no cover - 可能从未创建过
        pass


def _session_token(request: Request) -> str | None:
    """网页版从 Cookie 取会话，小程序从 Authorization: Bearer 取；两者共用同一张会话表。"""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if get_settings().standalone:
        # 本地版免登录：返回固定的虚拟单用户，所有档案/文书落在同一本地目录。
        return _LocalUser()  # type: ignore[return-value]
    token = _session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    session = db.execute(
        select(SessionToken).where(
            SessionToken.token_hash == hash_token(token),
            SessionToken.revoked.is_(False),
            SessionToken.expires_at > naive_utc(),
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


def get_user_store(user: User = Depends(get_current_user)) -> FileStore:
    """每个用户一个独立目录，物理隔离档案与文书正文。

    本地版（standalone）下返回固定的 local 目录，不依赖登录用户。
    """
    if get_settings().standalone:
        return _root_store().for_user("local")
    return _root_store().for_user(user.id)


def _day_start() -> datetime:
    return naive_utc().replace(hour=0, minute=0, second=0, microsecond=0)


def quota_used(db: Session, user_id: str) -> int:
    """今日总生成次数（旧有的总量护栏，含所有来源）。"""
    return int(
        db.scalar(
            select(func.count())
            .select_from(GenerationLog)
            .where(GenerationLog.user_id == user_id, GenerationLog.created_at >= _day_start())
        )
        or 0
    )


def system_key_used(db: Session, user_id: str) -> int:
    """今日消耗「系统默认 API Key」的成功生成次数。

    只数 status='ok' 且 llm_source='system' 的记录：调用失败不占免费额度，
    用户用自己的 Key 生成也不占用（费用由本人承担）。历史日志迁移后默认记为 system。
    """
    return int(
        db.scalar(
            select(func.count())
            .select_from(GenerationLog)
            .where(
                GenerationLog.user_id == user_id,
                GenerationLog.created_at >= _day_start(),
                GenerationLog.status == "ok",
                GenerationLog.llm_source == "system",
            )
        )
        or 0
    )


def has_personal_key(db: Session, user_id: str, settings: Settings) -> bool:
    """是否已启用自带 Key；只查密文是否存在，不解密、不触碰明文。"""
    if not settings.allow_personal_llm_keys:
        return False
    try:
        row = db.get(UserLLMSetting, user_id)
        return bool(row and row.api_key_cipher)
    except Exception:  # noqa: BLE001 - 展示型查询失败时按「未配置」处理
        logger.warning("读取用户自带 Key 状态失败（user=%s）", user_id)
        return False


def billing_source(
    user: User,
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    personal_key: bool | None = None,
) -> Literal["admin", "personal", "system"]:
    """判定本次生成由谁买单：管理员 / 用户自带 Key / 系统共享 Key。"""
    if getattr(user, "is_admin", False):
        return "admin"
    if llm is not None:
        return "personal" if getattr(llm, "source", "system") == "personal" else "system"
    return "personal" if personal_key else "system"


def quota_info(
    db: Session,
    user: User,
    llm: LLMClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """返回配额全貌。

    used/limit/remaining 保留旧语义（今日总生成次数 / 总量护栏），避免既有调用方
    与小程序回归；新增字段才是本次真正生效的计费口径，前端优先使用它们。
    """
    settings = settings or get_settings()
    personal = (
        getattr(llm, "source", "system") == "personal"
        if llm is not None
        else has_personal_key(db, user.id, settings)
    )
    source = billing_source(user, settings, llm=llm, personal_key=personal)
    used = quota_used(db, user.id)
    limit = user.daily_quota
    try:
        free_used = system_key_used(db, user.id)
    except Exception:  # noqa: BLE001 - 展示失败不能让登录/查询接口 500
        logger.warning("统计系统 Key 用量失败（user=%s）", user.id, exc_info=True)
        free_used = 0
    free_limit = max(0, settings.system_key_daily_limit)
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "unlimited": source != "system",
        "source": source,
        "system_key_used": free_used,
        "system_key_limit": free_limit,
        "system_key_remaining": max(0, free_limit - free_used),
    }


def check_quota(
    db: Session,
    user: User,
    llm: LLMClient | None = None,
    settings: Settings | None = None,
) -> None:
    """生成前的额度闸门。

    - 管理员账号：无限使用系统默认 Key；
    - 自带 Key 的账号：由本人承担费用，不受系统免费次数限制；
    - 其余账号：每天只有 system_key_daily_limit 次系统 Key 免费额度，
      用完后明确引导去配置自己的 Key，而不是含糊报「额度用完」。

    测试里的 StubLLM 没有 source 属性，按系统客户端处理，原有限流行为不变。
    """
    # 本地部署版（standalone）没有计费与免费额度概念：单用户、用自己的 Key，直接放行。
    if get_settings().standalone:
        return
    settings = settings or get_settings()
    if billing_source(user, settings, llm=llm) != "system":
        return
    limit = max(0, settings.system_key_daily_limit)
    if system_key_used(db, user.id) >= limit:
        if limit:
            detail = (
                f"今日 {limit} 次免费额度已用完（用的是系统共享 API Key）。"
                "请到「设置 → 我的大模型 API」填入自己的 Key，即可继续不限次数生成；也可以明天再试。"
            )
        else:
            detail = (
                "系统共享 API Key 不对普通账号开放。请到「设置 → 我的大模型 API」"
                "配置自己的 API Key 后即可生成。"
            )
        raise HTTPException(status_code=429, detail=detail)
    if quota_used(db, user.id) >= user.daily_quota:
        raise HTTPException(status_code=429, detail=f"今日生成额度已用完（{user.daily_quota} 次/天），请明天再试")


def get_llm(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    """解析本次请求真正生效的模型配置：用户自带 Key 优先，系统 Key 兜底。

    单测通过 dependency_overrides[get_llm] 注入 StubLLM 完全绕过本函数，
    因此这里的数据库读取不会影响既有测试。

    本地部署版（standalone）下不使用系统共享 Key，也不读数据库里的 BYOK：直接读
    本机 local_llm.json（应用内「设置」可改，未配置时回退到 .env 默认值）。
    """
    if settings.standalone:
        from app.llm.local_config import load_local_llm_config
        from app.llm.client import LLMNotConfiguredError

        cfg = load_local_llm_config()
        if not cfg.api_key.strip():
            raise LLMNotConfiguredError(
                "尚未配置大模型 API Key。请在「设置 → 我的大模型 API」填入你自己的 Key，"
                "或在 .env 设置 APPLICRAFT_LLM_API_KEY 后重启。"
            )
        effective = settings.model_copy(
            update={
                "llm_api_key": cfg.api_key,
                "llm_base_url": cfg.base_url or settings.llm_base_url,
                "llm_model": cfg.model or settings.llm_model,
            }
        )
        return LLMClient(effective, source="personal")
    personal = None
    if settings.allow_personal_llm_keys:
        try:
            personal = secret_config(db, user.id)
        except UserLLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 管理员始终可以用系统默认 Key，即使管理员开启了「强制其他用户自带 Key」。
    effective_settings = settings
    if getattr(user, "is_admin", False) and not personal:
        effective_settings = settings.model_copy(update={"require_personal_llm_key": False})
    try:
        effective = resolve_effective_llm(effective_settings, personal)
    except UserLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if effective.source == "system":
        return _system_llm()

    cfg = effective.settings
    fingerprint = hashlib.sha256(
        f"{cfg.llm_api_key}|{cfg.llm_base_url}|{cfg.llm_model}".encode("utf-8")
    ).hexdigest()[:24]
    return _llm_registry.get(
        (user.id, fingerprint),
        lambda: LLMClient(cfg, source="personal"),
    )
