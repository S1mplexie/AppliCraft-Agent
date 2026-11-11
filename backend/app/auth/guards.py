"""轻量安全护栏：注册策略、同源校验与登录限流。

全部在进程内完成，不依赖邮件、Redis、验证码服务或任何第三方组件，
符合「账号密码制、单机部署」的定位。多实例部署时应把限流换成 Redis。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def count_users(db: Session) -> int:
    """统计账号总数，用于判断是否还处于「首个账号」阶段。"""
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def registration_open(user_count: int, settings: Settings) -> bool:
    """默认开放注册；显式关闭后才收紧为「仅空库自助创建首个账号」。

    成本护栏不在这里，而在按账号的系统 Key 每日免费额度：新账号用完免费次数
    必须自带 Key，因此开放注册不会无限消耗管理员的模型额度。
    """
    if settings.allow_registration:
        return True
    return bool(settings.bootstrap_first_user and user_count == 0)


def client_ip(request: Request, settings: Settings) -> str:
    """仅在明确信任反向代理时才读取转发头，否则一律用真实连接地址。"""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _netloc(value: str) -> str:
    return urlparse(value).netloc.lower()


def same_origin(request: Request, settings: Settings) -> bool:
    """校验写请求的来源，挡住依赖 Cookie 自动携带的跨站请求（CSRF）。

    浏览器发起的跨站请求一定会带 Sec-Fetch-Site、Origin 或 Referer 之一；
    三者都没有时说明是 curl / 服务端脚本，不具备浏览器 CSRF 条件，予以放行。
    """
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site in {"same-origin", "none"}:
        return True
    if fetch_site == "cross-site":
        return False

    trusted = {request.headers.get("host", "").lower()}
    trusted.update(_netloc(origin) for origin in settings.origin_list)
    if settings.public_origin.strip():
        trusted.add(_netloc(settings.public_origin.strip()))
    # 反向代理常把 Host 改写成内部地址，此时以可信的转发头为准。
    if settings.trust_proxy_headers:
        forwarded_host = request.headers.get("x-forwarded-host", "")
        if forwarded_host:
            trusted.add(forwarded_host.split(",")[0].strip().lower())
    trusted.discard("")

    origin = request.headers.get("origin")
    if origin:
        return _netloc(origin) in trusted
    referer = request.headers.get("referer")
    if referer:
        return _netloc(referer) in trusted
    return True


@dataclass
class SlidingLimiter:
    """按 key 在滑动时间窗内计数；线程安全，进程内生效。"""

    max_attempts: int
    window_seconds: int
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: Lock = field(default_factory=Lock)

    def _recent(self, key: str, now: float) -> deque[float]:
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def check(self, key: str) -> bool:
        """是否还允许本次尝试（不计数）。"""
        with self._lock:
            return len(self._recent(key, time.monotonic())) < self.max_attempts

    def hit(self, key: str) -> None:
        """记录一次失败或尝试。"""
        with self._lock:
            now = time.monotonic()
            self._recent(key, now).append(now)

    def reset(self, key: str) -> None:
        """成功后清空计数，避免正常用户被历史失败拖累。"""
        with self._lock:
            self._hits.pop(key, None)
