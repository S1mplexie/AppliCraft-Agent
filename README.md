# AppliCraft 本地部署版

港新及申请制硕士材料生成 Agent（PS / 推荐信 / 学术 CV）的**本地部署版**。

免登录、单用户、用自己的 API Key，所有数据都保存在你本机。
**不需要 Docker、不需要数据库、不需要 Node**（前端已构建好随仓库发布）。
适合想在自己电脑上跑、用自己的 Key、数据不出本机的用户。

> **不想安装、想直接在线用？** 用网页版：**https://applicraft.cn/**
> 免安装、打开浏览器即用，支持多份档案与申请看板，每天有免费额度。两版怎么选见[第九节](#online)。
>
> **不想用了要卸载？** Windows 双击 `uninstall.bat`，macOS / Linux 运行 `bash uninstall.sh`。
> 运行后输入 `DELETE`（先备份 `backend/data/` 与 `.env` 再删除，推荐）、`PURGE`（不备份彻底删）
> 或其它任意内容（取消，不改任何文件）；备份默认放在项目同级目录 `AppliCraftLocal-backup/`。
> 一条命令清掉 8000 端口服务、Python 虚拟环境依赖和整个项目目录。完整说明见[第八节 · 一键卸载](#uninstall)。

**快速导航**：[一键卸载](#uninstall) · [网页在线版](#online) · 其余章节见下方目录（一 快速开始 / 二 配置 API Key / 三 功能一览 / 四 数据与备份 / 五 目录结构 / 六 常见问题 / 七 环境变量）

---

## 一、运行前提与快速开始（一键启动）

**唯一需要自己安装的是 Python 3.10 或更新版本**（首次启动还需联网装依赖）。其余都不需要：无 Docker、无数据库、无 Node。

### 安装 Python 的注意事项（Windows 必看）

- 从 https://www.python.org/downloads/ 下载，**安装时务必勾选 `Add python.exe to PATH`**。
- 建议关闭 Microsoft Store 的 Python「应用执行别名」：设置 → 应用 → 高级应用设置 → 应用执行别名 → 关掉 `python.exe` / `python3.exe`。这个系统自带的 0 字节快捷方式会被系统误判为 Python，但它根本不能执行 —— 表现就是 `Using Python:` 后面空白、紧接着 `Failed to create the virtual environment`。启动脚本已能自动识别并跳过它，只要装了真 Python 就能正常启动。
- **macOS**：`brew install python@3.12`，或从 python.org 下载安装包。
- **Ubuntu / Debian**：`sudo apt install python3 python3-venv python3-pip`（缺 `python3-venv` 时 `python3 -m venv` 会直接失败）。

### Windows
双击 `start.bat`，或在命令行运行：
```
start.bat
```

### macOS / Linux
```bash
bash start.sh
# 或赋予执行权限后：
chmod +x start.sh && ./start.sh
```

脚本会自动：创建 Python 虚拟环境 → 安装依赖 → 启动服务。
启动后浏览器打开 **http://localhost:8000** 即可使用。

> 首次启动安装依赖需要联网，之后会走缓存，速度很快。

### 重启服务
修改配置（例如 `.env` 里的 API Key）或遇到服务卡住时，无需手动关窗口再双击：
- **Windows**：双击 `restart.bat`；
- **macOS / Linux**：运行 `bash restart.sh`。

脚本会先结束占用 `8000` 端口的旧进程，再重新启动服务（Windows 在新窗口运行，macOS / Linux 以后台进程运行，日志在 `backend/nohup.out`）。

---

## 二、配置你的大模型 API Key

两种等价方式，**二选一**：

1. **网页里填（推荐）**：打开后进入「设置 → 我的大模型 API」，粘贴你的 Key、接口地址与模型名，点「保存配置」。配置会保存在本机 `backend/data/local_llm.json`。
2. **环境变量填**：把 `.env.example` 复制为 `.env`，填入 `APPLICRAFT_LLM_API_KEY` 等后重启。

支持任何 OpenAI 兼容端点（DeepSeek、OpenAI、Moonshot、通义千问、智谱 GLM 等），页面「快捷填入」里有一键预设。

> 没有配置 Key 时，首页会提示你去设置；生成会先保存档案再调用模型。

---

## 三、功能一览

- **申请者档案**：维护背景、成绩、科研 / 实习、申请动机等结构化信息。
- **选校评估**：大模型结合档案与 30 个港新项目官方要求，AI 给出适配等级（保底 / 稳妥 / 冲刺 / 硬性缺口）及判断依据，可一键加入目标项目。
- **文书生成**：基于档案与目标项目生成 PS / 推荐信 / 学术 CV，支持流式输出与改写的迭代。
- **参考文档库**：上传自己的素材作为生成参考；内置港新项目官方资料用于检索项目特色。
- **Skill 市场**：内置若干写作技能，可导入自定义 `.md` / `.zip` 技能注入生成。
- **RAG 检索**：本地知识库（`knowledge/chunks.jsonl`）在生成时检索项目信息，无需联网。

---

## 四、数据与备份

所有数据都在本机，目录为 `backend/data/`：
- `applicraft.db`（SQLite，存放档案 / 文书 / 参考文档索引 / 技能）
- `local_llm.json`（你填的 API Key 配置，明文，仅本机）
- 上传的参考文档、生成的 DOCX 等

**换电脑或重装前，请备份 `backend/data/` 目录。**

知识库（`knowledge/chunks.jsonl`，港新项目官方资料）随仓库发布，用于生成时检索项目特色，无需联网。

---

## 五、目录结构

```
AppliCraftLocal/
├── start.sh / start.bat     # 一键启动（无 Docker）
├── restart.sh / restart.bat # 一键重启服务
├── uninstall.sh / uninstall.bat # 一键卸载（删除依赖 + 整个项目）
├── .env.example             # 环境变量示例（可选）
├── backend/                 # FastAPI 后端（直接 python 启动）
│   ├── app/
│   ├── data/                # 运行时数据（自动生成，git 忽略）
│   └── requirements.txt
├── frontend/                # Vue3 前端（已构建为 dist/，随仓库发布）
│   └── dist/
└── knowledge/               # 港新项目官方资料（RAG 检索源）
```

---

## 六、常见问题

- **`Using Python:` 后面空白 / `Failed to create the virtual environment.`**：说明这台电脑没有真正可用的 Python（最常见是只有 Microsoft Store 的 `python.exe` 别名）。按上面「安装 Python 的注意事项」装好 Python 3.10+ 并勾选 `Add python.exe to PATH`，重新打开一个窗口再双击 `start.bat` 即可。脚本会自动清掉不完整的 `.venv` 并重建，不需要手动删东西；报错时窗口里会打印所选解释器路径和手动排查命令。
- **Linux 上 `python3 -m venv` 失败**：安装 `python3-venv`（`sudo apt install python3-venv python3-pip`），再运行 `bash start.sh`。
- **端口被占用**：编辑 `start.sh` / `start.bat` 里的 `--port 8000` 换成别的端口，访问对应地址。
- **想改前端界面**：`cd frontend && npm install && npm run build`，产物写入 `frontend/dist/`，重启服务即可。无需重新编译后端。
- **清掉所有本地数据**：只想重置数据，可停止服务后删除 `backend/data/` 目录，下次启动会重新初始化（档案 / 文书会丢失，请先备份）；想连程序、依赖一起彻底卸载，请用 `uninstall.sh` / `uninstall.bat`（见第八节，默认会先备份数据）。
- **安全提示**：API Key 以明文保存在本机文件，请妥善保管这台电脑；不要把它部署到公网裸奔，正式对外请自行加 HTTPS 与访问控制。

---

## 七、环境变量（可选）

复制 `.env.example` 为 `.env` 可预先配置大模型，常用项：

| 变量 | 说明 |
|------|------|
| `APPLICRAFT_LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `APPLICRAFT_LLM_API_KEY` | 你的 API Key |
| `APPLICRAFT_LLM_MODEL` | 模型名（如 `deepseek-chat`） |
| `APPLICRAFT_HOST` / `APPLICRAFT_PORT` | 监听地址 / 端口，默认 `0.0.0.0` / `8000` |

也可不配置，启动后到「设置 → 我的大模型 API」里填。

---

<a id="uninstall" name="uninstall"></a>

## 八、一键卸载（删除依赖与整个项目）

不想用了，可以一条命令把服务、依赖和整个项目目录一起清掉：

- **Windows**：双击 `uninstall.bat`
- **macOS / Linux**：`bash uninstall.sh`

运行后会先列出将删除的目录，然后要求**手动输入确认词**：

| 输入 | 行为 |
|------|------|
| `DELETE` | **先备份** `backend/data/` 与 `.env` 到项目同级目录 `AppliCraftLocal-backup/`，再删除（推荐） |
| `PURGE` | 不备份，直接彻底删除，数据不可恢复 |
| 其它 / 直接回车 | 取消，什么都不改动 |

脚本依次执行：

1. 结束占用 `8000` 端口的服务进程；
2. 备份个人数据（仅 `DELETE` 模式）；
3. 删除 `backend/.venv`（**全部 Python 依赖都装在这里**）与 `frontend/node_modules`；
4. 删除整个项目目录 —— 源码、前端 `dist/`、`knowledge/`、`.git`、`.env` 全部包含在内。

> 因为脚本要删除自己所在的目录，最后一步由系统临时目录里的辅助脚本延迟 2 秒执行；Windows 会弹出一个小窗口显示删除结果，macOS / Linux 的日志写在 `/tmp/applicraft-uninstall.log`。

**不会动的东西**：系统里安装的 Python 解释器、全局 pip 缓存以及其它项目。本项目的 Python 依赖全部隔离在 `backend/.venv/`，不污染系统环境，删掉即干净。若备份目录已存在，新的备份会自动加随机/时间戳后缀，不会覆盖旧备份。

**重装 / 找回数据**：重新下载 ZIP 或 clone 仓库后，把备份目录里的 `backend-data/` 内容拷回新项目的 `backend/data/` 即可恢复档案、文书与 Key 配置（`.env` 同理拷回项目根目录）。

> 只想清空档案但保留程序？停止服务后删除 `backend/data/`，下次启动会自动重新初始化。

---

<a id="online" name="online"></a>

## 九、网页在线版（不想装就用这个）

**在线版地址：https://applicraft.cn/**

如果不想在自己电脑上装 Python、也不想自己准备 API Key，可以直接用网页版：打开网站注册即用，同样可以维护申请人档案、做选校评估、生成 PS / 推荐信 / 学术 CV，核心文书生成能力与本地版一致。

| | 本地部署版（本仓库） | 网页在线版 |
|------|------------------|-----------|
| 地址 | 本机 `http://localhost:8000` | https://applicraft.cn/ |
| 安装 | 需 Python 3.10+，双击 `start.bat` / `bash start.sh` | 免安装，浏览器打开即用 |
| 登录 | 免登录、单用户 | 账号登录，数据按账号隔离 |
| 数据 | 全部留在本机 `backend/data/` | 存在服务端，见在线版[隐私政策](https://applicraft.cn/privacy.html) |
| API Key | 必须填自己的 | 每天有系统共享 Key 免费额度，用完可填自己的 Key |
| 适合 | 数据不出本机、想自己改代码 | 换设备也能用、不想折腾环境 |

两版可以一起用：本地版偏「数据完全自己掌控」，网页版偏「随时随地打开」。在线版源码不在本仓库，本仓库只发布本地部署版。

> 在线版相关：[隐私政策](https://applicraft.cn/privacy.html) · [用户协议](https://applicraft.cn/terms.html)
