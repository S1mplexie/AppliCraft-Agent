"""测试环境：把数据库指向临时 SQLite 文件，绝不碰本地真实数据。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="applicraft_test_"))
_DATA = _TMP / "data"
_DATA.mkdir(parents=True, exist_ok=True)
os.environ["APPLICRAFT_DATA_DIR"] = str(_DATA)
os.environ["APPLICRAFT_DATABASE_URL"] = "sqlite:///" + (_DATA / "test.db").as_posix()
# 业务默认关闭开放注册；既有隔离测试需要反复注册多个账号，故测试环境显式开放。
# 注册策略本身由 test_security.py 单独验证。
os.environ["APPLICRAFT_ALLOW_REGISTRATION"] = "true"
# 限流器是进程内全局计数，测试会连续创建大量账号；阈值在测试环境放宽，
# 限流算法与登录锁定行为由 test_security.py 用独立实例验证。
os.environ["APPLICRAFT_REGISTER_MAX_ATTEMPTS"] = "1000"
os.environ["APPLICRAFT_LOGIN_MAX_ATTEMPTS"] = "1000"
