"""注册、登录、登出与当前用户信息（账号密码制，可选微信一键登录，不依赖邮件服务）。

网页版走 HttpOnly Cookie；小程序走 Authorization: Bearer token。
两种通道共用同一张 SessionToken 表，因此账号、配额与文书数据完全互通，
任意一端登出只吊销自己的那条会话，不会影响另一端。
微信登录只是「换一种方式确认同一个本地账号」：openid 经 wechat_identities
绑定到 User，之后仍然签发同一套 Bearer token，不引入第二套权限体系。
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, quota_info
from app.auth.guards import SlidingLimiter, client_ip, count_users, registration_open
from app.auth.security import (
    COOKIE_NAME,
    hash_password,
    hash_token,
    new_token,
    normalize_email,
    validate_password,
    verify_password,
)
from app.auth.wechat import WechatIdentityInfo, WechatLoginError, exchange_code
from app.config import get_settings
from app.db.models import SessionToken, User, WechatIdentity, naive_utc
from app.db.session import get_db
from app.models.schemas import TokenSession

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# 登录只计失败次数，注册计每次尝试；两者都按 IP 做进程内滑动窗口限流。
_login_limiter = SlidingLimiter(settings.login_max_attempts, settings.auth_window_seconds)
_register_limiter = SlidingLimiter(settings.register_max_attempts, settings.auth_window_seconds)
# 微信 code 换取也要限流，避免攻击者用随机 code 反复打微信接口。
_wechat_limiter = SlidingLimiter(settings.login_max_attempts, settings.auth_window_seconds)


class RegisterIn(BaseModel):
    email: str
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class WechatLoginIn(BaseModel):
    """wx.login() 返回的一次性 code，5 分钟有效、只能用一次。"""

    code: str


class WechatBindIn(BaseModel):
    """未绑定的微信号用现有账号密码完成一次性绑定，绑定后即登录。"""

    code: str
    email: str
    password: str


def _create_session(db: Session, user: User) -> str:
    """签发会话并返回明文 token；数据库只保存哈希，token 丢失即无法找回。"""
    token = new_token()
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=naive_utc() + timedelta(days=settings.session_days),
        )
    )
    db.commit()
    return token


def _issue_cookie(db: Session, user: User, response: Response) -> None:
    """网页版：签发会话并写入 HttpOnly Cookie。"""
    token = _create_session(db, user)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.session_days * 86400,
        path="/",
    )


def _revoke(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if session:
        session.revoked = True
        db.commit()


def _token_session(db: Session, user: User) -> TokenSession:
    """小程序：明文 token 放进响应体，由客户端存入本地缓存。"""
    return TokenSession(token=_create_session(db, user), user=user.public(), quota=quota_info(db, user))


def _authenticate(payload: LoginIn, request: Request, db: Session, channel: str) -> User:
    """网页与小程序共用的密码校验，按通道区分限流计数。"""
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    key = f"{channel}:{client_ip(request, settings)}:{email}"
    if not _login_limiter.check(key):
        raise HTTPException(status_code=429, detail="登录尝试次数过多，请稍后再试")
    user = db.scalar(select(User).where(User.email == email))
    # 统一的错误提示，避免泄露某个邮箱是否已注册。
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        _login_limiter.hit(key)
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    _login_limiter.reset(key)
    return user


def _create_user(payload: RegisterIn, request: Request, db: Session) -> User:
    """网页与小程序共用的建号逻辑，注册策略与限流对两条通道一视同仁。"""
    if not registration_open(count_users(db), settings):
        raise HTTPException(status_code=403, detail="当前未开放注册，请联系管理员分配账号")
    ip = client_ip(request, settings)
    if not _register_limiter.check(ip):
        raise HTTPException(status_code=429, detail="注册尝试过于频繁，请稍后再试")
    _register_limiter.hit(ip)
    try:
        email = normalize_email(payload.email)
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="该邮箱已注册")
    user = User(
        id=uuid4().hex[:32],
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip()[:80],
        daily_quota=settings.daily_quota,
    )
    db.add(user)
    db.commit()
    return user


# ------------------------------------------------------------------ 网页版（Cookie）
@router.post("/register", status_code=201)
def register(payload: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _create_user(payload, request, db)
    _issue_cookie(db, user, response)
    return {"user": user.public(), "quota": quota_info(db, user)}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _authenticate(payload, request, db, channel="web")
    _issue_cookie(db, user, response)
    return {"user": user.public(), "quota": quota_info(db, user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _revoke(db, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
    )
    return {"logged_out": True}


# ------------------------------------------------------------------ 小程序（Bearer Token）
@router.post("/token-register", status_code=201, response_model=TokenSession)
def token_register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """小程序侧的自助注册；与网页共用注册策略，关闭开放注册后同样会被拒绝。"""
    user = _create_user(payload, request, db)
    return _token_session(db, user)


@router.post("/token-login", response_model=TokenSession)
def token_login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    return _token_session(db, _authenticate(payload, request, db, channel="miniprogram"))


@router.post("/token-logout")
def token_logout(request: Request, db: Session = Depends(get_db)):
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    _revoke(db, token)
    return {"logged_out": True}


# ------------------------------------------------------------------ 小程序（微信一键登录）
def _wechat_identity(code: str, request: Request) -> WechatIdentityInfo:
    """统一处理限流与微信错误码映射；换取成功后清空该 IP 的失败计数。"""
    key = "wechat:" + client_ip(request, settings)
    if not _wechat_limiter.check(key):
        raise HTTPException(status_code=429, detail="微信登录尝试次数过多，请稍后再试")
    _wechat_limiter.hit(key)
    try:
        info = exchange_code(code, settings)
    except WechatLoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    _wechat_limiter.reset(key)
    return info


def _find_wechat_identity(db: Session, info: WechatIdentityInfo) -> WechatIdentity | None:
    """openid 只在同一个 AppID 内有意义，查询必须同时带 AppID。"""
    return db.scalar(
        select(WechatIdentity).where(
            WechatIdentity.appid == settings.wechat_appid.strip(),
            WechatIdentity.openid == info.openid,
        )
    )


def _bind_identity(db: Session, user: User, info: WechatIdentityInfo) -> None:
    db.add(
        WechatIdentity(
            user_id=user.id,
            appid=settings.wechat_appid.strip(),
            openid=info.openid,
            unionid=info.unionid or None,
        )
    )
    db.commit()


def _wechat_only_user(db: Session, info: WechatIdentityInfo) -> User:
    """自动建号时用占位邮箱 + 随机不可知密码，该账号只能经微信登录进入。"""
    digest = hash_token(f"{settings.wechat_appid.strip()}:{info.openid}")[:24]
    email = f"wx-{digest}@wechat.local"
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing
    user = User(
        id=uuid4().hex[:32],
        email=email,
        password_hash=hash_password(new_token()),
        display_name="微信用户",
        daily_quota=settings.daily_quota,
    )
    db.add(user)
    db.flush()
    return user


@router.post("/wechat-login")
def wechat_login(payload: WechatLoginIn, request: Request, db: Session = Depends(get_db)):
    """已绑定直接签发 token；未绑定返回 need_bind 由前端引导绑定，或按配置自动建号。"""
    if not settings.wechat_login_enabled:
        raise HTTPException(status_code=503, detail="服务端尚未配置小程序 AppID / AppSecret，微信登录未启用")
    info = _wechat_identity(payload.code, request)
    identity = _find_wechat_identity(db, info)
    if identity:
        user = db.get(User, identity.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="该微信绑定的账号不可用，请联系管理员")
        return _token_session(db, user)
    if not settings.wechat_auto_register:
        return {"need_bind": True, "message": "该微信尚未绑定账号，请用账号密码登录一次完成绑定"}
    user = _wechat_only_user(db, info)
    _bind_identity(db, user, info)
    return _token_session(db, user)


@router.post("/wechat-bind", response_model=TokenSession)
def wechat_bind(payload: WechatBindIn, request: Request, db: Session = Depends(get_db)):
    """先校验账号密码再消耗 code；绑定成功后顺便完成登录。"""
    if not settings.wechat_login_enabled:
        raise HTTPException(status_code=503, detail="服务端尚未配置小程序 AppID / AppSecret，微信登录未启用")
    user = _authenticate(
        LoginIn(email=payload.email, password=payload.password),
        request,
        db,
        channel="wechat-bind",
    )
    info = _wechat_identity(payload.code, request)
    identity = _find_wechat_identity(db, info)
    if identity and identity.user_id != user.id:
        raise HTTPException(status_code=409, detail="该微信已绑定其它账号，请先联系管理员解绑")
    if not identity:
        _bind_identity(db, user, info)
    return _token_session(db, user)


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"user": user.public(), "quota": quota_info(db, user)}
