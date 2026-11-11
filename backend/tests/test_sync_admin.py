"""默认管理员同步（sync-admin）：创建、迁移、幂等、改密吊销与拒绝误改。"""
from __future__ import annotations

import argparse
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.auth.security import hash_password, hash_token, verify_password
from app.config import get_settings
from app.db.models import Base, SessionToken, User, naive_utc

ADMIN_EMAIL = "owner@example.com"
ADMIN_PASSWORD = "owner-pass-123"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """每个用例一个独立 SQLite，避免共享测试库里的账号互相干扰。"""
    engine = create_engine("sqlite:///" + (tmp_path / "sync_admin.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    settings = get_settings()
    monkeypatch.setattr(settings, "bootstrap_email", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "bootstrap_password", ADMIN_PASSWORD)
    return factory


def _run(capsys, email: str = "", password: str = ""):
    """执行 sync-admin，返回（退出码，输出文本）。"""
    code = cli.cmd_sync_admin(argparse.Namespace(email=email, password=password))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _users(factory) -> list[User]:
    with factory() as db:
        return db.scalars(select(User)).all()


def _add_user(factory, email: str, password: str, with_session: bool = False) -> tuple[str, str]:
    """插入一个已存在的账号，返回（用户 ID，会话 token 哈希）。"""
    user_id = uuid4().hex[:32]
    token_hash = hash_token("token-" + uuid4().hex)
    with factory() as db:
        db.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                display_name="旧管理员",
                daily_quota=20,
            )
        )
        if with_session:
            db.add(
                SessionToken(
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=naive_utc() + timedelta(days=1),
                    revoked=False,
                )
            )
        db.commit()
    return user_id, token_hash


def _session_revoked(factory, token_hash: str) -> bool:
    with factory() as db:
        session = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_hash))
        return bool(session and session.revoked)


def test_empty_db_creates_admin_without_printing_password(isolated, capsys):
    code, output = _run(capsys)
    assert code == 0
    users = _users(isolated)
    assert len(users) == 1
    assert users[0].email == ADMIN_EMAIL
    assert verify_password(ADMIN_PASSWORD, users[0].password_hash)
    assert ADMIN_PASSWORD not in output  # 明文密码不得出现在部署日志里


def test_migrates_single_old_account_and_keeps_user_id(isolated, capsys):
    user_id, token_hash = _add_user(isolated, "admin@applicraft.local", "old-pass-123", with_session=True)
    code, output = _run(capsys)
    assert code == 0
    users = _users(isolated)
    assert len(users) == 1
    assert users[0].id == user_id  # 档案与文书按用户 ID 归属，必须保持不变
    assert users[0].email == ADMIN_EMAIL
    assert verify_password(ADMIN_PASSWORD, users[0].password_hash)
    assert _session_revoked(isolated, token_hash)
    assert "原有数据不变" in output


def test_second_run_is_idempotent_and_keeps_sessions(isolated, capsys):
    code, _ = _run(capsys)
    assert code == 0
    user_id = _users(isolated)[0].id
    token_hash = hash_token("second-run-token")
    with isolated() as db:
        db.add(
            SessionToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=naive_utc() + timedelta(days=1),
                revoked=False,
            )
        )
        db.commit()
    code, output = _run(capsys)
    assert code == 0
    assert "未改动现有会话" in output
    assert not _session_revoked(isolated, token_hash)
    assert len(_users(isolated)) == 1


def test_password_change_revokes_old_sessions(isolated, capsys, monkeypatch):
    code, _ = _run(capsys)
    assert code == 0
    user_id = _users(isolated)[0].id
    token_hash = hash_token("before-password-change")
    with isolated() as db:
        db.add(
            SessionToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=naive_utc() + timedelta(days=1),
                revoked=False,
            )
        )
        db.commit()
    monkeypatch.setattr(get_settings(), "bootstrap_password", "brand-new-pass-456")
    code, output = _run(capsys)
    assert code == 0
    assert _session_revoked(isolated, token_hash)
    assert verify_password("brand-new-pass-456", _users(isolated)[0].password_hash)
    assert not verify_password(ADMIN_PASSWORD, _users(isolated)[0].password_hash)
    assert "已同步默认密码" in output


def test_multiple_unmatched_accounts_refuses_to_guess(isolated, capsys):
    _add_user(isolated, "a@example.com", "pass-123456")
    _add_user(isolated, "b@example.com", "pass-123456")
    code, _ = _run(capsys)
    assert code == 1
    assert {user.email for user in _users(isolated)} == {"a@example.com", "b@example.com"}


def test_unconfigured_skips_without_side_effects(isolated, capsys, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bootstrap_email", "")
    monkeypatch.setattr(settings, "bootstrap_password", "")
    code, output = _run(capsys)
    assert code == 0
    assert "跳过" in output
    assert _users(isolated) == []


def test_invalid_configuration_is_rejected(isolated, capsys, monkeypatch):
    monkeypatch.setattr(get_settings(), "bootstrap_password", "short")
    code, _ = _run(capsys)
    assert code == 2
    assert _users(isolated) == []
