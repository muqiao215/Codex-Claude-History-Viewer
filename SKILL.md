---
name: codex-claude-history-viewer
description: Use when users ask to browse or search local Codex, Claude Code, or OpenClaw session history, run the local history UI, recover context across projects, or launch the viewer on Windows, WSL, Ubuntu, or Linux.
---

# Codex Claude History Viewer

Use this skill for local session-history work with:

- Codex logs: `~/.codex/sessions`
- Claude Code logs: `~/.claude/projects`
- OpenClaw logs: `~/.openclaw/agents`

## What This Skill Is For

Use it when the user wants to:

- open the local history UI
- search old Codex / Claude Code / OpenClaw sessions
- recover context when `/resume` is workspace-scoped
- inspect sessions by project
- manage local history with the viewer's supported UI actions
- run the viewer on Windows, WSL, Ubuntu, or Linux

If the user only wants raw history export or markdown compaction, prefer the more specialized history/export skills instead.

## Runtime Rule

Do not assume Windows.

Pick the launcher by runtime:

- **Windows runtime** → use `scripts/start-cchv.ps1`
- **Ubuntu / Linux runtime** → use `scripts/start-cchv.sh`
- **WSL shell** → use `scripts/start-cchv.sh`

The installed skill copy is not the app repo itself. The launchers must first locate the real local repo containing `app.py`.

## Repo Resolution Rule

Default to an existing local repo. Do not clone unless the user explicitly asks.

Repo resolution priority:

1. `CCHV_REPO_DIR` environment variable
2. user-provided repo path
3. common local paths for this machine:
   - Windows: `E:\web\tools\Codex-Claude-History-Viewer`
   - Linux / WSL: `/mnt/e/web/tools/Codex-Claude-History-Viewer`
   - Linux: `~/web/tools/Codex-Claude-History-Viewer`

If no valid repo is found, say that the viewer repo is missing locally and ask whether to install or clone it.

## Launch Commands

### Windows

```powershell
& "$env:USERPROFILE\.gemini\skills\codex-claude-history-viewer\scripts\start-cchv.ps1"
```

Optional override:

```powershell
$env:CCHV_REPO_DIR='E:\web\tools\Codex-Claude-History-Viewer'
& "$env:USERPROFILE\.gemini\skills\codex-claude-history-viewer\scripts\start-cchv.ps1"
```

### Ubuntu / Linux / WSL

```bash
bash ~/.gemini/skills/codex-claude-history-viewer/scripts/start-cchv.sh
```

Optional override:

```bash
export CCHV_REPO_DIR=/mnt/e/web/tools/Codex-Claude-History-Viewer
bash ~/.gemini/skills/codex-claude-history-viewer/scripts/start-cchv.sh
```

### Ubuntu Desktop Entry

```bash
bash ~/.gemini/skills/codex-claude-history-viewer/scripts/install-linux-desktop-entry.sh
```

## Working Rules

- Keep the server bound to `127.0.0.1` unless the user explicitly asks for LAN access
- Do not mutate raw session JSONL files unless the user explicitly asks for destructive changes
- Prefer built-in viewer actions and sidecar metadata over raw file surgery
- When asked whether CRUD is supported, answer precisely: the viewer has local index/state management, not general arbitrary CRUD over source logs

Read `references/api-and-crud-notes.md` only when the user asks about API shape, CRUD behavior, or extension design.
