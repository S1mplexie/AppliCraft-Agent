"""AppliCraft FastAPI 入口：提供 API，并在生产环境中托管 Vue 构建产物。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import __version__
from app.api import (
    routes_auth,
    routes_documents,
    routes_feedback,
    routes_generate,
    routes_library,
    routes_llm,
    routes_match,
    routes_profile,
    routes_settings,
    routes_skills,
)
from app.auth.guards import SAFE_METHODS, count_users, registration_open, same_origin
from app.config import get_settings
from app.db.session import db_healthy, get_db, init_db
from app.llm.client import LLMCallError, LLMNotConfiguredError
from app.models.schemas import DOC_TYPE_LABELS, ConfigResponse

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库未就绪时只告警，避免健康检查都起不来；接口会在调用时报错。
    # 本地部署版（standalone）没有数据库，跳过初始化。
    if not settings.standalone:
        try:
            init_db()
        except Exception as exc:  # pragma: no cover - 取决于部署时数据库是否已就绪
            logger.warning("数据库初始化失败：%s", exc)
    yield
    try:
        from app.api.deps import close_llm_clients

        await close_llm_clients()
    except Exception:  # pragma: no cover - 关停阶段尽力而为
        pass


app = FastAPI(
    title="AppliCraft API",
    description="港新及申请制硕士材料生成 Agent（LangGraph + FastAPI）",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# LLM 相关错误统一转成友好 HTTP 错误：未配置 Key → 400，模型调用失败 → 502。
# 这样选校评估 / 文书生成在未配 Key 或调用异常时，前端能直接拿到可读信息，而不是 500。
@app.exception_handler(LLMNotConfiguredError)
async def _llm_not_configured_handler(request: Request, exc: LLMNotConfiguredError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LLMCallError)
async def _llm_call_error_handler(request: Request, exc: LLMCallError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# 小程序 token 通道：凭据在请求体或 Authorization 头里显式提交，不依赖浏览器自动携带 Cookie。
# wx.request 会固定带 https://servicewechat.com/<appid>/.../page-frame.html 的 Referer，
# 与网页版同源规则天然冲突；且这些接口的响应受 CORS 约束，跨站页面读不到 token，
# 因此不构成 CSRF 条件。登录/注册限流仍然生效，网页版 Cookie 通道的同源校验不放松。
TOKEN_CHANNEL_PATHS = frozenset({
    "/api/auth/token-login",
    "/api/auth/token-register",
    "/api/auth/token-logout",
    "/api/auth/wechat-login",
    "/api/auth/wechat-bind",
})


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    # 本地部署版（standalone）没有登录会话、不签发 Cookie，没有 CSRF 风险，直接放行；
    # 同时便于本机用不同端口的静态页直连 API 调试。
    if settings.standalone:
        return await call_next(request)
    # Cookie 会话依赖浏览器自动携带凭证，写操作必须确认来源同源。
    # Bearer token 由小程序显式写入请求头、浏览器不会自动携带，不构成 CSRF 条件，予以豁免。
    uses_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
    token_channel = request.url.path in TOKEN_CHANNEL_PATHS
    if (
        request.url.path.startswith("/api/")
        and request.method not in SAFE_METHODS
        and not uses_bearer
        and not token_channel
        and not same_origin(request, settings)
    ):
        return JSONResponse(status_code=403, content={"detail": "请求来源不合法：已拒绝跨站写请求"})
    return await call_next(request)


# 本地部署版（standalone）没有登录系统，不挂载 auth 路由，改为挂载本地 LLM 配置路由；
# 网页版（多租户）走完整的 auth + BYOK 体系。
if settings.standalone:
    app.include_router(routes_settings.router, prefix="/api")
else:
    app.include_router(routes_auth.router, prefix="/api")
app.include_router(routes_profile.router, prefix="/api")
app.include_router(routes_generate.router, prefix="/api")
app.include_router(routes_documents.router, prefix="/api")
app.include_router(routes_library.router, prefix="/api")
app.include_router(routes_llm.router, prefix="/api")
app.include_router(routes_skills.router, prefix="/api")
app.include_router(routes_feedback.router, prefix="/api")
app.include_router(routes_match.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "version": __version__,
        "llm_configured": settings.llm_configured,
        # 本地部署版无数据库；db_healthy 对 SQLite 会触发建文件，standalone 下直接视为就绪。
        "db_ok": True if settings.standalone else db_healthy(),
    }


@app.get("/api/config", response_model=ConfigResponse, tags=["system"])
def config(db: Session = Depends(get_db)):
    if settings.standalone:
        # 本地版：模型配置以本机 local_llm.json（回退 .env）为准；无注册/计费概念。
        from app.llm.local_config import load_local_llm_config, mask_key

        cfg = load_local_llm_config()
        key = cfg.api_key.strip()
        return ConfigResponse(
            version=__version__,
            llm_configured=bool(key),
            llm_model=cfg.model or settings.llm_model,
            llm_base_url=cfg.base_url or settings.llm_base_url,
            api_key_hint=mask_key(key),
            doc_types=DOC_TYPE_LABELS,
            max_revisions=settings.max_revisions,
            message=(
                "" if key
                else "尚未配置 API Key。请到「设置 → 我的大模型 API」填入你自己的 Key，"
                "或在 .env 设置 APPLICRAFT_LLM_API_KEY 后重启。"
            ),
            allow_registration=False,
            daily_quota=settings.daily_quota,
            wechat_login_enabled=False,
            allow_personal_llm_keys=False,
            require_personal_llm_key=False,
            system_key_daily_limit=0,
            standalone=True,
        )
    key = settings.llm_api_key.strip()
    return ConfigResponse(
        version=__version__,
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
        api_key_hint=f"***{key[-4:]}" if len(key) > 4 else "",
        doc_types=DOC_TYPE_LABELS,
        max_revisions=settings.max_revisions,
        message=(
            "" if settings.llm_configured
            else "系统尚未配置 API Key；你仍可在「设置 → 我的大模型 API」填入自己的 Key 使用。"
        ),
        allow_registration=registration_open(count_users(db), settings),
        daily_quota=settings.daily_quota,
        wechat_login_enabled=settings.wechat_login_enabled,
        allow_personal_llm_keys=settings.allow_personal_llm_keys,
        require_personal_llm_key=settings.require_personal_llm_key,
        system_key_daily_limit=settings.system_key_daily_limit,
    )


# --- 托管前端 SPA 静态资源（仅在前端已构建时启用）---
static_dir = settings.static_dir.resolve()
if static_dir.is_dir():
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (static_dir / full_path).resolve()
        if full_path and static_dir in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        # index.html 禁用启发式缓存：发版后浏览器必须回源校验，
        # 否则会一直用旧 index.html 引用旧资源哈希，出现「页面没变化」。
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})
