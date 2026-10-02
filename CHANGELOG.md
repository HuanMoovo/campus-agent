# 变更记录

本文件按时间倒序记录对外可见的变化。每个版本的验收范围、安装包大小与 SHA-256 见
[VERIFICATION.md](VERIFICATION.md)。

## 未发布

### 网站部署与登录

- **登录**：新增 `backend/app/auth.py`（PBKDF2-HMAC-SHA256 口令散列、服务端会话表、登录限速、
  首次启动引导管理员）与 `users` / `sessions` 数据表；新增 `/api/auth/login|logout|me`。
  开启 `AUTH_REQUIRED` 后，除健康检查与登录接口外的所有 `/api/*` 都要求登录 Cookie；
  桌面版自动豁免，管理员角色可执行管理操作。
- **界面**：新增登录页（三语）与侧栏退出入口；启动时先校验会话再渲染主界面。
- **部署**：新增 `Dockerfile.web`（前端构建 + FastAPI 单容器）、`render.yaml`（Render 免费实例蓝图）、
  `.dockerignore` 与 `DEPLOY.md`；后端在设置 `WEB_FRONTEND_DIR` 时托管前端产物，
  健康检查返回 `auth_required` 供前端判断是否显示登录页。
- **修复**：`CAMPUS_DATA_DIR` 现在同时决定 SQLite 位置（此前只改目录不改库，
  导致测试与多实例共用同一个数据库、测试账号污染开发库）。


### MCP 与命令行

- **MCP 客户端**：新增 `backend/app/mcp_client.py`（标准库实现 stdio 传输，按行分隔的
  JSON-RPC 2.0，完成 initialize / tools/list / tools/call）与 `backend/app/mcp_registry.py`
  （服务器登记、掩码、连通性检查、工具编目与调用）。新增 `/api/mcp/servers`、
  `/api/mcp/servers/{id}/test`、`/api/mcp/tools` 接口与 `mcp_servers` 数据表。
  工具以 `mcp__<服务器>__<工具>` 暴露给模型，一次问答最多调用一个，参数与结果原样透传。
- **界面**：「MCP」页可登记、测试、启停、删除服务器并查看工具清单，内含 CLI 命令速查卡；
  三语（中/英/日）文案与接口封装同步补齐。
- **命令行**：新增 `backend/app/cli.py`（`python -m app.cli`），提供 `ask`、`chat`、
  `mcp list/add/remove/test/tools`、`serve` 子命令，与桌面端共用同一数据目录。
- **测试**：新增 `test_mcp_client.py`、`test_mcp_registry.py`、`test_cli.py` 共 37 项
  （后端合计 294 项通过），前端构建与 17 项测试通过。


### 交付验收补强

- **签名与完整性**：新增 `scripts/sign_release.ps1`（用 .pfx 或 CA 证书签名 + 立即验签，
  并提供自签名演练开关）与 `scripts/release_checksums.py`（生成 `SHA256SUMS.txt`）。
  本机已用自签名证书跑通整条管线；对外分发仍需 CA 签发的证书与时间戳。
- **产物冒烟**：新增 `scripts/smoke_package.py`，启动打包产物后从调试端口取出内部地址，
  确认内置后端与界面进程就绪（外部请求得到 401 视为鉴权生效）。构建矩阵在
  Windows / macOS / Linux 三个平台的 runner 上都会执行该冒烟，作为“跑得起来”的证据。
- **校园网关接入**：新增 `CAMPUS-GATEWAY.md`（九类接口约定、登记联调步骤与验收清单），
  如实标注适配层已验证、真实网关待校方凭据。


### 网站（项目介绍页）

- **交互式 3D hero**：首页新增可拖拽旋转、滚轮缩放的「知识星图」场景（three.js 私有打包在
  `docs/vendor/`，非 CDN；在舞台进入视口后才加载，无 WebGL 或偏好减少动态时退回静态渐变）。
- **主题切换**：右上角「自动 / 浅色 / 深色」，选择记忆在本机，并同步浏览器主题色。
- **排版升级**：统一间距、圆角与字号令牌；hero 改为左文案右场景的双栏；功能卡加序号与悬浮反馈；
  移动端单列堆叠，顶部栏自动换行。

## 1.2.1 — 2026-10-01

### 新增

- **界面三语（中文 / English / 日本語）**：设置 → 外观里可切换界面语言（默认跟随系统），选择会被记住并在下次启动生效；本次覆盖应用外壳（侧栏、顶栏、连接状态）、问答页（空状态、建议问题、输入区、来源标注）与外观设置；其余管理面板仍为中文，后续批次补齐。
- **离线外壳缓存随版本更新**：Service Worker 的缓存名由构建时注入 package.json 版本（缺失占位符即构建失败），避免升级后继续使用旧外壳。
- **会话导出**：单条历史对话可导出 Markdown（便于阅读留档）或 JSON（便于脚本处理），
  桌面版走系统保存对话框，网页版直接下载；导出内容包含来源链接、工具调用与演示数据标注。
- **知识库网页导入**：可把公开网页（HTTPS）正文抓取并保存为本机文档，之后可离线检索；
  抓取沿用联网搜索的出站规则（仅 HTTPS、连接固定到校验过的公网地址、禁跳转、有大小上限），
  解析到内网地址直接拒绝。
- **批量上传文档**：一次可选择多个文件上传，逐个报告成功与失败原因。
- **CI 覆盖日常提交**：新增 `ci.yml`，push 到 main 与所有 PR 都会运行后端 / 前端 / 桌面三套测试
  并校验 compose 文件；`dependabot.yml`（pip / npm / GitHub Actions）与 CodeQL 静态分析。
- **仓库规范文件**：CHANGELOG、CONTRIBUTING、SECURITY、issue 与 PR 模板、`.editorconfig`。

## 1.2.0 — 2026-10-01

### 新增

- **联网搜索（可选，默认关闭）**：免密钥的 Bing 网页搜索（中国大陆可直连），或配置 Tavily /
  博查；逐条消息开关，回答引用网页链接与检索时间。
- **跨平台构建**：Windows（NSIS）、macOS（dmg/zip，Intel 与 Apple silicon）、Linux
  （AppImage / deb）由同一脚本与 CI 矩阵产出；Windows 之外的凭据存储与图标处理另行实现。
- **可安装网页版（PWA）**：清单、离线外壳与 iOS 安全区适配，手机浏览器「添加到主屏幕」即可。
- **Docker 部署**：`compose.yaml`（PostgreSQL 16 + 后端 + Nginx），本机实测通过（见验证记录）。
- **项目介绍页**：GitHub Pages 上的中 / 英 / 日三语介绍，含平台矩阵、截图与已知限制。
- **三语 README**：`README.md` / `README.en.md` / `README.ja.md` 与语言切换。

### 变更

- 许可证由 AGPL-3.0 调整为 **Apache License 2.0**（新增 `NOTICE`，安装包内一并分发）。
- 项目名说明：Mens 取自拉丁语 *mēns*（心智、理性、思维）。

## 1.1.0 — 2026-10-01

- 统一桌面、网页、安装包与 API 的版本号；新增流式回答与停止生成、按用户隔离的历史会话、
  Word (.docx) 知识库上传、模型下载断点续传、备份导出/导入、本机报修记录、窗口位置记忆、
  后端日志查看、前端单元测试与构建分包、可选的更新检查。

## 1.0.0 — 2026-09-30

- 首个可配置发布版：圆角透明 Logo、可定制外观、九类校园服务与数据接口、可选插件、
  聊天窗口内的本地 Ollama 模型切换；安装包完成安装验收。

## 0.4.x — 2026-09-29

- 模型不可用时明确报错，不自动转发云端；模型权重需单独下载。
