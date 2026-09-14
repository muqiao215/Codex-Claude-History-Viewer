# Progress

## Current

Linux 完整交付收口中：H0/H1/H2/H4 complete，H5 发布包/安装版本对齐待完成，4/5。范围 HV-independent-linux-v2；用户明确取消本轮 Windows/WSL 验收。

## Done

- 只读机器接口；修订绑定分页；原子增量/失效行清理；五来源能力与源文件/DB 不变验证。
- 来源快照交接、2 MiB 上限、未知历史基线、context_only、显式可选计划文件；无系统临时快照写入。
- 工作概览六栏目、历史/当前状态区分、demo/来源缺失/失败/过期标记，窄屏及证据导航真实浏览器验证。
- 弱会话批量清理 HTTP 405；demo-isolated 子缓存保护现有 pinned/AI 状态。独立审查复核通过。
- 257 Python（256 passed，1 CM 跨仓配置 skipped）、7 Node 文件通过。
- 固定基准：10k 11.3503 s / 34.95 MiB；热查 p95 202.56 ms；首查 0.3634 s；追加 1KiB 0.5376 s，解析 1 文件；16 项通过。
- 源码 clean venv/demo HTTP、v1.1.0 缓存升级和备份缓存回滚通过。

## Remaining

H5：提交审查后源码、构建 commit-bound archive、安装与实际运行身份核验、上传发布及收尾证据。

## Issues

无剩余已确认的代码审查问题。Hermes 无普通审计显式报错；原生数据库普通交接内容修订为 unknown，native v2 单独提供内容绑定契约。不把旧 M3 外部用户试用或 Windows/WSL 兼容记成新验收。

## Next

完成 Linux v1.2.0 发布和源码/产物/安装证据记录。
