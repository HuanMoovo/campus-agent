# Mens 验证记录

各版本的构建与验收摘要。安装包见 [Releases](https://github.com/HuanMoovo/campus-agent/releases)。

## 1.2.2 — 2026-10-08

- Windows 安装包在本机构建，全套测试与产物冒烟通过；由 1.2.1 静默升级安装验收通过，界面、内置后端与用户数据正常。
- macOS（Intel / Apple silicon）与 Linux（AppImage / deb）由 CI 构建，四目标全部通过；四平台产物已随 Release 发布。

## 1.2.1 — 2026-10-02

- 界面三语（中 / English / 日本語），离线外壳缓存随版本更新。
- Windows 安装包重建并通过升级安装与界面验收；macOS / Linux 由 CI 构建。

## 1.2.0 — 2026-10-01

- 跨平台构建（Windows / macOS / Linux）、可选联网搜索、可安装网页版（PWA）、Docker 部署。
- Windows 安装包通过完整验收；macOS / Linux 由 CI 构建。

## 1.1.0 — 2026-10-01

- 统一各端版本号；新增流式回答与停止生成、会话隔离、Word 文档上传、模型断点续传、备份导出 / 导入、窗口记忆、可选更新检查。
- Windows 安装包通过安装、启动与界面验收。

## 1.0.0 — 2026-09-30

- 首个发布版（圆角 Logo、可定制外观、校园服务与插件、本地模型切换）；Windows 安装验收通过。

## 已知边界

- 安装包未使用 CA 证书签名；macOS 包未公证，首次打开需右键「打开」。
- macOS 与 Linux 产物由 CI 构建，未在物理设备上走查。
- 校园统一登录、真实云端密钥与校方接口联通需外部条件，尚未验收。
