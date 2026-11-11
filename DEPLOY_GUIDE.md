# AppliCraft 服务器登录与部署指引

> 面向对象：接手部署的另一个 Agent 或运维同学。
> 目标：在**不破坏线上数据与密钥**的前提下，把仓库最新代码发布到 `43.136.175.87` 并验证生效。
> 关键前提：**服务器上的 `~/applicraft` 不是 git 仓库，是一份源码快照**。不要假设能 `git pull`。

---

## 0. 一句话流程

```
本地跑测试 → tar 源码同步到服务器（排除 .env / data）→ sudo bash deploy.sh → 健康检查 + 抽查验证
```

全程可重复执行（幂等）：重复同步、重复部署都不会丢数据，`data/` 与 `.env` 始终保留。

---

## 1. 连接信息

| 项 | 值 |
|---|---|
| 主机 | `43.136.175.87` |
| 登录用户 | `ubuntu` |
| SSH 别名（推荐） | `applicraft-server` |
| 私钥 | `~/.ssh/applicraft_deploy_ed25519` |
| sudo | **免密**（`sudo -n true` 应成功） |
| 应用目录 | `/home/ubuntu/applicraft` |
| 容器名 | `applicraft` |
| 对外端口 | `8000` |
| 健康检查 | `GET http://127.0.0.1:8000/api/health` |

本机 `~/.ssh/config` 已有别名（其他机器上没有就自己加）：

```
Host applicraft-server
    HostName 43.136.175.87
    User ubuntu
    IdentityFile ~/.ssh/applicraft_deploy_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
```

连不上时的排查顺序：

1. 私钥是否存在且权限为 `600`：`ls -l ~/.ssh/applicraft_deploy_ed25519`。
2. 是否走了别名：直接用 `ubuntu@43.136.175.87` 会**找不到私钥**，必须用 `applicraft-server`。
3. 报 `Permission denied (publickey)`：说明这台机器的公钥不在服务器 `~/.ssh/authorized_keys` 里，需要把公钥追加进去（服务器上以 `ubuntu` 用户操作，无需 sudo）：

```bash
ssh-copy-id -i ~/.ssh/applicraft_deploy_ed25519.pub applicraft-server
```

4. 命令必须能在**非交互环境**跑完，统一加：`ssh -o BatchMode=yes -o ConnectTimeout=15 applicraft-server '...'`。

---

## 2. 先读懂服务器拓扑（动手前必看）

```
/home/ubuntu/applicraft/
├── backend/                 # Python 源码（FastAPI + LangGraph）
├── frontend/                # Vue 3 源码（服务器内 npm run build）
├── knowledge/               # 知识库，chunks.jsonl 会被打进镜像 /knowledge
├── miniprogram/             # 微信小程序源码（不影响后端部署）
├── .env                     # ★ 线上密钥与管理员账密（600）——绝不覆盖
├── data/                    # ★ SQLite + 用户上传 + 文档版本——绝不覆盖
├── Dockerfile.server        # ★ 服务端专用构建文件（不在 git 里）
├── deploy.sh                # ★ 服务端部署脚本（不在 git 里）
└── verify.py                # 服务端验证脚本（不在 git 里）
```

`deploy.sh` 实际做的 5 件事：

1. `docker build -f Dockerfile.server -t applicraft:latest`（pip 走腾讯云镜像源）
2. `docker rm -f applicraft`（旧容器，数据卷保留）
3. `docker run -d --name applicraft --restart unless-stopped -p 8000:8000 --env-file .env -v data:/app/data`
4. 轮询 `/api/health` 最多 40 次（成功打印 `HEALTH_OK`）
5. 用容器内 `python -m app.cli sync-admin` 同步默认管理员（读 `.env`，不打印密码）→ 打印 `DEPLOY_OK`

> **不要用 `docker compose`**：服务器没有 compose 插件（只有过时的独立版 `docker-compose` v1.29.2），且 `docker-compose.yml` 不是线上实际部署入口。线上唯一入口是 `deploy.sh`。

---

## 3. 部署前自检

```bash
# 3.1 服务器可达 + 免密 sudo
ssh -o BatchMode=yes -o ConnectTimeout=15 applicraft-server \
  'echo CONNECTED; sudo -n true && echo SUDO_OK; sudo docker ps --format "{{.Names}}|{{.Status}}"'

# 3.2 关键文件在位（缺一个都别继续）
ssh applicraft-server 'cd /home/ubuntu/applicraft && \
  ls -l .env data Dockerfile.server deploy.sh knowledge/chunks.jsonl | head'

# 3.3 Dockerfile.server 必须包含知识库注入（否则 RAG 静默失效）
ssh applicraft-server 'grep -n "KNOWLEDGE_DIR\|COPY knowledge" /home/ubuntu/applicraft/Dockerfile.server'
```

本地（推送前）：

```bash
# Windows Git Bash
cd /d/AppliCraft/backend && .venv/Scripts/python.exe -m pytest -q
# Linux / macOS
cd backend && .venv/bin/python -m pytest -q
```

测试必须全绿再部署。当前基线：**65 passed**。

---

## 4. 标准部署（三步）

### 4.1 提交并推送（可选但推荐）

```bash
cd /d/AppliCraft
git add -A && git commit -m "feat/fix: 说明"
```

> Windows 本机 `git push` 会因 schannel 吊销检查失败（`CRYPT_E_NO_REVOCATION_CHECK`），临时绕过：

```bash
git config http.sslVerify false
git push origin main
git config --unset http.sslVerify   # 立即恢复，别长期关闭
```

### 4.2 同步源码到服务器

在**仓库根目录**执行。排除列表缺一不可：

```bash
cd /d/AppliCraft
tar czf - \
  --exclude='.git' --exclude='.env' --exclude='data' \
  --exclude='node_modules' --exclude='.venv' --exclude='frontend/dist' \
  --exclude='__pycache__' --exclude='backup_cred_change' \
  backend frontend knowledge miniprogram \
  Dockerfile docker-compose.yml .dockerignore .env.example .gitignore \
  | ssh -o ConnectTimeout=15 applicraft-server 'tar xzf - -C /home/ubuntu/applicraft'
```

- **显式列出要同步的目录**，不要用 `tar czf - .`——否则会把 `.env` 一起覆盖上去，线上密钥立刻失效。
- 不同步 `Dockerfile.server` / `deploy.sh` / `verify.py`（服务端专用，本地没有）；只有当你**改了构建逻辑**时才单独覆盖。
- 同步后抽查关键文件是否真的到位：

```bash
ssh applicraft-server 'cd /home/ubuntu/applicraft && \
  ls -l backend/app/knowledge/retriever.py knowledge/chunks.jsonl && \
  grep -n "pypdf\|multipart" backend/requirements.txt'
```

### 4.3 重建并重启容器

```bash
ssh -o ConnectTimeout=15 applicraft-server 'sudo bash /home/ubuntu/applicraft/deploy.sh'
```

- 耗时约 2–5 分钟（npm install + pip install + 构建）。
- 长命令请放后台执行并等结果，不要中途打断（会留下半成品容器）。
- 判定成功：输出里有 **`HEALTH_OK`** 和 **`DEPLOY_OK`**，且 health 返回 `{"status":"ok","db_ok":true,"llm_configured":true}`。

---

## 5. 验证清单（必做）

```bash
# 5.1 健康检查与容器状态
ssh applicraft-server 'curl -s http://127.0.0.1:8000/api/health; echo; \
  sudo docker ps --filter name=applicraft --format "{{.Names}} {{.Status}}"'

# 5.2 接口是否注册（★ 不要用 app.routes 判断，见第 6 节坑 4）
# 直接列出全部 API 路径，确认目标接口在其中
ssh applicraft-server 'curl -s http://127.0.0.1:8000/openapi.json' \
  | grep -o '"/api/[^"]*"' | sort -u
# 期望能看到例如 "/api/documents/{doc_id}/regenerate"

# 5.3 前端是否是新包（资源哈希变化 + 特征文案存在）
ssh applicraft-server 'curl -s http://127.0.0.1:8000/ | grep -o "assets/[^\"]*"; \
  sudo docker exec applicraft sh -c "grep -l \"按建议重新生成\" /app/static/assets/*.js"'

# 5.4 知识库是否进镜像（RAG 依赖）
ssh applicraft-server 'sudo docker exec applicraft sh -c "wc -l /knowledge/chunks.jsonl"'

# 5.5 出错时看日志
ssh applicraft-server 'sudo docker logs applicraft --tail 100'
```

---

## 6. 红线与常见坑

1. **绝不覆盖 `.env`**：里面有 DeepSeek Key、管理员账密、会话密钥。同步时必须排除。
2. **绝不覆盖/删除 `data/`**：SQLite 业务库、用户上传的简历、所有文书的版本历史都在这里，丢了无法恢复。
3. **`Dockerfile.server` 与仓库 `Dockerfile` 必须同步演进**：前者不在 git 里，是服务端唯一构建入口。若你在仓库 `Dockerfile` 里新增了 `COPY` 或 `ENV`（例如知识库目录），必须同样改服务端的 `Dockerfile.server`，否则线上缺文件且**不会报错，只会功能静默缺失**。
4. **不要用 `app.routes` 判断路由是否注册**：新版 FastAPI（0.162）把 `include_router` 的路由包成 `_IncludedRouter` 聚合对象，顶层 `app.routes` 看不到子路径。用 `openapi.json` 验证。
5. **前端发版后页面"没变化"**：`index.html` 已强制 `Cache-Control: no-cache`，但浏览器可能还开着旧标签页。让用户 **Ctrl+F5 强刷**；不要靠"再多发一版"解决。
6. **前后端字段名错配只表现为 422**：Pydantic 默认忽略多余字段，驼峰/下划线不一致时字段被静默丢弃。看 422 的 `detail` 数组，别猜。
7. **`frontend/dist` 不要上传**：服务器构建阶段自己 `npm run build`。上传 dist 既无用又容易造成"看起来用了旧包"的错觉。
8. **`knowledge/` 必须提交进 git 且同步到服务器**：镜像靠 `COPY knowledge/ /knowledge/` 打包，`.dockerignore` 只保留 `chunks.jsonl`。缺了它 RAG 会安全降级为不注入（不会崩，但你不知道它坏了）——用 5.4 验证。
9. **不要动服务器上其它容器/服务**：`deploy.sh` 只操作 `applicraft` 容器，保持这个边界。
10. **敏感信息不进日志**：`deploy.sh` 的 sync-admin 不打印密码，用其他命令时也不要 `cat .env` 到终端回显。

---

## 7. 回滚

镜像只有 `applicraft:latest` 一个 tag，`deploy.sh` 会覆盖它。所以**回滚靠代码回退后重建**，不是靠镜像 tag：

```bash
# 1) 本地回退代码（优先 revert，保留历史；不要用会丢弃未提交改动的 checkout）
cd /d/AppliCraft && git log --oneline -5
git revert <坏提交>

# 2) 重新同步 + 重建（同 4.2 / 4.3）
# 3) 数据不受影响：data/ 与 .env 始终在服务器上，未被触碰
```

若想保留镜像级回滚能力，可在部署前手动打备份 tag（可选）：

```bash
ssh applicraft-server 'sudo docker tag applicraft:latest applicraft:prev 2>/dev/null; echo tagged'
```

回滚时用 `applicraft:prev` 按 `deploy.sh` 第 3 步同样的 `docker run` 参数启动即可（注意 `--env-file` 与 `-v data:/app/data` 必须一致）。

---

## 8. 故障速查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `Permission denied (publickey)` | 用了 IP 而非别名，或公钥未授权 | 用 `applicraft-server` 别名；`ssh-copy-id` 加公钥 |
| `docker ps` 报权限不足 | `ubuntu` 不在 docker 组 | 所有 docker 命令加 `sudo`（已免密） |
| `HEALTH_TIMEOUT` | 启动异常（依赖缺失/配置错误） | 看 `sudo docker logs --tail 60 applicraft` |
| 页面 502 / 打不开 | 容器未起或端口占用 | `sudo docker ps -a`；`sudo docker logs applicraft` |
| 登录后功能正常但页面是旧版 | 浏览器缓存旧 JS | Ctrl+F5；核对 5.3 的资源哈希 |
| 生成文书不引用项目资料 | 镜像缺 `/knowledge` | 执行 5.4；确认 `Dockerfile.server` 有 COPY knowledge |
| 点按钮报 422 | 前后端字段名不一致 | 看响应 `detail`；对齐序列化字段名 |
| pip 安装超时 | 用了仓库 `Dockerfile`（默认源） | 必须用 `Dockerfile.server`（腾讯云源） |
| 同步后线上配置异常 | 误覆盖了 `.env` | 从备份恢复 `.env`，重新 `deploy.sh` |

---

## 9. 附录：只改一个文件时的轻量同步

改单个后端文件（例如 `backend/app/knowledge/retriever.py`）时，可以跳过 tar，直接用 scp：

```bash
scp -o ConnectTimeout=12 /d/AppliCraft/backend/app/knowledge/retriever.py \
  applicraft-server:/home/ubuntu/applicraft/backend/app/knowledge/retriever.py
ssh applicraft-server 'sudo bash /home/ubuntu/applicraft/deploy.sh'
```

注意：**改前端任何文件都必须走完整 tar 同步**（服务器要重新 `npm run build`），scp 单个 `.vue` 文件不会反映到页面上。
