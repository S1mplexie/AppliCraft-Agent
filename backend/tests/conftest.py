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
# 既有用例按多租户语义编写（register 建号、登录态调 API），standalone 分支无 auth 路由；
# 测试环境统一关闭 standalone，走与网页版一致的 auth 挂载分支。
os.environ["APPLICRAFT_STANDALONE"] = "false"
# get_llm 在依赖解析阶段就需要一个可用 Key 才能构造客户端；额度拦截测试
# 在调用 LLM 之前就返回 429，并不真正发请求。给个测试占位 Key 避免 503
# 抢在额度闸门之前返回（与网页版测试环境行为一致）。
os.environ.setdefault("APPLICRAFT_LLM_API_KEY", "sk-test-placeholder-not-a-real-key")
# 业务默认关闭开放注册；既有隔离测试需要反复注册多个账号，故测试环境显式开放。
# 注册策略本身由 test_security.py 单独验证。
os.environ["APPLICRAFT_ALLOW_REGISTRATION"] = "true"
# 限流器是进程内全局计数，测试会连续创建大量账号；阈值在测试环境放宽，
# 限流算法与登录锁定行为由 test_security.py 用独立实例验证。
os.environ["APPLICRAFT_REGISTER_MAX_ATTEMPTS"] = "1000"
os.environ["APPLICRAFT_LOGIN_MAX_ATTEMPTS"] = "1000"
