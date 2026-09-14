# Progress

## Current

Linux 完整交付 complete：H0/H1/H2/H4/H5 全部完成，5/5。范围 HV-independent-linux-v2；用户明确取消本轮 Windows/WSL 验收。

## Done

- 只读机器接口；修订绑定分页；原子增量/失效行清理；五来源能力与源文件/DB 不变验证。
- 来源快照交接、2 MiB 上限、未知历史基线、context_only、显式可选计划文件；无系统临时快照写入。
- 工作概览六栏目、历史/当前状态区分、demo/来源缺失/失败/过期标记，窄屏及证据导航真实浏览器验证。
- 弱会话批量清理 HTTP 405；demo-isolated 子缓存保护现有 pinned/AI 状态。独立审查复核通过。
- 257 Python（256 passed，1 CM 跨仓配置 skipped）、7 Node 文件通过。
- 固定基准：10k 11.3503 s / 34.95 MiB；热查 p95 202.56 ms；首查 0.3634 s；追加 1KiB 0.5376 s，解析 1 文件；16 项通过。
- 源码 clean venv/demo HTTP、v1.1.0 缓存升级和备份缓存回滚通过。

## Remaining

无本轮剩余项。

## Issues

无剩余已确认的代码审查问题。Hermes 无普通审计显式报错；原生数据库普通交接内容修订为 unknown，native v2 单独提供内容绑定契约。不把旧 M3 外部用户试用或 Windows/WSL 兼容记成新验收。

## Next

本轮结束；后续依据具体使用反馈另立任务。

## Release evidence — 2026-09-15

- 发布源码/标签：`v1.2.0` → `eb99792dadc46ca2b352be8b56ea16daa2138c6c`。后续仅文档收尾提交不改变发布标签或已安装代码。
- [GitHub release](https://github.com/muqiao215/Codex-Claude-History-Viewer/releases/tag/v1.2.0)。ZIP SHA256：`d9b015eef4f7687b14e00e8014e1c3180f36d4cec686f9d6ed9b55a6f7f9268e`，远端附件 digest 一致。
- [Linux CI](https://github.com/muqiao215/Codex-Claude-History-Viewer/actions/runs/34902276767)：Python 3.11、3.12（含安装烟测）及 frontend 全部 success。
- `/home/muqiao/.local/bin/cchv` → `/home/muqiao/.local/share/cchv/current` → `releases/1.2.0-eb99792`。实际 HTTP `/api/version` 与 CLI 均为 1.2.0，HTTP source_commit 对齐发布源码；测试进程已停。
- 启动器切回保留的 1.1.0、核验版本、再恢复 1.2.0 通过；独立临时缓存升级/备份回滚通过。
- 安装包 CLI refresh/search/handoff/health 的 strace 均退出 0，无创建子进程或网络调用，隔离 HOME 和合成来源内容未变。此证据限于记录的四个命令及合成 Codex 来源。
- 完整本地报告：`/home/muqiao/Documents/Codex/2026-09-06/app-py-audit-app-js-audit/outputs/linux-delivery-completion.md`；同目录保存 benchmark、CI、安装、发布、隐私 JSON 与 ZIP/SHA256。
- 不认证 Windows/WSL、真实模型外呼或 CM 执行；不将历史 M3 外部用户试用记为通过。原有三个无关未跟踪范围保留。
