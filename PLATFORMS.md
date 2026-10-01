# 平台支持与构建矩阵

Mens 由三部分组成：Electron 桌面外壳、Vue 3 前端、随应用一起分发的 Python（FastAPI）后端。
前端本身与平台无关，后端是 CPython，桌面外壳由 Electron 提供——这决定了各平台的支持方式。

| 平台 | 状态 | 交付物与说明 |
| --- | --- | --- |
| Windows 10/11 x64 | ✅ 已构建并在本机验收 | NSIS 安装包 `release/Mens-Setup-<版本>-x64.exe`，用户级安装（`%LOCALAPPDATA%\Programs\Mens`），数据在 `%APPDATA%\CampusAgent` |
| macOS 12+（Intel / Apple silicon） | 🔧 由 CI 构建，本机未验收 | `Mens-<版本>-x64.dmg` / `Mens-<版本>-arm64.dmg`（附 zip）；未签名、未公证，首次打开需右键→打开，或在系统设置中允许 |
| Linux x64（较新的 glibc 发行版） | 🔧 由 CI 构建，本机未验收 | AppImage（免安装）与 deb 包；数据在 `~/.config/CampusAgent` |
| Android / iOS | ⚠️ 不提供原生应用 | 使用可安装的 Web 应用（PWA）：手机浏览器打开部署好的站点 → “添加到主屏幕” |

“已验收 / 未验收”指的是：是否在对应操作系统上真正启动过安装后的应用并完成界面检查。
Windows 的记录见 `VERIFICATION.md`；macOS 与 Linux 的产物由 GitHub Actions 生成，尚未在真机上运行过。

## 代码层的跨平台处理

- **后端可执行文件**：PyInstaller 按平台各自冻结，Windows 产出 `campus-backend.exe`，macOS/Linux 产出 `campus-backend`；启动器（`desktop/lib/backend.cjs`）按 `process.platform` 选择文件名与虚拟环境解释器路径（`Scripts/python.exe` / `bin/python`）。
- **数据目录**：由 Electron 的 `app.getPath('appData')` 推导，Windows 为 `%APPDATA%\CampusAgent`，macOS 为 `~/Library/Application Support/CampusAgent`，Linux 为 `~/.config/CampusAgent`；保留该目录名以兼容 1.0.0 以来的升级。
- **凭据加密**：Windows 使用 DPAPI（`CryptProtectData`）；macOS/Linux 没有等价的内置接口，配置中的 API Key 以 `0600` 权限的明文保存在数据目录（`model-providers.json`、`web-search.json`），文件属主即当前用户。**这是有意的取舍，不是加密**：多用户机器上请自行限制该目录权限。
- **网络**：只监听 `127.0.0.1` 的随机端口，配一次性令牌；插件与联网搜索的出站请求全部为 HTTPS、固定到校验过的公网地址、禁止跳转。
- **图标**：`scripts/create_icon.py` 从同一张源图生成 Windows `.ico`、macOS `.icns`（纯 Python 组装容器）、Linux/网页用 PNG（192/512/180）。Windows 上优先用 Pillow，缺失时回退到原有的 PowerShell 缩放脚本。
- **前端**：Electron 与浏览器共用同一份构建产物；已加入 Web App Manifest、离线外壳（Service Worker，只缓存界面资源、不缓存 API）与 iOS 安全区适配。

## 为什么没有原生 Android / iOS 应用

后端是 Python（FastAPI + LangGraph，可选向量库依赖 ChromaDB/torch 等原生包）：

- **Android**：可以借助 Chaquopy 之类的方案嵌入 CPython，但需要为每个 ABI 交叉编译整套原生依赖，且与本项目的 PyInstaller 流程完全不同；本项目未实现，也不会提供未经验证的打包脚本。
- **iOS**：不允许应用在运行时下载或执行代码，也没有 torch/ChromaDB 等依赖的官方 iOS 轮子；嵌入 CPython 的应用在实践中无法以这种形态上架。
- **可行替代**：把后端部署到服务器（见 README 的服务器部署小节），前端作为可安装的 Web 应用使用；手机上“添加到主屏幕”后是全屏、有独立图标的类应用体验，问答与知识库仍由服务端完成。需要离线本机推理时，请使用桌面版。

## 构建方式

```bash
# Windows（PowerShell / cmd，或双击 build-desktop.cmd）
python scripts\build_desktop.py

# macOS（需在 macOS 上执行；Intel 用 --arch x64）
python scripts/build_desktop.py --os mac --arch arm64

# Linux
python scripts/build_desktop.py --os linux --arch x64

# 只产出未打包的目录（调试用）
python scripts/build_desktop.py --directory
```

要点：

- PyInstaller **不能交叉编译**，必须在目标平台上构建目标平台的产物，所以 `--os` 只允许指定当前平台（CI 用不同 runner 覆盖）。
- 首次运行会自动创建 `backend/.venv` 并安装依赖；本地已有依赖时加 `--skip-install`。
- 打包阶段由 electron-builder 完成：Windows → NSIS，macOS → dmg + zip，Linux → AppImage + deb。
- macOS 未配置签名证书，脚本会设置 `CSC_IDENTITY_AUTO_DISCOVERY=false`，产出未签名应用；正式分发前应购买证书并配置公证。

## 持续集成

`.github/workflows/build-desktop.yml` 在 `windows-latest`、`macos-13`（x64）、`macos-latest`（arm64）、`ubuntu-latest` 上分别执行同一套构建脚本：跑完全部测试 → 冻结后端 → 验证冻结后的后端 → 生成安装包 → 上传为构建产物。推送 `v*` 标签时会自动创建 Release 并附带安装包。
