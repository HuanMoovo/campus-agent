# 贡献指南

感谢你考虑为 Mens 校园助手做贡献。这个项目有两个硬性要求：**测试必须通过**、
**文档与界面里的描述必须与实现一致**（做不到的功能就写明做不到，不夸大）。

## 开发环境

- Python 3.10+（后端与构建脚本）、Node.js 22+（前端与桌面外壳）
- Windows 可直接双击 `scripts\install.cmd`；其他平台：

  ```bash
  cd backend && python -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt        # Windows: .venv\Scripts\python
  cd ../frontend && npm install
  cd ../desktop && npm install
  ```

## 提交前必须跑通

```bash
# 后端（当前 394 个用例）
cd backend && .venv/bin/python -m pytest -q

# 前端（单元测试 + 类型检查 + 构建）
cd frontend && npm test && npm run build

# 桌面外壳
cd desktop && node --test tests/main.test.cjs tests/policy.test.cjs tests/version.test.cjs
# 完整版（需要先冻结后端）：npm test
```

CI 会对每个 PR 跑上面三套（见 `.github/workflows/ci.yml`）。

## 修改约定

- **安全边界不可放宽**：后端只监听本机、随机端口 + 一次性令牌、Electron 的
  `contextIsolation` / `sandbox` / `webSecurity`、出站请求只允许 HTTPS 且固定到校验过的地址、
  禁止跳转并有大小与超时上限。任何放宽都需要在 PR 里说明威胁模型。
- **新增前端交互要带测试**：`frontend/tests/` 用 vitest；桌面外壳的 IPC 校验放在
  `desktop/lib/policy.cjs` 并补 `desktop/tests/policy.test.cjs`。
- **新增后端接口要带测试**：放在 `backend/tests/`，覆盖正常路径、鉴权、输入校验与失败路径。
- **演示数据必须标注**：未接入真实校园接口的返回值一律带「演示」标记。
- **密钥与隐私**：不要在代码、测试、截图、文档里写入真实的 API Key、令牌、学号、姓名或本机路径。
  测试里用 `example.edu` 之类的保留域名与明显的占位值。
- **提交信息**写清「为什么」，而不是「改了什么」；一次提交只做一件事。

## 文档更新

- 面向用户的变化：更新 `CHANGELOG.md`（未发布小节）与相应 README（三份语言都改）。
- 行为、范围或验证方式变化：更新 `docs/VERIFICATION.md`。
- 平台、构建方式变化：更新 `docs/PLATFORMS.md`。

## 分支与 PR

1. 从 `main` 建分支（`feat/...`、`fix/...`、`docs/...`）。
2. 保持 PR 聚焦，描述里写清：改了什么、为什么、怎么验证的（贴出实际命令与输出）。
3. PR 模板里会要求确认测试与文档状态，请如实填写。

## 许可证

提交代码即表示你同意以 [Apache License 2.0](LICENSE) 授权你的贡献。
