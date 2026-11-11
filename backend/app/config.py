"""集中配置：所有配置项均可通过 APPLICRAFT_* 环境变量覆盖。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent          # backend/app 目录
BACKEND_DIR = APP_DIR.parent                       # backend 目录
PROJECT_DIR = BACKEND_DIR.parent                   # 仓库根目录


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APPLICRAFT_",
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- OpenAI 兼容大模型端点 ---
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 180.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.5
    llm_max_tokens: int = 4096

    # --- 用户自带大模型 Key（BYOK）---
    # 开启后，用户可在「设置 → 我的大模型 API」填自己的 Key；生成时优先扣自己的额度，
    # 未配置的用户仍回退到上面的系统 Key。设为 False 可整体关闭该功能。
    allow_personal_llm_keys: bool = True
    # 设为 True 时强制每人使用自己的 Key：未配置的用户生成会收到明确提示，
    # 系统 Key 不再被普通用户消耗（管理员可据此彻底关闭「共用我的额度」）。
    require_personal_llm_key: bool = False

    # --- 系统 Key 的免费额度 ---
    # 非管理员账号每天可免费使用「系统默认 API Key」的生成次数；用完后必须
    # 在「设置 → 我的大模型 API」配置自己的 Key 才能继续生成，或等次日重置。
    # 管理员账号不受此限制；自带 Key 的账号也不计入（费用由本人承担）。
    # 设为 0 表示非管理员一律不得使用系统 Key（等同按账号强制 BYOK）。
    system_key_daily_limit: int = 3

    # --- 数据库与多用户 ---
    # 容器内由 compose 覆盖为 postgres 主机名；本地直连时用 localhost。
    # 留空时本机用 SQLite 单文件（便于离线开发与验证）；compose 会注入 PostgreSQL。
    database_url: str = ""
    daily_quota: int = 20                 # 每个用户每日生成总次数上限（旧有护栏）
    # 默认开放注册：新用户可自助建号。成本由「系统 Key 每日 3 次免费额度」兜住，
    # 用完必须到「设置 → 我的大模型 API」填自己的 Key；管理员账号不受限制。
    # 设为 false 可退回仅管理员分配账号的私有模式。
    allow_registration: bool = True
    # 开放注册关闭时，数据库为空仍允许自助创建首个账号（建完即自动关闭），不必先跑命令行。
    bootstrap_first_user: bool = True
    # 默认管理员账号：只从 .env 读取，绝不写进仓库或镜像。
    # 部署脚本启动后会执行 python -m app.cli sync-admin 按这里的值对齐数据库，
    # 两者留空时该命令直接跳过，仍可用 create-user 或页面自助注册首个账号。
    bootstrap_email: str = ""
    bootstrap_password: str = ""
    session_days: int = 14               # 会话有效期
    cookie_secure: bool = False          # 公网 HTTPS 部署时必须设为 true
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # 仅在后端位于可信反向代理之后时开启，否则伪造转发头可绕开限流。
    trust_proxy_headers: bool = False
    # 反向代理的对外地址（如 https://apply.example.com），用于同源校验。
    public_origin: str = ""
    # 进程内滑动窗口限流：单实例够用；多实例部署时换成 Redis。
    login_max_attempts: int = 10
    # 开放注册下按 IP 限制 10 分钟内的注册尝试；同一校园网/办公网 NAT 出口下
    # 多个正常用户可能共用 IP，故阈值不宜设得太低。
    register_max_attempts: int = 10
    auth_window_seconds: int = 600

    # --- 微信小程序一键登录（可选）---
    # 在微信公众平台注册小程序后获取 AppID / AppSecret；两者都留空时一键登录接口关闭，
    # 账号密码登录不受影响。密钥只放 .env，绝不写进小程序前端或提交到仓库。
    wechat_appid: str = ""
    wechat_secret: str = ""
    # 未绑定的微信号是否自动建号。默认关闭：必须先用账号密码登录并绑定，
    # 否则任何微信用户都能进来消耗模型额度。
    wechat_auto_register: bool = False
    wechat_api_timeout: float = 8.0

    # --- RAG / 知识库（港新项目官方资料召回）---
    # 默认开启：生成 PS / 推荐信时若档案指定了知识库覆盖范围内的目标项目，
    # 会自动检索其官方课程 / 特色 / 文书要点作为写作参考。目标项目不在覆盖范围内时安全降级。
    rag_enabled: bool = True
    rag_top_k: int = 6
    rag_max_chars: int = 2600
    # 知识库目录（chunks.jsonl 所在处）；容器内由 Dockerfile 通过环境变量覆盖为 /knowledge。
    knowledge_dir: Path = PROJECT_DIR / "knowledge"

    # --- RAG 向量召回预留：本阶段用词法召回，将来可指向任意 OpenAI 兼容 embedding 服务 ---
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1536

    # --- 本地部署版（免登录、单用户、用自己的 Key）---
    # 设为 true 时：跳过登录/注册与一切按用户隔离的数据库逻辑，所有档案/文书/参考/技能
    # 落在固定的本地目录，模型配置直接读本机 .env 与 data/local_llm.json（应用内「设置」可改）。
    # 网页版（多租户 SaaS）保持 false；本地版与网页版共用同一份代码，仅此开关不同。
    # 本目录（D:\AppliCraftLocal）是「本地部署版」独立项目，开箱即免登录、单用户、用自己的 Key。
    standalone: bool = True

    # --- 存储与静态资源 ---
    data_dir: Path = BACKEND_DIR / "data"
    static_dir: Path = PROJECT_DIR / "frontend" / "dist"

    # --- 服务与生成参数 ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_revisions: int = 2

    @property
    def db_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        return "sqlite:///" + (self.data_dir / "applicraft.db").resolve().as_posix()

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def wechat_login_enabled(self) -> bool:
        """只有 AppID 与 AppSecret 都配齐才开放微信登录入口。"""
        return bool(self.wechat_appid.strip() and self.wechat_secret.strip())

    @property
    def origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
