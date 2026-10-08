# Mens 验证记录

1.0.0 的构建与安装验证记录于 2026-09-30；1.1.0 于 2026-10-01 重新构建并完成安装验证；**1.2.0 于 2026-10-01 完成跨平台构建改造、联网搜索与可安装网页版，Windows 安装包通过完整验收**。校园统一登录仍未实现。

## 发布批次：Mens 1.2.2（2026-10-08）

- **版本统一为 1.2.2**：`desktop/package.json`、`frontend/package.json`（含两个 lock 文件的根包）、`backend/app/main.py`（FastAPI 版本）、`backend/app/cli.py`；README（中/英/日）、`DESKTOP.md`、站点徽标与 issue 模板示例同步；CHANGELOG 的「未发布」全部结转为本版。
- **本机构建（Windows）**：`scripts/build_desktop.py --skip-install --os win --arch x64` 全流程通过（构建内已跑：后端 394、前端 29 + 生产构建、桌面 9、冻结后端联调）→ `release/Mens-Setup-1.2.2-x64.exe`，**126,502,970 B，SHA-256 `7a0b9b9c3d5880606206eb571b53b7a4ab92fb438bbc7a1215517db3b0a7e93e`**；`latest.yml` 版本 1.2.2；打包内 `frontend/sw.js` 缓存名为 `mens-shell-1.2.2`（构建时注入）。
  - 构建备注：本机 electron-builder 的 asar 完整性注入对 `win-unpacked/Mens.exe` 的首次写入偶发 `UNKNOWN`（刚复制改名后的短暂文件占用；独立复现与随后重试均正常）。已在本地依赖中为该步骤加入退避重试（第 1 次失败、2 秒后重试成功），写入内容与常规路径一致。
- **静默升级安装**：从已安装的 1.2.1 覆盖升级到 1.2.2（安装目录 `%LOCALAPPDATA%\Programs\Mens`，`Mens.exe` 文件版本 1.2.2），升级后 `LICENSE`、`NOTICE`、`THIRD-PARTY-NOTICES.md` 均在。
- **安装版界面验收（CDP，真机）**：侧栏显示「后端已连接 v1.2.2」；本机历史对话保留；首次使用引导正常展示。
- **产物冒烟**：`scripts/smoke_package.py` 对已安装的 1.2.2 执行——内部地址取到、界面入口 401（桌面鉴权生效）→ 通过（exit 0）。

## 深度代码审查批次：全模块复查与加固（2026-10-08）

- **范围**：后端全模块（main / auth / mcp_client / mcp_registry / plugins / rag / db / models / model_runtime / web_search / schemas / desktop_runtime / config）、桌面三件套（main.cjs / preload.cjs / lib）、前端接口封装与 Markdown 渲染层逐文件复查。
- **结论**：未发现安全漏洞级问题。路由鉴权 100% 覆盖（全部管理写端点 require_admin）；口令 PBKDF2-SHA256 24 万次迭代 + 定时均衡；会话令牌 256 位随机并以散列存储；桌面端来源校验、导航拦截、请求白名单、令牌限定注入与 CSP 注入齐全；备份导入有 zip-slip 防护与清单校验；插件清单与更新检查禁用内网地址与重定向；模型下载固定 TLS、断点续传按分段哈希、导入前全量 SHA-256 校验。
- **修复 4 处**（详见 CHANGELOG 对应条目）：自助改密吊销其它会话（+1 测试）、限速表防膨胀、检索空值守卫、GitHub 引用名拒绝 `..`。
- **测试**：后端 394 项（65 subtests）全部通过；前端与桌面端代码未改动。

## 质量检查批次：依赖审计与全新 PG 建库（2026-10-06）

- **依赖审计**：前端 `npm audit`（--omit=dev）发现 1 项 high——`source-map-js` 事件循环 DoS（GHSA-68fv-2mgg-jv7q，经 jsdom / vite / vue 传递）；`npm audit fix` 升级锁文件后复核归零，前端 29 项测试与生产构建通过。后端 `pip-audit -r requirements.txt`：无已知漏洞。
- **全新 PostgreSQL 路径**：`Base.metadata.create_all` 在全新库建表成功（`pinned` 布尔默认在 DDL 上为 `false`）；按应用真实路径 ORM 写入——创建用户（uuid）、会话令牌、对话（`pinned=False`、带时区时间戳）、两条消息（自增 id、JSON `result_data`）——全部通过，会话解析为 True。旧库迁移路径见下节修复记录。
- **代码扫描（本轮）**：无 TODO/FIXME、无调试 print / console.log 残留、无 eval / shell 注入面、无 `verify=False`、无 f-string SQL；桌面端 `isOwnUrl` 为精确 origin 判定且令牌仅注入自家后端 URL；`/api/desktop/*` 由独立 DesktopGuard（一次性令牌）保护；MCP 子进程为管理员登记受控特性。

## 修复验证：PostgreSQL 旧库迁移与自建部署登录（2026-10-06）

- **发现**：验证「自建部署开启登录」时，带旧数据库的 compose（PostgreSQL 16.15）栈启动失败——`ensure_conversation_columns` 的 `pinned BOOLEAN NOT NULL DEFAULT 0` 在 PostgreSQL 上报 `DatatypeMismatch`（SQLite 宽松未暴露）。用临时库复现原错误，并验证修复语句（`DEFAULT FALSE`，插入行 `pinned=f`）。
- **compose 端到端（登录链路，经 nginx）**：`AUTH_REQUIRED=true` 由 `.env`/shell 透传进容器全链路生效——health `auth_required=true`；未登录业务接口 401「请先登录」；登录 200（首次启动创建 admin）；带会话 `me` 200；浏览器：登录页 → 登录 → 刷新保持（截图 `build/qa-auth/03、04`）。修复后的迁移在真实旧卷上自动补列成功，三服务全部启动。
- **测试**：后端 393 项（65 subtests）通过。
- **说明**：前端镜像本机构建受 npm 网络限制未重建，验证以挂载方式加载新 `nginx.conf` 与本地 dist（`nginx -t` 语法通过）；compose 配置校验（含新登录变量）通过。

## 跨平台验证：三平台测试矩阵 + 四平台构建冒烟（2026-10-06）

- **三平台测试矩阵（CI run 37412010625，success）**：日常流水线扩展为 ubuntu / macos / windows（提交 `7864ed0`）——`Suites (ubuntu-latest)`、`Suites (macos-latest)`、`Suites (windows-latest)` 全部通过：后端 393（65 subtests）、前端 29 + 生产构建、桌面 9 在三个系统上各跑一遍；Compose 校验仅在 ubuntu 执行（success），macOS / Windows 按设计跳过。
- **四平台构建 + 产物冒烟（CI run 37412010682，success）**：对最新 main 手动触发（含联网搜索过滤改动）——Windows x64（NSIS 静默安装后启动）、macOS x64、macOS arm64（挂载 dmg 启动 .app）、Linux x64（xvfb 运行 AppImage）四个目标全部成功；每个目标先跑全套测试再打包，「Smoke-test the packaged app」步骤在四个目标上均 completed/success（启动产物 → 探测内置后端与界面 → 正常退出）；四个平台产物已上传 Actions Artifacts（127–327 MB）。
- **本机 Linux 复测**：用本机已有的 `campus-agent-backend` 镜像（python:3.11-slim + 完整依赖）在 Docker 容器中跑后端全量测试——**393 passed，65 subtests passed**（本机直连 PyPI / Docker Hub 拉取受限，前端与桌面的 Linux 复测未在本机进行，由 CI ubuntu 运行器覆盖）。
- **范围说明**：以上为 GitHub 托管运行器（真实 macOS / Windows / Linux 系统环境）与本地 Docker Linux 上的执行结果；物理真机（校内设备、实际用户环境）仍未覆盖。

## 功能批次：联网搜索相关性过滤（2026-10-05）

- **后端（393 passed，65 subtests；+5 项过滤测试）**：`parse_bing_results` 跳过广告标记条目（`b_ad` 类名 / 「广告」标签）；新增 `filter_results(query, results)`——分词抽为 `app/text_terms.py`（知识库检索同步改为引用），标题命中 ≥2 个提问关键词（单关键词提问 ≥1）且同站去重（仅保留排名最前一条）；`search()` 对全部服务商统一应用过滤，抓取正文的目标也来自过滤后列表；全部被过滤时提示「没有找到与问题相关的内容」。测试覆盖：广告块跳过、无关条目 + 同站去重、SERP 垃圾与广告不进入结果、全过滤时的明确提示、仅摘要命中不放行（防「校内网」类漏网）。
- **真实网络实测（隔离数据目录，真实出网；过滤前 → 过滤后）**：
  - 「补办校园一卡通需要哪些材料？」9 → 6：保留百度文库《校园一卡通丢了怎么办》全文攻略、mycc.edu.cn《"校园一卡通"常见问题解答》、贴吧与爱企查问答等；
  - 「2026年有哪些法定节假日？」10 → 2：保留 gov.cn 放假通知、chinacalendar 日历（哔哩哔哩、研考网等无关条目全部剔除）；
  - 「英语四六级报名时间？」10 → 7：保留 cet.neea.edu.cn 官网、新东方、教育在线等；
  - 「校内图书馆的借阅与续借规则是什么？」9 → 0、「西区学生宿舍几点断网？」9 → 0、「学校奖学金申请条件是什么？」9 → 0：原始结果被 Bing 拆错的关键词主导（人人网 / 行政区 / 普通学校名录，见下条），过滤后为空，应用提示「没有找到与问题相关的内容」，不展示无关网页。
- **诊断说明（空结果的成因）**：Bing 免密钥通道对部分中文长问句的切词偶发失效（只抓「校内→校内网」「奖→汉语字典」「学生→学信网」等单个泛词），并观察到同一查询短时段内抓取与真实浏览器结果不一致的降级窗口（随后自行恢复，浏览器对照证明非本机网络问题）——属服务端行为；过滤器保证这类时段宁缺毋滥。另探测百度免密钥通道：首次请求可返回相关性很好的中文结果（国家奖学金政策页），随后请求即触发反爬校验页（1.4 KB），本轮未接入。
- **未验证**：桌面安装版未重新打包（随发版统一执行）；Tavily / 博查真实 Key 下的过滤效果未实测（同一代码路径由单测覆盖）；百度通道未接入。

## 功能批次：插件改版——移除推荐插件，GitHub 自定义安装（2026-10-03）

- **后端（388 passed，65 subtests；净 +30）**：删除推荐插件目录（`GET /api/plugins/catalog` 与一键安装端点；`plugin_catalog.py` 移除，常量并入 `plugins.py`）；`POST /api/plugins/install` 重写——支持 GitHub 仓库地址（含 `.git`、`?tab=`、`/tree/<分支>`、`/blob/<分支>/plugin.json` 形式）解析为 owner/repo/ref，按 **jsDelivr（cdn → fastly，逐解析地址自动重试）→ raw.githubusercontent.com** 顺序读取仓库根目录 `plugin.json`，直接 HTTPS 清单地址仍可用；出站门禁保持公网 HTTPS + 固定 IP + 禁重定向 + 100KB 限额，`PLUGIN_ALLOWED_HOSTS` 改为可选白名单（默认留空不额外限定，内网地址始终禁用）。测试覆盖：URL 解析正反例 18 项、候选顺序与回退链、404/502/422 映射、端点鉴权与输入校验、白名单/内网 IP 门禁、多地址重试（本轮 QA 实测发现 jsDelivr 一个解析地址被重置、另一个正常，据此实现逐地址重试）、百度百科回归 3 组。
- **前端（29 passed；vue-tsc/生产构建通过）**：插件页移除推荐插件区块与相关客户端方法，新增「GitHub 自定义安装」输入区与可折叠的插件清单示例；空态与已安装列表交互不变。
- **桌面联调（源码后端 7/7 通过）**：`backend.integration.cjs` 更新——catalog 路由确认移除（桌面模式无 token 为全局 401、带 token 404 静态挂载兜底）、`/api/plugins/install` 鉴权与地址校验（不发起真实 GitHub 访问）。
- **真实网络实测（隔离数据目录，真实出网）**：查询不存在的清单 `https://github.com/octocat/Hello-World` → **404**「仓库根目录未找到 plugin.json」（修复顺序与重试前 18.5s，现约 8s）；经 jsDelivr 直读真实文件 `three.js@HEAD/package.json` → **422** 清单格式无效（0.2s，边缘缓存生效）；种子 OpenAlex 插件真实调用 `api.openalex.org` → **200**、25 条结果（首条 “Machine Learning”，2–3s）。
- **真实浏览器（Edge + Playwright，11 项断言全绿；5 张截图逐张核验）**：插件页无推荐区块、「GitHub 自定义安装」+ 清单示例展示正常；`http://` 地址 → 400「仅支持 https://github.com/…」提示；真实缺失仓库 → 404 提示且列表不变；已安装行测试调用 → 真实返回且无错误弹窗；卸载确认 → 列表清空。控制台仅 2 条失败请求记录，分别对应两笔刻意发起的被拒安装（400/404），无其他错误。
- **上线后实测（提交推送后）**：以仓库内 `examples/plugin.json` 为真源，`https://github.com/HuanMoovo/campus-agent/tree/main/examples` 经真实网络安装成功（HTTP 200，1.3s；恰逢 cdn.jsdelivr.net 节点 503，自动回退 fastly.jsdelivr.net 命中，回退链得到实战验证）；随后真实调用返回 25 条结果；浏览器端重复完整流程：先卸载 → 从 GitHub 安装（提示「插件已安装」）→ 刷新后仍在（0 控制台错误，2 张截图核验）。
- **未验证**：桌面安装版未重新打包（随发版统一执行）；jsDelivr 对分支引用的缓存时效未计时验证（新推送后立刻安装可能读到旧内容或短暂 404，可用 `/tree/<提交>` 固定）；拖拽式“把仓库链接拖进窗口”等便捷入口未做。

## 功能批次：附件提问 / 快速提问窗 / 首次使用引导（2026-10-03）

- **后端（358 passed，65 subtests；+4 项附件测试）**：`ChatRequest.attachments`（`ChatAttachment.name` / `text` 上限 20 万字符，最多 3 个）；`attachments_augmented` 将附件拼为 fenced block 注入模型提示——**落库仍为提问原文**（单测断言回读内容不含附件正文块）；新增 `POST /api/chat/attachments/extract`（复用上传解析管线，TXT/MD/PDF/DOCX ≤5MB，返回 `{name,text}` 并截断至 20 万字符）。
- **前端（29 passed，+4 项附件逻辑测试；vue-tsc/生产构建通过）**：新增 `src/attachments.ts`（扩展名分类 / accept 列表 / 后缀拼接 / 文本校验纯函数）、`QuickAsk.vue`（Ctrl+Shift+K 浮层，Enter/Shift+Enter/Esc）、`OnboardingModal.vue`（4 步引导 + localStorage 标记）；`App.vue` 接入拖拽（含子元素 dragleave 防抖）、粘贴、点选三条通路与 chips 展示/移除；发送时正文以「含 [附件] 后缀的显示文本」入库，保证气泡、落库、刷新回读三处一致（由 QA 发现并修复的不一致项）；文案三语。
- **真实浏览器（Edge + Playwright，0 控制台错误；5 张截图逐张核验）**：首次启动引导弹出（4 步）→「开始使用」关闭 → 刷新不再出现；Ctrl+Shift+K 打开快速提问 → Enter 发送 → 浮层关闭且回答流式出现；附件通路——图片被拒（`不支持的文件类型：image.png`，0 chip）→ 点选 note.txt（1 chip）→ 拖拽 drag.md（2 chip）→ 260KB 超限被拒（`文件过大`，chip 不增）→ 粘贴 paste.txt（3 chip，`ClipboardEvent` 注入验证）→ 移除单个 chip → 重加 → 发送「请总结附件要点」：chips 清空、气泡含「[附件] drag.md、paste.txt、note.txt」、刷新后后缀仍在；mock 侧请求体证明带附件请求含注入块且提示字符数增加。
- **未验证**：云端真实 key 下同一流程（仅 mock 覆盖）；桌面安装版未重新打包（随发版统一执行）；拖拽验证经 `DragEvent` 注入（真实 OS 拖拽未覆盖）。

## 功能批次：命令面板与斜杠指令（2026-10-03）

- **前端（25 passed，+3 项指令匹配测试；vue-tsc/生产构建通过）**：新增 `CommandPalette.vue`（过滤 / 键盘导航 / 点击 / 遮罩关闭）与 `src/commands.ts`（`matchSlashCommands` / `filterCommands` 纯函数）；`App.vue` 全局 Ctrl+K 监听、斜杠状态机（与发送互斥的 ↑/↓/Enter/Esc 处理）、顶部栏入口按钮；文案三语。
- **真实浏览器（Edge + Playwright，0 控制台错误；4 张截图逐张核验）**：Ctrl+K 打开且输入框聚焦 → 过滤「设置」→ Enter 切换到设置页（`.settings-view` 出现）；Esc 关闭；点击条目执行；斜杠菜单 4 条指令、↓ 选中 `/history`、`/ne` 过滤为 1 条；普通文本不弹菜单；`/export` 触发真实下载 `mens-conversation-<id>-<ts>.md`；`/theme` 使 `data-theme` 由 light→dark；`/history` 重开面板；`/new` 清空会话（空状态出现）、输入框清空、菜单收起。
- **未验证**：桌面安装版未重打包（随发版统一执行）；全局快捷键经 `Control+k` 注入验证，物理键盘未覆盖。

## 功能批次：历史对话管理增强（2026-10-03）

- **后端（354 passed，65 subtests；+5 项历史测试）**：新增 `GET /api/conversations/search`（LIKE 全文匹配 + 通配符转义 + 大小写不敏感片段）、`PATCH /api/conversations/{id}`（重命名/置顶，空标题恢复默认，404/422 覆盖）、`POST /api/conversations/batch-delete`（仅删本 client，越权 id 静默跳过并返回实际删除数）；`ensure_conversation_columns` 对旧库自动补齐 `title`/`pinned`（幂等，含旧表迁移单测）。
- **前端（22 passed；vue-tsc/生产构建通过）**：搜索框（防抖 + 竞态令牌）、结果列表与空态、重命名对话框、置顶徽标与排序、多选批量删除、触屏 hover 修复、桌面端完成通知（窗口隐藏时）。
- **真实浏览器（Edge + Playwright，0 控制台错误；6 张截图逐张核验）**：3 条对话 → 搜索「课表」1 条命中（摘要含关键词）→ 点击切换会话 + 搜索清空；搜索「一卡通」3 条命中；无结果空态；重命名 →「已重命名」+ 标题更新；置顶 → 刷新后仍置顶且列首，取消置顶后徽标消失；多选 2 条批量删除 → 刷新后服务端仅剩 1 条；触屏模拟（has_touch/is_mobile）下 `hover:none` 规则存在且 `matchMedia('(hover: none)')` 为真。
- **未验证**：桌面安装版的系统通知为桌面端行为（窗口隐藏触发），无头浏览器无法观测，需安装版复验；搜索为 LIKE 匹配（无 FTS 索引），数据量大时可换 FTS5 trigram。

## 功能批次：界面细节优化（2026-10-03）

- **范围说明**：对照前端设计规范复核产品界面——该规范面向营销/落地页，此处只取其可迁移规则（轴线与间距一致性、空状态完备、控件风格统一、形状锁定），未改动品牌配色与信息架构。
- **前端（22 passed；vue-tsc/生产构建通过）**：五处改动（见 CHANGELOG）均为模板/样式级，无接口与数据变化；后端 349 passed 复核无回归。
- **真实浏览器（Edge + Playwright，14 张截图复核）**：轴线对齐用数值探针验证——历史面板开/关/再开三态下，标题左缘与输入框左缘 518/392/518px 完全一致，空状态中心与输入框中心 958/832/958px 一致；服务页空状态、账号页免登录文案、描边按钮均截图确认；移动端 390px 复核无溢出。控制台仅余一条预期 401（免登录探测 `/api/auth/me`）。
- **附带发现（未改）**：模型刷新按钮首屏 1–3 秒为禁用加载态（Ollama 探测返回前），随后恢复，属预期；触屏设备上历史项的导出/删除按钮依赖 hover 显示，触屏用户不可达（列为后续候选）。
- **未验证**：桌面安装版未重打包（随发版统一执行）；深色模式为人工截图复核，未做逐像素对比。

## 功能批次：回答操作条（复制 / 重新生成 / 用深度重答 / 有帮助 / 没帮助）（2026-10-03）

- **后端（349 passed，65 subtests；+4 项消息操作测试）**：`ChatRequest.regenerate`（bool）在流式与非流式路径均先行调用 `replace_trailing_exchange`——仅当末尾两行确为「同一问题的问答对」时整体替换，否则保持追加；新增反馈端点 `POST /api/conversations/{id}/messages/{mid}/feedback`（value=up/down/null，非 assistant 消息或跨会话返回 404，非法取值 422）；会话回读消息新增 `id`。
- **前端（22 passed；vue-tsc/生产构建通过）**：每条助手回答下方细体文字操作条（复制/重新生成/用深度重答/有帮助/没帮助）；重新生成仅最后一条回答可见（生成中隐藏）；反馈乐观更新 + 失败回滚；新流式回答的消息 ID 懒同步（按序对齐后提交反馈）；文案三语。
- **真实浏览器（Edge + Playwright，0 控制台错误；7 张截图逐张核验）**：复制 → 剪贴板内容与回答原文逐字一致（Windows 剪贴板 CRLF 规范化后比对）+「已复制到剪贴板」提示；重新生成 → 屏幕与刷新后均为「1 问 1 答、回答编号 2」（替换语义成立）；用深度重答 → 思考链出现、档位胶囊保持「快速」、刷新后仍为单对问答 + 思考可查看；有帮助 → 选中态；刷新后选中保持；切换没帮助 → 保持；再点取消 → 刷新后无选中；英文界面按钮 Copy / Regenerate / Retry in Deep / Helpful / Not helpful。mock 请求序列证明第 3 次流式请求（深度重答）`enable_thinking=true`，前两次为非思考直答。
- **未验证**：云服务商真实 key 下的同一流程（仅 mock 覆盖）；桌面安装版未重新打包（随发版统一执行）。

## 功能批次：思考链展示与 Markdown 富文本回答（2026-10-02）

- **后端（345 passed，65 subtests；+4 项思考流测试）**：`stream_model` 产出 (kind, text) 二元组（`content`/`thinking`）——Ollama 采集 `message.thinking`、OpenAI 兼容流采集 `delta.reasoning_content`；SSE 新增 `thinking` 事件（序列 ["meta","thinking","delta","done"]）；`persist_stream_exchange` 将思考写入 `result_data.thinking`（上限 12,000 字符），随 `/api/conversations/{id}` 回读。
- **前端（22 passed，+4 项 markdown 渲染测试；vue-tsc/生产构建通过）**：新增 `src/markdown.ts`（marked + marked-highlight + highlight.js 十种语言 + DOMPurify 净化，禁 img/iframe/表单/style 等）；助手回答渲染 Markdown；思考块自动展开→自动折叠→手动开合，文案三语（查看/收起思考过程、Show/Hide thinking、思考プロセスを表示/隠す）。DOMPurify 在 happy-dom 下行为失真的用例改用 `@vitest-environment jsdom`（新增 devDependency jsdom）。
- **隔离 HTTP 实测**（scratch 目录 + 127.0.0.1:8000 + mock 模型）：mock 流式 deep → `thinking` 3 帧先于 `delta` 5 帧；fast → 0 思考帧；**真实 `gemma4:e4b`（Ollama）深度档**：HTTP 200 / 11.1s，`thinking` 346 帧 + `delta` 170 帧；该会话回读 `thinking_len=1510`、`answer_len=279`。
- **真实浏览器（Edge + Playwright，0 控制台错误；6 张截图逐张核验）**：思考实时可见（自动展开）→ 完成自动折叠（「查看思考过程」）→ 展开显示完整思考文本 → Markdown 渲染（h1、表格、代码块）→ 刷新后历史恢复（思考可展开、表格仍在）→ 英文界面 `Show thinking`。脚本 13 项断言中 1 项因脚本自身选择器笔误误报（`.hljs-` 非法选择器），已用 DOM 探针复核：真实浏览器代码块含 `hljs-built_in`/`hljs-string` 两个高亮 span，高亮真实生效。
- **未验证**：思考内容不随会话导出（Markdown 导出暂无思考段）；Qwen/DeepSeek 云端 `reasoning_content` 仅 mock+单测（本机无真实 key）；非流式 `/api/chat` 不返回思考（设计如此）；桌面安装版未重新打包（随发版统一执行）。

## 功能批次：推理强度两档（快速 / 深度）（2026-10-02）

- **交互（参考 Hermes 会话设计）**：聊天输入栏右端、发送按钮左侧新增无边框文字胶囊（当前档位 + 小箭头）；点击向上弹出两档菜单（快速：直接作答，响应更快；深度：开启模型思考链，更细致但更慢；当前档右侧勾选），悬停浮层「推理强度：<档位> — <说明>」；生成中与未就绪时禁用。三语：快速 / Fast / 高速，深度 / Deep / じっくり。
- **后端映射（`reasoning` 逐请求生效）**：Ollama `think`（深度 true / 快速 false）；Qwen 流式 `enable_thinking`（深度 true，快速与全部非流式 false——DashScope 非流式限制）；DeepSeek 深度档切换官方推理模型 `deepseek-reasoner`（不带 temperature）；本地模型不支持思考链时自动退回普通调用。
- **测试**：后端 341 passed（65 subtests；新增 15 项推理档测试，另更新 1 项旧用例并断言参数透传）；前端 18 passed（+1 存储测试）与 vue-tsc/生产构建通过；桌面 9 passed（workspace IPC 新增 reasoning 接受/拒绝断言）。
- **隔离 HTTP 实测（scratch 数据目录，127.0.0.1:8000，mock 模型记录实际请求体）**：非流式 deep 200；非法档位 422；流式 deep/fast 两档 SSE 正常；mock 侧请求体——流式 deep `enable_thinking: true`、流式 fast `false`、非流式 `false`。
- **真实本地模型**：`gemma4:e4b`（Ollama 0.23.4）以深度档实测返回真实回答（200，8.8 秒）；直连探测确认该模型接受 `think: true` 并产出 `message.thinking`，即真机走的是原生思考路径；「模型不支持思考链时退回」由单元测试覆盖（本机无纯对话模型，未在真机触发 400 回退）。
- **真实浏览器（Edge + Playwright，后端直接托管生产构建产物）**：初始「快速」→ 菜单两档可选且勾选正确 → 选「深度」→ 刷新后保持（localStorage）→ 浮层文案精确 → deep 发送流式回答正常 → 切回「快速」再次发送正常（两次发送的 mock 请求体 `enable_thinking` 分别为 true/false）→ 英文 `Fast`、日文 `高速`；全程 0 控制台错误；8 张截图逐张目视核验（菜单、勾选、浮层、双语、作答）。
- **未验证**：DeepSeek 深度档仅有单元测试（本机无云端 key）；Qwen 云端未真实调用（以 mock 验证请求体与流式链路）；桌面安装版未在本批重新打包（未发版时统一执行）；思考过程文本不随回答展示（仅按开关影响模型行为）。

## 网站批次：3D hero、主题切换与排版升级（2026-10-02）

- **本地静态服务验收**（`python -m http.server` 于 127.0.0.1:8899 提供 `docs/`，Edge + Playwright）：
  - 3D 舞台 `data-scene="ready"`，`#hero-canvas` 存在，拖拽后 `data-rotation` 由 `0.16,-0.32`
    变为 `0.43,0.49`，提示胶囊显示「拖动旋转 · 滚轮缩放」。
  - 主题：点「深色」→ `html[data-theme=dark]` 且 `theme-color` 变 `#0b1717`；点「浅色」→ `light`；
    点「自动」→ 移除属性（跟随系统）。
  - 三语：切到 English 后提示为 `Drag to rotate · scroll to zoom`、主题按钮为
    `Auto / Light / Dark`、标题与正文同步；切到日本語 后为「ドラッグで回転・スクロールでズーム」
    与「自動 / ライト / ダーク」；选择写入 `localStorage`。
  - 资源全部来自同源：本次会话只请求了 `127.0.0.1:8899`（无 CDN 外链）。
  - 卡片序号 01–12（CSS 计数器）与悬浮反馈正常；420px 宽下单列堆叠、顶部栏换行、无横向溢出。
  - 三次会话均 **零 console 错误**。
- **未验证**：Safari / iOS 未跑；深色主题仅按系统偏好与手动切换验证，未做打印样式检查。

## 验收补强批次：签名管线、产物冒烟与网关契约（2026-10-02）

- **签名管线（本机实测）**：对安装包副本执行 `scripts/sign_release.ps1 -SelfSignedDemo`，
  signtool 逐步完成签名与验签，`Get-AuthenticodeSignature` 返回 `UnknownError`（自签名根不受信任，
  属预期），签名主体与指纹正确，演练后证书与临时 pfx 已清理。**正式分发仍需 CA 证书与时间戳**。
- **校验清单**：`scripts/release_checksums.py` 为 `release/` 下的安装包生成 `SHA256SUMS.txt`，
  本机产出 3 项（1.1.0 / 1.2.0 / 1.2.1），其中 1.2.1 的哈希与 VERIFICATION 记录一致。
- **产物冒烟（本机实测）**：`scripts/smoke_package.py` 对**已安装的 1.2.1** 执行——
  启动后从 CDP 取到内部地址 `http://127.0.0.1:11134/`，探测返回 401（外部请求无外壳请求头，
  说明内置后端已启动且鉴权生效），脚本判定「冒烟通过」。
- **CI 平台冒烟（待运行结果）**：`build-desktop.yml` 新增冒烟步骤，在 Windows 上静默安装后启动，
  macOS 上挂载 dmg 后启动 .app，Linux 上以 `--appimage-extract-and-run` 配合 xvfb 启动；
  通过标题为 “Smoke-test the packaged app” 的步骤判定。**结果以 Actions 页面为准**。

## 发布批次：Mens 1.2.1（2026-10-02）

- **版本统一为 1.2.1**：`desktop/package.json`、`frontend/package.json`（含两个 lock 文件的根包）、
  `backend/app/main.py`、三份 README 徽章、`docs/index.html` 三语徽章、`DESKTOP.md`、issue 模板同步。
- **测试**：后端 266 passed（65 subtests）、前端 17、桌面 9。
- **构建**：`scripts/build_desktop.py --skip-install` → `release/Mens-Setup-1.2.1-x64.exe`，
  **126,409,577 字节，SHA-256 `e2f7fa9dba68f6911f130a8b2c9076562ef0c761dfdac6aa48a75268a8f7b91a`**；
  包内 `resources/LICENSE`（11,339 B）、`NOTICE`（731 B）、`THIRD-PARTY-NOTICES.md`（2,401 B）；
  `resources/frontend/sw.js` 的缓存名为 `mens-shell-1.2.1`（构建时注入）。
- **静默升级安装**：从已安装的 1.2.0 覆盖升级到 1.2.1（安装目录 `%LOCALAPPDATA%\Programs\Mens`，
  `Mens.exe` 文件版本 1.2.1），升级后许可与清单文件都在。
- **安装版界面验收（CDP，真机）**：侧栏版本显示 `v1.2.1`；设置 → 外观显示「外观」并有 4 个语言单选项；
  切到 English 后侧栏为 `Chat / Campus services / Knowledge base / Plugins / Settings`、外观标题 `Appearance`、
  问答页 `Chat`、输入框占位符 `Type a question…`、模型选择器 `Auto routing`、`html lang=en`；
  切到日本語 侧栏为 `質問応答 / 学内サービス / ナレッジベース / プラグイン / 設定`；切回中文后 `html lang=zh-CN`。
  **零控制台错误、零失败请求**。
- **夹具中性化**：`test_export_and_import.py` 的内网地址夹具已改为中性网段 `10.255.255.7`。

## 功能批次：界面三语与离线外壳版本注入（2026-10-01）

- **前端 17 passed（+4）**：新增 `frontend/tests/i18n.test.ts` 校验三语字典键完全一致、无空值、参数插值、缺失键回退（先中文后键名）以及选择持久化与 `document.lang`。
- 真实浏览器（Edge，dev 栈）：设置 → 外观 → 语言依次切换 English / 日本語，侧栏显示 `Chat / Campus services / Knowledge base / Plugins / Settings`、顶栏 `Backend connected`、问答页 `Chat` 与 `What can I help you with today?`、输入框占位符 `Type a question…`；日语下侧栏为 `質問応答 / 学内サービス / ナレッジベース / プラグイン / 設定`；刷新后语言保持（localStorage `ja`，`html lang=ja`），零页面错误。
- 离线外壳：`npm run build` 后 `dist/sw.js` 的缓存名为 `mens-shell-1.2.0`（构建时从 package.json 注入），占位符无残留；把占位符改掉后构建以非零退出（负向检查）。
- 覆盖范围：应用外壳、问答页与外观设置为三语；服务、知识库、插件、设置内的其余面板仍为中文，属下一批工作。

## 功能批次：会话导出、网页导入、批量上传与工程化（2026-10-01）

- **后端 266 passed（+6）、前端 13 passed 且 `vue-tsc`/Vite 构建干净、桌面外壳 9 passed（+1）**。
- 新增测试：`backend/tests/test_export_and_import.py` 覆盖两种导出格式、未知会话 404、非法格式 422、
  导入需管理员令牌、非 HTTPS 拒绝、**解析到内网地址时由真实抓取路径拒绝**（patch `socket.getaddrinfo`
  指向私网仍被拦下、文档数不变）、无正文 400。
- 真实浏览器（Edge，dev 栈 5173 + 8000）：
  - 从历史面板导出会话 → 得到 `mens-conversation-<id>-<时间>.md`，首行为标题，含 `## 1. 用户` / `## 2. 助手`
    与 `**参考来源**`；JSON 导出可被 `json.loads` 解析，消息角色为 `['user', 'assistant']` 且来源标题保留。
  - 知识库「导入网页」导入 `https://example.com/` → 提示「已导入：[网页] Example Domain」，列表出现该文档。
  - 一次选择两个文件上传 → 提示「已上传 2 份文档」，两份文件均出现在列表。
  - 验收产生的文档与测试会话随后通过管理接口清理，未留在开发数据目录。
- CI：`ci.yml`（后端 / 前端 / 桌面三套测试 + `docker compose config` 校验）与 `codeql.yml` 在 main 上
  首次运行即通过（run 见 GitHub Actions）；Dependabot 已按配置为 pip / npm / actions 开出更新 PR。
- 未覆盖：应用界面本身的多语言（界面仍为中文，README 与介绍页为三语）；代码签名与真机（macOS/Linux）验收。



## Docker 部署验证（compose 栈，2026-10-01）

- `docker compose build` 在本机 Docker Desktop 29.1.3 上通过，生成 `campus-agent-backend` 与 `campus-agent-frontend` 两个镜像（后端 `python:3.11-slim`，前端 `node:22-alpine` 构建 + `nginx:alpine` 运行）。
- `docker compose up -d` 后 database / backend / frontend 三个服务全部启动，`postgres:16-alpine` 与后端均通过健康检查（后端的检查调用 `/api/health`）。
- 端点实测：`http://localhost:8080/` → 200（1,265 字节 HTML）、`/manifest.webmanifest` → 200（588 字节）、`/sw.js` → 200（1,622 字节）、`/api/health` → 200 且内容为 `{"status":"ok","rag_enabled":false,"rag_degraded":false,"models":{"qwen":false,"deepseek":false},"demo_services":true}`。
- 数据库：后端在容器内用 `DATABASE_URL` 连接 `database:5432`，`select 1` 与 `select version()` 均成功，返回 PostgreSQL 16.15；连接串由根目录 `.env` 透传（`POSTGRES_PASSWORD` 为随机生成，`.env` 已被 `.gitignore` 忽略）。
- 真实浏览器（Edge）打开 `http://localhost:8080/`：标题「Mens 工作台」、侧栏与「后端已连接」正常，零失败请求、零页面错误。
- 验收结束后执行 `docker compose down` 停止容器（保留命名卷，数据不丢）。

## Mens 1.2.0：跨平台构建、联网搜索与可安装网页版（2026-10-01）

Windows 安装包 `release/Mens-Setup-1.2.0-x64.exe`（126,402,135 字节，SHA-256 `02d9bfa13e2a5251ce00890f053e080eb33a033246077e6cd42d92279652ab71`）由跨平台构建脚本 `scripts/build_desktop.py` 完整重建；macOS 与 Linux 产物由 CI 构建（见下）。

- 许可证：项目以 **Apache License 2.0** 发布（仓库根目录 `LICENSE`，归属声明见 `NOTICE`，第三方组件清单见 `THIRD-PARTY-NOTICES.md`）。安装包通过 electron-builder 的 `extraResources` 把 `LICENSE`、`NOTICE` 与 `THIRD-PARTY-NOTICES.md` 放进 `resources/`，安装后可在 `%LOCALAPPDATA%\Programs\Mens\resources\` 核对（本机已确认 LICENSE、NOTICE 与第三方清单分别为 11,339、731 与 2,401 字节，Mens.exe 版本 1.2.0）。

- 跨平台构建：单一脚本支持 `--os win|mac|linux` 与 `--arch x64|arm64`；因为 PyInstaller 无法交叉编译，指定非当前平台会被明确拒绝；虚拟环境解释器（`Scripts/python.exe` 与 `bin/python`）、npm 命令、图标与打包目标均按平台选择；macOS 构建自动设置 `CSC_IDENTITY_AUTO_DISCOVERY=false` 以跳过未配置的签名身份。打包目标：Windows NSIS、macOS dmg+zip、Linux AppImage+deb。
- 图标：`scripts/create_icon.py` 在装有 Pillow 时跨平台生成，缺失 Pillow 时仅在 Windows 回退到原有 PowerShell 缩放。本机校验生成结果：`.icns` 容器 7 个条目（icp4/5/6、ic07/08/09/10，负载均为有效 PNG），`.ico` 9 档（16–256），PWA 图标 192/512/180 尺寸精确。
- 跨平台代码：桌面启动器按 `process.platform` 选择 `campus-backend(.exe)` 与虚拟环境解释器；冻结后端集成测试同样按平台解析路径；数据目录沿用 Electron 的 appData 规则（macOS `~/Library/Application Support/CampusAgent`，Linux `~/.config/CampusAgent`）。凭据存储：Windows 用 DPAPI，macOS/Linux 为 `0600` 明文文件（已在 PLATFORMS.md 标明这不是加密）。
- 可安装网页版（PWA）：Web App Manifest、离线外壳 Service Worker（仅缓存界面资源，`/api` 一律走网络）、iOS 安全区适配；构建产物包含 `manifest.webmanifest`、`sw.js`、`icon-192/512.png`、`apple-touch-icon.png`。
- 持续集成：`.github/workflows/build-desktop.yml` 在 windows-latest、macos-13（x64）、macos-latest（arm64）、ubuntu-latest 上分别执行同一套构建脚本并上传产物，推送 `v*` 标签时自动创建 Release 并把各平台产物附加到 Release；已存在的同名资产不会被覆盖，因此 Release 上的 Windows 安装包保持为本机已验证的那一份。
- 测试：后端 260 passed（65 subtests）、前端 13 passed、桌面 8/8；构建脚本内部的冻结后端真实集成测试同样通过。
- Windows 安装验收：静默升级安装退出码 0；`Mens.exe` 文件版本 1.2.0；卸载项显示“Mens 1.2.0”；桌面与开始菜单快捷方式指向 `%LOCALAPPDATA%\Programs\Mens`。
- 安装版界面验收（CDP 驱动安装后的应用，无控制台错误与失败请求）：侧栏显示 v1.2.0；设置页可通过界面启用「联网搜索」并保存（返回“已保存：自动选择。”，状态显示“当前生效：自动选择（bing）”）；聊天窗口开关可开启，开启后提问返回 5 条真实网页结果与可点击链接（`baike.baidu.com` 等），并提示“已联网检索（刚刚）”。
- 未验证：**macOS 与 Linux 产物未在真机安装运行**；**CI 流水线尚未实际执行**（仓库首次推送后才会运行）；移动端 PWA 仅在桌面浏览器验证，未在真机 Android/iOS 上安装；安装包未签名、未公证；Tavily 与博查仅按文档结构解析（无 Key），实测的免密钥通道为 Bing；真实云端模型对联网资料的引用质量仍以 mock 模型验证链路。
- 脚本与截图：`.tmp/qa-batch6/`；安装验收脚本 `check_installed_120.py` 与截图 `installed-1.2.0-chat.png`（位于验证用临时目录）。

## 开发副本第六批改进：联网搜索（2026-10-01，已包含在 1.2.0 安装包）

新增可选的实时联网搜索与网页读取，聊天窗口可按消息开关。本节改动已包含在 1.2.0 安装包中。

- 改动范围：`backend/app/web_search.py`（Bing HTML 搜索、Tavily/博查 API、页面正文提取、配置持久化）；`agent.py`（联网结果与知识库资料统一编号注入提示词，网页条目带链接与检索时间；无模型时降级回答也会列出链接）；`main.py`（`GET /api/web/status`、`PUT /api/web/config`、`ChatRequest.web`、来源规范化 `public_sources`）；前端聊天底部「联网搜索」开关与来源链接、设置页「联网搜索」区块；桌面 `campus:open-external-https`（HTTPS 白名单校验）供网页链接打开；`web-search.json` 纳入备份清单。
- 后端测试：260 passed，65 subtests passed（新增解析、URL 安全、配置加密、联网接线 21 项）。
- 前端测试：13 passed（新增联网偏好持久化）；桌面 Electron 测试 8/8（preload 暴露面精确断言 + HTTPS 打开器校验）。
- 真实网络验证（本机真实 Bing）：`POST /api/chat/stream` 携带 `web:true` 返回 `web.provider=bing`、4 条真实结果（百度百科、中国政府网等）与真实 URL；`fetched_at` 记录检索时间；回答降级路径（未配置模型）在正文中列出链接。
- 浏览器验证（Playwright + 本机 Edge，真实后端 + mock 模型）：开关可切换并记住；发送后出现「参考来源（含联网检索）」、4 条来源与 4 个可点击域名链接（`baike.baidu.com`、`www.gov.cn`）、提示「已联网检索（刚刚）」；设置页显示「当前生效：Bing 网页搜索（免密钥）（bing）」；无控制台错误与失败请求。
- 安全约束：仅 HTTPS 与 443、连接固定到解析后的公网地址（保留 SNI，防 DNS 重绑定）、禁止跳转、响应 ≤400 KB、单页正文 ≤2000 字；主机解析到内网/回环地址直接拒绝；未启用时完全不发起请求（测试断言不会触网）。
- 未验证：Tavily 与博查 API 的真实响应（本机无这两个服务的 Key，仅按文档结构解析并用模拟响应覆盖）；真实云端模型对网页资料的引用质量（用 mock 模型验证链路）；安装包内的联网搜索（需重建安装包）。
- 脚本与截图：`.tmp/qa-batch6/`（ui_check_web.py、聊天与设置页截图）。

## 开发副本第五批改进：1.1.0 版本与更新检查

安装包 `release/Mens-Setup-1.1.0-x64.exe`（120,292,332 字节，SHA-256 `cb73d6b02e044fc1cc09f113cf89d3a6a4df4032a058f0c1835efe30b15d3e55`）由 `build-desktop.cmd` 完整重建：脚本内依次通过后端 240 项与 44 subtests、前端 12 项 vitest、桌面 8 项 Electron 测试，以及冻结后端前后的真实后端集成测试，再由 PyInstaller 冻结后端、electron-builder 生成 NSIS 安装包。

- 安装：静默升级安装（`/S`）退出码 0；`Mens.exe` 文件版本 1.1.0；安装目录为 `%LOCALAPPDATA%\Programs\Mens`，桌面与开始菜单快捷方式指向新目录；卸载入口注册为“Mens 1.1.0”。
- 启动：安装版启动后自动拉起冻结后端，`%APPDATA%\CampusAgent\logs\backend.log` 出现 “Application startup complete.”；退出应用时后端输出 “Application shutdown complete.” 并退出进程，无残留。
- 界面验收（CDP 驱动安装版窗口；无控制台错误、无失败请求）：侧栏版本显示 v1.1.0；设置页含「备份与恢复」「后端日志」「版本与更新」等区块；「后端日志」区块读取到真实日志内容；窗口调整为 1240×820 后 `window.json` 记录 `{"x":660,"y":286,"width":1240,"height":820,"maximized":false}`。
- 更新检查（安装版 + 冻结后端）：临时在数据目录 `.env` 配置 `UPDATE_MANIFEST_URL=https://registry.npmjs.org/vue/latest` 后，界面显示“当前版本 v1.1.0。发现新版本 3.5.43。”，证明冻结后的后端可以完成真实 HTTPS 请求；验证完成后已还原用户 `.env`。未配置时提示“未配置更新清单地址（.env 中的 UPDATE_MANIFEST_URL），不联网检查”。
- 更新检查单独验证：真实 HTTPS 清单读取并按版本比较；不可达域名返回“无法读取更新清单”；非 HTTPS 地址在发起请求前即被拒绝；缺少管理员令牌返回 401。
- 升级路径说明：1.0.0 的安装目录为 `%LOCALAPPDATA%\Programs\CampusAgent`，1.1.0 起为 `%LOCALAPPDATA%\Programs\Mens`；升级后旧目录会残留（约 390 MB），注册表只保留“Mens 1.1.0”，可手动删除旧目录。用户数据始终位于 `%APPDATA%\CampusAgent`，升级不丢失（本次验证后原有会话、设置与 .env 均保持原样）。
- 未验证：真实云端 API Key 与真实大模型断点续传（同前）；代码签名与自动更新（未配置发行者证书，更新检查只提示并打开下载页）；多显示器拔插后的窗口坐标还原（仅由桌面单元测试覆盖越界忽略）。
- 脚本与截图：`.tmp/qa-batch5/`（ui_check_update.py、版本与更新区块截图）；安装验收脚本 `check_installed_app.py`、`check_install.ps1`（在验证用临时目录）。

## 开发副本第一批改进（2026-10-01，已包含在 1.1.0 安装包）

在 1.0.0 源码基础上增加流式回答、停止生成和历史会话管理。本节记录当时的验证结果；安装包已在 1.1.0 中重新构建。

- 改动范围：`POST /api/chat/stream`（SSE：meta/delta/done/error，中断时保存已生成内容并标记 `partial`）；会话列表/删除/清空接口与会话 `client_id` 隔离（网页用浏览器本地存储，桌面用 `workspace.json`，旧会话在下一次发言时归属请求方）；聊天页“历史对话”面板、逐字流式显示与“停止生成”按钮。
- 后端测试：222 passed，44 subtests passed（新增流式协议、停止持久化、会话隔离、旧库列迁移等 15 项）。
- 前端 TypeScript 检查与生产构建通过（保留既有的大资源块体积提示）；Electron 单元测试 6/6 通过（含 clientId 读写与校验断言）。
- 真实 HTTP 冒烟：使用模拟 Ollama 流式服务经 `curl -N` 验证事件序列 meta→delta×8→done，末事件 `mode=llm`；错误 client_id 删除返回 404、他人会话列表为空。
- 浏览器自动化（Playwright 驱动本机 Edge，模拟模型每段 0.4 秒）：回答在界面逐段增长（8 次采样 2→17 字符）、流式光标出现后在完成时消失；“停止生成”保留半截回答并显示“已停止”徽标，再次打开该会话仍带该标记；历史面板列出会话、可恢复、可清空。
- 未验证：真实云端 API Key 的流式链路（提供商地址必须 HTTPS，本次未使用密钥）；真实模型权重（验证时本机 Ollama 未安装模型）；重新构建后的安装包验收。
- 脚本与截图：`.tmp/qa-streaming/`（mock 服务、ui_check.py、report.json、两张界面截图）。

## 开发副本第二批改进（2026-10-01，已包含在 1.1.0 安装包）

新增 Word (.docx) 知识库上传、镜像模型下载断点续传、数据备份导出/导入。安装包仍未重新构建。

- 改动范围：`POST /api/documents/upload` 支持 docx（标准库解析 `word/document.xml`，旧版 .doc 明确报错）；GGUF 下载按 pinned SHA-256 保存断点文件、`Range` 续传并在续传前重算已下载部分的哈希，完整未导入的文件可直接重试导入；`GET /api/backup/export`（VACUUM INTO 快照 + 配置文件 + SHA-256 清单）与 `POST /api/backup/import`（先校验清单与表结构，再通过 SQLite backup API 原地恢复，config 文件原子替换）；设置页「备份与恢复」；桌面通过 IPC 系统对话框读写备份 zip。
- 后端测试：234 passed，44 subtests passed（本批新增 docx 解析/拒绝、备份往返与恶意 zip 拒绝、断点续传/续传校验/导入重试共 12 项）。
- 桌面 Electron 测试 7/7；前端类型检查与生产构建通过。
- 真实 HTTP：docx 上传返回逐段提取文本；导出 zip 含 `campus.db` 与 `mens-backup.json`（含大小与 SHA-256）；删除会话后导入成功恢复（404 → 200）。
- 浏览器自动化（Playwright + 本机 Edge）：通过真实文件输入上传 docx（列表 4→5 行）；「导出备份」触发真实下载 `mens-backup-2026-10-01.zip`（含 campus.db 与清单）；「导入备份」经确认弹窗与文件选择器完成并显示“已恢复：campus.db。”
- 未验证：真实 400MB–1.1GB 模型断点续传（用 2.7MB 模拟流验证中断保留、Range 续传、校验后跳过下载与导入重试）；跨机器导入（DPAPI 加密的密钥在他机无法解密，需重新填写）。
- 脚本与截图：`.tmp/qa-batch2/`（docx 夹具、ui_check2.py、report.json、界面截图）。

## 开发副本第三批改进（2026-10-01，已包含在 1.1.0 安装包）

新增本机报修记录列表、窗口大小/位置记忆、桌面设置页后端日志查看。安装包仍未重新构建。

- 改动范围：`GET /api/services/repairs`（含联系方式，管理员授权才可读，桌面模式自动授权）；校园服务页在报修表单下方显示本机报修记录并支持刷新；`window.json` 记录窗口大小/位置/最大化，读取时校验尺寸范围与是否仍在显示器内；桌面设置页「后端日志」通过 IPC 读取最近 200 KB 日志（缺失时给出提示）。
- 后端测试：235 passed，44 subtests passed（新增报修记录授权与排序 1 项）；桌面 Electron 测试 7/7（新增窗口状态越界忽略与关闭时持久化、日志读取与来源校验）。
- 真实 HTTP：报修记录接口未带令牌返回 401，带令牌按时间倒序返回并包含地点/问题/状态。
- 浏览器自动化（Playwright + 本机 Edge）：报修页显示“本机报修记录”表格（提交时间/地点/问题/状态），提交新工单后列表出现对应记录，演示数据提示可见。
- 未验证：安装包内的窗口记忆与日志查看（需重建安装包后人工确认；Electron 侧已由 vm 单元测试覆盖）。
- 脚本与截图：`.tmp/qa-batch3/`（ui_check3.py、check_repairs.py、界面截图）。

## 开发副本第四批改进（2026-10-01，已包含在 1.1.0 安装包）

新增前端单元测试与构建分包，安装包仍未重新构建。

- 改动范围：`frontend/tests/`（SSE 帧解析、外观推导、工作区存储与 client_id 校验，共 12 项，`npm test`）；`frontend/vitest.config.ts`；`vite.config.ts` 手动分包（vendor-vue / vendor-element）并调整体积阈值；`scripts/build_desktop.py` 在编译前增加 `npm test` 门禁。
- 前端测试：12 passed（vitest + happy-dom）。
- 构建产物：主包 1,105 kB → 71 kB，vendor-vue 86 kB，vendor-element 947 kB，构建警告消失。
- 浏览器验证（Playwright + 本机 Edge 加载分包后的构建）：控制台无错误、无 4xx/5xx 请求；聊天页模型选择器、设置页「备份与恢复」、校园服务页均正常渲染。
- 未验证：重建安装包后的整体验收。

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
- BGE-M3/Chroma 完整向量包不在本次桌面升级验收范围；PostgreSQL 与 Docker 全栈已在「Docker 部署验证」小节中实测。
