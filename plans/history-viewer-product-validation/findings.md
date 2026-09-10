# Findings

## 已核实（2026-09-06）

- 当前工作树包含未提交的四项升级和后续修复；保留全部既有改动。
- 004 文档已更新去重和新增回归测试说明；这些说明不能替代本轮独立验收。
- 原审查记录是修复前的历史快照，不应直接改成"已全部通过"。
- 用户明确本轮只做 History Viewer。跨仓库取舍、Star 数量和 PR 数量不构成本计划验收依据。

## M1 独立复审证据（2026-09-06 完成）

复审后全量基线：`python3 -m unittest discover -s tests` → **186 tests OK**；
五个 `tests/test_*.js` 全部退出 0（含新增 3 个用例）。

### A4 完整聚合 / 2000 上限 — 发现缺陷并已修复

- 复现：临时索引植入 250 个同日会话（每个 100 tokens），`patch BRIEFING_MAX_SESSIONS=100`
  后调用 `Handler._build_briefing_for_range`。修复前返回
  `session_count=200 / tokens=20000`，无 `truncated` 字段、markdown 无提示 ——
  **静默截断确认存在**（分页过冲到页边界后直接退出，永不置标记）。
- 修复（app.py `_build_briefing_for_range`）：触及上限时置 `briefing["truncated"]=True`
  与 `session_limit`，markdown 追加"⚠️ 本日超过安全上限，合计仅覆盖最新 N 个会话"，
  前端 `buildBriefingHtml` 渲染 `briefing-truncated-note` 警示条（styles.css 新增样式）。
- 回归测试：`test_briefing.py::test_safety_cap_is_flagged_not_silent`（标记 + 提示文案）、
  210 会话用例补 `truncated` 不出现断言；`test_insight_panels.js::testBriefingHtmlShowsTruncationNotice`。
- 剩余限制：截断点按页（200）过冲，覆盖的是"最新 N 条"而非精确 2000；已由提示文案明示。

### A1 Claude 去重 — 三方一致

- 固定样本：`~/.claude/projects/*/1eaa060d-9215-4e4b-894d-a1c36ab94985.jsonl`
  （37 个唯一 message.id、114 条 usage 记录）。
- `parse_claude_session_file` = **1,283,304**；植入临时索引（parser v5）扫描后
  `tokens_total` = **1,283,304**；对该日（2026-08-07）调用简报端点，overview 与
  highlight 均为 **1,283,304**。三层一致。
- 口径回归测试：同 ID 重复只计一次、同 ID 变体取最大、无 ID 旧记录直接累加
  （`tests/test_usage.py::ClaudeUsageParseTests`）。不把 token 数称为费用。

### A2 会话切换 — 事件路径全覆盖

- `tests/test_insight_panels.js`（shim DOM + 可注入 fetch）：
  - 成功路径：audit 响应 B 后预览立即从 HANDOFF_OLD_A 变为 HANDOFF_NEW_B。
  - 404 路径：无审计会话把预览清为 "No handoff available"，不残留 STALE_A。
  - 乱序：A 的慢响应在 B 已渲染后才返回，被 `auditFetchSeq` 丢弃（LATE_A 不出现）。
  - Plans：面板展开时 `onSessionChanged()` 重拉新会话计划，PLAN_OF_SESSION_A 不残留。
- 剩余限制：导出内容与可见内容一致性由同一 `currentHandoffText()` 提供，未单独截屏比对（M2 浏览器环节覆盖）。

### A3 合并证据 — 保持修复

- `test_briefing.py::test_merge_keeps_blocked_and_unique_files_of_merged_session`：
  高分完成 A + 低分失败 B（Jaccard 2/3）合并后，B 仍在 blocked、`new.py` 仍在 deliverables。
- blocked/deliverables 基于全部原始会话构建；合并只作用于 highlights。

### A5 缓存版本 — 实测回填

- 静态检查：`ParserRegistrationVersionTests` 断言全部活跃注册（Windows/WSL/Linux × codex/claude）
  均为 v5（排除 indexer_factory 占位行）。
- 行为检查：`test_old_parser_version_cache_backfills_usage` 手工植入 parser_version=4、
  tokens_total=0 的旧行（mtime 不变），v5 扫描后重解析并回填 tokens_total=1000、版本号更新为 5。

### A6 叙事上下文 — 事件路径全覆盖

- 日期切换：新简报日期 ≠ 叙事日期 → 叙事框清空、`currentNarrative=null`
  （`testNarrativeClearedWhenBriefingMovesToAnotherDate`）。
- 慢 POST：请求后把日期输入改为另一天，响应携带旧日期 → 判定丢弃，不写回
  （`testNarrativeDroppedWhenDateMovedMidFlight`）。
- 同日期换来源：`resetSessionPane` 递增 `briefingNarrativeSeq` 并清空叙事框（代码路径），
  生成失败路径只 alert、不更新叙事框。

### A7 扫描上限 — 计数验证

- 读取字节计数：monkeypatch `Path.open` 统计真实读取量，3 × (cap+5000) 字符文件
  总读取 ≤ 3 × `PLAN_FILE_MAX_CHARS`（`test_read_volume_measured_within_bounds`）。
- 越界内容不可达：标记位于 cap 之外时不出现在任何 section（`test_read_is_bounded_by_size_cap`）。
- 枚举提前停止：120 个计划目录仍恰好返回 80 项（`test_enumeration_bounded_not_just_result_slice`）。
- 缺失候选不占配额：79 个只含 progress/findings 的目录 + 根 task_plan.md → 恰好 80 个真实文件
  且根文件在列（`test_missing_candidates_do_not_consume_real_file_quota`）。
- 只读性：扫描/端点全程只读，未触碰源历史与上游数据库。

## 用户输入与待验证

- 陌生用户试用者与时间尚未安排；不能将开发者或 Agent 测试计作独立用户试用（M3）。

## M2 真实浏览器验收证据（2026-09-06 完成）

环境：Python 3.13.13、Linux 运行时、Chromium（Playwright 驱动）。可重复操作记录：

1. demo 轮 `python3 app.py --codex-dir ./demo/codex --claude-dir ./demo/claude --data-dir ./demo/.data --port 8787`
2. 真实轮 `python3 app.py`（默认 `~/.codex` + `~/.claude`，仓库根既有 gitignored 索引被复用并按 v5 回填）

### 闭环结果

- **安装/启动**：两轮均从 README 命令启动，Linux 系统自动识别；demo 4 Codex + Claude 会话、真实 95 Codex / 37 Claude 会话载入。
- **检索**：demo 关键词精确命中 1/1；真实全文检索 "vscode" 命中 4（含正文匹配）、"找找原因" 命中 1。
- **审计证据**：审计面板六段（Intent/Outcome/Deliverables/Command intents/Friction/Value）真实渲染；无审计会话 404 路径 UI 优雅降级（"No handoff available"），不崩溃。
- **交接导出**：Preview 三主题（plain/card/feishu）切换即生效；Rich 复制按钮反馈 "✓ Copied"；`.md`/`.html` 下载落盘且结构完整（含 goal/constraints/verified 等字段），真实会话导出文件验证后已删除。
- **Usage**：demo 源无 token 数据 → 空态文案准确（已对照源 jsonl 确认无 usage 记录）；真实 Codex 858,007,975 tokens / 95 会话、Claude 2,805,430 / 37，by-day/by-project/top-sessions 齐全。
- **A1 UI 交叉验证**：真实 Claude 2026-08-07 简报面板显示 **1,283,304 TOKENS**，Usage top session `1eaa060d…` 亦为 1,283,304 —— parse=index=briefing=UI 四方一致。
- **A2 浏览器验证**：富会话 A（下载opencode客户端）→ B（下载zcode）真实点击切换，handoff 与 audit 均随会话更新、无残留。
- **Briefing**：空日期（今日）与数据日（demo 2026-02-11、真实 2026-08-07）两种路径均正确。
- **Plans**：空 cwd 路径文案准确；真实会话（cwd=本仓库）列出 `docs/session-plans/002-detail-panel-and-ai-audit.md` 并只读渲染。
- **主题/响应式**：六种代码主题全部生效（`data-code-theme`）；420px/480px 窄窗口无横向溢出，长中文标题正常换行不裁切。
- **源切换**：Codex↔Claude 切换后列表与主面板干净重置；源选择经 localStorage 跨重启持久化（曾致两轮显示同源，排查确认是特性非缺陷）。

### M2 发现并修复

- **键盘不可达（已修复）**：会话/项目行原为纯 div，无 tabindex/role/键盘激活，核心"选择会话"步骤键盘不可操作。
  修复：行加 `role="button" tabindex="0"`（`:focus-visible` 样式已存在），列表级 Enter/Space 键委托复用 click 路径
  （`static/app.js` renderSessions/renderProjects + sessionListEl keydown）。浏览器实测 focus→Enter→会话打开。
- favicon 404（外观性，未处理）；无审计 `/audit` 404 为既定 API 语义（UI 已优雅处理）。

### 未验证项（如实列出）

- LLM 已配置模式的外部调用（无授权测试环境，未验证）。
- Windows / WSL 运行时平台（未验证）。
- OpenClaw / OpenCode / Hermes 源仅确认 tab 存在，未逐一点击验证内容。


## M3 材料预检（2026-09-06，不是独立试用）

- 复用五个既有合成 demo 日志，逐文件 SHA-256 记录在 m3-materials/manifest.json；不复制真实历史。
- 用现有 extractor 确认 demo-alpha-0001 的 errors 包含 demo error；任务答案与源数据一致。
- 任务单与观察者答案分离；压缩包仅有五个 JSONL、两份说明和清单，共八项。
- 发现 demo 启动仍会自动发现其他本机来源；试用前使用干净 Linux 账户，不把不存在的显式数据库路径当禁用开关。
- 试用源码版本需包含未提交升级，独立源码交付与参与者安排尚未完成；未声称 M3 通过。


## M3 候选包预检（2026-09-07）

- 已按文件白名单加入当前候选源码，基础 commit 与每个文件 SHA-256 随包提供；组织者答案不在试用 ZIP 内。
- 从 ZIP 解压后验证全部哈希，app.py --help、node --check 均通过；独立临时索引加载四个 Codex demo，会话 alpha 的失败审计可见。
- 无真实日志、索引、凭据、缓存或个人交接导出；未启动扫描个人来源的服务器。
- 候选包已就绪，仍需干净 Linux 账户与实际试用者；这些预检不代表 M3 通过。
