"""微信小程序登录：把一次性 code 换成 openid。

流程：小程序 wx.login() 取 code → 发给本服务 → 本服务用 AppSecret 调微信
jscode2session 接口换 openid → 按 openid 找到（或绑定）本地账号 → 签发原有
Bearer token。后续所有业务接口完全复用现有鉴权，不需要第二套会话机制。

安全约定：
- AppSecret 只在服务端使用，绝不出现在小程序代码、日志或响应里；
- session_key 不落库、不返回前端，换取到 openid 后立即丢弃；
- 微信原始 errmsg 不直接透传，统一映射成中文提示，避免泄露内部信息。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings

JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

# 常见微信错误码的用户可读提示；未列出的错误码走统一兜底文案。
ERROR_MESSAGES = {
    40029: "微信登录凭证无效或已过期，请退出小程序重新进入再试",
    45011: "微信登录过于频繁，请稍后再试",
    40226: "该微信账号暂不可用于登录",
    40013: "服务端小程序 AppID 配置有误，请联系管理员",
    40125: "服务端小程序密钥配置有误，请联系管理员",
    -1: "微信服务暂时不可用，请稍后再试",
}


@dataclass(frozen=True)
class WechatIdentityInfo:
    """code2session 成功后的身份标识，不含 session_key。"""

    openid: str
    unionid: str = ""


class WechatLoginError(Exception):
    """可安全展示给用户的微信登录失败原因。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def exchange_code(code: str, settings: Settings) -> WechatIdentityInfo:
    """用 wx.login 的 code 向微信换取 openid；失败时抛出可展示的错误。"""
    if not settings.wechat_login_enabled:
        raise WechatLoginError("服务端尚未配置小程序 AppID / AppSecret，微信登录未启用", 503)

    code = (code or "").strip()
    if not code or len(code) > 256:
        raise WechatLoginError("微信登录凭证无效，请退出小程序重新进入再试")

    query = urlencode(
        {
            "appid": settings.wechat_appid.strip(),
            "secret": settings.wechat_secret.strip(),
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    request = Request(
        f"{JSCODE2SESSION_URL}?{query}",
        headers={"User-Agent": "AppliCraft/1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=settings.wechat_api_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise WechatLoginError("无法连接微信登录服务，请稍后再试", 502) from exc

    if not isinstance(payload, dict):
        raise WechatLoginError("微信登录返回内容异常，请稍后再试", 502)
    try:
        errcode = int(payload.get("errcode") or 0)
    except (TypeError, ValueError):
        raise WechatLoginError("微信登录返回内容异常，请稍后再试", 502) from None
    if errcode:
        raise WechatLoginError(ERROR_MESSAGES.get(errcode, "微信登录失败，请稍后再试"))
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise WechatLoginError("微信登录未返回身份信息，请稍后再试", 502)
    return WechatIdentityInfo(openid=openid, unionid=str(payload.get("unionid") or "").strip())
