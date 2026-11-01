<div align="center">

<img src="site/img/logo.png" alt="Mens 校园助手" width="104" height="104" />

# Mens 校园助手

**本地优先的校园问答工作台**  
Electron 桌面外壳 + Vue 3 界面 + FastAPI 后端，可在单机上离线运行

<a href="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml"><img src="https://github.com/HuanMoovo/campus-agent/actions/workflows/build-desktop.yml/badge.svg" alt="桌面构建状态" /></a>
<img src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-1.2.2-0e7c74" alt="版本 1.2.2" />
<img src="https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-Apache--2.0-0e7c74" alt="Apache-2.0" />
<img src="https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20PWA-0e7c74" alt="平台" />
<a href="https://star-history.com/#HuanMoovo/campus-agent&Date"><img src="https://img.shields.io/github/stars/HuanMoovo/campus-agent?label=%E2%98%85%20Stars&color=0e7c74" alt="Stars" /></a>

**中文** · [English](README.en.md) · [日本語](README.ja.md)

[下载 Windows 安装包](https://github.com/HuanMoovo/campus-agent/releases/latest) ·
[项目介绍页](https://huanmoovo.github.io/campus-agent/)（中文 / English / 日本語） ·
[平台支持](docs/PLATFORMS.md) ·
[验证记录](docs/VERIFICATION.md) ·
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
| 断流提示 | 模型已输出后发生断线、错误帧或缺少结束标记时明确报错，已有回答按部分内容保留，避免误当完整结果 |
| 停止生成 | 随时中断；已生成内容连同「已停止」标记一并保存，历史不会伪造完整答案 |
| 多轮对话 | 保留上下文；刷新或重启后可恢复历史会话 |
| 恢复失败保护 | 桌面偏好读取失败时暂停会话操作和自动回写，保留原文件；可在聊天页或设置页重试恢复 |
| 来源片段 | 回答附带命中的知识库片段，便于核对依据 |
| 会话隔离 | 开启网站登录后按登录账号隔离；桌面版和免登录网页版按客户端配置隔离；历史、续聊、重答、反馈、导出及删除使用相同归属检查 |
| 回答可信度标记 | 演示数据、降级检索、联网来源等状态在界面上明确标注 |
| 会话导出 | 任意历史对话可导出 Markdown（便于阅读留档）或 JSON（便于脚本处理），内容含来源链接、工具调用与演示数据标注；桌面版走系统保存对话框，网页版直接下载 |
| 推理强度 | 输入框内提供「默认 / 低 / 中 / 高 / 超高 / 最高」，按当前模型和接口的支持情况启用；选择逐请求生效并保存在本机。Responses 使用 reasoning.effort，Chat Completions 使用 reasoning_effort；自定义接口可在高级设置声明支持档位。仅支持思考开关的模型单独显示「开启推理」，自动路由使用默认策略 |
| 项目修改与恢复 | 桌面版可为既有单文件生成完整 diff；Windows 本地 NTFS 支持逐次原生确认后应用、撤销或保留修改。版本冲突时保留当前文件及恢复原文，恢复记录跨重启保存；生成提案本身不写项目文件 |
| 项目权限 | 输入框内可选「只读 / 修改前确认」，保存在本机；仅控制本应用的项目应用、撤销与保留操作，读取、提案与复制仍可用 |
| 思考过程 | 深度档回答时，思考链实时流式展示、思考中自动展开、回答开始后自动收起；可随时手动开合，随对话保存，恢复历史后仍可查看 |
| 富文本回答 | 回答按 Markdown 渲染：标题、列表、表格、代码块（语法高亮）、引用与链接；HTML 经净化，链接在桌面版走系统浏览器打开 |
| 回答操作 | 每条回答下方提供操作条：复制原文、重新生成（替换该回答，不留重复问答）、用深度重答（不改档位的一次性深度回答）、有帮助 / 没帮助（反馈随对话保存，再次点击可取消） |
| 附件提问 | 拖拽、粘贴或点选文件随问发送：文本类直接读取，PDF / Word 经解析接口处理（单文件 ≤ 5 MB）；最多 3 个附件，附件正文仅注入本次提问，历史保留原文与「[附件]」文件标注 |
| 命令面板与斜杠指令 | `Ctrl + K` 打开命令面板：输入即过滤（新建对话、历史、导出、切换页面、深浅色等），↑ / ↓ 选择、回车执行；输入框内以 `/` 唤出斜杠指令（`/new`、`/history`、`/export`、`/theme`） |
| 历史管理 | 历史对话全文检索（提问与回答，带命中摘要）、重命名、置顶与批量删除；触屏设备不依赖悬停同样可操作 |

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
| 结果处理 | 先过滤广告位与无关条目（相关性按标题关键词命中判定，同站去重），再抓取前 1–3 个网页正文（单页 ≤ 2000 字、响应 ≤ 400 KB），与知识库资料统一编号后注入提示词；全部结果与问题无关时明确提示、不展示无关网页 |
| 引用 | 回答中列出带链接的来源与检索时间 |
| 搜索兼容 | 跳过异常候选链接；本地解码 Bing 已知跳转链接后按目标站点去重；支持 UTF-8、GB18030 等中文页面编码 |
| 出站约束 | 仅 HTTPS、固定到已校验的公网 IP（保留 SNI，防 DNS 重绑定）、禁止跳转、有大小与超时上限 |

### 校园服务与报修

| 功能 | 说明 |
| --- | --- |
| 校园数据接口 | 九类可配置的 HTTPS JSON 接口：成绩、课表、学分统计、空教室、报修、校园公告、图书馆、餐饮、校车 |
| 接口配置 | 支持结果路径（JSON 取值路径）与 Bearer 令牌；地址必须 HTTPS |
| 报修 | 用户显式提交；配置接口后 POST 到学校，未配置时仅保存本机记录并标注「演示」 |
| 本机记录 | 报修提交后按时间倒序列出，便于确认提交结果 |
| 演示数据 | 未配置的接口返回明确标识的演示数据，不会假装已接入学校系统 |

### 有限校园查询任务（P4A）

在当前消息中明确请求成绩、课表、学分或空教室，例如「查询我的成绩和课表」，会按提及顺序执行最多 3 项不同的内置只读查询，重复请求只执行一次。同时请求全部 4 项时不发起任何查询，而是提示缩小范围。历史、附件、项目文本及模型或工具结果不能增加本轮读取授权；否定查询、解释政策或文档/代码讨论不会因包含服务名称而触发个人数据查询。

任务使用 20 秒协作式时间预算，在每次查询启动前和返回后检查时间与取消状态。这不是硬超时：进行中的同步调用可能超过预算后才返回，取消会阻止后续查询。无自动重试，规划与结果整理不额外调用模型。单项结果最多 4,000 字符，总结果最多 12,000 字符，并标注截短；部分查询失败时保留已成功结果，各项分别标明演示数据或学校接口。

普通回答和 SSE 共用同一执行器。SSE 断线后等待当前调用收尾，保留已完成结果和真实的部分/失败状态到历史；折叠运行详情显示查询次数、停止原因与截短提示。本阶段未加入持久任务续跑、MCP 批处理或扩大文件读取范围。详见 [P4A 规格](docs/superpowers/specs/2026-10-31-bounded-campus-reads-design.md)。

### 模型接入

| 方式 | 说明 |
| --- | --- |
| 云端 API | 13 家国内、14 个国际接入预设与自定义网关，共28个云配置槽；另有 Ollama；配置独立保存，密钥不回显 |
| 自动路由 | 分析 / 比较类问题优先选择已配置的 DeepSeek，其余优先 Qwen3；两者未配置时可选择已配置的兼容接口，也可手动指定 |
| 本地模型 | 内置模型目录（Qwen3 0.6B / 1.7B、DeepSeek R1 1.5B），支持 Ollama 官方 / Hugging Face / HF Mirror 下载源 |
| 下载可靠性 | 断点续传、固定版本、SHA-256 校验、导入重试，可查看进度与取消 |
| 降级策略 | 无密钥或模型不可用时，使用规则规划 + 知识库原文摘录，并明确标注 |

在「设置 → 模型 → 云端模型 API」选择提供商，填写对应账号的模型/接入点 ID 和密钥。国内预设包括百炼、DeepSeek、智谱 GLM、Kimi、豆包、硅基流动、腾讯混元（原平台）、百度千帆、MiniMax、阶跃星辰、讯飞星火、零一万物、小米 MiMo；国际预设包括 OpenAI Responses、Anthropic Claude、Google Gemini、Z.AI GLM、xAI Grok、OpenRouter、Groq、Mistral、Together、Fireworks、DeepInfra、Cerebras、Hugging Face Inference Providers、Cohere OpenAI 兼容入口。每项都有独立配置、基础地址、协议与官方文档提示。百炼地域/套餐、讯飞 APIPassword、千帆 V2 API Key、混元迁移等说明应按账号核对。

小米 MiMo 默认使用 api-key 原值认证头、max_completion_tokens 并关闭自定义温度；智谱国内与 Z.AI 国际标准 API 为不同配置槽，密钥不会复制。Groq 默认 max_completion_tokens；Cohere 使用专用 compatibility/v1 入口。Coding/Token Plan、批量、云 IAM 并不等于标准按量接口，需按官方账号合同另行接入。新增厂商预设都可从真实普通/流式问答入口选择；先前残留旧名单已修复并增加逐厂商路由回归。

自定义网关可选择 Chat Completions / Responses / Anthropic Messages / Gemini generateContent。展开「兼容选项」可设最大输出 token 数（64–65536），Chat Completions 还能选择 `max_tokens` 或 `max_completion_tokens`，并可关闭 temperature、流式或工具调用；原生协议自动使用各自字段与认证头。关闭流式后使用单次异步请求，关闭工具后保留确定性校园查询。旧配置保留默认值。

保存后分别测试对话、流式和工具能力，诊断保留耗时、错误分类与建议。每次只验证所选能力；没有观察到工具调用不等于不支持。未保存草稿须先保存再测试；清除密钥只清除密钥，换服务主机或端口须更换/清除原密钥。对话、附件和检索上下文会发送给所选服务商。当前支持纯文本、多协议流式与受控工具规划；P4A校园组合查询使用上述确定性执行器。模型专有推理扩展、多模态和云 IAM/OAuth 不表示已支持。Responses 深度模式请求 high 推理与自动摘要，其它原生模型暂按提供方默认思考设置；未知参数应按模型说明调整。DeepSeek 新版或自定义模型名保留，旧别名不保证仍可用。实际范围见 [完整支持矩阵](docs/research/2026-10-31-model-support-matrix.md) 与 [国内官方接口核验](docs/research/2026-10-31-domestic-model-providers.md)。

### 只读项目问答（桌面端）

在聊天输入区展开「项目文件」，通过系统目录选择器打开项目。可逐级浏览、点击文件作本机预览，再勾选最多 4 个文件随下一条问题发送。预览本身不会发送模型；提问时后端重新读取当前文件，回答来源显示相对路径、行号与截断状态。片段会发送到所选模型，并可能作为引用保留在本机对话历史中。

项目读取限定于本次授权目录，排除凭据、私钥和常见生成目录，拒绝路径越界、符号链接、junction 与硬链接。仅支持白名单 UTF-8 文本；每文件最多读取 256 KiB 并预览 12,000 字符，每次最多提供 16,000 字符，进入模型时还遵守统一上下文预算。最终裁剪使用连续片段，路径/行号/指纹与实际模型片段一致。文件内容不能触发个人成绩查询、MCP 或项目写入。

重选、关闭目录或重启会撤销旧项目引用；历史重答不能仅按相同文件名自动切换到另一个项目，需要重新选择并发送新问题。网页版保留附件问答，项目目录授权仅桌面端开放。文件应用走下述独立确认流程；没有终端执行或全盘自动扫描。

### 项目修改与恢复（桌面端）

输入框内的「项目权限」在「只读」与「修改前确认」间切换，并保存在本机；桌面默认「修改前确认」，网页版固定只读。「只读」阻止本应用原生项目的应用、撤销和保留操作，预览、生成提案、复制原文、状态查询及备份原文材料仍可使用。「修改前确认」下每项修改仍需原生确认。切到只读会先撤销主进程内存中的修改许可，再尝试保存；磁盘保存失败不会放开修改，切回确认模式须保存成功才生效，并会显示保存失败提示。此设置只覆盖本应用的这三种项目操作，不是操作系统、MCP 或沙箱权限，也不提供完全访问模式。见 [项目权限规格](docs/superpowers/specs/2026-10-31-project-permission-selector-design.md)。

预览文件后可输入修改要求，按当前模型与推理档位生成提案，再审阅逐行 diff、原文和修改后全文。编辑仅支持 Windows 本地 NTFS 上的单个既有白名单 UTF-8 文件，完整正文最多 12,000 字符、64 KiB、2,000 行；超限拒绝，不用截断内容覆盖全文。BOM 和换行格式单独展示，版本保护使用完整原字节哈希及文件身份。

「应用」「撤销」「保留修改」每次都需系统原生确认。应用采用 COW：新内容写入暂存文件并校验，再通过两次不覆盖已有目标的重命名发布，原文件对象不原位写入。它不是崩溃原子事务，提交中原文件名可短暂缺失，故障可能留下暂存或备份材料。冲突不强制覆盖；结果待确认时只查询状态或复制原文，不自动重试写入。撤销要求文件仍匹配应用后的身份和完整哈希；保留修改只结束该条一键恢复记录，不改文件。

恢复原字节和操作记录持久保存在应用数据目录的 `project-changes.sqlite3`，属于需保管的本机数据，不会为恢复再次发送模型。关闭项目、提案过期和重启不会删除待恢复记录；重新通过原生选择器选择同一物理目录后，可查看记录、撤销匹配版本或复制恢复原文。最多保留 32 条未解决记录和 32 条已结束记录，已结束记录可淘汰。启动与状态查询不自动恢复项目文件。

支持普通用户文件的 owner/group、DACL（含保护状态）及相同完整性标签；owner/group 必须与新暂存文件一致。只读、系统、reparse、加密、压缩、稀疏文件及命名备用数据流（ADS）等不支持。自定义文件审计规则（SACL）不在本轮支持范围，不自动启用 `SeSecurityPrivilege`，也不声称保留完整 Windows 安全描述符。此阶段没有新建、删除、重命名用户文件、多文件事务、终端或自动 Git 操作。

### 设置与 Token 使用量

- 设置整合为「通用、模型、Token 用量、连接、数据与应用」五组，沿用黑白主题；切换分组保留未保存的模型和接口草稿，日志与诊断按需展开。
- 「Token 用量」展示近 7／30 个 UTC 自然日的输入、输出、已报告总量、日趋势和模型分布，并提供逐日明细。仅记录启用功能后的实际模型请求，不按历史文本补算，也不代表服务商账单。
- 接口缺少计数时显示「—」及未报告／部分报告请求数；停止或失败后的快照可能不完整。缓存和推理细分不会重复加到总量。模型连接测试不计入；规则回答不产生模型请求。
- Chat Completions 接口如支持流式用量，可在「模型 → 高级兼容选项」启用 `stream_usage`；默认关闭，避免向不支持的兼容网关强加参数。其他已接入协议读取各自返回的用量字段。
- 桌面统计当前本机应用的无账号记录；开启网站登录时按账号隔离，免登录网站按客户端隔离。用量独立于聊天记录，删除或重新生成对话不清除已发生的使用量；普通数据库备份包含新表，旧备份仍可导入。

实现边界和验证见[设置整合与用量说明](docs/research/2026-10-31-settings-token-usage.md)。

### 数据、备份与更新

| 功能 | 说明 |
| --- | --- |
| 备份导出 | 默认 format 1：知识库文档、会话、模型与校园接口配置，SQLite 通过 backup API 生成一致性快照，附各文件大小与 SHA-256 清单；可勾选「包含项目恢复原文」导出 format 2 |
| 备份导入 | 完整校验 ZIP、清单、原文材料及数据库后恢复文档、会话和配置；可选原文仅合并为复制材料，并报告新增与重复数量（zip 内含密钥文件，请妥善保管） |
| 更新检查 | 管理员配置 HTTPS 清单后，设置页可检查新版本并打开下载页；留空则该功能完全不联网 |
| 版本一致性 | 构建脚本校验桌面、前端、后端三处版本号一致后才允许打包 |

「包含项目恢复原文」默认不勾选；普通 format 1 不包含项目恢复原文。勾选后请求 `include_project_recoveries=true`，format 2 可附带受控的 `project-recovery.json`，包含已有恢复原文及此前导入的材料。每包及本机材料库最多 256 条、原始字节合计 16 MiB，JSON 最多 25 MiB；单文件仍限 64 KiB、12,000 字符、2,000 行。超限会明确失败，不会静默删除原文。

导入原文按物理根目录、相对路径和原字节哈希去重，事务合并到独立的 `project-recovery-archive.sqlite3`，只供复制。它不替换 `project-changes.sqlite3`、操作状态或防重放 tombstone，不恢复旧撤销权限，也不向项目工作目录写入文件。重新通过原生选择器选择同一物理目录后，可在独立的备份材料区复制原文；另一设备或目录副本不会自动关联。普通备份和可选原文备份均不包含项目工作树或可执行的恢复操作状态。

旧 format 1 备份继续兼容。导入拒绝重复、未知或越界 ZIP 条目，限制单项及合计解压内容为 200 MB，并验证适用清单的大小与 SHA-256；format 2 要求清单与条目严格对应。数据库按可信应用 schema 重建后才发布，不执行上传的触发器或视图；每次请求使用独立暂存目录，导入/导出发布串行处理。无效输入在应用数据变更前拒绝；运行时 I/O 失败仍可能造成部分应用数据或配置恢复，不保证跨数据库与文件系统的崩溃原子性。

### 桌面体验

| 功能 | 说明 |
| --- | --- |
| 开箱即用 | 安装包内置 Python 运行时，无需另装 Python / Node / 数据库 |
| 窗口记忆 | 记住窗口大小与位置（越界坐标会被丢弃） |
| 日志与数据目录 | 设置页可查看后端日志、打开数据目录 |
| 外观 | 黑白灰工作台，支持浅色 / 深色 / 跟随系统；统一侧栏导航与历史，移动端抽屉适配 |
| 界面语言 | 中文 / English / 日本語，默认跟随系统，选择会记住（当前覆盖应用外壳、问答页与外观设置） |
| 运行时校验 | 冻结后端以随机端口 + 一次性令牌启动，桌面外壳校验启动信封后才加载界面 |
| 快速提问窗 | `Ctrl + Shift + K` 全局唤起居中浮层：输入回车即发送并自动跳转到对话页 |
| 首次使用引导 | 首次启动显示 4 步引导（对话 / 模型与推理强度 / 历史与导出 / 快捷键与指令），可随时从命令面板重新打开 |
| 完成通知 | 窗口不在前台时，回答完成后发送系统通知 |

### 插件与运维

| 功能 | 说明 |
| --- | --- |
| 插件安装 | GitHub 自定义安装：粘贴 GitHub 仓库地址即读取仓库根目录 `plugin.json`（经 jsDelivr 与 raw.githubusercontent.com 依次尝试并自动重试多个解析地址）；也支持 `/tree/<分支>` 链接与 HTTPS 清单地址，示例见 `examples/plugin.json` |
| 插件清单 | HTTPS JSON 清单；插件地址须为公网 HTTPS 主机，`PLUGIN_ALLOWED_HOSTS` 可进一步限定 |
| 调用方式 | 由管理员显式试调用；插件只能返回 JSON，普通问答不会自动向外部插件发送消息 |
| 出站约束 | 与联网搜索相同的 HTTPS / 固定 IP / 禁跳转 / 限额策略 |

### MCP 服务器（外部工具）

系统同时是一个 MCP（Model Context Protocol）客户端，用标准输入输出连接本机的 MCP 服务器，
把它们的工具按需交给模型：

- 在「MCP」页登记服务器（启动命令、参数、环境变量），点「测试」会**真实启动一次子进程**，
  完成握手并拉取工具清单；只有已启用且测试过的服务器才会把工具暴露给模型。
- 工具名统一为 `mcp__<服务器>__<工具>`，参数原样透传，一次问答最多调用一个，结果原样展示。
- 环境变量（可放令牌）在接口层只回键名与掩码，不回显明文。
- 本次实现只包含 stdio 传输，网络型传输（SSE / streamable HTTP）不在范围内。

### 命令行（CLI，独立安装）

命令行是**独立工具**，不打包进桌面程序：它与桌面端共用同一套后端代码，数据目录默认在安装目录下，
也可用 `CAMPUS_DATA_DIR` 指向桌面端的数据目录。一键安装（脚本会放到用户目录、建独立虚拟环境、生成 `mens` 命令）：

```powershell
# Windows（PowerShell）
irm https://raw.githubusercontent.com/HuanMoovo/campus-agent/main/scripts/install-cli.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/HuanMoovo/campus-agent/main/scripts/install-cli.sh | bash
```

也可直接在仓库里运行（开发用）：

```bash
python -m app.cli ask "图书馆开放时间"                 # 提问一次（--json 便于脚本处理）
python -m app.cli chat                                 # 交互式对话：/quit 退出、/new 新对话
python -m app.cli mcp add campus --command npx --args -y <server-package>
python -m app.cli mcp list                             # 已登记服务器
python -m app.cli mcp test campus                      # 真实连通性检查
python -m app.cli mcp tools --json                     # 暴露给模型的工具
python -m app.cli serve --port 8000                    # 只启动本地后端
```

`--args` 后面的内容原样传给服务器进程，因此可写连字符开头的参数；`--env KEY=VALUE` 可重复。

### 网站部署（可选）

除桌面版外，还可以把 Mens 部署成带登录的网站，免费平台即可运行：

- 仓库自带 `Dockerfile.web`（前端构建 + FastAPI 单容器）与 `render.yaml`；
  在 Render 用 GitHub 登录后 **New → Blueprint** 选中本仓库即可，详见 [DEPLOY.md](docs/DEPLOY.md)。
- 打开 `AUTH_REQUIRED=true` 后，除健康检查与登录接口外的所有接口都要求登录：
  口令以 PBKDF2-HMAC-SHA256 散列存储，会话走 HttpOnly Cookie，服务端只存令牌散列。
- 首次启动会按 `AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD` 创建管理员
  （口令留空则生成随机口令并打印在服务端日志里，仅打印一次）。
- 「账号」页提供完整用户管理（新建、改角色、禁用、删除、重置口令、强制下线），并支持自助注册与登录后自助改密（`ALLOW_REGISTRATION`、`REGISTER_CODE`）。
- 桌面版不受影响：`AUTH_REQUIRED` 默认关闭，桌面包继续使用外壳注入的令牌。
- 免费实例的限制（15 分钟休眠、SQLite 随实例重建重置）已写入 docs/DEPLOY.md。

## 平台支持

| 平台 | 状态 | 交付物与数据目录 |
| --- | --- | --- |
| Windows 10/11 x64 | **已构建并真机验收** | `Mens-Setup-1.2.2-x64.exe`（NSIS，用户级安装到 `%LOCALAPPDATA%\Programs\Mens`），数据在 `%APPDATA%\CampusAgent` |
| macOS 12+（Intel） | CI 构建，未真机验收 | `Mens-1.2.2-x64.dmg` / `.zip`；未签名未公证，首次打开需右键「打开」 |
| macOS 12+（Apple silicon） | CI 构建，未真机验收 | `Mens-1.2.2-arm64.dmg` / `.zip`；数据在 `~/Library/Application Support/CampusAgent` |
| Linux x64 | CI 构建，未真机验收 | `Mens-1.2.2-x86_64.AppImage`（免安装）、`Mens-1.2.2-amd64.deb`；数据在 `~/.config/CampusAgent` |
| Android / iOS | 不提供原生应用 | 使用可安装网页版（PWA）：浏览器打开部署好的站点 → 添加到主屏幕；推理由服务端完成 |

> 「已验收」指在对应系统上真实安装、启动并完成界面检查；「CI 构建」指由 GitHub Actions 生成产物但尚未真机运行。
> 平台矩阵、构建命令与原因说明见 [PLATFORMS.md](docs/PLATFORMS.md)，实际结果与验收范围见 [VERIFICATION.md](docs/VERIFICATION.md)。

### Release 资产（v1.2.2）

| 资产 | 大小 | 说明 |
| --- | --- | --- |
| `Mens-Setup-1.2.2-x64.exe`（+ `.blockmap`） | 126,502,970 B | Windows 安装包，本机安装验收使用的就是这一份 |
| `Mens-1.2.2-x64.dmg` / `Mens-1.2.2-x64.zip` | ≈ 158 MB | macOS Intel |
| `Mens-1.2.2-arm64.dmg` / `Mens-1.2.2-arm64.zip` | ≈ 151 MB | macOS Apple silicon |
| `Mens-1.2.2-x86_64.AppImage` / `Mens-1.2.2-amd64.deb` | 191 MB / 153 MB | Linux |

安装包内含 `LICENSE`、`NOTICE` 与 `THIRD-PARTY-NOTICES.md`（安装后位于 `resources/`）。

## 快速开始

### 1. 安装 Windows 桌面版

下载 [最新 Release](https://github.com/HuanMoovo/campus-agent/releases/latest) 中的
`Mens-Setup-1.2.2-x64.exe`，双击安装（用户级安装，无需管理员权限），从开始菜单或桌面启动。
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

Windows 可直接双击 `scripts\install.cmd`（安装依赖、检查 LangGraph、跑后端测试、编译前端），
随后分别运行 `scripts\start-backend.cmd` 与 `scripts\start-frontend.cmd`，访问 <http://localhost:5173>。

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
- 该 compose 默认免登录，适合单机或可信网络；对公网开放时在根目录 `.env` 设置 `AUTH_REQUIRED=true` 启用内置登录（首次启动创建管理员；全部登录变量见 `.env.example`），并自行加上 HTTPS 与限流。
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
| `PLUGIN_ALLOWED_HOSTS` | 空 | 插件访问主机的可选白名单（逗号分隔；留空不额外限定，内网地址始终禁用） |
| `CORS_ORIGINS` | `http://localhost:5173` | 网页版跨域来源 |
| `WEB_SEARCH_ENABLED` | `false` | 联网搜索总开关 |
| `WEB_SEARCH_PROVIDER` | `auto` | `auto` / `bing`（免密钥）/ `tavily` / `bocha` |
| `WEB_SEARCH_API_KEY` | 空 | Tavily 或博查的密钥 |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 每次检索返回的结果条数 |
| `WEB_SEARCH_FETCH_PAGES` | `2` | 抓取正文的网页数（最多 3） |
| `UPDATE_MANIFEST_URL` | 空 | 可选的 HTTPS 更新清单，例如 `{"version":"1.2.2","url":"https://…","notes":"…"}`；留空则不做更新检查 |

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

九类接口的字段、取值路径与示例见 [CAMPUS-DATA.md](docs/CAMPUS-DATA.md)。要点：

- 只接受 HTTPS JSON；支持 Bearer 令牌与结果路径。
- 未配置的接口使用明确标识的演示数据；项目**不附带**任何真实学校接口、统一身份认证或模型密钥。
- 生产部署需学校提供已授权接口并完成验收；多人使用前还需补齐统一身份认证、按用户绑定学号、访问审计与限流（详见 [校园数据说明](docs/CAMPUS-DATA.md) 与 [架构说明](docs/ARCHITECTURE.md)）。

## 架构与安全边界

### 技术栈

- **前端**：Vue 3 + TypeScript + Vite + Element Plus + Pinia；构建时按依赖分包（主包约 71 KB）。
- **后端**：FastAPI + SQLAlchemy + LangGraph；默认 SQLite 单文件数据库，可选 PostgreSQL。
- **桌面**：Electron 外壳 + PyInstaller 冻结的 CPython（安装包内置运行时）。
- **可安装网页版**：清单（manifest）、离线外壳（service worker）与 iOS 安全区适配。

### 安全设计

- **本机优先**：桌面版后端只监听 `127.0.0.1` 的随机端口，每次启动生成一次性令牌；外壳注入额外请求头并收紧 Electron 配置（`nodeIntegration:false`、`contextIsolation:true`、`sandbox:true`、`webSecurity:true`、禁用 `webviewTag`），外部页面拿不到这些接口。
- **出站纪律**（插件 / 联网搜索 / 更新检查共用）：仅 HTTPS + 443；连接固定到解析并经校验的公网地址（保留 SNI，防 DNS 重绑定）；禁止跳转；有响应大小与超时上限；忽略系统代理环境变量（`trust_env=False`）；解析到内网地址直接拒绝。
- **密钥存储**：Windows 用 DPAPI 加密；macOS / Linux 无等价系统接口，改为 `0600` 权限的明文文件（同一用户可读）——这一点在 [PLATFORMS.md](docs/PLATFORMS.md) 中明确写出。
- **备份**：导出 zip 内含密钥文件，请妥善保管；勾选项目恢复原文后还会包含选定源码的原始内容。导入先校验清单与内容，可选原文仅合并为复制材料，不恢复项目写权限。
- **不伪造**：演示数据、降级检索、联网来源等状态一律在界面标注。

### 目录结构

```text
campus-agent/
├─ backend/         FastAPI 后端（app/ 源码、tests/ 测试、requirements*.txt）
├─ frontend/        Vue 3 前端（src/、tests/、dist/ 构建产物）
├─ desktop/         Electron 外壳（main.cjs、preload.cjs、lib/、assets/ 图标）
├─ docs/            项目文档（架构、平台、部署、校园数据与验证记录）
├─ site/            项目介绍页（GitHub Pages，中 / 英 / 日）
├─ scripts/         构建、打包与本地脚本（build_desktop.py、install.cmd、verify.ps1 等）
├─ assets/          品牌源图
├─ examples/        插件清单示例
├─ compose.yaml     Docker 部署（PostgreSQL + 后端 + Nginx）
└─ README.md 等     三语 README、CHANGELOG、CONTRIBUTING / LICENSE / NOTICE
```

## 性能重构（2026-10-31）

本轮按热点拆分模块，保留现有界面、接口和权限边界：

| 模块 | 当前行为 |
| --- | --- |
| `frontend/src/ui.ts` | 生产与集成测试共用安装器，只注册实际使用的 19 个 Element Plus 组件及 Loading，保留原 CSS |
| `ChatMarkdown` 与聊天滚动 | 已有消息不重复解析；流式首段即时显示，后续最多每 80 ms 渲染一次，结束、失败或停止时同步刷新最终正文；滚动请求合并调度 |
| `history_queries.py` | 先按归属筛选，再按置顶、最后消息活动时间及 ID 分页；每页最多 2 条 SQL，不读取完整回答与结果 JSON |
| 模型配置 | 每次状态枚举读取一个新的操作内快照，存储读取从 29 次降至 1 次；下次调用立即读取新配置，不跨请求缓存密钥 |
| 规划与恢复列表 | 无需 MCP 规划时使用确定性分支，省去一次规划模型请求；`ProjectRecoveryList` 合并刷新信号，同一目录只保留一个在途读取，期间变更触发一次后续读取并丢弃旧结果 |
| `compiled_documents.py` | 缓存不可变分段和 token 集合，默认上限 32 MiB / 2,048 条；稳定准入避免遍历淘汰抖动，每次仍读取当前 SQL 正文并校验内容哈希 |

相同构建口径下，前端 JS 从 **1,430,135 降至 853,863 字节（−40.3%）**，gzip 从 **449,828 降至 275,318 字节**。合成 SQLite 的 1,000 会话 / 40,000 消息、每页 50 项场景从 **1,001 降至 2 条 SQL**，中位耗时 **320.293 → 9.083 ms**。合成知识库 100 文档的旧版 / 新版冷 / 新版暖检索为 **69.910 / 90.768 / 2.438 ms**，500 文档为 **336.510 / 400.848 / 26.599 ms**；冷缓存和小预算可能增加开销，SQL 文档读取仍是全量。这些是构建与合成微基准，不是桌面启动计时或真实模型服务测速。详见[本轮结果与限制](docs/research/2026-10-31-performance-refactor-results.md)。

**向量索引兼容：** 文档版本哈希改为带独立域及 UTF-8 长度边界的格式，修复标题/正文含 NUL 时的分界歧义；旧向量版本失效，检索保持正确的关键词回退，重新索引或重建后恢复向量匹配。认证、项目授权及 NTFS 文件身份/完整哈希检查均不缓存。

## 测试与验证

本轮最终验证：后端 **1,349 passed、2 skipped、87 subtests passed**，前端 **298 passed**，桌面 **46 passed**；Vue 类型检查与生产构建通过。测试使用合成数据和空配置，未读取真实密钥或个人项目，未调用真实学校或模型服务，未重建安装包。此前 P4A 的 1,312 / 285 / 46 项为历史批次证据。

```powershell
# 后端
cd backend
.venv\Scripts\python -m pytest -q

# 前端与生产构建
cd ..\frontend
npm test
npm run build

# 桌面外壳
cd ..\desktop
npm test

# 一次跑完以上全部（Windows）
.\scripts\verify.ps1
```

离线环境可用系统 Python 运行两组纯逻辑测试（不依赖框架 / 网络 / 数据库）：

```powershell
cd backend
python -m unittest discover -s tests -p test_core_unit.py -v
python -m unittest discover -s tests -p test_agent_unit.py -v
```

这些测试覆盖核心校验与决策逻辑，但不能替代真实 FastAPI、LangGraph、Chroma、模型服务或浏览器联调；
没有任何测试能保证绝对无 Bug。已完成的验证范围与结论见 [VERIFICATION.md](docs/VERIFICATION.md)，安装包见 [Releases](https://github.com/HuanMoovo/campus-agent/releases)。

## 界面

| 聊天（含联网来源） | 设置（联网搜索） |
| --- | --- |
| <img src="site/img/chat-web-search.png" alt="聊天界面：联网搜索结果与来源链接" /> | <img src="site/img/settings-web-search.png" alt="设置界面：联网搜索配置" /> |

| 校园服务（报修与本机记录） |
| --- |
| <img src="site/img/campus-services.png" alt="校园服务界面：报修与本机记录" /> |

## 已知限制

- **macOS / Linux 产物未真机验收**：由 CI 构建，尚未在真机上安装运行。
- **未签名、未公证**：没有发行者证书，Windows / macOS 首次打开可能出现系统提示；正式分发前应配置签名。
- **校园接口与统一登录**：项目不附带任何真实学校接口、统一身份认证或模型密钥；生产部署需学校提供已授权接口并验收。
- **云端模型与联网搜索**：需要各自的 API Key（联网搜索的 Bing 通道免密钥）；搜索服务端的可用性受网络环境限制。
- **原生 Android / iOS 应用**：不在本项目范围，原因见 [PLATFORMS.md](docs/PLATFORMS.md)（Python 后端无法随应用上架移动平台）。
- **一键更新**：更新检查只提示版本差异并打开下载页，不做自动下载与静默安装。
- **多人部署**：应开启 `AUTH_REQUIRED` 并使用 HTTPS；登录账号的会话归属由服务端确认，免登录模式的客户端 ID 不能替代身份认证。生产仍需要操作审计、限流、数据库迁移与备份策略。
- **旧对话归属**：启用登录后，旧的无账号归属对话不会自动显示或被登录用户认领；数据仍保留，当前没有自动迁移入口。关闭登录也不会暴露已绑定账号的对话。桌面和免登录模式仍保留原有客户端历史及未分配历史的首次续聊认领行为。

## Star 趋势

> 本项目 star 增长曲线由第三方服务 **star-history.com** 实时生成；点击图表可查看交互版（支持 PNG / CSV 导出）。

[![Star History Chart](https://api.star-history.com/svg?repos=HuanMoovo/campus-agent&type=Date&theme=light)](https://star-history.com/#HuanMoovo/campus-agent&Date)

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
| [PLATFORMS.md](docs/PLATFORMS.md) | 平台矩阵、构建命令、macOS / Linux 凭据存储差异、移动端方案原因 |
| [DESKTOP.md](docs/DESKTOP.md) | 桌面版运行方式、数据目录、IPC 与安全设置 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构、模块职责与主要接口 |
| [开源 Agent 调研与方向建议](docs/research/2026-10-31-agent-roadmap-recommendation.md) | 54 仓库分类核验、重点源码机制、已完成基础修复与后续候选方向 |
| [CAMPUS-DATA.md](docs/CAMPUS-DATA.md) | 九类校园接口的字段与接入格式 |
| [VERIFICATION.md](docs/VERIFICATION.md) | 各版本的验证范围、结论与已知边界 |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | 第三方组件与许可证清单 |
