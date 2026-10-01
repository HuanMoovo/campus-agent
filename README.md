<div align="center">

<img src="docs/img/logo.png" alt="Mens 校园助手" width="104" height="104" />

# Mens 校园助手

**本地优先的校园问答工作台**  
Electron 桌面外壳 + Vue 3 界面 + FastAPI 后端，可在单机上离线运行

<a href="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml"><img src="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml/badge.svg" alt="桌面构建状态" /></a>
<img src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-1.2.1-0e7c74" alt="版本 1.2.1" />
<img src="https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-Apache--2.0-0e7c74" alt="Apache-2.0" />
<img src="https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20PWA-0e7c74" alt="平台" />

**中文** · [English](README.en.md) · [日本語](README.ja.md)

[下载 Windows 安装包](https://github.com/HuanMoovo/campus-agent/releases/latest) ·
[项目介绍页](https://huanmoovo.github.io/campus-agent/)（中文 / English / 日本語） ·
[平台支持](PLATFORMS.md) ·
[验证记录](VERIFICATION.md) ·
[开源协议](LICENSE)

</div>

---

## 这是什么

Mens 把「校园政策与办事流程问答」「本地知识库检索」「校园数据服务」放进一个桌面应用，
并默认让文档、数据与密钥都留在本机。它适合在个人电脑上试用、评估与二次开发；
作为校园生产系统部署前，还需要补齐统一身份认证、审计与数据合规（见[已知限制](#已知限制)）。

### 名称由来

**Mens 是拉丁语，不是英文。** 拉丁语 *mēns*（属格 *mentis*）意为**心智、理性、思维**，
同源词如英语的 mental（心智的）、dementia（失智，字面是"离开心智"）。
它与英文单词 *men*（*man* 的复数，意为"男人们"）没有任何关系，项目名也不含性别指向——
取的是"帮助思考的工具"之意，与"校园助手"的定位相配。

- **本地优先**：知识库、会话、配置与密钥保存在本机（SQLite + 用户数据目录），无需外部数据库，不出网也能问答。
- **如实标注**：未接入真实校园接口时使用明确标识的「演示数据」；模型不可用时降级为知识库原文摘录，不伪造模型回答。
- **可选联网**：联网搜索默认关闭，由管理员在设置页启用（免密钥的 Bing，或 Tavily / 博查），并可逐条消息开关；回答引用来源链接与检索时间。
- **跨平台**：Windows 安装包开箱即用；macOS（Intel / Apple silicon）与 Linux（AppImage / deb）由 CI 构建；手机与平板使用可安装网页版（PWA）。
- **开源**：Apache License 2.0（[`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)），第三方组件清单见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

## 功能说明

### 问答与对话

| 功能 | 说明 |
| --- | --- |
| 流式回答 | 逐字输出，生成过程中界面即时更新 |
| 停止生成 | 随时中断；已生成内容连同「已停止」标记一并保存，历史不会伪造完整答案 |
| 多轮对话 | 保留上下文；刷新或重启后可恢复历史会话 |
| 来源片段 | 回答附带命中的知识库片段，便于核对依据 |
| 会话隔离 | 桌面版按本机配置、网页版按浏览器分别隔离；支持单条删除与一键清空 |
| 回答可信度标记 | 演示数据、降级检索、联网来源等状态在界面上明确标注 |
| 会话导出 | 任意历史对话可导出 Markdown（便于阅读留档）或 JSON（便于脚本处理），内容含来源链接、工具调用与演示数据标注；桌面版走系统保存对话框，网页版直接下载 |

### 知识库与检索

| 功能 | 说明 |
| --- | --- |
| 文档格式 | PDF、Markdown、TXT、Word（.docx），单文件 ≤ 5 MB |
| 文档管理 | 上传、替换、删除；文档数据库是权威数据源 |
| 关键词检索 | 默认方式，无额外依赖，随安装包即可使用 |
| 向量检索（可选） | 启用 RAG 后使用 BGE-M3 + Chroma 做语义检索；向量不可用时自动降级为关键词检索并在界面提示 |
| 索引一致性 | 索引记录版本哈希；删除或更新文档后不会返回过期分段 |
| 演示资料 | 首次启动的 SQLite 会加载三份明确标识的演示文档；PostgreSQL 不加载演示数据 |
| 网页导入 | 把公开网页（HTTPS）的正文抓取并保存为本机文档，之后可离线检索；抓取沿用联网搜索的出站规则（仅 HTTPS、固定到校验过的公网地址、禁跳转、有大小上限），解析到内网地址直接拒绝 |
| 批量上传 | 一次可选择多个文件上传，逐个报告成功与失败原因 |

### 联网搜索（可选，默认关闭）

| 功能 | 说明 |
| --- | --- |
| 开关粒度 | 管理员总开关 + 每条消息的单独开关；关闭时应用完全不发起检索 |
| 服务商 | `auto`（自动）/ Bing（免密钥，中国大陆可直连）/ Tavily / 博查（需 API Key） |
| 结果处理 | 抓取前 1–3 个网页正文（单页 ≤ 2000 字、响应 ≤ 400 KB），与知识库资料统一编号后注入提示词 |
| 引用 | 回答中列出带链接的来源与检索时间 |
| 出站约束 | 仅 HTTPS、固定到已校验的公网 IP（保留 SNI，防 DNS 重绑定）、禁止跳转、有大小与超时上限 |

### 校园服务与报修

| 功能 | 说明 |
| --- | --- |
| 校园数据接口 | 九类可配置的 HTTPS JSON 接口：成绩、课表、学分统计、空教室、报修、校园公告、图书馆、餐饮、校车 |
| 接口配置 | 支持结果路径（JSON 取值路径）与 Bearer 令牌；地址必须 HTTPS |
| 报修 | 用户显式提交；配置接口后 POST 到学校，未配置时仅保存本机记录并标注「演示」 |
| 本机记录 | 报修提交后按时间倒序列出，便于确认提交结果 |
| 演示数据 | 未配置的接口返回明确标识的演示数据，不会假装已接入学校系统 |

### 模型接入

| 方式 | 说明 |
| --- | --- |
| 云端 API | Qwen3 / DeepSeek，填写各自 API Key 与 HTTPS 地址；密钥在本机保存，界面不回显 |
| 自动路由 | 分析 / 比较类问题优先选择已配置的 DeepSeek，其余优先 Qwen3；也可手动指定 |
| 本地模型 | 内置模型目录（Qwen3 0.6B / 1.7B、DeepSeek R1 1.5B），支持 Ollama 官方 / Hugging Face / HF Mirror 下载源 |
| 下载可靠性 | 断点续传、固定版本、SHA-256 校验、导入重试，可查看进度与取消 |
| 降级策略 | 无密钥或模型不可用时，使用规则规划 + 知识库原文摘录，并明确标注 |

### 数据、备份与更新

| 功能 | 说明 |
| --- | --- |
| 备份导出 | 一键导出 zip：知识库文档、会话、模型与校园接口配置；SQLite 用 `VACUUM INTO` 生成一致性快照，附各文件 SHA-256 清单 |
| 备份导入 | 校验后恢复，换机或重装后可完整还原（zip 内含密钥文件，请妥善保管） |
| 更新检查 | 管理员配置 HTTPS 清单后，设置页可检查新版本并打开下载页；留空则该功能完全不联网 |
| 版本一致性 | 构建脚本校验桌面、前端、后端三处版本号一致后才允许打包 |

### 桌面体验

| 功能 | 说明 |
| --- | --- |
| 开箱即用 | 安装包内置 Python 运行时，无需另装 Python / Node / 数据库 |
| 窗口记忆 | 记住窗口大小与位置（越界坐标会被丢弃） |
| 日志与数据目录 | 设置页可查看后端日志、打开数据目录 |
| 外观 | 浅色 / 深色 / 跟随系统，自定义主题色；侧栏与移动端布局分别适配；聊天首页可拖拽旋转的 3D 场景（无 WebGL 或开启「减少动态」时自动降级为静态面板） |
| 界面语言 | 中文 / English / 日本語，默认跟随系统，选择会记住（当前覆盖应用外壳、问答页与外观设置） |
| 运行时校验 | 冻结后端以随机端口 + 一次性令牌启动，桌面外壳校验启动信封后才加载界面 |

### 插件与运维

| 功能 | 说明 |
| --- | --- |
| 内置插件 | OpenAlex 学术检索、Crossref 文献查询、百度百科词条跳转（按需安装，仅登记配置） |
| 插件清单 | 支持 HTTPS JSON 清单；主机需写入 `PLUGIN_ALLOWED_HOSTS` 白名单 |
| 调用方式 | 由管理员显式试调用；插件只能返回 JSON，普通问答不会自动向外部插件发送消息 |
| 出站约束 | 与联网搜索相同的 HTTPS / 固定 IP / 禁跳转 / 限额策略 |

## 平台支持

| 平台 | 状态 | 交付物与数据目录 |
| --- | --- | --- |
| Windows 10/11 x64 | **已构建并真机验收** | `Mens-Setup-1.2.1-x64.exe`（NSIS，用户级安装到 `%LOCALAPPDATA%\Programs\Mens`），数据在 `%APPDATA%\CampusAgent` |
| macOS 12+（Intel） | CI 构建，未真机验收 | `Mens-1.2.1-x64.dmg` / `.zip`；未签名未公证，首次打开需右键「打开」 |
| macOS 12+（Apple silicon） | CI 构建，未真机验收 | `Mens-1.2.1-arm64.dmg` / `.zip`；数据在 `~/Library/Application Support/CampusAgent` |
| Linux x64 | CI 构建，未真机验收 | `Mens-1.2.1-x86_64.AppImage`（免安装）、`Mens-1.2.1-amd64.deb`；数据在 `~/.config/CampusAgent` |
| Android / iOS | 不提供原生应用 | 使用可安装网页版（PWA）：浏览器打开部署好的站点 → 添加到主屏幕；推理由服务端完成 |

> 「已验收」指在对应系统上真实安装、启动并完成界面检查；「CI 构建」指由 GitHub Actions 生成产物但尚未真机运行。
> 平台矩阵、构建命令与原因说明见 [PLATFORMS.md](PLATFORMS.md)，实际结果与验收范围见 [VERIFICATION.md](VERIFICATION.md)。

### Release 资产（v1.2.1）

| 资产 | 大小 | 说明 |
| --- | --- | --- |
| `Mens-Setup-1.2.1-x64.exe`（+ `.blockmap`） | 126,409,577 B | Windows 安装包，本机安装验收使用的就是这一份 |
| `Mens-1.2.1-x64.dmg` / `Mens-1.2.1-x64.zip` | ≈ 158 MB | macOS Intel |
| `Mens-1.2.1-arm64.dmg` / `Mens-1.2.1-arm64.zip` | ≈ 151 MB | macOS Apple silicon |
| `Mens-1.2.1-x86_64.AppImage` / `Mens-1.2.1-amd64.deb` | 191 MB / 153 MB | Linux |

安装包内含 `LICENSE`、`NOTICE` 与 `THIRD-PARTY-NOTICES.md`（安装后位于 `resources/`）。

## 快速开始

### 1. 安装 Windows 桌面版

下载 [最新 Release](https://github.com/HuanMoovo/campus-agent/releases/latest) 中的
`Mens-Setup-1.2.1-x64.exe`，双击安装（用户级安装，无需管理员权限），从开始菜单或桌面启动。
首次启动后在设置页填写模型 API Key（或选择 Ollama 本地模型）即可开始问答。

### 2. 从源码构建桌面版

三个平台使用同一脚本，产物写入 `release/`：

```bash
# 当前平台（自动判断架构）
python scripts/build_desktop.py

# 指定目标
python scripts/build_desktop.py --os mac   --arch arm64
python scripts/build_desktop.py --os linux --arch x64

# 常用开关
#   --skip-install   使用已装好的依赖（快速重建）
#   --directory      只生成未打包的应用目录
#   --full-rag       一并打包向量检索依赖（体积更大）
```

脚本会依次执行后端 / 前端 / 桌面三套测试、冻结后端、再用 electron-builder 打包；
任一步失败即停止，不会产出安装包。

### 3. 源码开发运行（网页版）

Windows 可直接双击 `install.cmd`（安装依赖、检查 LangGraph、跑后端测试、编译前端），
随后分别运行 `start-backend.cmd` 与 `start-frontend.cmd`，访问 <http://localhost:5173>。

也可以手动执行：

```powershell
# 后端（终端一）
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env          # 把 ADMIN_TOKEN 改成自行生成的强随机值
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（终端二）
cd frontend
npm install
npm run dev
```

前端 <http://localhost:5173>，接口文档 <http://localhost:8000/docs>。
在设置页填入 `backend/.env` 中的 `ADMIN_TOKEN` 后即可管理文档与插件（令牌只保存在当前浏览器会话）。

### 4. Docker 部署（服务器 / PWA）

```bash
cp .env.example .env          # 设置 POSTGRES_PASSWORD 与 ADMIN_TOKEN
docker compose up -d --build
docker compose logs -f backend
```

打开 <http://localhost:8080>（栈只绑定 `127.0.0.1:8080`）。随后在手机浏览器打开该地址并「添加到主屏幕」，
即得到可安装网页版（PWA）。

栈由 PostgreSQL + 后端 + Nginx 组成：

| 服务 | 镜像 | 说明 |
| --- | --- | --- |
| `database` | `postgres:16-alpine` | 通过健康检查后后端才启动；数据在 `postgres_data` 卷 |
| `backend` | `python:3.11-slim` | 以非 root 用户运行；数据在 `backend_data`，模型缓存在 `model_cache`；健康检查 `/api/health` |
| `frontend` | `nginx:alpine` | 提供构建好的 Vue 前端，并把 `/api/` 反向代理到后端；上传上限 6 MB |

要点：

- 根目录 `.env` 的变量会透传给后端，联网搜索、更新清单与插件白名单的配置方式与本地安装一致（见[配置参考](#配置参考)）。
- `ENABLE_RAG=true` 会把向量检索依赖打进镜像（`INSTALL_VECTOR` 构建参数），需要重新构建。
- 数据都在命名卷里：`docker compose down` 保留数据，`docker compose down -v` 删除数据；升级前请先备份数据库。
- 该 compose 面向单机或可信网络；对公网开放仍需自行加上 HTTPS、前置认证与限流。
- **本机已实测**（Docker Desktop 29.1.3）：两个镜像构建通过；database / backend / frontend 三个服务全部启动，前两者通过健康检查；`http://localhost:8080/` 返回 200，`/api/health` 返回 `{"status":"ok",...}`；后端在容器内确认连接 **PostgreSQL 16.15**；真实浏览器打开「Mens 工作台」，零失败请求、零页面错误。

### 5. 不用 Docker 的手机 / 平板（PWA）

在任何可达的服务器上部署后端（见上一节的镜像构成，或直接在服务器上按第 3 节的方式运行），
手机浏览器打开站点后「添加到主屏幕」，即可获得全屏、独立图标的类应用体验。

## 配置参考

### backend/.env

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///backend/data/campus.db` | 也可用 PostgreSQL：`postgresql+psycopg://user:pass@host:5432/campus_agent`（保留字符需 URL 编码） |
| `ADMIN_TOKEN` | 空 | 管理令牌；设置页凭它管理文档与插件，部署前必须替换 |
| `QWEN_API_KEY` / `DEEPSEEK_API_KEY` | 空 | 云端模型密钥（也可在设置页保存） |
| `QWEN_BASE_URL` / `DEEPSEEK_BASE_URL` | 官方 HTTPS 地址 | 必须是 HTTPS |
| `QWEN_MODEL` / `DEEPSEEK_MODEL` | `qwen3-235b-a22b` / `deepseek-chat` | 改成账号实际有权限的模型 |
| `ENABLE_RAG` | `false` | 启用 BGE-M3 + Chroma 向量检索（需先安装 `requirements-ai.txt`） |
| `BGE_MODEL_NAME` | `BAAI/bge-m3` | 也可指向已下载到本机的模型 |
| `PLUGIN_ALLOWED_HOSTS` | 空 | 允许插件访问的主机白名单（逗号分隔） |
| `CORS_ORIGINS` | `http://localhost:5173` | 网页版跨域来源 |
| `WEB_SEARCH_ENABLED` | `false` | 联网搜索总开关 |
| `WEB_SEARCH_PROVIDER` | `auto` | `auto` / `bing`（免密钥）/ `tavily` / `bocha` |
| `WEB_SEARCH_API_KEY` | 空 | Tavily 或博查的密钥 |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 每次检索返回的结果条数 |
| `WEB_SEARCH_FETCH_PAGES` | `2` | 抓取正文的网页数（最多 3） |
| `UPDATE_MANIFEST_URL` | 空 | 可选的 HTTPS 更新清单，例如 `{"version":"1.2.1","url":"https://…","notes":"…"}`；留空则不做更新检查 |

桌面版由外壳注入 `CAMPUS_DESKTOP_MODE`、`CAMPUS_DESKTOP_TOKEN`、`CAMPUS_DESKTOP_NONCE`、
`CAMPUS_DATA_DIR`、`CAMPUS_FRONTEND_DIR`、`CAMPUS_CONFIG_FILE`（无需手填；仅接受绝对路径）。

### 模型与向量检索

- 设置页保存密钥后点「测试已保存配置」验证连通性；Windows 用 DPAPI 加密保存新密钥，页面不回显。
- 本地模型：先安装并启动 Ollama，在设置页选择模型与下载源；GGUF 下载固定版本并校验 SHA-256 后导入本机 Ollama。模型文件不随安装包附带。
- 启用向量检索：

  ```powershell
  cd backend
  .venv\Scripts\python -m pip install -r requirements-ai.txt
  # 在 .env 设置 ENABLE_RAG=true，重启后端后在知识库页点「重建索引」
  ```

  首次加载 `BAAI/bge-m3` 需要联网下载；向量初始化或检索失败会保留文档并降级为关键词检索。

### 校园数据接口

九类接口的字段、取值路径与示例见 [CAMPUS-DATA.md](CAMPUS-DATA.md)。要点：

- 只接受 HTTPS JSON；支持 Bearer 令牌与结果路径。
- 未配置的接口使用明确标识的演示数据；项目**不附带**任何真实学校接口、统一身份认证或模型密钥。
- 生产部署需学校提供已授权接口并完成验收；多人使用前还需补齐统一身份认证、按用户绑定学号、访问审计与限流（详见 [校园数据说明](CAMPUS-DATA.md) 与 [架构说明](ARCHITECTURE.md)）。

## 架构与安全边界

### 技术栈

- **前端**：Vue 3 + TypeScript + Vite + Element Plus + Pinia；构建时按依赖分包（主包约 71 KB）。
- **后端**：FastAPI + SQLAlchemy + LangGraph；默认 SQLite 单文件数据库，可选 PostgreSQL。
- **桌面**：Electron 外壳 + PyInstaller 冻结的 CPython（安装包内置运行时）。
- **可安装网页版**：清单（manifest）、离线外壳（service worker）与 iOS 安全区适配。

### 安全设计

- **本机优先**：桌面版后端只监听 `127.0.0.1` 的随机端口，每次启动生成一次性令牌；外壳注入额外请求头并收紧 Electron 配置（`nodeIntegration:false`、`contextIsolation:true`、`sandbox:true`、`webSecurity:true`、禁用 `webviewTag`），外部页面拿不到这些接口。
- **出站纪律**（插件 / 联网搜索 / 更新检查共用）：仅 HTTPS + 443；连接固定到解析并经校验的公网地址（保留 SNI，防 DNS 重绑定）；禁止跳转；有响应大小与超时上限；忽略系统代理环境变量（`trust_env=False`）；解析到内网地址直接拒绝。
- **密钥存储**：Windows 用 DPAPI 加密；macOS / Linux 无等价系统接口，改为 `0600` 权限的明文文件（同一用户可读）——这一点在 [PLATFORMS.md](PLATFORMS.md) 中明确写出。
- **备份**：导出 zip 内含密钥文件，请自行妥善保管；导入前校验 SHA-256 清单。
- **不伪造**：演示数据、降级检索、联网来源等状态一律在界面标注。

### 目录结构

```text
campus-agent/
├─ backend/         FastAPI 后端（app/ 源码、tests/ 测试、requirements*.txt）
├─ frontend/        Vue 3 前端（src/、tests/、dist/ 构建产物）
├─ desktop/         Electron 外壳（main.cjs、preload.cjs、lib/、assets/ 图标）
├─ scripts/         构建与打包（build_desktop.py、install.py、create_icon.py 等）
├─ docs/            项目介绍页（GitHub Pages，中 / 英 / 日）
├─ assets/          品牌源图
├─ examples/        插件清单示例
├─ compose.yaml     Docker 部署（PostgreSQL + 后端 + Nginx）
├─ PLATFORMS.md     平台矩阵与构建方式
├─ DESKTOP.md       桌面版说明
├─ ARCHITECTURE.md  架构与主要接口
├─ CAMPUS-DATA.md   校园接口接入格式
├─ VERIFICATION.md  验证记录（含大小、SHA-256 与验收范围）
└─ LICENSE / NOTICE / THIRD-PARTY-NOTICES.md
```

## 测试与验证

```powershell
# 后端（260 个用例，含 65 个子测试）
cd backend
.venv\Scripts\python -m pytest -q

# 前端（13 个单元测试）与生产构建
cd ..\frontend
npm test
npm run build

# 桌面外壳（8 个测试）
cd ..\desktop
npm test

# 一次跑完以上全部（Windows）
.\verify.ps1
```

离线环境可用系统 Python 运行两组纯逻辑测试（不依赖框架 / 网络 / 数据库）：

```powershell
cd backend
python -m unittest discover -s tests -p test_core_unit.py -v
python -m unittest discover -s tests -p test_agent_unit.py -v
```

这些测试覆盖核心校验与决策逻辑，但不能替代真实 FastAPI、LangGraph、Chroma、模型服务或浏览器联调；
没有任何测试能保证绝对无 Bug。已完成的验证范围、安装包大小与 SHA-256 见 [VERIFICATION.md](VERIFICATION.md)。

## 界面

| 聊天（含联网来源） | 设置（联网搜索） |
| --- | --- |
| <img src="docs/img/chat-web-search.png" alt="聊天界面：联网搜索结果与来源链接" /> | <img src="docs/img/settings-web-search.png" alt="设置界面：联网搜索配置" /> |

| 校园服务（报修与本机记录） |
| --- |
| <img src="docs/img/campus-services.png" alt="校园服务界面：报修与本机记录" /> |

## 已知限制

- **macOS / Linux 产物未真机验收**：由 CI 构建，尚未在真机上安装运行。
- **未签名、未公证**：没有发行者证书，Windows / macOS 首次打开可能出现系统提示；正式分发前应配置签名。
- **校园接口与统一登录**：项目不附带任何真实学校接口、统一身份认证或模型密钥；生产部署需学校提供已授权接口并验收。
- **云端模型与联网搜索**：需要各自的 API Key（联网搜索的 Bing 通道免密钥）；搜索服务端的可用性受网络环境限制。
- **原生 Android / iOS 应用**：不在本项目范围，原因见 [PLATFORMS.md](PLATFORMS.md)（Python 后端无法随应用上架移动平台）。
- **一键更新**：更新检查只提示版本差异并打开下载页，不做自动下载与静默安装。
- **多人部署**：当前演示会话以随机会话 ID 作为访问凭据，仅适合本地开发；生产需要用户归属校验、操作审计、限流、HTTPS、数据库迁移与备份策略。

## 开源协议

本项目以 **Apache License 2.0** 发布（[`LICENSE`](LICENSE)），版权与归属声明见 [`NOTICE`](NOTICE)。

- **可以**：自由使用、修改、再分发，包括商业使用、校园内部部署与闭源的修改版本。
- **需要**：保留版权、许可证与 NOTICE 声明，标注修改过的文件；本许可证不授予项目名称或商标的使用权。
- **无担保**：软件按「现状」提供，不附带任何明示或默示担保。
- **第三方组件**：安装包内含 Electron、Chromium、CPython、PyInstaller、FastAPI、Vue、Element Plus 等，各自按原许可证分发，清单见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [项目介绍页](https://huanmoovo.github.io/campus-agent/) | 中 / 英 / 日三语的图文介绍、平台矩阵与已知限制 |
| [PLATFORMS.md](PLATFORMS.md) | 平台矩阵、构建命令、macOS / Linux 凭据存储差异、移动端方案原因 |
| [DESKTOP.md](DESKTOP.md) | 桌面版运行方式、数据目录、IPC 与安全设置 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构、模块职责与主要接口 |
| [CAMPUS-DATA.md](CAMPUS-DATA.md) | 九类校园接口的字段与接入格式 |
| [VERIFICATION.md](VERIFICATION.md) | 每批改动的验证方式、安装包大小与 SHA-256、未验证范围 |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | 第三方组件与许可证清单 |
