# Mens 校园助手

**Windows 桌面版 Mens 1.2.0。** Windows 安装包 `release/Mens-Setup-1.2.0-x64.exe` 已重新构建、升级安装并逐项验收；macOS（Intel/Apple silicon）与 Linux（AppImage/deb）的产物由 GitHub Actions 构建，尚未真机验收；Android/iOS 使用可安装网页版（PWA）。平台矩阵、构建方式与限制见 [平台支持说明](PLATFORMS.md)，实际结果和验收范围见 [验证记录](VERIFICATION.md)。以下保留网页开发/服务器部署的使用说明。

1.0 基于 0.4.1 验证版本，包含圆角透明 Logo、可定制外观、校园服务和数据接口、可选择的插件，以及聊天窗口中的本地 Ollama 模型切换。0.4.x 已验证模型不可用时会明确报错，不会自动转发给云端；模型权重需在本机单独下载。**1.1.0 统一了 Mens 桌面应用、网页、安装包配置和 API 的版本号，并包含 1.0.0 之后加入的流式回答（可停止生成）、按浏览器/桌面配置隔离的历史对话、Word (.docx) 知识库上传、模型下载断点续传、数据备份导出/导入、本机报修记录、窗口位置记忆、后端日志查看、前端单元测试与构建分包、可选的更新检查；安装包已重新构建并完成安装验收。** **1.2.0 进一步加入可选的联网搜索（Bing 免密钥 / Tavily / 博查，逐条消息开关，回答引用网页链接）、跨平台构建（Windows NSIS、macOS dmg/zip、Linux AppImage/deb，同一脚本与 CI 矩阵）、可安装网页版（PWA：清单、离线外壳、iOS 安全区）以及 Windows 之外的凭据存储与图标处理。** 校园统一登录仍未实现。

校园政策与办事流程问答、知识库管理、有限工具调用、校园服务和外部插件管理。前端采用 Vue 3 + TypeScript + Vite + Element Plus + Pinia；后端采用 FastAPI + SQLAlchemy + LangGraph，支持 Qwen3 / DeepSeek、BGE-M3 + Chroma 和 PostgreSQL。

**1.0 可配置发布版（现为 1.1.0）。** 设置页可配置模型 API Key、Ollama 开源模型下载和九类校园 HTTPS JSON 数据接口。未配置的校园类型使用明确标识的演示数据；软件不附带真实学校接口、统一身份认证或模型密钥，校园生产部署仍需学校提供已授权的接口并验收。接入格式见 [校园接口说明](CAMPUS-DATA.md)，验证范围见 [验证记录](VERIFICATION.md)。

## Windows 快速启动

要求 Python 3.10+、Node.js 22+。可直接双击 `install.cmd`，它会安装项目内依赖、检查 LangGraph、执行后端测试并编译前端；任何一步失败会停止。完成后分别双击 `start-backend.cmd` 和 `start-frontend.cmd`，访问 <http://localhost:5173>。前端 CMD 入口提供编译后的页面；这两个终端应保持运行，关闭终端即停止服务。

完整向量依赖可以运行 `install.cmd --full-rag`。已有 `.env` 会被保留，若此前关闭向量检索，需要自行设置 `ENABLE_RAG=true`。

也可以在本目录打开 PowerShell：

```powershell
.\setup.ps1
```

脚本在 `backend/.venv` 中安装 Python 依赖，安装前端依赖并执行构建；首次运行会创建 `backend/.env` 和随机管理员令牌。已有 `.env` 不会被覆盖。脚本需要联网访问官方软件包仓库。

在两个终端分别执行：

```powershell
.\start-backend.ps1
```

```powershell
.\start-frontend.ps1
```

打开 <http://localhost:5173>；接口文档位于 <http://localhost:8000/docs>。在设置页填写 `backend/.env` 内的 `ADMIN_TOKEN` 后，即可管理文档和插件。令牌只保存在当前浏览器会话中。

如系统执行策略不允许运行脚本，可按下面的手动命令启动，无需降低系统执行策略。

## 手动安装

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env，替换 ADMIN_TOKEN 为自行生成的强随机令牌
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```powershell
cd frontend
npm install --cache .npm-cache
npm run dev
```

## 模型与向量检索

基本安装包含 LangGraph。无模型密钥时使用规则规划和知识库原文摘录，不会伪造模型回答。SQLite 首次启动加载三份明确标识的演示资料；PostgreSQL 不自动加载演示知识库。

在设置页保存 Qwen/DeepSeek 的 API Key、HTTPS API 地址和模型名称，再点“测试已保存配置”。桌面版通过 Windows DPAPI 保护新保存的密钥，页面不回显密钥。也兼容在 `backend/.env` 设置 `QWEN_API_KEY` 或 `DEEPSEEK_API_KEY`。`QWEN_MODEL`、`DEEPSEEK_MODEL` 可指定账号实际有权限使用的模型。自动路由对分析/比较问题优先选择已配置的 DeepSeek，其余问题优先选择已配置的 Qwen3；用户可明确选择。模型请求失败会降级到明确标识的原文检索结果。

本地生成模型：先安装并启动 Ollama，在设置页选择 Qwen3 0.6B、Qwen3 1.7B 或 DeepSeek R1 1.5B，选择 Ollama 官方、Hugging Face 或 HF Mirror 下载源。镜像 GGUF 下载固定版本并校验 SHA-256，下载后导入本机 Ollama；可查看进度和取消。选择已安装模型后切换到“本地模型”进行问答。模型文件不随安装包附带。

启用 BGE-M3 + Chroma：

```powershell
cd backend
.venv\Scripts\python -m pip install -r requirements-ai.txt
# 在 .env 设置 ENABLE_RAG=true
```

也可首次运行 `.\setup.ps1 -FullRag`。BGE-M3 默认模型为 `BAAI/bge-m3`，首次加载需要下载模型；可用 `BGE_MODEL_NAME` 指向已下载的本地模型。重启后端后，在知识库页点击“重建索引”。向量初始化/检索失败会保留 SQL 文档并降级关键词检索；更新失败的旧向量不会被当作最新资料返回。

## PostgreSQL 与 Docker Compose

本地默认使用 `backend/data/campus.db`。使用现有 PostgreSQL 时设置：

```dotenv
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/campus_agent
```

用户名和密码中保留字符应 URL 编码。也可使用包含 PostgreSQL、后端和 Nginx 前端的 Compose 配置：

```powershell
Copy-Item .env.example .env
# 编辑根目录 .env，设置 POSTGRES_PASSWORD 和 ADMIN_TOKEN
# Compose 示例密码应使用字母、数字、连字符或下划线
docker compose up --build
```

根目录 `.env` 专用于 Compose，`backend/.env` 专用于手动开发。Compose 默认只绑定 `127.0.0.1:8080`；访问 <http://localhost:8080>。数据库、向量文件和模型缓存使用独立持久化卷。启用完整向量检索时，在根目录 `.env` 设置 `ENABLE_RAG=true`，再重建镜像。Docker 路径尚未在本机运行验证。

## 功能说明

| 功能 | 实现 |
| --- | --- |
| 智能问答 | 政策/流程/FAQ 检索、多轮对话、来源片段、刷新恢复历史 |
| Agent | LangGraph 规划 → 检索或有限工具 → 回答；模型原生 Tool Calling；每次最多一个只读服务调用 |
| 知识库 | TXT/Markdown/PDF 上传、文件替换、删除、向量重建；单文件 5 MB、50 万字符限制 |
| 校园服务 | 九类可配置校园数据；成绩、课表、学分、空教室未配置时为演示数据 |
| 报修 | 用户明确提交；配置接口后 POST 至学校，未配置时仅保存本地演示工单 |
| 插件 | OpenAlex、Crossref、百度百科可选安装；亦支持 HTTPS JSON 清单、启停、卸载和显式调用 |
| 管理与状态 | 管理令牌、模型密钥配置状态、后端健康状态、检索降级状态 |

三个推荐插件是内置连接器，点击安装仅登记配置，不下载或执行第三方 Python/JavaScript。百度百科按用户选择替换原百科方案，以系统浏览器搜索词条，不提供未获授权的内容抓取或 JSON API。OpenAlex/Crossref 通过公开 JSON 接口查询。参照 `examples/plugin-manifest.json` 建立清单，将清单与服务主机写入 `PLUGIN_ALLOWED_HOSTS`。目前插件由管理员显式试调用，普通问答不会自动向外部插件传输消息。清单和服务都只允许公网 HTTPS，禁用重定向/环境代理、固定经过校验的目标 IP 并保留 TLS 主机校验。

## 验证

依赖安装成功后运行：

```powershell
.\verify.ps1
```

包括后端核心逻辑、请求模型、API 集成测试和前端类型检查/生产构建。也可单独执行：

```powershell
cd backend
.venv\Scripts\python -m pytest -q
cd ..\frontend
npm run build
```

无法联网时，可用系统 Python 运行两组隔离测试：

```powershell
cd backend
python -m unittest discover -s tests -p test_core_unit.py -v
python -m unittest discover -s tests -p test_agent_unit.py -v
```

这两组替代了框架/网络/数据库导入，测试生产的核心校验和决策逻辑，不能替代真实 FastAPI、LangGraph、Chroma、模型服务或浏览器联调。没有测试可以保证绝对无 Bug。

## 接入真实校园系统之前

先按 [校园接口说明](CAMPUS-DATA.md) 配置学校授权 HTTPS JSON 网关；若学校接口格式不同，需要适配字段。多人部署前还需增加统一身份认证、按登录用户绑定学号和数据访问权限。演示对话当前使用随机会话 ID 作为访问凭据，只适合本地开发；生产需要用户归属校验、操作审计、限流、HTTPS、数据库迁移与备份策略。真实报修需定义幂等和审批/派工流程。当前版本不包含这些学校相关能力，不应直接公开作为生产校园系统。

源文件和主要接口见 [架构说明](ARCHITECTURE.md)。
