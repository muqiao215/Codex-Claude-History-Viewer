# Progress

## Current

首个稳定版本 `v1.0.0` 已完成审查、验证和发布。

## Done

- 确认远程、分支、tag 和 Release 初始状态
- 创建发布计划
- 审查后端、前端、测试和文档 diff
- 确认 `controlmesh` 迁移计划与发布无关
- 修复用户在最后 assistant reply 后发言却被标为 completed 的问题
- 恢复 handoff 中被误过滤的文件 evidence
- 增加 OpenCode audit/handoff 专门测试并修正 scope 文档
- 通过 143 个 Python 测试、全部 JavaScript 测试、Python compileall、JavaScript 语法和 `git diff --check`
- 用合成 Codex/Claude 数据启动服务，验证 UI、sources API、sessions API 和 handoff audit API
- 精确提交发布内容，排除无关 `controlmesh` 文件
- 推送 `main` 并创建 GitHub Release `v1.0.0`

## Remaining

- 无

## Issues

- 无阻塞。

## Next

收集发布后反馈。
