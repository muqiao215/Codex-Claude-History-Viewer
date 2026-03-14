---
name: codex-claude-history-viewer
description: Use when users ask to browse or search local Codex and Claude session history, work around /resume project scope limits, run a local history UI on Windows, or assess and extend CCHV for local CRUD-style session management.
---

# Codex Claude History Viewer

Use this skill for local session history workflows with:

- `The-Zombie0/Codex-Claude-History-Viewer`
- Codex logs: `~/.codex/sessions`
- Claude logs: `~/.claude/projects`

## 1) Confirm Current Capability First

Treat the upstream app as read-first:

- Cross-project browse/search: supported
- Session/project API (GET): supported
- Built-in business CRUD on sessions: not supported by default

If user asks "does it support CRUD", answer clearly:

- It maintains a local SQLite index internally.
- That internal index maintenance is not user-facing CRUD on source session logs.

For endpoint and code evidence, read:
[references/api-and-crud-notes.md](references/api-and-crud-notes.md)

## 2) Run on Windows (Local-Only)

From repo directory:

```powershell
python .\app.py `
  --codex-dir C:\Users\11614\.codex `
  --claude-dir C:\Users\11614\.claude `
  --data-dir E:\cchv-data `
  --host 127.0.0.1 `
  --port 8787
```

Open `http://127.0.0.1:8787`.

You can also use:

```powershell
.\scripts\start-cchv.ps1 -CodexDir C:\Users\11614\.codex -ClaudeDir C:\Users\11614\.claude -DataDir E:\cchv-data
```

## 3) Default Working Rules

- Keep service bound to `127.0.0.1` unless user explicitly asks LAN access.
- Do not mutate raw `.jsonl` session files unless user explicitly requests destructive changes.
- Prefer "soft management" first (metadata/tag/archive layer), then optional hard delete.

## 4) If User Wants CRUD

Use a safe, incremental plan:

1. Add metadata CRUD first (title, tags, archived, notes) in a sidecar SQLite table.
2. Keep original logs immutable.
3. Add explicit backup + confirmation flow before hard delete of source logs.
4. Expose new endpoints (`POST/PUT/DELETE`) only for metadata unless user asks otherwise.

Use the extension blueprint in:
[references/api-and-crud-notes.md](references/api-and-crud-notes.md)
