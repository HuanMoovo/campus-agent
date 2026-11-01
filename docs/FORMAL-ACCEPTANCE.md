# 正式验收交接

本文用于区分本机回归、合成联调和正式现场验收。测试替身、自签名演练、工作流配置与未签名安装包均不能代替正式通过记录。

## 校方联调

需要校方提供授权的 HTTPS 网关、接口字段说明、测试账号或 Bearer 凭据，以及可使用合成业务数据的测试环境。九类接口和已有字段要求见 [CAMPUS-GATEWAY.md](CAMPUS-GATEWAY.md)。凭据应通过运行环境或应用设置配置，不写入工单、聊天或验收报告。

逐项记录实际查询是否成功、来源是否明确、失败提示是否可见，以及返回数据是否符合双方协议。报修必须使用授权测试环境和测试工单；HTTP 200 仅表示收到接口回执，业务受理结果以学校回执为准。未配置时返回的演示数据应标为未联通，不能计作学校通过。

CAS、OIDC、SAML 等学校 SSO 尚未实现。需要校方先确定协议、回调地址、身份字段和授权规则，再进行协议适配与验收；当前本机账号与会话 Cookie 不构成学校 SSO。

## Windows 正式签名

现有工程通路使用可供构建机使用的 PFX 证书。GitHub 构建可选配置 `WINDOWS_SIGNING_PFX_BASE64`（无换行的 Base64 PFX）和 `WINDOWS_SIGNING_PASSWORD`；没有密码的 PFX 可留空密码。其他证书存储、硬件令牌或签名服务需另行接入，不能假定此 PFX 通路已经覆盖。

流程必须按以下顺序执行：

1. 构建阶段将凭据传给 electron-builder 的 Windows 签名配置，先签主程序、冻结后端、附加 EXE 和 NSIS 卸载器，再封装安装包。
2. `prepare_release_ci.py` 在封装后进行只读验签：检查 `win-unpacked/Mens.exe`、`win-unpacked/resources/backend/campus-backend.exe`，并核验目录内全部 EXE（包括存在的 `resources/elevate.exe`）和顶层安装包。缺失必需文件、目录链接、验签失败或缺少时间戳均不能生成签名成功状态。
3. 正式成功要求 `signtool verify` 返回 0、Authenticode 状态为 `Valid`，且有时间戳证书。自签名演练仅用于流程检查，不能用于满足此门槛。
4. 验签完成后生成最终文件的 SHA256SUMS 和签名状态，再上传产物。签名前生成的 blockmap、`latest*.yml` 不在当前发布范围内。

`prepare_release_ci.py` 现在是只读结算门禁，不再替独立调用者补签文件。未通过工作流构建时，须在构建前向 electron-builder 提供 `WIN_CSC_LINK` 和 `WIN_CSC_KEY_PASSWORD`；仅在事后给 prepare 传入 `WINDOWS_SIGNING_*` 不会为包内程序或安装器补签。需要单文件签名时仍使用 `sign_release.ps1 -Pfx` 通路。

NSIS 卸载器在封装前由 builder 签名；prepare 不会从最终安装器独立提取卸载器。因此正式现场还须受控安装后对实际卸载器验签，并保留安装、退出和卸载记录，不能把本机只读门禁或签名替身当作这项已经通过。

只读复核现有文件可运行：

```powershell
pwsh -NoProfile -File scripts/sign_release.ps1 -File release/win-unpacked/Mens.exe -VerifyOnly
```

`-VerifyOnly` 不签名、不导入或生成证书，也不接收 PFX、密码、自签名或保留证书选项。没有凭据的构建保持 `unsigned`；测试中的签名替身成功不等于真实 CA 与时间戳服务通过。本机已有未签名演练包应被正式门槛拒绝。

## macOS 与 Linux

PyInstaller 必须使用与目标系统、CPU 架构相符的 64 位解释器。构建脚本会先检查本机 OS，再探测实际 `backend/.venv` 的解释器；在 Windows 上指定 `--os mac` 或 `--os linux` 会失败，不能产生跨平台验收结论。

当前工作流已配置 macOS Intel、Apple Silicon 与 Linux x64 runner，但本轮没有触发远程构建。macOS 仍缺 Developer ID 签名、公证与系统校验通路的真实资源；当前 `identity: null` 和 `unsigned` 状态不能算正式分发通过。现有 smoke 会移除 quarantine，其结果也不能代替 Gatekeeper 验收。

Linux 需要在真实 Linux 环境验证后端与 Electron 启动、AppImage 执行、deb 安装/升级/卸载、数据保留和权限。本机 Windows 下的 VM 分支替身只验证路径与控制流。Docker CLI、已停止的 Docker 内部 WSL 发行版或工作流 YAML 的存在，都不表示已经完成这些执行。

最终记录应包含提交或源码输入哈希、实际 Python/Node/Electron 版本、OS/CPU、产物 SHA256、安装与退出结果、签名/公证结果及跳过原因。复用已有依赖时应保留实际版本与声明版本不一致的限制。
