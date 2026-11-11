# AppliCraft 本地部署版

港新及申请制硕士材料生成 Agent（PS / 推荐信 / 学术 CV）的**本地部署版**。

免登录、单用户、用自己的 API Key，所有数据都保存在你本机。
**不需要 Docker、不需要数据库、不需要 Node**（前端已构建好随仓库发布）。
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

## 三、功能一览

- **申请者档案**：维护背景、成绩、科研 / 实习、申请动机等结构化信息。
- **选校评估**：上传目标项目，规则比对匹配度，给出语言分数与建议。
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

- **端口被占用**：编辑 `start.sh` / `start.bat` 里的 `--port 8000` 换成别的端口，访问对应地址。
- **想改前端界面**：`cd frontend && npm install && npm run build`，产物写入 `frontend/dist/`，重启服务即可。无需重新编译后端。
- **清掉所有本地数据**：停止服务后删除 `backend/data/` 目录，下次启动会重新初始化（档案 / 文书会丢失，请先备份）。
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
