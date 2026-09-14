# 核对事实与边界

## 输入、基线与证据等级

本轮依据用户提供的 `THREE_PROJECTS_BOUNDED_DELIVERY.md` 与确认后的独立交付方向。附件自己的第 2 节说明其 9 月 11 日材料不是最新 HEAD/进度证明。2026-09-14 本地增量核对：`main` / `9ea53f1db182cee5351dbf8079033290cbf0d6bf`，开始时 tracked diff 为空，但并非 clean workspace。

既有 untracked 范围原样保留：

- `agents/controlmesh_typescript_migration_plan(1)..md`
- `plans/specmesh-r001-validation/`
- `plans/ubuntu-keyboard-recovery/`

本次仅读相关源码和旧验收记录，未运行产品测试、未检索私人会话正文、未调用模型 CLI。2026-09-13 发布审计已在线确认 stable/latest v1.1.0，对应 `6dfbbd15d79dd206758416c3ce41e4126c4e7126`；当时远端 main 与当前本地 HEAD 一致。该在线观察有日期，不保证随后不变。`VERSION` 当前仍写 1.1.0，但 main 已包含 tag 后的 native-reference 变更。

当时默认 8787 无监听且 HTTP 连接失败；桌面入口指向本机 main checkout。新一轮文档编辑未启动服务，当前运行版本为**未重新验证**。这替代“本机服务一直运行 v1.1.0”的静态断言；旧安装/发布记录仍保留。

## 已有能力和剩余映射

| 原阶段 | 当前证据 | 承接与限制 |
|---|---|---|
| HV-H0 | [CLI](../../history_core/__main__.py) 有 refresh/health/search/handoff/native-reference；[service](../../history_core/service.py) 不导入 HTTP。 | 已实现基础能力；CLI 仍直接构造带 legacy mutations 的 Indexer，机器公共只读边界未完整隔离。新 HV-H0/HV-H0.1。 |
| HV-H1 | [Indexer](../../history_core/sources.py) 的 `scan_sessions` 按 mtime/parser/audit 版本跳过未变文件；CLI health 明确 unknown freshness、explicit refresh。 | 并非完全没有增量；仍全目录枚举，单文件变化、新鲜度、删除/替换/恢复和规模门槛需专项验证。先基准，不重做 parser。 |
| HV-H2 | [旧 progress](../agent-handoff-service/progress.md) 记录三来源严格引用与跨仓比对；CLI 返回 native_candidate.v2/context_only。普通 handoff 为 history.handoff.v1。 | native-reference 不重写；普通交接的来源/基线/unknown/上下文限额仍需收口，不依赖 CM 实际启动。 |
| HV-H3 | 旧 progress 记录 OpenCode 同 session 回忆及更新文件读取；Claude 2026-09-12 有实际接管、当前文件写入、保留结果恢复。更新的 CM findings 记录 Codex 正常 configured/History adoption 与原生 CLI 路径，模型端为 synthetic。 | 这些是限定 provider/device/代码快照的证据，本次未重放。Codex 正常接管路径不再列为未实现；真实账号模型调用及完整故障矩阵仍待验收。经 CM 的受监督执行归 CM，退出 History 独立分母；用户仍可使用 History 提供的显式命令直接调用所选原生 CLI。 |
| HV-H4 | [workspace 页面](../../static/workspace.html)、[渲染](../../static/workspace.js) 已成果优先，旧设置在 `/history`。service 输出 historical_evidence / live_task_state unknown。 | 现有成果复用；完整项目进展/结果/阻塞/决定/下一步还需逐项验收。CM 当前事实可选；不能靠取消“历史快照”标识伪造实时完成。 |
| HV-H5 | [旧发布验证](../codekit-integration/progress.md) 有 191 Python、六 Node 文件与 synthetic HTTP/browser 记录。 | 这是旧快照记录，不是本次新测试；完整平台、升级、隐私及新版本安装/进程对齐待验收。 |

Codex 更新依据已只读核对 CM 提交 `3596526525c2b74f1e20b09983d8048cb384baad`：[configured/History adoption 与两次原会话续接](https://github.com/muqiao215/ControlMesh/blob/3596526525c2b74f1e20b09983d8048cb384baad/plans/runtime-convergence/findings.md#L1894) 使用实际安装的 Codex 0.154.0 CLI 和真实 headless Viewer，CM reopen 后保留原上下文；[并发 fanout 与保留结果恢复](https://github.com/muqiao215/ControlMesh/blob/3596526525c2b74f1e20b09983d8048cb384baad/plans/runtime-convergence/findings.md#L2065) 进一步覆盖原生 session/command/version 行为。两处模型端均为 synthetic loopback，不能据此声称真实账号、物理多设备或全故障矩阵已验收；History 旧 progress 中笼统的 Codex adoption pending 已被这些限定证据更新。

新独立范围 5 阶段，严格 0/5；旧 6 阶段 0/6 的审计没有被补写为已完成。基础实现、partial 与已通过的局部证明继续保留。

## 当前代码核实：避免复制旧缺陷说法

- 短会话风险仍存在：`history_core/sources.py` 的 `cleanup_weak_sessions` 仅按 `user_count < min_user_messages` 筛选，默认 5；经 `_delete_sessions_with_backup` 的 `shutil.move` 移动原 JSONL。`app.py` POST `/cleanup/weak-sessions` 暴露该路径。
- 触发边界也存在：`static/app.js` 的 `cleanupWeakSessions` 先 `confirm`，文字说明 `<5` 和移动到备份目录，再发 POST；未发现现有 headless CLI 自动调用 cleanup。准确结论是**人工清理仍使用短会话启发式并移动原日志**，不是“后台正在自动删所有新会话”。机器 API 隔离不能代替后续 Web 策略验收。
- 缺失 cwd 回落已修：`audit/git_snapshot.py::legacy_git_state` 对 missing/relative cwd 返回 unavailable；[现有测试](../../tests/test_history_core.py) 验证不探测进程仓库。此处只保留回归门槛，不排重复修复任务。
- 新鲜度没有完整保证：`legacy_git_state` 虽返回完整 HEAD/dirty，`content_digest` 是 None、`verification_baseline` 是 unknown、consistency 是 best_effort_not_atomic。不能把导出时观察升级为过去测试基线或 dirty 内容指纹。
- 普通索引 `scan_sessions` 遇解析器返回 None 会跳过；本轮仅静态发现错误可见性需要验证，不据此宣称所有坏文件已静默丢失。native 严格读者与展示容错 parser 保持不同职责。
- 模块导入与服务启动分开：现有测试检查 `app`/`http.server` 未加载，但独立产品门槛是核心不依赖 app 业务初始化，且无 HTTP 监听/服务、后台、模型或意外网络副作用；无副作用的标准库 import 本身不构成风险。

## 决定与待研究

独立交付按 HV-H0→HV-H1→HV-H2/HV-H4→HV-H5 排队；只详写 HV-H0.1，不新增总控项目，不把 native runtime 塞回 History。首版继续显式 refresh，不同时增加 CLI/MCP/gRPC/daemon；若以后需要常驻模式，要以实测需求另选有界子卡。

外部开源参考未研究。下一张卡有本仓 code seam 和测试，暂无需要外部实现才能推进的缺口；若研究，最多两个、登记精确来源 commit/许可证/范围，不扩展为长期调研。


## HV-H0.1 执行基线（2026-09-14）

用户已明确开始独立交付，选中首卡 HV-H0.1。HEAD 9ea53f1db182cee5351dbf8079033290cbf0d6bf；目标代码与测试初始无既有 diff，既有文档改动及未跟踪范围保留。完整文件摘要与清单保存在本地 work/hv-h01-baseline.json。当前单一实现者，未启动其他写入者、Goal 或自动续卡。费用/token unknown。


## HV-H0.1 实现与验收（2026-09-14）

- 公共边界位于 history_core/reader.py；低层 sources.py/service.py 继续作为共享兼容实现，不以 Python 私有属性作为安全沙箱。
- 派生缓存从 CLI 旧 index_<source>.sqlite 转为 machine-<source>-<绝对来源SHA256>/index.sqlite；旧缓存不删除，新入口需显式 refresh。防止缓存文件路径携带另一来源的授权。
- 默认拒绝源树符号链接（包括指向树内的链接），避免目录链接静默遗漏；缓存 SQLite 与 sidecar 的链接同样拒绝。扫描结果可见性和规模优化留给 HV-H1。
- 自审发现给共享分页直接添加 tie-breaker 会影响网页默认排序，修正为 stable_order 仅在 HistoryReader.search 开启；旧 Web 行为不变。
- 文件效果、构造/调用副作用守卫及故障路径见新增 MachineReaderBoundaryTests；临时原生 SQLite 通过原适配器访问后字节及目录清单均不变。没有复用私人日志作证据。
- 指定源构造、方法调用无 HTTP/socket/后台线程；handoff 的有效绝对 cwd 仍使用既有只读 Git 观察，缺失/相对 cwd 不执行 Git。不把观察时 HEAD 当历史验证基线。
- 同时间戳排序保证仅针对固定索引内容；跨 refresh 分页失效/修订协议仍需后续 HV-H1。


## HV-H1.1 执行基线与测量发现（2026-09-14）

用户明确授权执行 HV-H1.1（合成增量与性能基线）。单一实现者在主工作区执行，无其他写入者。
- 硬件与环境：`AMD Ryzen 7 7435H` (16核), 31.08 GiB RAM, Linux-6.8.0-139-generic, Python 3.12.3。
- 源码 HEAD：`9ea53f1db182cee5351dbf8079033290cbf0d6bf`。既有未跟踪范围与 HV-H0.1 未提交改动完整保留。
- 模型与费用：Gemini 3.8 Flash (Medium) via 本地 AGY，费用/token 外部不可直接测得记 unknown；未读取任何密钥。
- 合成数据集生成器（`scripts/generate_synthetic_sessions.py`，v1.0.0，seed=20260914）：
  - 1k 数据集：1,000 文件，16,453,748 字节，单文件均值 16,453.75 字节（在 16 KiB ±10% 内），SHA256 `eb59250c51f61cce0700bfb11940430766e43bd003810f2217341aa7b4aa6251`。
  - 10k 数据集：10,000 文件，164,540,666 字节，单文件均值 16,454.07 字节（在 16 KiB ±10% 内），SHA256 `67e280af5e071642cc68edf93dfbec828f04bb3136b3de07a5bd3480483b10b1`。
  - 包含 Unicode/中文、单行 >2 KiB 长行、坏尾行（`raw_json:malformed_line`）、同时间戳样本。
- 门槛测量实测成绩（共 15 项，12 PASS，3 FAIL）：
  1. 初始索引 1k：1.0293 s（门槛 $\le$ 10.0 s）-> **PASS**
  2. 初始索引 10k：10.2583 s（门槛 $\le$ 90.0 s）-> **PASS**
  3. 10k 初始索引峰值 RSS：745.32 MiB（门槛 $\le$ 512.0 MiB）-> **FAIL**（全量缓冲 10,000 条会话对象导致堆膨胀）
  4. 单文件追加 1KiB (1k)：0.0489 s，解析计数 1（门槛 $\le$ 2.0 s，解析计数 1）-> **PASS**
  5. 单文件追加 1KiB (10k)：0.4394 s，解析计数 1（门槛 $\le$ 5.0 s，解析计数 1）-> **PASS**
  6. 无变化 refresh：1k=0, 10k=0 文件解析，耗时 0.04s/0.41s（门槛解析计数 0）-> **PASS**
  7. 10k 首次进程查询 (CLI 冷启动)：0.6784 s（门槛 $\le$ 1.0 s）-> **PASS**
  8. 10k 索引 100 次热查 p95：666.81 ms（门槛 $\le$ 250.0 ms）-> **FAIL**（`HistoryReader.__ready` 每次查询无条件执行全量 10k 文件 `os.walk` + `open` 校验）
  9. 分页一致性：连续 5 页无重复、无漏项 -> **PASS**
  10. 同路径替换：原地更新 session ID 后旧记录清除、新记录入库 -> **PASS**
  11. 删除/轮转清理：磁盘删除文件后，SQLite `sessions` 表仍残留失效行，handoff 抛 FileNotFoundError -> **FAIL**（Indexer 未实现差异清理）
  12. 不可读坏文件：严格抛出 PermissionError -> **PASS**
  13. 来源丢失：严格抛出 FileNotFoundError -> **PASS**
  14. 进程重启恢复：派生 SQLite 复用正常，无需重构 -> **PASS**
  15. CLI 退出：退出码 0，无孤儿进程或后台残留 -> **PASS**
- 缺陷客观结论：本卡严格不修改产品代码，不放宽冻结门槛，如实输出失败基线与根因。阶段 HV-H1 仍处于 OPEN/PARTIAL，仅关闭 HV-H1.1 子卡。唯一下一步建议授权 HV-H1.2 进行针对性修复。



## HV-H1.2 完成（2026-09-15）

- 审查 AGY 超时残留后完成本卡。四项基准问题已修复：预期分页顺序、跨进程完整记录值比较、现有来源丢失保留缓存、明确损坏错误及恢复验证。
- 产品修复：文件签名识别替换（含同大小、保留 mtime）；完整枚举后逐文件解析写入一个事务，失败回滚，成功才清理已删除来源记录；热查只检查根/缓存，显式 unknown；匹配置顶/排序和项目过滤的 SQLite 索引避免冗余正文扫描。
- Handoff 保留单文件路径检查，拒绝符号链接、缓存 `..` 越界和不可读源。独立审查发现的不可读源缺陷已修复并由审查者复验 2/2。
- 10k 初始索引 10.9114 s、峰值 34.86 MiB；热查询 p95 192.06 ms；独立进程首查 0.3284 s；追加 1024 B 0.54 s、仅解析目标 1 文件；无变化解析 0 文件。
- 固定 1k/10k 的实际文件数、字节数及 SHA256 校验通过，16 项基准判定 PASS。基准内后台 I/O 仍如实标 unmeasured；额外 strace 跟踪合成 CLI 四种入口，全部正常退出且无 clone/fork/网络调用，证明这些被跟踪运行没有留下后台执行体。
- Python 全量 240 项：239 通过、1 跳过（未配置 CM 跨仓读取器）；最后的基准断言调整后专项 20/20。JS 6 套通过，node --check、git diff --check 通过。
- 本卡仅验收 Linux 合成来源；不推广为 Windows/WSL、所有 provider/超大单文件的性能结论。分页仍要求同一索引内容，跨 refresh 修订协议尚未交付，因此完整阶段保持 0/5。
- 交付证据：`/home/muqiao/Documents/Codex/2026-09-06/app-py-audit-app-js-audit/outputs/hv-h12-completion-review.md`、`hv-h12-benchmark.json`、`hv-h12-cli-exit-evidence.json`。工作树未提交/未推送/未发布，既有未跟踪目录保留。


## Linux 完整交付（2026-09-15）

用户最新授权一次性完成并以 Linux 为主；Windows/WSL 未进行安装或远程运行。范围改为 HV-independent-linux-v2，阶段分母仍 5。

独立审查发现 demo 复用真实缓存可覆盖 pinned/AI 状态；已改固定 demo-isolated 子目录，真 HTTP 启动前后逐字节验证原 SQLite 未变。handoff 的旧索引 metadata 与新文件身份混用风险以 source_changed_since_index 显式拒绝，要求 refresh。

真实浏览器观察：默认 5 条 Codex/Claude 合成记录；6 栏完整；OpenClaw 缺失明确；演示与历史过期明确；跳转 dense 会话 ID 正确。420px/480px 的 scrollWidth 分别 405/465，没有横向溢出。服务停止后重新读取清除旧记录并显示失败。浏览器和测试服务器已关闭。

源码验收 257 Python（256 passed, 1 skipped）、7 Node 文件。Linux 冻结基准 16 项通过，报告在本任务 outputs/linux-delivery-benchmark.json。v1.1.0 缓存升级/回滚均保留四条合成会话；现有缓存与源内容未被 demo 修改。

## 发布收口

Linux v1.2.0 已发布并安装，5/5 complete。源码 eb99792dadc46ca2b352be8b56ea16daa2138c6c、归档摘要、CI 34902276767、本机实际进程、升级和回滚证据均已核对；详见 [progress](progress.md#release-evidence--2026-09-15)。发布后仅更新收尾文档，保留标签与产物身份。
