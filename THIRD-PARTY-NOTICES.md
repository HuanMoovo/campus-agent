# 第三方组件与许可证

Mens 校园助手本体以 **Apache License 2.0**（见 [LICENSE](LICENSE)，版权与归属声明见 [NOTICE](NOTICE)）发布。
安装包里同时包含下列第三方组件，它们各自按其原许可证分发，版权归各自的作者。以下为主要组件
（版本以构建时的 `package-lock.json` / `requirements-desktop.txt` 为准）。

## 桌面外壳与运行时

| 组件 | 许可证 | 说明 |
| --- | --- | --- |
| Electron | MIT | 桌面外壳 |
| Chromium | BSD-3-Clause 及若干其他许可 | Electron 内置的浏览器引擎 |
| Node.js | MIT | Electron 内置的运行时 |
| CPython | PSF-2.0 | 冻结后端内置的解释器 |
| PyInstaller | GPL-2.0-or-later（含 Bootloader 例外） | 将后端冻结为单目录应用；其例外条款允许分发任意许可证的应用 |

## 后端（随应用冻结分发）

| 组件 | 许可证 |
| --- | --- |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic / pydantic-settings | MIT |
| SQLAlchemy | MIT |
| LangGraph / LangChain Core / langgraph-sdk | MIT |
| httpx / httpcore | BSD-3-Clause |
| pypdf | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| psycopg（PostgreSQL 驱动，可选） | LGPL-3.0 |
| pytest | MIT（仅开发/构建时，不随应用分发） |
| Pillow | MIT-CMU（仅构建时用于生成图标，不随应用分发） |

可选构建（`--full-rag`）还会包含 ChromaDB（Apache-2.0）、sentence-transformers（Apache-2.0）、
Transformers（Apache-2.0）、PyTorch（BSD-3-Clause）与 FlagEmbedding（MIT）。

## 前端

| 组件 | 许可证 |
| --- | --- |
| Vue 3 | MIT |
| Pinia | MIT |
| Vue Router（如使用） | MIT |
| Element Plus / @element-plus/icons-vue | MIT |
| Vite | MIT |
| TypeScript | Apache-2.0 |

## 网络服务

应用会连接用户自行配置的服务（Qwen / DeepSeek API、Ollama、校园数据接口、插件主机、
Bing / Tavily / 博查 搜索服务）。这些服务由其提供方按其自身条款提供，本项目不分发其任何内容，
也不对其可用性与数据处理方式负责。使用前请确认你所在学校或组织对相关服务的授权与合规要求。

## 品牌资源

仓库中的 `assets/branding/mens-source.png` 及由其生成的全部图标（`.ico` / `.icns` / PNG）
为本项目自有资源，随项目一并按 Apache License 2.0 提供。
