# Progress

## Current

M1 七项独立复审完成（A1–A7 全部有独立证据，A4 修复静默截断 + 回归测试）；
M2 真实浏览器验收完成（demo + 真实数据两轮闭环，键盘可达性缺口已修复）；
M3 材料就绪，独立试用 pending（试用者由用户安排）；M4 候选整理完成，按用户新要求准备 v1.1.0-rc.1，稳定版验收未完成。

## Done

- 确认仅 History Viewer 的范围与现有未提交改动。
- 建立 M1–M4 和 A1–A7 可观察验收标准。
- 重跑当前基线：182 Python tests、5 JS 测试文件全部通过。
- 将本计划接入 PROJECT 的当前优先级与 Knowledge Map。
- 三份计划文件和文档链接检查通过；`git diff --check` 通过。
- **M1（2026-09-06）**：A1–A7 全部复验，详见 findings.md 证据表。
  - A4 发现并修复：`_build_briefing_for_range` 触及 2000 保护上限时静默返回部分聚合。
    修复为返回 `truncated` + `session_limit` 标记、markdown 追加不完整提示、
    UI 简报面板显示警示条；新增越界复现测试（250 会话 × cap 100）与 UI 测试。
  - 复审后全量：**186 Python tests OK，5/5 JS 套件通过**（新增 4 项 Python、3 项 JS）。
- **M2（2026-09-06）**：demo + 真实数据两轮浏览器闭环，详见 findings.md「M2 真实浏览器验收证据」。
  - 安装→检索→审计证据→交接导出闭环通过（Preview 三主题 / Rich 复制 / .md + .html 下载）。
  - A1 四方一致在 UI 复核：真实 2026-08-07 简报 = 1,283,304 tokens。
  - A2 浏览器路径复核：富会话 A→B 切换无残留。
  - 发现并修复键盘不可达：会话/项目行 tabindex+role+Enter/Space 委托（app.js）。
  - 未验证：LLM 外呼模式、Windows/WSL 平台、OpenClaw/OpenCode/Hermes 源内容（已在 findings 列明）。
  - 收尾全量：**186 Python tests OK，5/5 JS 套件通过**；真实数据导出物已删除。

- **M3 材料准备**：五个仓库合成 JSONL、一页任务单、独立组织者判定说明、SHA-256 清单已准备；复核 alpha 的失败证据及打包内容。未执行独立用户试用。

## Remaining

- M3：陌生用户试用（试用者与时间由用户安排；候选源码、合成数据和任务单已打包就绪）。
- M4：候选发布见 ../release-alignment/；稳定版晋升等待 M3。

## Issues

- 无阻断问题。试用者未安排（M3 保持 pending，不用 Agent 自测替代）。

## Next

由用户安排独立试用者和干净 Linux 账户，提供当前候选源码与 m3-materials/trial-sheet.md；按 observer-guide.md 记录基线。M3 不因材料预检通过而完成。


## M3 候选包预检（2026-09-07）

- 已按文件白名单加入当前候选源码，基础 commit 与每个文件 SHA-256 随包提供；组织者答案不在试用 ZIP 内。
- 从 ZIP 解压后验证全部哈希，app.py --help、node --check 均通过；独立临时索引加载四个 Codex demo，会话 alpha 的失败审计可见。
- 无真实日志、索引、凭据、缓存或个人交接导出；未启动扫描个人来源的服务器。
- 候选包已就绪，仍需干净 Linux 账户与实际试用者；这些预检不代表 M3 通过。

## 2026-09-11 候选整理

复验 186 Python tests、6 个 JS 文件通过；修正测试的日期依赖和 Node 22 navigator fixture。候选清单及说明见 docs/release-v1.1.0-rc.1.md（仓库根目录）。旧 ZIP 为历史快照，当前试用使用新 Release 源码包；M3 仍未执行。
