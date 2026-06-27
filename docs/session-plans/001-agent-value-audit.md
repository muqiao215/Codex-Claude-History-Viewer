> **Status (2026-06-27)**: M1 ✅ · M2 ✅ · M3 ✅ — delivered in commit `4462cfb`. Backend `audit/` package + SQLite migration + sidebar badges + value sort all live; full suite 43/43 green.
> M4 / M5 / M6 still pending — see [`002-detail-panel-and-ai-audit.md`](./002-detail-panel-and-ai-audit.md) for the next phase.
>
> **Scope note**: OpenCode was added as a 5th read-only source in the same commit (mirrors the Hermes contract over `opencode.db`). OpenCode/Hermes sessions emit neutral audit defaults because they have no JSONL transcript to mine.

---

# Codex-Claude-History-Viewer：聊天记录二次加工与 Agent 价值审计计划

> 目标：把 Codex / Claude / OpenClaw / Hermes 等 Agent 的历史 JSONL 聊天记录，从“原始 transcript 浏览器”升级为“Agent 价值复盘、交付审计、远端运维足迹看板”。

---

## 0. 一句话定位

当前项目不需要做 Langfuse、Helicone、OpenTelemetry 那类企业级平台，也不需要一开始引入 MCP、向量库或 embedding 聚类。

本阶段只做一件事：

> 直接分析已有 JSONL 聊天记录，提取 Agent 做过什么、动过什么、是否闭环，并把这些信息压缩成可视化价值信号。

核心判断边界：

- 规则负责判断“发生了什么”。
- AI 负责解释“这意味着什么”。
- 所有 AI 审计结论必须能回溯到原始 evidence。

---

## 1. 当前问题

原始 Viewer 已经能展示聊天记录，但仍然回答不了这些真正有价值的问题：

1. 哪些 session 真正产生了交付？
2. 哪些 session 只是聊天、查资料、探索？
3. Agent 到底动了哪些文件？
4. 哪些 session 做了 SSH、部署、服务重启、日志排查？
5. 哪些 session 在报错循环里浪费了时间？
6. 一个文件是如何在多次 AI 会话中逐步演进的？
7. 用户最初的需求最后有没有被满足？
8. 如果没有满足，缺口是什么？

因此下一阶段的重点不是继续优化 transcript 渲染，而是建立“聊天记录二次加工层”。

---

## 2. 产品目标

把每个 session 从一段长聊天，压缩成一张工程战报：

```text
[2026-06-27] 修复 Viewer 滚动和主题
Claude | 12min | ✓ Completed | 📂 4 Files | 🛠 36 Tools | 🧪 Test | Value 84
```

打开详情后，用户能看到：

```text
Agent Value Audit

Intent
修复聊天记录 Viewer 的滚动体验，并补充主题质感。

Outcome
Partially Delivered

Deliverables
- static/app.js
- static/styles.css

Command Intents
- TEST: 1
- DEBUG: 3
- FILE_OP: 4

Gap
Session 列表虚拟化未落地。
```

最终产品形态：

> Agent 帮我做事的账本，而不是 AI 和我聊天的流水账。

---

## 3. 本阶段明确不做

为了避免过度设计，本阶段明确不做：

1. 不做实时 MCP 拦截。
2. 不做实时 agent memory gateway。
3. 不做向量数据库。
4. 不做 embedding 聚类。
5. 不做 OpenTelemetry trace。
6. 不做多租户平台。
7. 不做完整 event sourcing 系统。
8. 不让 LLM 肉身读取完整几万行 JSONL。
9. 不一开始全量 AI 审计所有历史 session。

本阶段只做：

```text
JSONL -> 确定性证据提取 -> SQLite 缓存 -> 前端价值展示 -> 可选 AI 审计
```

---

## 4. 核心原则

### 4.1 规则负责“发生了什么”

以下事实只能由代码解析，不能让 AI 猜：

- 使用了哪些工具。
- 修改了哪些文件。
- 执行了哪些 bash 命令。
- 是否出现 SSH / SCP / RSYNC。
- 是否部署。
- 是否跑测试。
- 是否报错。
- 是否中断。
- 是否有最终回复。
- 是否存在远端操作。

这些属于 evidence layer。

### 4.2 AI 负责“这意味着什么”

AI 只做语义审计：

- 用户真实意图是什么。
- session 类型是什么：bugfix / feature / deploy / debug / exploration。
- 用户需求可以拆成哪些 checklist。
- 哪些 checklist 有证据支撑。
- 哪些只是讨论，没有落地。
- 最终是 delivered / partially delivered / failed / exploration。

### 4.3 审计结论必须可回溯

任何 AI 给出的完成判断都必须引用 evidence_ids。

错误示例：

```json
{
  "status": "COMPLETED",
  "evidence": "修改了 app.py"
}
```

正确示例：

```json
{
  "status": "COMPLETED",
  "evidence_ids": [
    "session_abc123:file:static/app.js",
    "session_abc123:tool:edit:14"
  ]
}
```

---

## 5. 总体数据流

```text
原始 JSONL Session
    ↓
Heuristic Extractor
    ↓
Audit Payload
    ↓
SQLite Cache
    ↓
Session List Badges / Detail Evidence Panel
    ↓
可选：LLM Audit
    ↓
需求闭环 Checklist / 满足度 / Gap Analysis
```

最重要的工程边界：

```text
完整 JSONL 不直接喂给模型。
模型只读取 extractor 生成的 audit_payload。
```

---

## 6. 模块设计

建议新增目录：

```text
audit/
  __init__.py
  schema.py
  extractor.py
  command_classifier.py
  scoring.py
  ai_auditor.py
```

如果第一版想少动结构，可以先写成单文件：

```text
history_audit.py
```

但长期建议拆模块。

---

## 7. Audit Payload 结构

Extractor 对每个 session 生成如下结构：

```json
{
  "session_id": "session_abc123",
  "source": "claude",
  "model": "claude-3-5-sonnet",
  "started_at": 1710000000000,
  "ended_at": 1710000300000,
  "duration_ms": 300000,

  "first_user_prompt": "...",
  "last_user_prompt": "...",
  "important_user_prompts": [],
  "last_assistant_reply": "...",

  "message_count": {
    "user": 8,
    "assistant": 12,
    "tool": 45,
    "other": 2
  },

  "tools_used": {
    "bash": 12,
    "edit": 4,
    "write": 2,
    "grep": 8,
    "read": 19
  },

  "files_touched": {
    "local": [],
    "remote": [],
    "inferred": []
  },

  "file_mutation_stats": {
    "static/app.js": {
      "edit_count": 4,
      "write_count": 0,
      "confidence": "high",
      "net_value_weight": 0.3
    }
  },

  "command_intents": {
    "TEST": 2,
    "BUILD": 1,
    "DEPLOY": 1,
    "REMOTE": 3,
    "DEBUG": 5,
    "FILE_OP": 4,
    "GIT": 2,
    "INSTALL": 1,
    "DB": 0
  },

  "remote_context": {
    "has_remote": true,
    "targets": ["root@server"],
    "remote_command_count": 8
  },

  "errors": {
    "count": 3,
    "samples": []
  },

  "outcome_signal": "completed",
  "value_score": 78,
  "friction_score": 12,
  "action_density": 3.4,

  "evidence": []
}
```

---

## 8. Evidence ID 规范

### 8.1 全局唯一 ID

Evidence ID 必须带 session_id 前缀，避免跨 session DOM 节点、文件侧边栏、跳转路由冲突。

不推荐：

```text
tool:bash:8
file:app.py
```

推荐：

```text
{session_id}:tool:bash:8
{session_id}:tool:edit:14
{session_id}:file:static/app.js
{session_id}:cmd:ssh:3
{session_id}:error:tool:22
{session_id}:msg:user:0
{session_id}:msg:assistant:final
```

示例：

```text
session_abc123:tool:bash:8
session_abc123:file:/etc/nginx/nginx.conf
```

### 8.2 Evidence 对象

```json
{
  "id": "session_abc123:tool:bash:8",
  "session_id": "session_abc123",
  "type": "tool_call",
  "tool_name": "bash",
  "summary": "ssh root@server 'cd /app && docker compose up -d'",
  "confidence": "high",
  "message_index": 42,
  "raw_ref": {
    "line_no": 128,
    "json_path": "$.tool_calls[0]"
  }
}
```

### 8.3 前端跳转策略

Evidence ID 可直接作为路由锚点：

```text
/session/session_abc123#session_abc123:tool:bash:8
```

前端渲染 DOM 时使用安全转义后的 ID：

```text
data-evidence-id="session_abc123:tool:bash:8"
```

不要直接把包含 `/`、空格、冒号的字符串无处理地塞进 `id` 属性。可以使用 base64url / encodeURIComponent。

---

## 9. 文件足迹提取

### 9.1 本地文件路径：高置信度

来源：

- Edit tool
- Write tool
- MultiEdit tool
- Notebook edit
- explicit `file_path`
- explicit `path`

示例规则：

```python
if tool_name.lower() in {"edit", "write", "multiedit"}:
    path = args.get("file_path") or args.get("path")
    if path:
        add_local_file(path, confidence="high")
```

### 9.2 远端文件路径：中置信度

来源：

- ssh command 内的 `sed -i`
- ssh command 内的 `cat > file`
- ssh command 内的 `tee file`
- scp / rsync 目标路径
- vim / nano 打开的路径

示例：

```bash
ssh root@server 'sed -i "s/foo/bar/g" /etc/nginx/nginx.conf'
```

提取：

```json
{
  "path": "/etc/nginx/nginx.conf",
  "source": "ssh_sed_i",
  "confidence": "medium",
  "remote": true
}
```

### 9.3 推断文件路径：低置信度

来源：

- traceback 中的路径
- build error 中的路径
- grep output 中出现的路径
- final answer 中提到的文件

这些必须放入：

```json
"files_touched": {
  "inferred": []
}
```

不要和真实修改混在一起。

---

## 10. Ghost Modification：幽灵修改处理

### 10.1 问题

Agent 可能在一个 session 中反复修改同一个文件，最后又回滚、失败或中断。

如果只要 Edit/Write 过就给高分，会出现“净资产为零但 value_score 很高”的假象。

典型场景：

```text
Turn 3: 修改 app.py
Turn 4: 报错
Turn 5: 再改 app.py
Turn 6: 又报错
Turn 7: 回滚 app.py
Turn 8: session aborted
```

此时 `app.py` 确实被 touch 过，但不应该被当作高价值交付。

### 10.2 第一版轻量规则

对每个文件统计：

```json
{
  "edit_count": 5,
  "write_count": 0,
  "final_outcome": "errored",
  "net_value_weight": 0.3
}
```

规则：

```text
如果同一文件 edit_count > 3 且 outcome_signal 为 errored / interrupted：
    该文件 value 权重打 3 折

如果同一文件 edit_count > 5 且 error_count > 5：
    该文件 value 权重打 2 折

如果 outcome_signal 为 completed 且存在 TEST / BUILD 成功迹象：
    保持正常权重
```

### 10.3 不做过度复杂 diff

第一版不需要真正读取 git diff，也不需要判断最终文件内容是否等于初始内容。

原因：

- JSONL 未必包含完整文件前后状态。
- 远端文件无法直接读取。
- 复杂 diff 成本高，收益低。

先用“频繁修改 + 失败/中断”作为 ghost modification 的近似信号即可。

---

## 11. Bash Command Intent 分类

### 11.1 分类枚举

```text
TEST       测试
BUILD      构建
DEPLOY     部署 / 重启服务
REMOTE     SSH / SCP / RSYNC
DEBUG      日志 / 搜索 / 排查
FILE_OP    文件操作
GIT        Git 操作
INSTALL    安装依赖
DB         数据库迁移 / SQL / backup
NETWORK    curl / wget / ping / nc
SECURITY   chmod / chown / ssh-key / certbot
UNKNOWN    未分类
```

### 11.2 规则示例

```python
COMMAND_PATTERNS = {
    "TEST": [
        r"\bpytest\b",
        r"\bnpm\s+test\b",
        r"\bpnpm\s+test\b",
        r"\byarn\s+test\b",
        r"\bcargo\s+test\b",
        r"\bgo\s+test\b"
    ],
    "BUILD": [
        r"\bnpm\s+run\s+build\b",
        r"\bpnpm\s+build\b",
        r"\byarn\s+build\b",
        r"\bmake\s+build\b",
        r"\bdocker\s+build\b"
    ],
    "DEPLOY": [
        r"\bsystemctl\s+restart\b",
        r"\bsystemctl\s+reload\b",
        r"\bdocker\s+compose\s+up\b",
        r"\bdocker-compose\s+up\b",
        r"\bpm2\s+restart\b",
        r"\bkubectl\s+apply\b",
        r"\bnginx\s+-s\s+reload\b",
        r"\bsupervisorctl\s+restart\b"
    ],
    "REMOTE": [
        r"\bssh\b",
        r"\bscp\b",
        r"\brsync\b"
    ],
    "DEBUG": [
        r"\btail\b",
        r"\bjournalctl\b",
        r"\bdocker\s+logs\b",
        r"\bgrep\b",
        r"\brg\b",
        r"\blsof\b",
        r"\bps\s+",
        r"\bnetstat\b",
        r"\bss\s+"
    ],
    "FILE_OP": [
        r"\bsed\s+-i\b",
        r"\bcat\s+>",
        r"\btee\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\brm\b",
        r"\bchmod\b",
        r"\bchown\b"
    ],
    "GIT": [
        r"\bgit\s+status\b",
        r"\bgit\s+diff\b",
        r"\bgit\s+add\b",
        r"\bgit\s+commit\b",
        r"\bgit\s+pull\b",
        r"\bgit\s+push\b"
    ],
    "INSTALL": [
        r"\bnpm\s+install\b",
        r"\bpnpm\s+install\b",
        r"\bpip\s+install\b",
        r"\bapt\s+install\b",
        r"\bbrew\s+install\b"
    ],
    "DB": [
        r"\bprisma\s+migrate\b",
        r"\balembic\b",
        r"\bknex\b",
        r"\bmysql\b",
        r"\bpsql\b",
        r"\bsqlite3\b"
    ]
}
```

### 11.3 一个命令可以多标签

示例：

```bash
ssh root@server 'cd /app && git pull && docker compose up -d && docker logs app'
```

分类结果：

```json
["REMOTE", "GIT", "DEPLOY", "DEBUG"]
```

---

## 12. SSH 上下文传播

### 12.1 问题

真实开发中，远端操作不一定总是单行命令。

可能出现：

```bash
ssh -i key.pem user@vps "sudo su -c 'systemctl restart nginx'"
```

也可能先进入交互式 SSH，然后后续命令看起来只是：

```bash
git pull
systemctl restart nginx
journalctl -u app -n 100
```

这些命令本质上是远端操作，但单看每条命令未必含有 `ssh`。

### 12.2 规则补丁

在 session 级别维护 remote_context：

```python
remote_context = {
    "active": False,
    "targets": set(),
    "last_seen_index": None
}
```

规则：

```text
如果检测到成功执行 ssh / scp / rsync：
    remote_context.active = True
    后续 bash 命令默认附加 REMOTE 标签

如果检测到 exit / logout / Connection closed：
    remote_context.active = False

如果一直没有 exit，但 session 结束：
    remote_context.active 在 session 结束时自然失效
```

### 12.3 注意

这不是完美判断，但对 Viewer 足够实用。

所有通过 remote_context 自动打上的 REMOTE 标签，confidence 应为 medium，而不是 high。

```json
{
  "intent": "REMOTE",
  "source": "session_remote_context",
  "confidence": "medium"
}
```

---

## 13. JSONL 流式解析策略

### 13.1 问题

Agent JSONL 可能非常畸形：

- 单行 stdout 巨大。
- Webpack / npm / pip 报错输出数 MB。
- tool_result 中嵌入大量日志。
- 某些行 JSON 结构不稳定。
- 某些日志缺少 timestamp。

如果 extractor 对每一行都无脑 `json.loads(line)`，可能导致卡顿、内存峰值过高或扫描历史时体验很差。

### 13.2 头尾侦察

先快速读取文件前几行和后几行：

```text
head 3 lines -> started_at / source / model / first_user_prompt
tail 3 lines -> ended_at / final assistant reply / outcome hints
```

用途：

- 快速拿到 duration 基础信息。
- 快速判断是否有 final convergence。
- 避免为标题、时间、模型等基础信息扫描全文件。

### 13.3 中间过滤

逐行读取中间内容时，先做字符串预检，再决定是否 json.loads。

示例逻辑：

```python
INTERESTING_HINTS = [
    '"role"',
    '"tool_calls"',
    '"tool_use"',
    '"name"',
    '"bash"',
    '"Edit"',
    '"Write"',
    '"file_path"',
    '"error"',
    '"Traceback"',
    '<turn_aborted>',
    '<turn_interrupted>'
]

if len(line) > MAX_LINE_BYTES:
    if not any(hint in line for hint in INTERESTING_HINTS):
        skip_large_line()
    else:
        parse_with_truncation(line)
else:
    json.loads(line)
```

### 13.4 大行处理

建议：

```text
MAX_LINE_BYTES = 1_000_000
MAX_ERROR_SAMPLE_CHARS = 300
MAX_COMMAND_CHARS = 500
MAX_ASSISTANT_REPLY_CHARS = 2000
```

超大行策略：

1. 先字符串扫描关键词。
2. 只保存摘要。
3. 不保存完整 stdout。
4. JSON 解析失败时不终止整个 session。

### 13.5 容错原则

Extractor 必须保证：

```text
单个坏 JSON 行不能导致整个 session 审计失败。
```

错误行记录到：

```json
{
  "parse_errors": 3
}
```

但不要直接中断。

---

## 14. Outcome Signal 规则

### 14.1 枚举

```text
completed
partially_completed
errored
interrupted
incomplete
exploration
unknown
```

### 14.2 初始规则

```text
如果包含 <turn_aborted> / <turn_interrupted>：
    interrupted

否则如果最后 5 个 tool result 有 error 且没有后续成功命令：
    errored

否则如果 user 最后一条之后没有 assistant 回复：
    incomplete

否则如果没有 write/edit/bash/deploy/test，且主要是 read/search：
    exploration

否则如果有明显文件改动或部署动作，且最后 assistant 有收敛总结：
    completed

否则：
    unknown
```

### 14.3 用户可覆盖

Outcome 第一版允许误判。

UI 后续应允许用户覆盖：

```text
Auto: completed
User override: partially_completed
```

用户覆盖结果后续可以作为规则调优样本。

---

## 15. 价值指标

### 15.1 value_score

目标：帮助用户排序，优先看到高价值 session。

初版公式：

```text
value_score =
  + 12 * weighted_local_files_touched_count
  + 15 * weighted_remote_files_touched_count
  + 8  * write_ops
  + 6  * edit_ops
  + 5  * successful_bash_count
  + 10 * deploy_intent_count
  + 8  * test_intent_count
  + 6  * git_intent_count
  - 8  * error_count
  - 12 * interrupted_flag
```

限制范围：

```text
0 <= value_score <= 100
```

### 15.2 Ghost Modification 权重接入

文件计数不要直接按 unique files 计算，要使用 net_value_weight：

```text
weighted_local_files_touched_count = sum(file.net_value_weight for local files)
```

示例：

```json
{
  "static/app.js": {
    "net_value_weight": 0.3
  },
  "static/styles.css": {
    "net_value_weight": 1.0
  }
}
```

### 15.3 friction_score

目标：看 AI 卡在哪里。

```text
friction_score =
  + 10 * error_count
  + 8  * failed_bash_count
  + 6  * repeated_command_count
  + 12 * interrupted_flag
```

### 15.4 action_density

目标：区分“在干活”还是“在聊天”。

```text
action_density = tool_call_count / max(duration_minutes, 1)
```

### 15.5 命名注意

这些分数不是科学 KPI。

UI 不要写成“生产力评分”，建议写：

```text
Value Signal
Friction
Action Density
```

---

## 16. SQLite 设计

### 16.1 最小字段

```sql
ALTER TABLE sessions ADD COLUMN files_touched_json TEXT;
ALTER TABLE sessions ADD COLUMN tool_summary_json TEXT;
ALTER TABLE sessions ADD COLUMN command_intents_json TEXT;
ALTER TABLE sessions ADD COLUMN outcome_signal TEXT;
ALTER TABLE sessions ADD COLUMN value_score INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN friction_score INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN action_density REAL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN audit_status TEXT DEFAULT 'not_started';
ALTER TABLE sessions ADD COLUMN audit_json TEXT;
ALTER TABLE sessions ADD COLUMN audit_updated_at INTEGER;
```

### 16.2 平滑迁移函数

在 `init_db()` 或数据库启动流程中调用：

```python
def patch_db_for_audit(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]

    new_fields = {
        "files_touched_json": "TEXT",
        "tool_summary_json": "TEXT",
        "command_intents_json": "TEXT",
        "outcome_signal": "TEXT",
        "value_score": "INTEGER DEFAULT 0",
        "friction_score": "INTEGER DEFAULT 0",
        "action_density": "REAL DEFAULT 0",
        "audit_status": "TEXT DEFAULT 'not_started'",
        "audit_json": "TEXT",
        "audit_updated_at": "INTEGER"
    }

    for field, field_type in new_fields.items():
        if field not in columns:
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {field} {field_type};")

    db_conn.commit()
```

### 16.3 中期独立表方案

如果后续 audit 字段越来越多，再拆成独立表：

```sql
CREATE TABLE session_audits (
  session_id TEXT PRIMARY KEY,
  audit_status TEXT NOT NULL DEFAULT 'not_started',
  evidence_json TEXT,
  audit_payload_json TEXT,
  audit_json TEXT,
  value_score INTEGER DEFAULT 0,
  friction_score INTEGER DEFAULT 0,
  action_density REAL DEFAULT 0,
  outcome_signal TEXT,
  updated_at INTEGER
);
```

第一版建议先走扩展字段，减少改动面。

---

## 17. 前端 UI 改造

### 17.1 Session 列表战报化

目标：不开详情页，也能看到 Agent 价值。

示例：

```text
重构 Indexer 解析逻辑
Claude | 14min | ✓ Completed | 📂 6 Files | 🛠 45 Tools | 🌐 Remote | 🧪 Tests | 🚀 Deploy | Value 82
```

Badge：

```text
📂 N Files
🛠 N Tools
🌐 Remote
🧪 Test
🚀 Deploy
🐞 Debug
⚠️ N Errors
✓ Completed
✗ Error
⏸ Interrupted
```

排序：

```text
Recent
Value Signal
Files Touched
Friction
Remote Ops
```

### 17.2 Session 详情审计面板

新增右侧或顶部 panel：

```text
Agent Value Audit

Outcome
✓ Completed

Value Signal
82 / 100

Touched Files
- static/app.js
- app.py
- /etc/nginx/nginx.conf

Command Intents
- TEST: 2
- DEPLOY: 1
- REMOTE: 3
- DEBUG: 5

Errors
3 detected

Final Summary
最后 assistant 的收敛回复摘要
```

### 17.3 Tool Call 折叠时间轴

默认折叠 tool output，只展示摘要：

```text
[Bash] npm run build        ✓ 2.1s
[Edit] static/app.js        modified
[SSH] root@server           deploy + logs
```

展开后再看完整 stdout / stderr。

### 17.4 Files Touched 侧边栏

新增 file-centric 入口：

```text
Files Touched

static/app.js       8 sessions
app.py              6 sessions
/etc/nginx.conf     2 sessions
```

点击文件后显示所有触碰过该文件的 session。

---

## 18. AI 审计层

### 18.1 触发策略

不全量自动审计所有 session。

推荐策略：

```text
用户打开 session 详情
    如果 audit_json 不存在：
        显示“生成审计”按钮
        用户点击后生成
        写入 SQLite
    如果已存在：
        直接展示缓存
```

后续再支持批量：

```text
Audit top 50 high-value sessions
Audit sessions from last 7 days
Audit only completed sessions
```

### 18.2 LLM 输入

模型只读取 audit_payload，不读取完整 JSONL。

```json
{
  "first_user_prompt": "...",
  "important_user_prompts": [],
  "last_user_prompt": "...",
  "last_assistant_reply": "...",
  "files_touched": {
    "local": [],
    "remote": [],
    "inferred": []
  },
  "tools_used": {},
  "command_intents": {},
  "errors": {
    "count": 0,
    "samples": []
  },
  "outcome_signal": "completed",
  "evidence": []
}
```

### 18.3 LLM 输出 Schema

```json
{
  "intent_summary": "修复聊天记录 Viewer 的滚动跳动和主题质感问题",
  "session_type": "bugfix",
  "delivery_grade": "PARTIALLY_DELIVERED",
  "satisfaction_score": 72,
  "tasks": [
    {
      "task": "修复向上加载消息时的滚动锚定",
      "status": "COMPLETED",
      "evidence_ids": [
        "session_abc123:file:static/app.js",
        "session_abc123:tool:edit:4"
      ],
      "confidence": 0.86
    },
    {
      "task": "实现 session 列表虚拟化",
      "status": "NOT_DONE",
      "evidence_ids": [],
      "confidence": 0.77
    }
  ],
  "deliverables": [
    "static/app.js",
    "static/styles.css"
  ],
  "gap_analysis": "滚动和主题已处理，但虚拟化未落地。",
  "next_action": "补 session list windowing 或先观察 1000+ session 性能。"
}
```

### 18.4 枚举

```text
session_type:
bugfix / feature / refactor / debug / deploy / ops / research / review / docs / exploration / mixed

completion grade:
DELIVERED / PARTIALLY_DELIVERED / FAILED / EXPLORATION

task status:
COMPLETED / PARTIALLY_COMPLETED / NOT_DONE / FAILED / EXPLORED
```

### 18.5 Prompt 原则

```text
你是一个软件工程行为审计员。

你不能凭空假设。
你只能根据 evidence 判断任务是否完成。
如果没有 evidence，必须标记为 NOT_DONE 或 EXPLORED。
如果用户只是咨询，没有代码/部署/测试动作，可以标记为 EXPLORATION。
每个 COMPLETED / PARTIALLY_COMPLETED / FAILED 判断必须给出 evidence_ids。
输出必须是严格 JSON。
```

---

## 19. Milestones

### Milestone 1：Audit Payload 生成

目标：后端能对单个 session 生成 audit payload。

任务：

1. 新增 extractor。
2. 支持读取 JSONL。
3. 实现头尾侦察。
4. 实现大行跳过与解析容错。
5. 提取 user prompts。
6. 提取 assistant final reply。
7. 提取 tool counts。
8. 提取 files_touched。
9. 提取 bash commands。
10. command intent 分类。
11. SSH remote_context 传播。
12. error_count 统计。
13. outcome_signal 计算。
14. ghost modification 权重。
15. value_score / friction_score / action_density 计算。
16. 输出 JSON。

验收标准：

```text
对任意 session，能生成 audit_payload_json。
不调用 AI。
不会因为某一行 JSON 解析失败导致整个 session 失败。
超大 stdout 不会拖死扫描。
```

### Milestone 2：SQLite 持久化

目标：Indexer 扫描时写入审计元数据。

任务：

1. 增加 patch_db_for_audit。
2. Indexer 调用 extractor。
3. 将 files_touched_json 写入 SQLite。
4. 将 tool_summary_json 写入 SQLite。
5. 将 command_intents_json 写入 SQLite。
6. 将 outcome_signal / value_score 写入 SQLite。
7. 对旧 session 支持 backfill。

验收标准：

```text
刷新索引后，sessions 表里有审计字段。
旧数据可通过 backfill 命令补齐。
旧 Viewer 数据不丢失。
```

### Milestone 3：Session 列表 Badge

目标：列表页一眼看到 Agent 价值。

任务：

1. API 返回新增字段。
2. 前端解析 JSON 字段。
3. 渲染 Files / Tools / Remote / Deploy / Test / Error badge。
4. 增加 outcome badge。
5. 增加 value_score 显示。
6. 增加按 value_score 排序。

验收标准：

```text
用户无需打开详情页，就能看出哪个 session 动了文件、跑了命令、远端部署、是否成功。
```

### Milestone 4：详情页证据面板

目标：打开 session 后看到结构化行动轨迹。

任务：

1. 右侧新增 Agent Value Audit 面板。
2. 展示 files_touched。
3. 展示 command intents。
4. 展示 errors。
5. 展示 outcome。
6. 展示 last assistant summary。
7. 点击文件可筛选相关 session。
8. 点击 evidence 可滚动到对应 message/tool block。

验收标准：

```text
详情页能回答：
这次需求是什么？
Agent 动了哪些文件？
做了哪些远端操作？
跑没跑测试？
最后是否收敛？
```

### Milestone 5：Tool Call 折叠时间轴

目标：把冗长 transcript 压缩成行动轨迹。

任务：

1. tool block 默认折叠。
2. bash block 显示 command summary。
3. edit/write block 显示 file path。
4. tool result 显示 success/error。
5. stderr/error 高亮。
6. 长 stdout 默认截断。

验收标准：

```text
长 session 不再被 tool output 淹没。
用户能快速扫过 Agent 行动过程。
```

### Milestone 6：AI 审计

目标：给高价值 session 生成需求闭环判断。

任务：

1. 设计 JSON Schema。
2. 增加 audit_status。
3. 增加“生成 AI 审计”按钮。
4. 后端将 audit_payload 发给模型。
5. 模型返回 audit_json。
6. 写入 SQLite。
7. 前端展示 checklist。
8. 每个 checklist item 展示 evidence_ids。
9. 支持重新生成审计。

验收标准：

```text
打开一个 session，可以生成：
- 用户真实意图
- 任务 checklist
- 每项完成状态
- 交付物
- gap analysis
- next action
```

---

## 20. 推荐执行顺序

最优顺序：

```text
1. command_classifier.py
2. extractor.py
3. scoring.py
4. patch_db_for_audit
5. Indexer 写入审计字段
6. Session list badges
7. Detail audit panel
8. Tool call 折叠
9. AI audit
10. File-centric view
```

不要一开始就做 AI。

先把确定性 metadata 做扎实。

---

## 21. MVP 范围

第一版最小可用功能：

```text
files_touched_json
工具数量统计
command_intents_json
outcome_signal
value_score
friction_score
session list badges
```

MVP 不需要：

```text
LLM audit
checklist
file graph
semantic memory
embedding
```

MVP 完成后，产品已经从 transcript viewer 变成 Agent behavior viewer。

---

## 22. 风险与规避

### 风险 1：不同 agent JSONL 格式不统一

规避：

```text
先写 adapter 层。
不同 source 各自 normalize 成统一 AuditEvent。
```

统一结构：

```json
{
  "role": "assistant",
  "content": "...",
  "tool_calls": [],
  "tool_result": null,
  "timestamp": 0
}
```

### 风险 2：bash 命令太复杂，正则漏判

规避：

```text
允许 UNKNOWN。
先覆盖高频命令。
UI 上显示 raw command summary。
后续根据真实日志补规则。
```

### 风险 3：AI 审计胡说

规避：

```text
必须 evidence_ids。
没有 evidence 不许标 completed。
temperature 设低。
输出严格 JSON。
前端显示 confidence。
允许用户手动修正。
```

### 风险 4：审计成本失控

规避：

```text
默认不全量审计。
只审计用户打开的 session。
只给模型喂 audit_payload。
缓存结果。
```

### 风险 5：远端路径误判

规避：

```text
区分 local / remote / inferred。
为每个文件路径加 confidence。
不要把 inferred 当确定修改。
```

### 风险 6：超大 JSONL 行导致扫描卡顿

规避：

```text
头尾侦察。
字符串预检。
大行跳过或截断解析。
单行解析失败不影响整个 session。
```

### 风险 7：Evidence ID 冲突

规避：

```text
所有 evidence ID 必须带 session_id 前缀。
前端 DOM id 使用转义版本，不直接使用原始 evidence 字符串。
```

### 风险 8：幽灵修改导致价值虚高

规避：

```text
对同一文件频繁 edit + errored/interrupted 的 session 降权。
value_score 使用 weighted files count。
```

---

## 23. 成功标准

这个阶段完成后，用户应该能回答：

1. 上周 Agent 帮我改了哪些文件？
2. 哪些 session 是真正有交付的？
3. 哪些 session 是探索讨论，没有落地？
4. 哪些 session 卡在报错循环？
5. 哪些 session 做了远端 SSH / 部署？
6. 一个文件是在哪几次 AI 会话里逐步改出来的？
7. 用户需求是否真的闭环？
8. 没闭环的话，缺口是什么？
9. 哪些远端操作是 Agent 完成的？
10. 哪些 session 价值高但摩擦也高，值得复盘？

如果这些问题能被回答，这个 Viewer 就已经不是普通聊天记录浏览器，而是 Agent 价值审计工具。

---

## 24. 最终结论

这条路线的关键不是“让 AI 看懂所有聊天”，而是：

```text
先用规则把聊天记录压缩成证据，
再让 AI 基于证据判断需求是否闭环。
```

第一阶段只要完成：

```text
Extractor + SQLite 字段 + Session List Badges
```

产品价值就会立刻质变。

第二阶段再做：

```text
AI Checklist Audit + Evidence 跳转 + File-centric View
```

这会把项目从 transcript viewer 推进到真正的 Agent 工作记账系统。
