## 改了什么

<!-- 一到三句说明这次改动解决的问题，而不是逐条复述 diff。 -->

## 为什么

<!-- 触发这次改动的场景、缺陷或限制。 -->

## 怎么验证的

<!-- 贴出实际执行的命令与关键输出（测试、构建、浏览器或安装包验收）。 -->

- [ ] `cd backend && .venv/bin/python -m pytest -q`
- [ ] `cd frontend && npm test && npm run build`
- [ ] `cd desktop && node --test tests/main.test.cjs tests/policy.test.cjs tests/version.test.cjs`

## 检查清单

- [ ] 没有放宽既有的安全边界（本机监听、随机端口 + 一次性令牌、Electron 沙箱、出站 HTTPS 规则）；若有改动，已在描述里说明威胁模型
- [ ] 新增或修改的行为有对应测试，且覆盖失败路径
- [ ] 没有在代码、测试、文档或截图里写入真实密钥、令牌、学号、姓名或本机路径
- [ ] 面向用户的改动已更新 `CHANGELOG.md` 与三份 README；验证方式变化已更新 `docs/VERIFICATION.md`
