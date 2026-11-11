"""密码哈希与会话令牌工具。"""
from __future__ import annotations

import hashlib
import re
import secrets

import bcrypt

COOKIE_NAME = "applicraft_session"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL_RE.match(value) or len(value) > 254:
        raise ValueError("邮箱格式不正确")
    return value


def validate_password(password: str) -> None:
    if not 8 <= len(password or "") <= 128:
        raise ValueError("密码长度需在 8-128 位之间")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
