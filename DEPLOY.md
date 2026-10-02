# 把 Mens 部署成网站（免费平台）

桌面版之外，Mens 也可以直接跑成一个带登录的网站：后端托管前端构建产物，
数据默认落在容器内的 SQLite，单容器即可运行。

## 一、平台选择

| 平台 | 免费额度 | 适合度 | 备注 |
| --- | --- | --- | --- |
| **Render**（推荐） | Web Service 免费实例 | ★★★★ | GitHub 直接登录即可，蓝图文件 `render.yaml` 一键部署；15 分钟无访问休眠，冷启动 30–60 秒 |
| Hugging Face Spaces | Docker Space 免费 | ★★★ | 休眠更慢（48 小时），但国内访问常不稳定，且需要 HF 账号 |
| Vercel / Netlify / Cloudflare Pages | 静态托管免费 | ★ | 无状态环境，跑不了本项目的常驻后端与 MCP 子进程 |

本仓库自带 `Dockerfile.web`（前端构建 + FastAPI 一体）与 `render.yaml`，**首选 Render**。

## 二、Render 部署步骤

1. 用 GitHub 账号登录 <https://render.com>。
2. 控制台 → **New → Blueprint** → 选择本仓库（`HuanMoovo/campus-agent`）→ Apply。
   Render 会读取 `render.yaml`：免费实例、新加坡区域、健康检查 `/api/health`。
3. 等首次构建（约 5–8 分钟）。完成后访问 `https://<服务名>.onrender.com`。
4. 打开控制台 → 该服务 → **Environment**，查看自动生成的 `AUTH_ADMIN_PASSWORD`，
   用它和用户名 `admin` 登录（首次启动时创建的账号）。
5. 需要真实问答时，在同一页面补 `QWEN_API_KEY` 或 `DEEPSEEK_API_KEY`（不填则走演示回答）。

## 三、环境变量

| 变量 | 作用 | 部署建议 |
| --- | --- | --- |
| `AUTH_REQUIRED` | 打开登录门禁 | `true` |
| `AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD` | 首次启动创建的管理员 | 口令用平台生成的随机值 |
| `COOKIE_SECURE` | 会话 Cookie 只在 HTTPS 下发送 | `true`（Render 自带 HTTPS） |
| `SESSION_DAYS` | 会话有效期（默认 14 天） | 按需 |
| `CAMPUS_DATA_DIR` | 数据目录（SQLite 所在） | `/data` |
| `WEB_FRONTEND_DIR` | 后端托管的前端产物目录 | `/app/backend/web` |
| `DATABASE_URL` | 换用外部数据库（如 Postgres） | 默认 SQLite，可不填 |
| `QWEN_API_KEY` / `DEEPSEEK_API_KEY` | 模型密钥 | 按需，仅存放在服务端 |

## 四、登录是怎么实现的

- 口令用 **PBKDF2-HMAC-SHA256**（标准库）散列存储，格式 `pbkdf2_sha256$轮数$盐$散列`。
- 登录成功后下发 `HttpOnly` + `SameSite=Lax` 的会话 Cookie，服务端只存令牌的 SHA-256；
  即使数据库泄露也无法直接复用会话。
- 除 `/api/health` 与 `/api/auth/*` 外的所有 `/api/*` 都要求登录；桌面版自动豁免，
  沿用外壳注入的令牌机制，不受影响。
- 管理员角色可执行管理操作（等同原来的管理员令牌）；普通用户只能使用问答与只读接口。
- 登录失败有窗口限速（5 分钟 8 次），错误提示不区分"用户不存在"与"口令错误"。

## 五、已知限制（如实说明）

- **数据不持久**：Render 免费实例不挂持久磁盘，重新部署或实例重建会重置 SQLite；
  需要在正式环境长期保存时，请配置外部 `DATABASE_URL`（Postgres）或升级挂载磁盘。
- **冷启动**：免费实例 15 分钟无访问后休眠，下次访问需要 30–60 秒唤醒。
- **模型密钥**：不配置密钥时系统仍可用，但回答来自知识库检索与演示数据，质量有限。
- **安全边界**：网站部署面向校内小范围试用；对外开放前请更换强口令、开启 HTTPS（Render 默认）、
  并确认学校网络与网关的使用政策。
