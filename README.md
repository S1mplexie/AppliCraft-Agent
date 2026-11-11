# AppliCraft 本地部署版

港新及申请制硕士材料生成 Agent（PS / 推荐信 / 学术 CV）的**本地部署版**。

与网页版（多租户 SaaS）是**两个独立项目**：
- 网页版：`D:\AppliCraft`（部署在服务器，多用户、登录、计费）
- 本地版（本目录）：**免登录、单用户、用自己的 API Key**，数据全部保存在你本机

本版**不需要 Docker、不需要数据库、不需要 Node**（前端已构建好随仓库发布）。
适合想在自己电脑上跑、用自己的 Key、数据不出本机的用户。

---

## 一、快速开始（一键启动）

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

---

## 二、配置你的大模型 API Key

两种等价方式，**二选一**：

1. **网页里填（推荐）**：打开后进入「设置 → 我的大模型 API」，粘贴你的 Key、接口地址与模型名，点「保存配置」。配置会保存在本机 `backend/data/local_llm.json`。
2. **环境变量填**：把 `.env.example` 复制为 `.env`，填入 `APPLICRAFT_LLM_API_KEY` 等后重启。

支持任何 OpenAI 兼容端点（DeepSeek、OpenAI、Moonshot、通义千问、智谱 GLM 等），页面「快捷填入」里有一键预设。

> 没有配置 Key 时，首页会提示你去设置；生成会先保存档案再调用模型。

---

## 三、数据与备份

所有数据都在本机，目录为 `backend/data/`：
- `applicraft.db`（SQLite，存放档案 / 文书 / 参考文档索引 / 技能）
- `local_llm.json`（你填的 API Key 配置，明文，仅本机）
- 上传的参考文档、生成的 DOCX 等

**换电脑或重装前，请备份 `backend/data/` 目录。**

知识库（`knowledge/chunks.jsonl`，港新项目官方资料）随仓库发布，用于生成时检索项目特色，无需联网。

---

## 四、目录结构

```
AppliCraftLocal/
├── start.sh / start.bat     # 一键启动（无 Docker）
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

## 五、常见问题

- **端口被占用**：编辑 `start.sh` / `start.bat` 里的 `--port 8000` 换成别的端口，访问对应地址。
- **想改前端界面**：`cd frontend && npm install && npm run build`，产物写入 `frontend/dist/`，重启服务即可。无需重新编译后端。
- **清掉所有本地数据**：停止服务后删除 `backend/data/` 目录，下次启动会重新初始化（档案/文书会丢失，请先备份）。
- **安全提示**：API Key 以明文保存在本机文件，请妥善保管这台电脑；不要把它部署到公网裸奔，正式对外请自行加 HTTPS 与访问控制。

---

## 六、与网页版的区别

| 维度 | 本地版（本目录） | 网页版（D:\AppliCraft） |
|------|----------------|------------------------|
| 部署 | 本机纯 Python，双击启动 | 服务器多租户 SaaS |
| 登录 | 免登录（单用户） | 账号密码 / 注册 |
| API Key | 你自己的 Key（本地保存） | 系统共享 Key + 用户自带 Key |
| 数据库 | SQLite（本机文件） | PostgreSQL |
| 计费 | 无（你承担全部费用） | 每日免费额度 + 自带 Key |
| Docker | 不需要 | 使用（容器化部署） |

功能（档案、选校评估、文书生成、参考文档库、Skill 市场、RAG 检索）两者一致。
