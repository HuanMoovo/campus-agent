# Mens 1.0.0 验证记录

日期：2026-09-30。状态：1.0.0 构建、安装和启动验证完成。本次在 0.4.1 功能基础上统一版本号，不代表新增流式回答、校园 SSO 或其他尚未实现的建议功能。

## 开发副本改进验证（未发布，2026-10-01）

在 1.0.0 源码基础上增加流式回答、停止生成和历史会话管理。**安装包尚未重新构建**，`release/` 中仍是 2026-09-30 构建的 1.0.0 安装包；本节只记录工作副本的验证结果。

- 改动范围：`POST /api/chat/stream`（SSE：meta/delta/done/error，中断时保存已生成内容并标记 `partial`）；会话列表/删除/清空接口与会话 `client_id` 隔离（网页用浏览器本地存储，桌面用 `workspace.json`，旧会话在下一次发言时归属请求方）；聊天页“历史对话”面板、逐字流式显示与“停止生成”按钮。
- 后端测试：222 passed，44 subtests passed（新增流式协议、停止持久化、会话隔离、旧库列迁移等 15 项）。
- 前端 TypeScript 检查与生产构建通过（保留既有的大资源块体积提示）；Electron 单元测试 6/6 通过（含 clientId 读写与校验断言）。
- 真实 HTTP 冒烟：使用模拟 Ollama 流式服务经 `curl -N` 验证事件序列 meta→delta×8→done，末事件 `mode=llm`；错误 client_id 删除返回 404、他人会话列表为空。
- 浏览器自动化（Playwright 驱动本机 Edge，模拟模型每段 0.4 秒）：回答在界面逐段增长（8 次采样 2→17 字符）、流式光标出现后在完成时消失；“停止生成”保留半截回答并显示“已停止”徽标，再次打开该会话仍带该标记；历史面板列出会话、可恢复、可清空。
- 未验证：真实云端 API Key 的流式链路（提供商地址必须 HTTPS，本次未使用密钥）；真实模型权重（验证时本机 Ollama 未安装模型）；重新构建后的安装包验收。
- 脚本与截图：`.tmp/qa-streaming/`（mock 服务、ui_check.py、report.json、两张界面截图）。

## 开发副本第二批改进验证（未发布，2026-10-01）

新增 Word (.docx) 知识库上传、镜像模型下载断点续传、数据备份导出/导入。安装包仍未重新构建。

- 改动范围：`POST /api/documents/upload` 支持 docx（标准库解析 `word/document.xml`，旧版 .doc 明确报错）；GGUF 下载按 pinned SHA-256 保存断点文件、`Range` 续传并在续传前重算已下载部分的哈希，完整未导入的文件可直接重试导入；`GET /api/backup/export`（VACUUM INTO 快照 + 配置文件 + SHA-256 清单）与 `POST /api/backup/import`（先校验清单与表结构，再通过 SQLite backup API 原地恢复，config 文件原子替换）；设置页「备份与恢复」；桌面通过 IPC 系统对话框读写备份 zip。
- 后端测试：234 passed，44 subtests passed（本批新增 docx 解析/拒绝、备份往返与恶意 zip 拒绝、断点续传/续传校验/导入重试共 12 项）。
- 桌面 Electron 测试 7/7；前端类型检查与生产构建通过。
- 真实 HTTP：docx 上传返回逐段提取文本；导出 zip 含 `campus.db` 与 `mens-backup.json`（含大小与 SHA-256）；删除会话后导入成功恢复（404 → 200）。
- 浏览器自动化（Playwright + 本机 Edge）：通过真实文件输入上传 docx（列表 4→5 行）；「导出备份」触发真实下载 `mens-backup-2026-10-01.zip`（含 campus.db 与清单）；「导入备份」经确认弹窗与文件选择器完成并显示“已恢复：campus.db。”
- 未验证：真实 400MB–1.1GB 模型断点续传（用 2.7MB 模拟流验证中断保留、Range 续传、校验后跳过下载与导入重试）；跨机器导入（DPAPI 加密的密钥在他机无法解密，需重新填写）。
- 脚本与截图：`.tmp/qa-batch2/`（docx 夹具、ui_check2.py、report.json、界面截图）。

## 开发副本第三批改进验证（未发布，2026-10-01）

新增本机报修记录列表、窗口大小/位置记忆、桌面设置页后端日志查看。安装包仍未重新构建。

- 改动范围：`GET /api/services/repairs`（含联系方式，管理员授权才可读，桌面模式自动授权）；校园服务页在报修表单下方显示本机报修记录并支持刷新；`window.json` 记录窗口大小/位置/最大化，读取时校验尺寸范围与是否仍在显示器内；桌面设置页「后端日志」通过 IPC 读取最近 200 KB 日志（缺失时给出提示）。
- 后端测试：235 passed，44 subtests passed（新增报修记录授权与排序 1 项）；桌面 Electron 测试 7/7（新增窗口状态越界忽略与关闭时持久化、日志读取与来源校验）。
- 真实 HTTP：报修记录接口未带令牌返回 401，带令牌按时间倒序返回并包含地点/问题/状态。
- 浏览器自动化（Playwright + 本机 Edge）：报修页显示“本机报修记录”表格（提交时间/地点/问题/状态），提交新工单后列表出现对应记录，演示数据提示可见。
- 未验证：安装包内的窗口记忆与日志查看（需重建安装包后人工确认；Electron 侧已由 vm 单元测试覆盖）。
- 脚本与截图：`.tmp/qa-batch3/`（ui_check3.py、check_repairs.py、界面截图）。

## 1.0 已完成检查

- 桌面与前端 package.json、两份 package-lock.json、FastAPI 版本均为 1.0.0。
- 网页版本显示从 frontend/package.json 派生；桌面继续从 Electron IPC 读取实际版本。
- Electron 单元测试 6/6 通过，包含桌面、前端与 API 源码版本一致性校验。
- 前端 TypeScript 检查与 Vite 生产构建通过；保留原有的大资源块体积提示。
- 源码后端实际启动后，/openapi.json 的 info.title 和 info.version 断言通过，版本为 1.0.0。
- 冻结后端联调 7/7 通过；NSIS 安装器退出码为 0。
- 1.0.0 安装包为 120,202,858 字节，SHA-256：`289E146F7971FC7593E66249FAD52A66D3C6C970CF271115728F3C2E4360EB87`。
- 解压目录 `release/win-unpacked/Mens.exe` 文件版本为 1.0.0，SHA-256：`11671E5036FD1E0E3588523E9C12C95BB716B2C9E12880F61D1F65B05ED15BA1`。
- 已安装 `%LOCALAPPDATA%\\Programs\\CampusAgent\\Mens.exe` 文件版本为 1.0.0，窗口标题为“Mens 工作台”，进程响应正常，后端日志确认 `Application startup complete.`。
- 使用打包后端完成真实本地模型问答：`gemma4:e4b`，模式 `llm`，耗时 5.258 秒，返回“你好！😊”。
- 升级前后 `campus.db`、`workspace.json`、`.env`、`model-providers.json` 的 SHA-256 完全一致；原本不存在的 `campus-sources.json` 仍不存在。完整记录见 `build/upgrade-verification.json`。
- 源码归档已刷新：`campus-agent-source.zip`，共 96 个文件；归档脚本确认未包含用户数据库、密钥、日志、依赖和构建缓存。

## 1.0 仍需外部条件的项目

- 未使用真实云端 API Key 或学校账号；学校接口、云端推理的业务联通仍需真实配置验收。
- 安装包未附带模型权重；本次只验证了本机已有的 `gemma4:e4b`。
- computer-use 工具此前未获准访问 Mens 窗口，因此没有声称完成工具内的鼠标点击验收；本次使用进程、窗口标题和后端日志完成桌面启动验证，并保留已有浏览器自动化验证记录。

以下 0.4.x 记录为历史结果，不代表 1.0 需要重复旧版本的安装步骤。

## 0.4.1 验证历史

日期：2026-09-30。此补丁仅调整 Logo 外形：20% 半径圆角、透明四角、四倍采样平滑边缘，保留原图案和米白底色。网页、头像、启动页、窗口和安装程序图标已同步。未改变后端功能，复用 0.4.0 冻结后端。

- 图像资源目视检查通过；256px 桌面 PNG 四个角的 Alpha 均为 0，中心 Alpha 为 255。
- 前端类型检查及生产构建通过；Electron 5 项测试、后端 207 项测试与 44 项子测试通过。
- NSIS 0.4.1 安装包已构建并升级安装，退出码 0；已安装文件版本为 0.4.1.0。
- 升级前后 campus.db、workspace.json、.env、model-providers.json 的 SHA-256 一致。
- 安装后 Mens 工作台和冻结后端已重新启动，日志确认 Application startup complete。本次未新增窗口内点击验收。
- 安装包：release/Mens-Setup-0.4.1-x64.exe，120,202,615 字节。
- SHA-256：111F7B742F4648B54AAF5233EAC5DEBB99AEFBB0E7C7EC6CCC79EF6118FFBCF0。

## 0.4.0 功能验证历史

日期：2026-09-30。Windows x64 安装包已构建，当前用户升级安装退出码为 0；安装后的 Mens.exe 文件版本为 0.4.0.0。升级后已观察到“Mens 工作台”主窗口，冻结后端日志确认启动完成，随后正常退出。

## 本次变更

- 采用用户提供的蓝色 Logo 原图，保留图案和米白底色，生成网页、启动页、桌面窗口与安装程序图标。原图位于 assets/branding/mens-source.png。
- 新增「设置 → 外观」：浅色、深色、跟随系统、六种预设主题色、取色器、六位 HEX 自定义颜色和恢复默认。主题立即应用并保存，系统模式随操作系统变更。
- 聊天页提供模型选择器，列出 Ollama 实际安装的模型，包括预置下载目录以外的模型。具体选择逐请求传递，切换保留会话，不会将本地请求改为云端请求。
- 普通学习、编程、日常对话可以使用本地模型；缺少资料的校内政策回答仍明确说明没有可靠依据。不可用、被删除或推理失败的模型明确显示错误。

## 测试与构建

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 后端全量测试 | 207 passed，44 subtests passed | 既有功能及新增本地模型请求、历史保留、无云端回退、超时和失败处理 |
| 前端类型检查与生产构建 | 通过 | Vue TypeScript 与 Vite，存在已有的大资源块体积提示 |
| Electron 单元测试 | 5 passed | IPC 校验、颜色/显示模式/模型名持久化、原数据目录和退出 |
| 源码后端与桌面联调 | 6 passed | 真正启动后端、鉴权、知识库、历史、模型和校园配置、百度百科插件 |
| 冻结后端联调 | 6 passed | 同组业务测试在 PyInstaller 后端 EXE 上通过 |
| 浏览器界面自动验证 | 通过 | Logo、浅/深/系统模式、颜色校验、浅色按钮深色文字、重载恢复、聊天请求中的具体模型、模型删除后禁止发送、390px 窄屏布局 |
| 真实本地模型问答 | 通过 | 实际打包后端调用本机 gemma4:e4b，59.743 秒返回中文问候，响应 mode 为 llm |
| NSIS 安装包 | 通过 | Mens 0.4.0 x64，含 Python 后端与 Electron |
| 当前用户升级与启动 | 通过 | 安装退出码 0，文件版本 0.4.0.0，Mens 主窗口与后端正常启动 |
| 旧用户数据保留 | 通过 | campus.db、workspace.json、.env、model-providers.json 在升级前后 SHA-256 完全一致 |

界面测试脚本：scripts/verify_ui.cjs（需要 Playwright 和本机 Edge）；截图与结果位于 build/ui-verification。API 响应为隔离测试数据，不调用收费模型。

真实模型测试脚本：scripts/verify_local_model.cjs。它启动已打包后端，使用 build/local-model-verification 的独立数据目录，禁用云端密钥；未向用户已有聊天记录写入测试内容。真实回复为“你好！有什么可以帮到你的吗？”。此结果证明当时本机该模型可用，不保证所有模型和硬件组合均可运行。

## 安装文件

- 安装包：release/Mens-Setup-0.4.0-x64.exe
- 大小：120,168,897 字节
- SHA-256：6FEA796757FDD8B8F86994AABBC1454ECF807474C6EADFCBAD134FC6A336B8C1
- 安装位置：%LOCALAPPDATA%\Programs\CampusAgent\Mens.exe
- 数据位置：%APPDATA%\CampusAgent
- 安装包未配置发行者签名，Authenticode 状态为 NotSigned。

## 安装后的窗口验收

窗口列表已确认新版本启动并显示“Mens 工作台”。computer-use 对窗口访问返回 Computer Use was not approved to use Mens。用户再次明确授权后，重试启动仍返回同一错误。因此，本次尚未完成安装后窗口内的实际点击验收。没有绕过工具的应用访问权限；浏览器截图、IPC 测试和进程启动检查不能替代这一部分。

## 仍需外部条件的项目

- 未使用真实云端 API Key 或学校账号；学校接口、云端推理的业务联通仍需真实配置验收。
- 本次没有进行 GB 级模型下载。下载镜像、大小/校验和、取消和失败处理由既有隔离测试覆盖；已安装的 gemma4:e4b 完成了真实推理验证。
- 百度百科仍采用系统浏览器搜索交接，不声称提供百度百科 JSON 内容接口。OpenAlex、Crossref 的网络状况没有在本次更新中重新验收。
- BGE-M3/Chroma 完整向量包、PostgreSQL 和 Docker 全栈不在本次桌面升级验收范围。
