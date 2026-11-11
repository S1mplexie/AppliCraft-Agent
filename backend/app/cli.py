"""本地账号管理：无邮件、无 Web 后台，账号全部在服务器命令行分配。

在后端目录（本机 backend/，容器内 /app）执行：
    python -m app.cli create-user you@example.com
    python -m app.cli create-user you@example.com --name 张三 --quota 30
    python -m app.cli list-users
    python -m app.cli reset-password you@example.com
    python -m app.cli sync-admin

Docker 部署时：
    docker compose exec applicraft python -m app.cli create-user you@example.com

sync-admin 读取 .env 里的 APPLICRAFT_BOOTSTRAP_EMAIL / APPLICRAFT_BOOTSTRAP_PASSWORD，
把默认管理员账号对齐配置（幂等）；部署脚本会在容器启动后自动执行一次。
不传 --password 时，交互终端会提示输入；非交互环境自动生成随机初始密码并只打印一次。
密码通过命令行明文传入会留在 shell 历史里，正式账号请用交互方式或 .env 配置。
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from uuid import uuid4

from sqlalchemy import select, update

from app.auth.security import hash_password, normalize_email, validate_password, verify_password
from app.config import get_settings
from app.db.models import SessionToken, User
from app.db.session import SessionLocal, init_db


def _resolve_password(provided: str | None) -> tuple[str, bool]:
    """返回（密码，是否为自动生成的初始密码）。"""
    if provided:
        return provided, False
    if sys.stdin.isatty():
        first = getpass.getpass("新密码（至少 8 位）：")
        second = getpass.getpass("再输入一次：")
        if first != second:
            raise SystemExit("两次输入不一致，账号未改动")
        return first, False
    return secrets.token_urlsafe(12), True


def _credentials(args: argparse.Namespace) -> tuple[str, str, bool] | None:
    try:
        email = normalize_email(args.email)
        password, generated = _resolve_password(args.password)
        validate_password(password)
        return email, password, generated
    except ValueError as exc:
        print(f"输入有误：{exc}", file=sys.stderr)
        return None


def cmd_create_user(args: argparse.Namespace) -> int:
    init_db()
    credentials = _credentials(args)
    if credentials is None:
        return 2
    email, password, generated = credentials
    settings = get_settings()
    quota = args.quota if args.quota is not None else settings.daily_quota
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print("该邮箱已存在；如需改密码请用 reset-password。", file=sys.stderr)
            return 1
        user = User(
            id=uuid4().hex[:32],
            email=email,
            password_hash=hash_password(password),
            display_name=(args.name or email.split("@")[0])[:80],
            daily_quota=quota,
            is_admin=bool(getattr(args, "admin", False)),
        )
        db.add(user)
        db.commit()
    role = "，管理员" if user.is_admin else ""
    print(f"账号已创建：{email}（{user.display_name}，{quota} 次/天{role}）")
    if generated:
        print(f"初始密码（仅显示一次，请立即保存）：{password}")
    return 0


def cmd_list_users(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.created_at)).all()
    if not users:
        print("（暂无账号；可在页面注册首个账号，或用 create-user 创建）")
        return 0
    print(f"共 {len(users)} 个账号：")
    for user in users:
        created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "-"
        status = "启用" if user.is_active else "停用"
        role = "管理员" if user.is_admin else "普通"
        print(f"  {user.email}\t{user.display_name or '-'}\t{status}\t{role}\t{user.daily_quota} 次/天\t{created}")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    init_db()
    credentials = _credentials(args)
    if credentials is None:
        return 2
    email, password, generated = credentials
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            print("账号不存在。", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        # 改密后吊销全部旧会话，避免旧 Cookie 继续可用。
        db.execute(
            update(SessionToken)
            .where(SessionToken.user_id == user.id, SessionToken.revoked.is_(False))
            .values(revoked=True)
        )
        db.commit()
    print(f"密码已重置：{email}（该账号的所有登录会话已失效）")
    if generated:
        print(f"新密码（仅显示一次，请立即保存）：{password}")
    return 0


def cmd_sync_admin(args: argparse.Namespace) -> int:
    """按 .env 配置对齐默认管理员账号（幂等，供部署脚本调用）。

    规则：
    - 目标邮箱已存在：密码一致就什么都不做；不一致才改哈希并吊销该账号的全部会话；
    - 目标邮箱不存在且库里只有一个账号：视为旧默认账号迁移，改邮箱 + 改密，用户 ID 与数据保留；
    - 库为空：直接创建默认管理员账号；
    - 库里有多个账号且都不匹配：拒绝猜测，要求人工确认，避免误改他人账号。
    全程不打印密码明文。
    """
    settings = get_settings()
    raw_email = args.email or settings.bootstrap_email
    raw_password = args.password or settings.bootstrap_password
    if not raw_email.strip() and not raw_password.strip():
        print("未配置默认管理员（APPLICRAFT_BOOTSTRAP_EMAIL / _PASSWORD），跳过。")
        return 0
    if not raw_email.strip() or not raw_password.strip():
        print("默认管理员的邮箱与密码必须同时配置。", file=sys.stderr)
        return 2
    try:
        email = normalize_email(raw_email)
        validate_password(raw_password)
    except ValueError as exc:
        print(f"默认管理员配置有误：{exc}", file=sys.stderr)
        return 2

    init_db()
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            if len(users) > 1:
                print(
                    "数据库中存在多个账号且都不匹配默认邮箱，未做任何改动；请用 list-users 检查。",
                    file=sys.stderr,
                )
                return 1
            if users:
                # 单账号迁移：用户 ID 不变，已有档案与文书全部保留。
                user = users[0]
                old_email = user.email
                user.email = email
                print(f"已把原账号 {old_email} 的登录邮箱改为 {email}（原有数据不变）")
            else:
                db.add(
                    User(
                        id=uuid4().hex[:32],
                        email=email,
                        password_hash=hash_password(raw_password),
                        display_name=email.split("@")[0][:80],
                        daily_quota=settings.daily_quota,
                        is_admin=True,
                    )
                )
                db.commit()
                print(f"默认管理员账号已创建：{email}")
                return 0
        else:
            print(f"默认管理员账号已存在：{email}")

        # 无论「旧单账号迁移」还是「已存在的账号」，都确保管理员标记到位；
        # 管理员可无限使用系统默认 Key，不受每日免费次数限制。
        user.is_admin = True

        if verify_password(raw_password, user.password_hash):
            db.commit()  # 提交可能发生的邮箱改名
            print("密码与配置一致，未改动现有会话。")
            return 0
        user.password_hash = hash_password(raw_password)
        # 改密后吊销该账号全部旧会话，避免旧 Cookie / Bearer Token 继续可用。
        db.execute(
            update(SessionToken)
            .where(SessionToken.user_id == user.id, SessionToken.revoked.is_(False))
            .values(revoked=True)
        )
        db.commit()
        print("已同步默认密码，并吊销该账号的全部旧会话。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="AppliCraft 本地账号管理（纯账号密码，不发送邮件）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="创建账号")
    create.add_argument("email", help="登录邮箱")
    create.add_argument("--password", help="密码；省略则交互输入或自动生成")
    create.add_argument("--name", default="", help="显示名称")
    create.add_argument("--quota", type=int, default=None, help="每日生成额度，默认取 .env 配置")
    create.add_argument("--admin", action="store_true", help="设为管理员（可无限使用系统默认 API Key）")
    create.set_defaults(func=cmd_create_user)

    listing = sub.add_parser("list-users", help="列出全部账号")
    listing.set_defaults(func=cmd_list_users)

    reset = sub.add_parser("reset-password", help="重置密码并吊销旧会话")
    reset.add_argument("email", help="登录邮箱")
    reset.add_argument("--password", help="新密码；省略则交互输入或自动生成")
    reset.set_defaults(func=cmd_reset_password)

    sync = sub.add_parser("sync-admin", help="按 .env 配置对齐默认管理员账号（幂等）")
    sync.add_argument("--email", default="", help="覆盖 .env 中的默认邮箱")
    sync.add_argument("--password", default="", help="覆盖 .env 中的默认密码（明文会留在命令历史，不建议）")
    sync.set_defaults(func=cmd_sync_admin)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
