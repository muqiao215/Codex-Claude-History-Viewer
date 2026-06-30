#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone, time as dt_time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from audit import (
    AUDIT_VERSION,
    build_audit_for_file,
    deserialize_audit_summary,
    patch_db_for_audit,
    serialize_audit_fields,
)

MAX_SEARCH_CHARS = 2_000_000
DEFAULT_LIMIT = 200
MESSAGE_INLINE_FULL_THRESHOLD = 12_000
MESSAGE_PREVIEW_CHARS = 4_000
MESSAGE_PREVIEW_FETCH_CHARS = MESSAGE_PREVIEW_CHARS + 2_048
SEARCH_MATCH_CONTEXT_CHARS = 1_600
SEARCH_MATCH_MAX_CHARS = 3_600
DEFAULT_PAGE_LIMIT = 50
SESSION_PREVIEW_CACHE_SIZE = 12


def _neutral_audit_summary():
    return {
        "files_touched": [],
        "tools_used": [],
        "command_intents": [],
        "remote_context": [],
        "outcome_signal": "unknown",
        "value_score": 0,
        "friction_score": 0,
        "action_density": 0.0,
    }


_AUDIT_RAW_JSON_KEYS = frozenset({
    "files_touched_json",
    "tool_summary_json",
    "command_intents_json",
    "remote_context_json",
})


def _strip_audit_raw_json(item):
    for key in _AUDIT_RAW_JSON_KEYS:
        item.pop(key, None)
    return item


def _match_files_touched(files_touched_json, target_path):
    # ALGO: two-stage filter for ?file= cross-session drill-down (002 §M4).
    # Stage 1 (SQL LIKE) narrows candidate rows; stage 2 (this) parses the JSON
    # and matches the exact path field, eliminating prefix-collisions that
    # coarse LIKE would admit (e.g. /a/b.py vs /a/b_backup.py).
    if not files_touched_json or not target_path:
        return False
    try:
        data = json.loads(files_touched_json) if isinstance(files_touched_json, str) else files_touched_json
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    needle = str(target_path)
    for bucket in ("local", "remote", "inferred"):
        entries = data.get(bucket) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("path") or "") == needle:
                return True
    return False


def _escape_sql_like(value):
    # SECURITY: user-supplied ?file= paths flow into a LIKE clause; escape the
    # pattern metacharacters so %/_ in a path can't broaden the match.
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def detect_runtime_system(os_name=None):
    return "windows" if str(os_name or os.name).lower() == "nt" else "linux"


def build_truncated_message_preview(text, preview_chars=MESSAGE_PREVIEW_CHARS):
    value = str(text or "")
    preview = value[:preview_chars]
    last_newline = preview.rfind("\n")
    if last_newline >= int(preview_chars * 0.6):
        preview = preview[:last_newline]
    return (
        preview.rstrip()
        + "\n\n---\nPreview truncated for performance. Expand to render the full message."
    )


def normalize_message_payload(text, *, include_full_text=False, char_count=None, is_truncated=None):
    value = str(text or "")
    total_chars = len(value) if char_count is None else int(char_count)
    truncated = bool(is_truncated) if is_truncated is not None else (
        (not include_full_text) and total_chars > MESSAGE_INLINE_FULL_THRESHOLD
    )
    rendered = value
    if not include_full_text and truncated:
        rendered = build_truncated_message_preview(value)
    return rendered, total_chars, truncated


class RecallTitleStore:
    def __init__(self, db_path: Path, source: str):
        self.db_path = Path(db_path)
        self.source = str(source or "").strip()
        self._lock = threading.Lock()

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_meta (
                session_id TEXT PRIMARY KEY,
                source TEXT DEFAULT '',
                custom_title TEXT,
                updated_at INTEGER
            )
            """
        )
        conn.commit()
        return conn

    def get_custom_title(self, session_id):
        if not session_id:
            return None
        try:
            with self._lock:
                conn = self._connect()
                try:
                    row = conn.execute(
                        """
                        SELECT custom_title
                        FROM session_meta
                        WHERE session_id = ? AND (source = ? OR source = '')
                        """,
                        (session_id, self.source),
                    ).fetchone()
                    if not row:
                        return None
                    title = row["custom_title"]
                    if isinstance(title, str) and title.strip():
                        return title.strip()
                    return None
                finally:
                    conn.close()
        except (OSError, PermissionError, sqlite3.Error):
            return None

    def set_custom_title(self, session_id, title):
        if not session_id:
            return False
        clean_title = str(title or "").strip()
        if not clean_title:
            return False
        try:
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute(
                        """
                        INSERT INTO session_meta (session_id, source, custom_title, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            source = excluded.source,
                            custom_title = excluded.custom_title,
                            updated_at = excluded.updated_at
                        """,
                        (session_id, self.source, clean_title, int(time.time() * 1000)),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except (OSError, PermissionError, sqlite3.Error):
            return False


def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 1e12:
            return int(value)
        return int(value * 1000)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None
    return None


def build_message_preview_text(text, preview_chars=MESSAGE_PREVIEW_CHARS):
    value = str(text or "")
    if len(value) <= preview_chars:
        return value

    preview = value[:preview_chars]
    last_newline = preview.rfind("\n")
    if last_newline >= int(preview_chars * 0.6):
        preview = preview[:last_newline]
    return preview.rstrip()


def build_search_excerpt_text(
    text,
    match_start,
    match_end,
    context_chars=SEARCH_MATCH_CONTEXT_CHARS,
    max_chars=SEARCH_MATCH_MAX_CHARS,
):
    value = str(text or "")
    if not value:
        return {
            "text": "",
            "start": 0,
            "end": 0,
            "has_more_before": False,
            "has_more_after": False,
        }

    clean_start = max(0, int(match_start or 0))
    clean_end = max(clean_start, int(match_end or clean_start))
    clean_context = max(0, int(context_chars or 0))
    clean_max = max(1, int(max_chars or 1))

    excerpt_start = max(0, clean_start - clean_context)
    excerpt_end = min(len(value), clean_end + clean_context)

    if excerpt_end - excerpt_start > clean_max:
        match_width = max(1, clean_end - clean_start)
        remaining = max(0, clean_max - match_width)
        left_room = remaining // 2
        right_room = remaining - left_room
        excerpt_start = max(0, clean_start - left_room)
        excerpt_end = min(len(value), clean_end + right_room)

        window = excerpt_end - excerpt_start
        if window < clean_max:
            missing = clean_max - window
            if excerpt_start == 0:
                excerpt_end = min(len(value), excerpt_end + missing)
            elif excerpt_end == len(value):
                excerpt_start = max(0, excerpt_start - missing)

    excerpt = value[excerpt_start:excerpt_end]
    prefix = "...\n" if excerpt_start > 0 else ""
    suffix = "\n..." if excerpt_end < len(value) else ""
    return {
        "text": f"{prefix}{excerpt}{suffix}",
        "start": excerpt_start,
        "end": excerpt_end,
        "has_more_before": excerpt_start > 0,
        "has_more_after": excerpt_end < len(value),
    }


def normalize_page_args(limit, offset, default_limit=DEFAULT_PAGE_LIMIT, max_limit=DEFAULT_LIMIT):
    try:
        clean_limit = int(limit)
    except (TypeError, ValueError):
        clean_limit = int(default_limit)
    try:
        clean_offset = int(offset)
    except (TypeError, ValueError):
        clean_offset = 0

    clean_limit = max(1, min(int(max_limit), clean_limit))
    clean_offset = max(0, clean_offset)
    return clean_limit, clean_offset


def add_raw_message(messages, ts_ms, role, obj, reason="unhandled"):
    try:
        raw = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        raw = repr(obj)
    messages.append({
        "ts_ms": ts_ms,
        "role": role or "other",
        "kind": f"raw_json:{reason}",
        "text": f"```json\n{raw}\n```",
    })


def parse_date_param(value, end=False):
    if not value:
        return None
    try:
        date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    local_tz = datetime.now().astimezone().tzinfo
    if end:
        dt = datetime.combine(date, dt_time(23, 59, 59))
    else:
        dt = datetime.combine(date, dt_time(0, 0, 0))
    dt = dt.replace(tzinfo=local_tz)
    return int(dt.timestamp() * 1000)


def slugify_path_label(value):
    text = str(value or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-.")
    return text or "project"


def extract_text(content_items):
    texts = []
    if not content_items:
        return ""
    for item in content_items:
        if not isinstance(item, dict):
            continue
        if "text" in item and isinstance(item["text"], str):
            texts.append(item["text"])
            continue
        item_type = item.get("type")
        if item_type in ("input_text", "output_text"):
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)
            continue
        if item_type in ("image_url", "input_image", "output_image"):
            texts.append("[image]")
            continue
    return "\n".join(t for t in texts if t)


def normalize_codex_context_message(role, kind, text):
    if not text:
        return role, kind, text, False
    s = text.strip()

    if "<permissions instructions>" in s and "</permissions instructions>" in s:
        m = re.search(r"<permissions instructions>\s*(.*?)\s*</permissions instructions>", s, re.S)
        cleaned = (m.group(1).strip() if m else s)
        # Usually developer-scoped, but keep original role if present.
        return role, "context", cleaned, True

    if "<environment_context>" in s and "</environment_context>" in s:
        m = re.search(r"<environment_context>\s*(.*?)\s*</environment_context>", s, re.S)
        inner = m.group(1) if m else ""
        pairs = re.findall(r"<([a-zA-Z0-9_]+)>(.*?)</\\1>", inner, re.S)
        lines = ["Environment context:"]
        for k, v in pairs:
            val = v.strip()
            if val:
                lines.append(f"- {k}: {val}")
        if len(lines) == 1:
            lines.append("(empty)")
        # This is harness metadata; treat as system by default.
        return "system", "context", "\n".join(lines), True

    if s.startswith("# AGENTS.md instructions for ") or "<INSTRUCTIONS>" in s:
        first = s.splitlines()[0].strip()
        skills = re.findall(r"^-\\s*([a-zA-Z0-9_-]+):", s, re.M)
        skills = sorted({x for x in skills if x})
        lines = [first]
        if skills:
            lines.append(f"Skills: {', '.join(skills)}")
        lines.append("(omitted)")
        return "system", "context", "\n".join(lines), True

    return role, kind, text, False


def _codex_try_parse_json(text):
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if not (s.startswith("{") or s.startswith("[")):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _codex_format_tool_use(name, call_id=None, raw_input=None, *, is_custom=False):
    tool_name = str(name or "tool").strip() or "tool"
    tool_key = tool_name.lower()
    lines = [f"Tool use: {tool_name}"]
    if call_id:
        lines.append(f"Call ID: {call_id}")

    if tool_key == "apply_patch" and isinstance(raw_input, str) and raw_input.strip():
        lines.append("Patch:")
        lines.append(f"```patch\n{raw_input.rstrip()}\n```")
        return "\n".join(lines).strip()

    parsed = _codex_try_parse_json(raw_input) if isinstance(raw_input, str) else None

    if tool_key == "shell_command" and isinstance(parsed, dict):
        command = parsed.get("command")
        workdir = parsed.get("workdir")
        if isinstance(workdir, str) and workdir.strip():
            lines.append(f"Workdir: `{workdir.strip()}`")
        if isinstance(command, str) and command.strip():
            lines.append("Command:")
            lines.append(f"```bash\n{command.rstrip()}\n```")
        else:
            lines.append("Input:")
            lines.append(f"```json\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n```")
        return "\n".join(lines).strip()

    if parsed is not None:
        lines.append("Input:")
        lines.append(f"```json\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n```")
        return "\n".join(lines).strip()

    if isinstance(raw_input, str) and raw_input.strip():
        label = "Input:" if not is_custom else "Input:"
        lines.append(label)
        lines.append(f"```\n{raw_input.rstrip()}\n```")

    return "\n".join(lines).strip()


def _codex_format_tool_result(tool_name=None, call_id=None, raw_output=None):
    tool_label = str(tool_name).strip() if tool_name else ""
    header = f"Tool result: {tool_label}" if tool_label else "Tool result:"
    lines = [header]
    if call_id:
        lines.append(f"Call ID: {call_id}")

    exit_code = None
    wall_time = None
    body = None

    if isinstance(raw_output, str):
        parsed = _codex_try_parse_json(raw_output)
        if isinstance(parsed, dict) and ("output" in parsed or "metadata" in parsed):
            meta = parsed.get("metadata")
            if isinstance(meta, dict):
                code = meta.get("exit_code")
                if isinstance(code, (int, float)):
                    exit_code = int(code)
                dur = meta.get("duration_seconds")
                if isinstance(dur, (int, float)):
                    wall_time = f"{dur:.3f}s"
            out = parsed.get("output")
            if isinstance(out, str):
                body = out.strip("\n")
            elif out is not None:
                body = json.dumps(out, ensure_ascii=False, indent=2)
        else:
            m = re.search(r"^Exit code:\\s*(-?\\d+)\\s*$", raw_output, re.M)
            if m:
                exit_code = int(m.group(1))
            m = re.search(r"^Wall time:\\s*(.+?)\\s*$", raw_output, re.M)
            if m:
                wall_time = m.group(1).strip()
            if "\nOutput:\n" in raw_output:
                _, body_part = raw_output.split("\nOutput:\n", 1)
                body = body_part.strip("\n")
            else:
                body = raw_output.strip("\n")

    if exit_code is not None:
        lines.append("Status: ok" if exit_code == 0 else "Status: error")
        lines.append(f"Exit code: {exit_code}")
    if wall_time:
        lines.append(f"Wall time: {wall_time}")
    if isinstance(body, str) and body.strip():
        lines.append("Output:")
        lines.append(f"````\n{body.rstrip()}\n````")

    return "\n".join(lines).strip()


# BDD: spec docs/session-plans/002 §M5 — every tool_use/tool_result message
# carries a structured `tool_summary` so the transcript UI can render collapsed
# one-line rows without re-parsing the raw text.
_TOOL_CATEGORY_MAP = {
    "shell_command": "shell", "bash": "shell", "powershell": "shell", "cmd": "shell", "sh": "shell",
    "apply_patch": "edit", "str_replace_editor": "edit", "write": "edit", "edit": "edit",
    "multi_edit": "edit", "create_file": "edit", "delete_file": "edit",
    "read_file": "read", "read": "read", "get_file_contents": "read", "view": "read",
    "grep": "search", "glob": "search", "search": "search", "find": "search",
    "webfetch": "deploy", "web_search": "deploy", "curl": "deploy",
    "todo_write": "deploy", "update_plan": "deploy", "task": "deploy",
    "askuserquestion": "deploy",
}


def _classify_tool_category(name):
    key = str(name or "").lower().strip()
    if not key:
        return "other"
    if key in _TOOL_CATEGORY_MAP:
        return _TOOL_CATEGORY_MAP[key]
    if key.startswith("text_editor"):
        return "edit"
    return "other"


def _truncate_str(text, max_len):
    if text is None:
        return None
    s = " ".join(str(text).split())
    if not s:
        return None
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _empty_tool_summary(name):
    return {
        "name": str(name or "tool")[:80],
        "category": _classify_tool_category(name),
        "headline": None,
        "file_path": None,
        "change_kind": None,
        "lines_added": None,
        "lines_removed": None,
        "exit_status": None,
        "exit_code": None,
        "output_preview": None,
        "is_error": False,
    }


def _count_diff_lines(patch_text):
    # ALGO: count +/- lines inside @@ hunks, skipping +++/---/*** file markers.
    added = 0
    removed = 0
    in_hunk = False
    for line in patch_text.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith(("+++", "---", "***")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _codex_summarize_tool_use(name, raw_input=None, *, is_custom=False):
    s = _empty_tool_summary(name)
    parsed = _codex_try_parse_json(raw_input) if isinstance(raw_input, str) else None
    cat = s["category"]
    if cat == "shell" and isinstance(parsed, dict):
        cmd = parsed.get("command")
        if isinstance(cmd, str) and cmd.strip():
            s["headline"] = _truncate_str(cmd, 80)
        wd = parsed.get("workdir")
        if isinstance(wd, str) and wd.strip():
            s["file_path"] = wd.strip()
    elif cat == "edit":
        if str(name or "").lower() == "apply_patch" and isinstance(raw_input, str):
            body = raw_input.strip()
            current_path = None
            change_kind = None
            for line in body.splitlines():
                if not line.startswith("*** "):
                    continue
                marker = line[4:].strip()
                for prefix, kind in (
                    ("Add File:", "create"),
                    ("Delete File:", "delete"),
                    ("Update File:", "modify"),
                    ("Modified File:", "modify"),
                ):
                    if marker.startswith(prefix):
                        change_kind = kind
                        current_path = marker[len(prefix):].strip()
                        break
                if change_kind:
                    break
            if current_path:
                s["file_path"] = current_path
            if change_kind:
                s["change_kind"] = change_kind
            added, removed = _count_diff_lines(body)
            s["lines_added"] = added
            s["lines_removed"] = removed
            if current_path and change_kind:
                s["headline"] = _truncate_str(f"{change_kind} {current_path}", 80)
        elif isinstance(parsed, dict):
            path = parsed.get("path") or parsed.get("file_path")
            if isinstance(path, str) and path.strip():
                s["file_path"] = path.strip()
            cmd = parsed.get("command")
            if isinstance(cmd, str) and cmd.strip():
                key = cmd.lower().strip()
                s["change_kind"] = "create" if key == "create" else "delete" if key == "delete" else "modify"
            if s["file_path"] and s["change_kind"]:
                s["headline"] = _truncate_str(f"{s['change_kind']} {s['file_path']}", 80)
    elif cat == "read" and isinstance(parsed, dict):
        path = parsed.get("path") or parsed.get("file_path")
        if isinstance(path, str) and path.strip():
            s["file_path"] = path.strip()
            s["headline"] = _truncate_str(path.strip(), 80)
    elif cat == "search" and isinstance(parsed, dict):
        pattern = parsed.get("pattern")
        path = parsed.get("path")
        parts = []
        if isinstance(pattern, str) and pattern.strip():
            parts.append(pattern.strip())
        if isinstance(path, str) and path.strip():
            parts.append(f"in {path.strip()}")
        if parts:
            s["headline"] = _truncate_str(" ".join(parts), 80)
    elif cat == "deploy" and isinstance(parsed, dict):
        url = parsed.get("url") or parsed.get("query") or parsed.get("prompt")
        if isinstance(url, str) and url.strip():
            s["headline"] = _truncate_str(url.strip(), 80)
        elif str(name or "").lower() in ("todo_write", "update_plan"):
            todos = parsed.get("todos")
            if isinstance(todos, list):
                s["headline"] = f"plan: {len(todos)} items"
    if s["headline"] is None and isinstance(parsed, dict) and parsed:
        for k, v in list(parsed.items())[:1]:
            if v is not None and v != "":
                s["headline"] = _truncate_str(f"{k}: {v}", 80)
                break
    return s


def _codex_summarize_tool_result(tool_name=None, raw_output=None):
    s = _empty_tool_summary(tool_name or "tool")
    if not isinstance(raw_output, str) or not raw_output.strip():
        return s
    parsed = _codex_try_parse_json(raw_output)
    exit_code = None
    body = None
    if isinstance(parsed, dict) and ("output" in parsed or "metadata" in parsed):
        meta = parsed.get("metadata")
        if isinstance(meta, dict):
            code = meta.get("exit_code")
            if isinstance(code, (int, float)):
                exit_code = int(code)
        out = parsed.get("output")
        if isinstance(out, str):
            body = out.strip("\n")
        elif out is not None:
            body = json.dumps(out, ensure_ascii=False)
    else:
        m = re.search(r"^Exit code:\s*(-?\d+)\s*$", raw_output, re.M)
        if m:
            exit_code = int(m.group(1))
        if "\nOutput:\n" in raw_output:
            _, body_part = raw_output.split("\nOutput:\n", 1)
            body = body_part.strip("\n")
        else:
            body = raw_output.strip("\n")
    if exit_code is not None:
        s["exit_code"] = exit_code
        s["exit_status"] = "ok" if exit_code == 0 else "error"
        s["is_error"] = exit_code != 0
    if body:
        s["output_preview"] = _truncate_str(body, 200)
    return s


def _claude_summarize_tool_use(item):
    name = item.get("name") if isinstance(item, dict) else None
    s = _empty_tool_summary(name)
    tool_input = item.get("input") if isinstance(item, dict) and isinstance(item.get("input"), dict) else None
    if not tool_input:
        return s
    cat = s["category"]
    if cat == "shell":
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            s["headline"] = _truncate_str(cmd, 80)
    elif cat == "edit":
        path = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(path, str) and path.strip():
            s["file_path"] = path.strip()
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            key = cmd.lower().strip()
            s["change_kind"] = "create" if key == "create" else "delete" if key == "delete" else "modify"
        new_s = tool_input.get("new_str") or tool_input.get("new_string") or tool_input.get("file_text")
        old_s = tool_input.get("old_str") or tool_input.get("old_string")
        if isinstance(new_s, str) or isinstance(old_s, str):
            s["lines_added"] = len([ln for ln in (new_s or "").splitlines() if ln.strip()])
            s["lines_removed"] = len([ln for ln in (old_s or "").splitlines() if ln.strip()])
        if s["file_path"] and s["change_kind"]:
            s["headline"] = _truncate_str(f"{s['change_kind']} {s['file_path']}", 80)
    elif cat == "read":
        path = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(path, str) and path.strip():
            s["file_path"] = path.strip()
            s["headline"] = _truncate_str(path.strip(), 80)
    elif cat == "search":
        pattern = tool_input.get("pattern")
        path = tool_input.get("path")
        parts = []
        if isinstance(pattern, str) and pattern.strip():
            parts.append(pattern.strip())
        if isinstance(path, str) and path.strip():
            parts.append(f"in {path.strip()}")
        if parts:
            s["headline"] = _truncate_str(" ".join(parts), 80)
    elif cat == "deploy":
        url = tool_input.get("url") or tool_input.get("query") or tool_input.get("prompt")
        if isinstance(url, str) and url.strip():
            s["headline"] = _truncate_str(url.strip(), 80)
        elif str(name or "").lower() == "todo_write":
            todos = tool_input.get("todos")
            if isinstance(todos, list):
                s["headline"] = f"plan: {len(todos)} items"
    if s["headline"] is None:
        for k, v in list(tool_input.items())[:1]:
            if v is not None and v != "":
                s["headline"] = _truncate_str(f"{k}: {v}", 80)
                break
    return s


def _claude_summarize_tool_result(tool_result_item, tool_use_result=None):
    s = _empty_tool_summary("tool")
    is_error = None
    content = None
    if isinstance(tool_result_item, dict):
        is_error = tool_result_item.get("is_error")
        content = tool_result_item.get("content")
    stdout = None
    stderr = None
    if isinstance(tool_use_result, dict):
        stdout = tool_use_result.get("stdout")
        stderr = tool_use_result.get("stderr")
    if is_error is True:
        s["exit_status"] = "error"
        s["is_error"] = True
    elif is_error is False:
        s["exit_status"] = "ok"
        s["is_error"] = False
    body = None
    if isinstance(content, str) and content.strip():
        body = content.strip()
    elif isinstance(stdout, str) or isinstance(stderr, str):
        combined = ""
        if isinstance(stdout, str) and stdout:
            combined += stdout
        if isinstance(stderr, str) and stderr:
            if combined and not combined.endswith("\n"):
                combined += "\n"
            combined += stderr
        body = combined.strip() or None
    elif content is not None:
        body = json.dumps(content, ensure_ascii=False)
    if body:
        s["output_preview"] = _truncate_str(body, 200)
    return s


def parse_codex_session_file(path: Path):
    session_id = None
    start_ts_ms = None
    end_ts_ms = None
    cwd = None
    title = None
    message_count = 0
    messages = []
    search_parts = []
    search_len = 0
    tool_names = {}

    def add_search(text):
        nonlocal search_len
        if not text:
            return
        if search_len >= MAX_SEARCH_CHARS:
            return
        remaining = MAX_SEARCH_CHARS - search_len
        if len(text) > remaining:
            text = text[:remaining]
        search_parts.append(text)
        search_len += len(text)

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    messages.append({
                        "ts_ms": start_ts_ms or end_ts_ms or 0,
                        "role": "other",
                        "kind": "raw_json:malformed_line",
                        "text": f"```\n{line.rstrip()}\n```",
                    })
                    continue

                ts_ms = parse_ts(obj.get("timestamp"))
                if ts_ms is not None:
                    if start_ts_ms is None or ts_ms < start_ts_ms:
                        start_ts_ms = ts_ms
                    if end_ts_ms is None or ts_ms > end_ts_ms:
                        end_ts_ms = ts_ms

                obj_type = obj.get("type")
                if obj_type == "session_meta":
                    payload = obj.get("payload", {})
                    session_id = payload.get("id", session_id)
                    cwd = payload.get("cwd", cwd)
                    meta_ts = parse_ts(payload.get("timestamp"))
                    if meta_ts is not None:
                        if start_ts_ms is None or meta_ts < start_ts_ms:
                            start_ts_ms = meta_ts
                        if end_ts_ms is None or meta_ts > end_ts_ms:
                            end_ts_ms = meta_ts
                elif obj_type == "response_item":
                    payload = obj.get("payload", {})
                    payload_type = payload.get("type")
                    if payload_type == "message":
                        role = payload.get("role", "unknown")
                        text = extract_text(payload.get("content", []))
                        role, kind, text, is_context = normalize_codex_context_message(role, "message", text)
                        if text:
                            messages.append({
                                "ts_ms": ts_ms,
                                "role": role,
                                "kind": kind,
                                "text": text,
                            })
                            if not is_context:
                                message_count += 1
                                add_search(text)
                                if title is None and role == "user":
                                    first_line = text.strip().splitlines()[0] if text.strip() else ""
                                    if first_line:
                                        title = first_line[:80]
                    elif payload_type == "reasoning":
                        summary = payload.get("summary")
                        if summary:
                            parts = []
                            for item in summary:
                                if not isinstance(item, dict):
                                    continue
                                if item.get("type") == "summary_text":
                                    txt = item.get("text", "")
                                    if txt:
                                        parts.append(txt)
                                elif "text" in item:
                                    txt = item.get("text", "")
                                    if isinstance(txt, str) and txt:
                                        parts.append(txt)
                            text = "\n".join(parts).strip()
                            if text:
                                messages.append({
                                    "ts_ms": ts_ms,
                                    "role": "assistant",
                                    "kind": "reasoning_summary",
                                    "text": text,
                                })
                                add_search(text)
                    elif payload_type in ("function_call", "custom_tool_call"):
                        name = payload.get("name") or "tool"
                        call_id = payload.get("call_id")
                        if name == "update_plan":
                            if call_id:
                                tool_names[call_id] = str(name)
                            continue
                        raw_input = payload.get("arguments") if payload_type == "function_call" else payload.get("input")
                        if call_id:
                            tool_names[call_id] = str(name)
                        text = _codex_format_tool_use(name, call_id=call_id, raw_input=raw_input, is_custom=(payload_type == "custom_tool_call"))
                        if text:
                            messages.append({
                                "ts_ms": ts_ms,
                                "role": "tool",
                                "kind": "tool_use",
                                "text": text,
                                "tool_summary": _codex_summarize_tool_use(name, raw_input, is_custom=(payload_type == "custom_tool_call")),
                            })
                            add_search(text)
                    elif payload_type in ("function_call_output", "custom_tool_call_output"):
                        call_id = payload.get("call_id")
                        name = tool_names.get(call_id)
                        if name == "update_plan":
                            continue
                        raw_output = payload.get("output")
                        text = _codex_format_tool_result(name, call_id=call_id, raw_output=raw_output)
                        if text:
                            messages.append({
                                "ts_ms": ts_ms,
                                "role": "tool",
                                "kind": "tool_result",
                                "text": text,
                                "tool_summary": _codex_summarize_tool_result(name, raw_output=raw_output),
                            })
                            add_search(text)
                    else:
                        add_raw_message(messages, ts_ms, "other", obj, reason=f"response_item:{payload_type or 'unknown'}")
                elif obj_type == "event_msg":
                    payload = obj.get("payload", {})
                    if payload.get("type") == "agent_reasoning":
                        text = payload.get("text", "")
                        if isinstance(text, str) and text:
                            messages.append({
                                "ts_ms": ts_ms,
                                "role": "assistant",
                                "kind": "agent_reasoning",
                                "text": text,
                            })
                            add_search(text)
                    else:
                        add_raw_message(messages, ts_ms, "other", obj, reason=f"event_msg:{payload.get('type') or 'unknown'}")
                else:
                    add_raw_message(messages, ts_ms, "other", obj, reason=f"type:{obj_type or 'unknown'}")
    except FileNotFoundError:
        return None

    if not session_id:
        session_id = f"file-{path.stem}"

    if start_ts_ms is None:
        start_ts_ms = end_ts_ms or 0
    if end_ts_ms is None:
        end_ts_ms = start_ts_ms

    if not title:
        title = f"Session {session_id[:8]}"

    search_blob = "\n".join(search_parts)

    return {
        "id": session_id,
        "file_path": str(path),
        "start_ts_ms": int(start_ts_ms),
        "end_ts_ms": int(end_ts_ms),
        "cwd": cwd,
        "title": title,
        "message_count": message_count,
        "messages": messages,
        "search_blob": search_blob,
    }


def _claude_extract_text_item(item):
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type == "text":
        text = item.get("text")
        return text if isinstance(text, str) and text else None
    if "text" in item and isinstance(item["text"], str) and item["text"]:
        return item["text"]
    return None


def _claude_format_tool_use(item):
    name = item.get("name") or "tool"
    tool_id = item.get("id")
    tool_input = item.get("input")
    lines = [f"Tool use: {name}"]
    if tool_id:
        lines.append(f"Tool ID: {tool_id}")
    if isinstance(tool_input, dict):
        desc = tool_input.get("description")
        if isinstance(desc, str) and desc.strip():
            lines.append(f"Description: {desc.strip()}")

        tool_name = str(name or "").strip()
        tool_key = tool_name.lower()

        if "command" in tool_input and isinstance(tool_input["command"], str):
            lines.append("Command:")
            lines.append(f"```bash\n{tool_input['command']}\n```")
        elif "file_path" in tool_input and isinstance(tool_input["file_path"], str):
            lines.append(f"File: {tool_input['file_path']}")
        elif tool_key == "grep":
            pattern = tool_input.get("pattern")
            path = tool_input.get("path")
            output_mode = tool_input.get("output_mode")
            head_limit = tool_input.get("head_limit")
            if isinstance(pattern, str) and pattern:
                lines.append(f"Pattern: `{pattern}`")
            if isinstance(path, str) and path:
                lines.append(f"Path: `{path}`")
            if isinstance(output_mode, str) and output_mode:
                lines.append(f"Mode: `{output_mode}`")
            if isinstance(head_limit, int):
                lines.append(f"Limit: `{head_limit}`")
        elif tool_key == "glob":
            pattern = tool_input.get("pattern")
            path = tool_input.get("path")
            if isinstance(pattern, str) and pattern:
                lines.append(f"Pattern: `{pattern}`")
            if isinstance(path, str) and path:
                lines.append(f"Path: `{path}`")
        elif tool_key == "askuserquestion":
            questions = tool_input.get("questions")
            if isinstance(questions, list) and questions:
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    header = q.get("header")
                    question = q.get("question")
                    if isinstance(header, str) and header.strip():
                        lines.append(f"Question ({header.strip()}):")
                    else:
                        lines.append("Question:")
                    if isinstance(question, str) and question.strip():
                        lines.append(question.strip())
                    options = q.get("options")
                    if isinstance(options, list) and options:
                        lines.append("Options:")
                        for opt in options:
                            if not isinstance(opt, dict):
                                continue
                            label = opt.get("label")
                            desc = opt.get("description")
                            if isinstance(label, str) and label.strip():
                                if isinstance(desc, str) and desc.strip():
                                    lines.append(f"- {label.strip()} — {desc.strip()}")
                                else:
                                    lines.append(f"- {label.strip()}")
                    multi = q.get("multiSelect")
                    if isinstance(multi, bool):
                        lines.append(f"Multi-select: `{str(multi).lower()}`")
        else:
            # Keep other tool inputs visible but compact.
            other = {k: v for k, v in tool_input.items() if k not in ("description", "command")}
            if other:
                lines.append("Input:")
                for k, v in other.items():
                    if isinstance(v, str):
                        value = v.strip()
                    else:
                        value = json.dumps(v, ensure_ascii=False)
                    if value:
                        lines.append(f"- {k}: {value}")
    elif tool_input is not None:
        lines.append("Input:")
        lines.append(f"```json\n{json.dumps(tool_input, ensure_ascii=False, indent=2)}\n```")
    return "\n".join(lines).strip()


def _claude_format_tool_result(tool_result_item, tool_use_result=None):
    tool_use_id = None
    is_error = None
    content = None
    if isinstance(tool_result_item, dict):
        tool_use_id = tool_result_item.get("tool_use_id")
        is_error = tool_result_item.get("is_error")
        content = tool_result_item.get("content")

    lines = ["Tool result:"]
    if tool_use_id:
        lines.append(f"Tool use ID: {tool_use_id}")
    if is_error is True:
        lines.append("Status: error")
    elif is_error is False:
        lines.append("Status: ok")

    stdout = stderr = None
    if isinstance(tool_use_result, dict):
        stdout = tool_use_result.get("stdout")
        stderr = tool_use_result.get("stderr")

    if isinstance(content, str) and content.strip():
        lines.append("Output:")
        lines.append(f"````\n{content}\n````")
    elif isinstance(stdout, str) or isinstance(stderr, str):
        combined = ""
        if isinstance(stdout, str) and stdout:
            combined += stdout
        if isinstance(stderr, str) and stderr:
            if combined and not combined.endswith("\n"):
                combined += "\n"
            combined += stderr
        lines.append("Output:")
        lines.append(f"````\n{combined}\n````")
    elif content is not None:
        lines.append("Output:")
        lines.append(f"````\n{json.dumps(content, ensure_ascii=False, indent=2)}\n````")

    return "\n".join(lines).strip()


def parse_claude_session_file(path: Path):
    session_id = None
    start_ts_ms = None
    end_ts_ms = None
    cwd = None
    title = None
    message_count = 0
    messages = []
    search_parts = []
    search_len = 0

    def add_search(text):
        nonlocal search_len
        if not text:
            return
        if search_len >= MAX_SEARCH_CHARS:
            return
        remaining = MAX_SEARCH_CHARS - search_len
        if len(text) > remaining:
            text = text[:remaining]
        search_parts.append(text)
        search_len += len(text)

    def add_message(ts_ms, role, kind, text, count_for_stats=False, tool_summary=None):
        nonlocal message_count, title
        if not text:
            return
        msg = {
            "ts_ms": ts_ms,
            "role": role,
            "kind": kind,
            "text": text,
        }
        if isinstance(tool_summary, dict):
            msg["tool_summary"] = tool_summary
        messages.append(msg)
        add_search(text)
        if count_for_stats:
            message_count += 1
            if title is None and role == "user":
                first_line = text.strip().splitlines()[0] if text.strip() else ""
                if first_line and first_line.strip().lower() != "warmup":
                    title = first_line[:80]

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    add_message(start_ts_ms or end_ts_ms or 0, "other", "raw_json:malformed_line", f"```\n{line.rstrip()}\n```", count_for_stats=False)
                    continue

                if not session_id and isinstance(obj, dict) and isinstance(obj.get("sessionId"), str):
                    session_id = obj.get("sessionId")

                ts_ms = parse_ts(obj.get("timestamp")) if isinstance(obj, dict) else None
                if ts_ms is not None:
                    if start_ts_ms is None or ts_ms < start_ts_ms:
                        start_ts_ms = ts_ms
                    if end_ts_ms is None or ts_ms > end_ts_ms:
                        end_ts_ms = ts_ms

                if isinstance(obj, dict) and not cwd and isinstance(obj.get("cwd"), str) and obj.get("cwd"):
                    cwd = obj.get("cwd")

                if not isinstance(obj, dict):
                    continue

                obj_type = obj.get("type")
                if obj_type == "summary":
                    summary = obj.get("summary")
                    if isinstance(summary, str) and summary.strip() and not title:
                        title = summary.strip()[:80]
                    continue
                if obj_type == "file-history-snapshot":
                    continue

                msg = obj.get("message")
                if not isinstance(msg, dict):
                    add_raw_message(messages, ts_ms, "other", obj, reason=f"type:{obj_type or 'missing_message'}")
                    continue

                role = msg.get("role") or obj_type
                content = msg.get("content")

                if role == "user":
                    tool_use_result = obj.get("toolUseResult") if isinstance(obj.get("toolUseResult"), dict) else None
                    if isinstance(content, str):
                        text = content.strip()
                        add_message(ts_ms, "user", "message", text, count_for_stats=True)
                    elif isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            item_type = item.get("type")
                            if item_type == "tool_result":
                                text = _claude_format_tool_result(item, tool_use_result=tool_use_result)
                                add_message(ts_ms, "tool", "tool_result", text, count_for_stats=False, tool_summary=_claude_summarize_tool_result(item, tool_use_result=tool_use_result))
                                continue
                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "user", "message", text.strip(), count_for_stats=True)
                            else:
                                add_raw_message(messages, ts_ms, "other", item, reason=f"claude_user_item:{item_type or 'unknown'}")
                    continue

                if role == "assistant":
                    if isinstance(content, str):
                        add_message(ts_ms, "assistant", "message", content.strip(), count_for_stats=True)
                    elif isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            item_type = item.get("type")
                            if item_type == "text":
                                text = item.get("text")
                                if isinstance(text, str) and text.strip():
                                    add_message(ts_ms, "assistant", "message", text.strip(), count_for_stats=True)
                                continue
                            if item_type == "thinking":
                                thinking = item.get("thinking")
                                if isinstance(thinking, str) and thinking.strip():
                                    # Hide by default via the "other" role filter.
                                    add_message(ts_ms, "other", "thinking", thinking.strip(), count_for_stats=False)
                                continue
                            if item_type == "tool_use":
                                text = _claude_format_tool_use(item)
                                add_message(ts_ms, "tool", "tool_use", text, count_for_stats=False, tool_summary=_claude_summarize_tool_use(item))
                                continue

                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "assistant", "message", text.strip(), count_for_stats=True)
                            else:
                                add_raw_message(messages, ts_ms, "other", item, reason=f"claude_assistant_item:{item_type or 'unknown'}")
                    continue
                add_raw_message(messages, ts_ms, role or "other", obj, reason=f"claude_role:{role or 'unknown'}")
    except FileNotFoundError:
        return None

    if not session_id:
        session_id = f"file-{path.stem}"

    if start_ts_ms is None:
        start_ts_ms = end_ts_ms or 0
    if end_ts_ms is None:
        end_ts_ms = start_ts_ms

    if not title:
        title = f"Session {session_id[:8]}"

    search_blob = "\n".join(search_parts)

    return {
        "id": session_id,
        "file_path": str(path),
        "start_ts_ms": int(start_ts_ms),
        "end_ts_ms": int(end_ts_ms),
        "cwd": cwd,
        "title": title,
        "message_count": message_count,
        "messages": messages,
        "search_blob": search_blob,
    }


def _openclaw_format_tool_use(item):
    if not isinstance(item, dict):
        return None
    name = item.get("name") or "tool"
    call_id = item.get("id")
    arguments = item.get("arguments")
    if arguments is None:
        raw_input = None
    elif isinstance(arguments, str):
        raw_input = arguments
    else:
        raw_input = json.dumps(arguments, ensure_ascii=False)
    return _codex_format_tool_use(name, call_id=call_id, raw_input=raw_input)


def _openclaw_format_tool_result(message):
    if not isinstance(message, dict):
        return None

    tool_name = message.get("toolName")
    tool_call_id = message.get("toolCallId")
    is_error = message.get("isError")
    details = message.get("details") if isinstance(message.get("details"), dict) else None
    content = message.get("content")

    header = f"Tool result: {tool_name}" if tool_name else "Tool result:"
    lines = [header]
    if tool_call_id:
        lines.append(f"Tool call ID: {tool_call_id}")

    status = None
    exit_code = None
    duration_ms = None
    if is_error is True:
        status = "error"
    elif is_error is False:
        status = "ok"

    if details:
        detail_status = str(details.get("status") or "").strip().lower()
        if detail_status in ("completed", "ok", "success") and status is None:
            status = "ok"
        elif detail_status in ("error", "failed", "failure") and status is None:
            status = "error"
        if isinstance(details.get("exitCode"), (int, float)):
            exit_code = int(details["exitCode"])
        if isinstance(details.get("durationMs"), (int, float)):
            duration_ms = int(details["durationMs"])

    if status:
        lines.append(f"Status: {status}")
    if exit_code is not None:
        lines.append(f"Exit code: {exit_code}")
    if duration_ms is not None:
        lines.append(f"Wall time: {duration_ms}ms")

    text = ""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = extract_text(content).strip()

    if text:
        lines.append("Output:")
        lines.append(f"````\n{text}\n````")
    elif details:
        lines.append("Output:")
        lines.append(f"````\n{json.dumps(details, ensure_ascii=False, indent=2)}\n````")

    return "\n".join(lines).strip()


def _openclaw_summarize_tool_use(item):
    if not isinstance(item, dict):
        return _empty_tool_summary("tool")
    name = item.get("name") or "tool"
    arguments = item.get("arguments")
    if arguments is None:
        raw_input = None
    elif isinstance(arguments, str):
        raw_input = arguments
    else:
        raw_input = json.dumps(arguments, ensure_ascii=False)
    return _codex_summarize_tool_use(name, raw_input)


def _openclaw_summarize_tool_result(message):
    s = _empty_tool_summary("tool")
    if not isinstance(message, dict):
        return s
    tool_name = message.get("toolName")
    if isinstance(tool_name, str) and tool_name.strip():
        s["name"] = tool_name.strip()[:80]
        s["category"] = _classify_tool_category(tool_name)
    is_error = message.get("isError")
    details = message.get("details") if isinstance(message.get("details"), dict) else None
    content = message.get("content")
    status = None
    exit_code = None
    if is_error is True:
        status = "error"
    elif is_error is False:
        status = "ok"
    if details:
        detail_status = str(details.get("status") or "").strip().lower()
        if detail_status in ("completed", "ok", "success") and status is None:
            status = "ok"
        elif detail_status in ("error", "failed", "failure") and status is None:
            status = "error"
        if isinstance(details.get("exitCode"), (int, float)):
            exit_code = int(details["exitCode"])
    if exit_code is not None:
        s["exit_code"] = exit_code
        if status is None:
            status = "ok" if exit_code == 0 else "error"
    if status == "error":
        s["exit_status"] = "error"
        s["is_error"] = True
    elif status == "ok":
        s["exit_status"] = "ok"
        s["is_error"] = False
    body = None
    if isinstance(content, str):
        body = content.strip()
    elif isinstance(content, list):
        body = extract_text(content).strip()
    elif details:
        body = json.dumps(details, ensure_ascii=False)
    if body:
        s["output_preview"] = _truncate_str(body, 200)
    return s


def parse_openclaw_session_file(path: Path):
    session_id = None
    start_ts_ms = None
    end_ts_ms = None
    cwd = None
    title = None
    message_count = 0
    messages = []
    search_parts = []
    search_len = 0

    def add_search(text):
        nonlocal search_len
        if not text:
            return
        if search_len >= MAX_SEARCH_CHARS:
            return
        remaining = MAX_SEARCH_CHARS - search_len
        if len(text) > remaining:
            text = text[:remaining]
        search_parts.append(text)
        search_len += len(text)

    def add_message(ts_ms, role, kind, text, count_for_stats=False, tool_summary=None):
        nonlocal message_count, title
        if not text:
            return
        cleaned = text.strip()
        if not cleaned:
            return
        msg = {
            "ts_ms": ts_ms,
            "role": role,
            "kind": kind,
            "text": cleaned,
        }
        if isinstance(tool_summary, dict):
            msg["tool_summary"] = tool_summary
        messages.append(msg)
        add_search(cleaned)
        if count_for_stats:
            message_count += 1
            if title is None and role == "user":
                first_line = cleaned.splitlines()[0] if cleaned else ""
                if first_line:
                    title = first_line[:80]

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    add_message(start_ts_ms or end_ts_ms or 0, "other", "raw_json:malformed_line", f"```\n{line.rstrip()}\n```", count_for_stats=False)
                    continue

                if not isinstance(obj, dict):
                    add_raw_message(messages, start_ts_ms or end_ts_ms or 0, "other", obj, reason="openclaw_non_object")
                    continue

                ts_ms = parse_ts(obj.get("timestamp"))
                if ts_ms is not None:
                    if start_ts_ms is None or ts_ms < start_ts_ms:
                        start_ts_ms = ts_ms
                    if end_ts_ms is None or ts_ms > end_ts_ms:
                        end_ts_ms = ts_ms

                obj_type = obj.get("type")
                if obj_type == "session":
                    session_id = obj.get("id") or session_id
                    if isinstance(obj.get("cwd"), str) and obj.get("cwd"):
                        cwd = obj["cwd"]
                    continue

                if obj_type != "message":
                    add_raw_message(messages, ts_ms, "other", obj, reason=f"openclaw_type:{obj_type or 'unknown'}")
                    continue

                message = obj.get("message")
                if not isinstance(message, dict):
                    add_raw_message(messages, ts_ms, "other", obj, reason="openclaw_missing_message")
                    continue

                role = message.get("role") or "unknown"
                content = message.get("content")

                if role == "user":
                    if isinstance(content, str):
                        text = content.strip()
                        if text.startswith("A new session was started via /new or /reset."):
                            add_message(ts_ms, "system", "context", text, count_for_stats=False)
                        else:
                            add_message(ts_ms, "user", "message", text, count_for_stats=True)
                    elif isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            text = _claude_extract_text_item(item)
                            if not text:
                                add_raw_message(messages, ts_ms, "other", item, reason=f"openclaw_user_item:{item.get('type') or 'unknown'}")
                                continue
                            if text.startswith("A new session was started via /new or /reset."):
                                add_message(ts_ms, "system", "context", text, count_for_stats=False)
                            else:
                                add_message(ts_ms, "user", "message", text, count_for_stats=True)
                    continue

                if role == "assistant":
                    error_message = message.get("errorMessage")
                    if isinstance(error_message, str) and error_message.strip():
                        add_message(ts_ms, "assistant", "message", f"[error] {error_message.strip()}", count_for_stats=False)
                    if isinstance(content, str):
                        add_message(ts_ms, "assistant", "message", content, count_for_stats=True)
                    elif isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            item_type = item.get("type")
                            if item_type == "text":
                                add_message(ts_ms, "assistant", "message", item.get("text"), count_for_stats=True)
                                continue
                            if item_type == "thinking":
                                add_message(ts_ms, "other", "thinking", item.get("thinking"), count_for_stats=False)
                                continue
                            if item_type in ("toolCall", "tool_use"):
                                add_message(ts_ms, "tool", "tool_use", _openclaw_format_tool_use(item), count_for_stats=False, tool_summary=_openclaw_summarize_tool_use(item))
                                continue
                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "assistant", "message", text, count_for_stats=True)
                            else:
                                add_raw_message(messages, ts_ms, "other", item, reason=f"openclaw_assistant_item:{item_type or 'unknown'}")
                    continue

                if role in ("toolResult", "tool_result", "tool"):
                    add_message(ts_ms, "tool", "tool_result", _openclaw_format_tool_result(message), count_for_stats=False, tool_summary=_openclaw_summarize_tool_result(message))
                    continue

                if isinstance(content, str):
                    add_message(ts_ms, role, "message", content, count_for_stats=False)
                elif isinstance(content, list):
                    text = extract_text(content)
                    if text:
                        add_message(ts_ms, role, "message", text, count_for_stats=False)
                    else:
                        add_raw_message(messages, ts_ms, role, message, reason=f"openclaw_role:{role or 'unknown'}")
                else:
                    add_raw_message(messages, ts_ms, role, message, reason=f"openclaw_role:{role or 'unknown'}")
    except FileNotFoundError:
        return None

    if not session_id:
        session_id = f"file-{path.stem}"

    if start_ts_ms is None:
        start_ts_ms = end_ts_ms or 0
    if end_ts_ms is None:
        end_ts_ms = start_ts_ms

    if not title:
        title = f"Session {session_id[:8]}"

    search_blob = "\n".join(search_parts)

    return {
        "id": session_id,
        "file_path": str(path),
        "start_ts_ms": int(start_ts_ms),
        "end_ts_ms": int(end_ts_ms),
        "cwd": cwd,
        "title": title,
        "message_count": message_count,
        "messages": messages,
        "search_blob": search_blob,
    }


class Indexer:
    def __init__(
        self,
        sessions_dir: Path,
        data_dir: Path,
        source: str,
        db_filename: str = "index.sqlite",
        scan_interval: int = 5,
        parse_file_fn=None,
        file_filter_fn=None,
        parser_version: int = 1,
        recall_db_path: Path | None = None,
    ):
        self.sessions_dir = sessions_dir
        self.source = str(source or "").strip()
        self.db_path = data_dir / db_filename
        self._parse_file_fn = parse_file_fn or parse_codex_session_file
        self._file_filter_fn = file_filter_fn or (lambda p: True)
        self.parser_version = int(parser_version)
        self.recall_titles = RecallTitleStore(recall_db_path, self.source) if recall_db_path else None
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.last_scan = 0
        self.scan_interval = max(1, int(scan_interval))
        self._local_title_backfill_done = False
        self._session_preview_cache = OrderedDict()
        self._init_db()

    def _clear_session_preview_cache(self, session_id=None):
        if session_id is None:
            self._session_preview_cache.clear()
            return
        self._session_preview_cache.pop(str(session_id), None)

    def _remember_session_preview_cache(self, session_id, payload):
        key = str(session_id or "")
        if not key:
            return
        self._session_preview_cache[key] = payload
        self._session_preview_cache.move_to_end(key)
        while len(self._session_preview_cache) > SESSION_PREVIEW_CACHE_SIZE:
            self._session_preview_cache.popitem(last=False)

    def _init_db(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    file_path TEXT UNIQUE,
                    start_ts_ms INTEGER,
                    end_ts_ms INTEGER,
                    cwd TEXT,
                    title TEXT,
                    message_count INTEGER,
                    mtime REAL,
                    search_blob TEXT,
                    parser_version INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    ts_ms INTEGER,
                    role TEXT,
                    kind TEXT,
                    text TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, ts_ms)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_start_ts ON sessions(start_ts_ms)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_end_ts ON sessions(end_ts_ms)")
            try:
                cur.execute("ALTER TABLE sessions ADD COLUMN parser_version INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            patch_db_for_audit(self.conn)
            try:
                cur.execute("ALTER TABLE messages ADD COLUMN tool_summary_json TEXT")
            except sqlite3.OperationalError:
                pass
            self.conn.commit()

    def maybe_update_index(self, max_age_seconds=None):
        if max_age_seconds is None:
            max_age_seconds = self.scan_interval
        now = time.time()
        if now - self.last_scan < max_age_seconds:
            self.backfill_local_title_overrides()
            return
        self.scan_sessions()
        self.last_scan = now
        self.backfill_local_title_overrides()

    def scan_sessions(self):
        if not self.sessions_dir.exists():
            return
        session_files = [p for p in self.sessions_dir.rglob("*.jsonl") if self._file_filter_fn(p)]
        with self.lock:
            existing_rows = self.conn.execute(
                "SELECT id, file_path, mtime, parser_version, title, pinned, audit_version FROM sessions"
            ).fetchall()
        existing_by_path = {str(row["file_path"]): row for row in existing_rows}

        updates = []
        for path in session_files:
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue

            row = existing_by_path.get(str(path))
            if (
                row
                and row["mtime"] is not None
                and row["mtime"] >= mtime
                and row["parser_version"] == self.parser_version
                and row["audit_version"] == AUDIT_VERSION
            ):
                continue

            session = self._parse_file_fn(path)
            if session is None:
                continue

            if self.recall_titles:
                custom_title = self.recall_titles.get_custom_title(session["id"])
                if (
                    not custom_title
                    and row
                    and row["title"]
                    and str(row["title"]).strip()
                    and str(row["title"]).strip() != str(session["title"]).strip()
                ):
                    custom_title = str(row["title"]).strip()
                    self.recall_titles.set_custom_title(session["id"], custom_title)
                if custom_title:
                    session["title"] = custom_title

            updates.append((row, session, mtime))

        if not updates:
            return

        with self.lock:
            self._clear_session_preview_cache()
            for row, session, mtime in updates:
                if row and row["id"] != session["id"]:
                    self.conn.execute("DELETE FROM messages WHERE session_id = ?", (row["id"],))
                    self.conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))

                self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session["id"],))
                pinned = int(row["pinned"] or 0) if row else 0
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["id"],
                        session["file_path"],
                        session["start_ts_ms"],
                        session["end_ts_ms"],
                        session["cwd"],
                        session["title"],
                        session["message_count"],
                        mtime,
                        session["search_blob"],
                        self.parser_version,
                        pinned,
                    ),
                )

                messages = session["messages"]
                if messages:
                    self.conn.executemany(
                        """
                        INSERT INTO messages (session_id, ts_ms, role, kind, text, tool_summary_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                session["id"],
                                int(m["ts_ms"] or session["start_ts_ms"]),
                                m["role"],
                                m["kind"],
                                m["text"],
                                json.dumps(m["tool_summary"]) if isinstance(m.get("tool_summary"), dict) else None,
                            )
                            for m in messages
                        ],
                    )

                audit_payload = build_audit_for_file(Path(session["file_path"]), self.source, session_id_hint=session["id"])
                if audit_payload is not None:
                    fields = serialize_audit_fields(audit_payload)
                    fields["audit_updated_at"] = int(time.time() * 1000)
                    self.conn.execute(
                        """
                        UPDATE sessions
                           SET files_touched_json = ?,
                               tool_summary_json = ?,
                               command_intents_json = ?,
                               remote_context_json = ?,
                               outcome_signal = ?,
                               value_score = ?,
                               friction_score = ?,
                               action_density = ?,
                               audit_status = ?,
                               audit_updated_at = ?,
                               audit_version = ?
                         WHERE id = ?
                        """,
                        (
                            fields["files_touched_json"],
                            fields["tool_summary_json"],
                            fields["command_intents_json"],
                            fields["remote_context_json"],
                            fields["outcome_signal"],
                            fields["value_score"],
                            fields["friction_score"],
                            fields["action_density"],
                            fields["audit_status"],
                            fields["audit_updated_at"],
                            fields["audit_version"],
                            session["id"],
                        ),
                    )

            self.conn.commit()

    def backfill_local_title_overrides(self):
        if self._local_title_backfill_done or not self.recall_titles:
            return

        with self.lock:
            rows = self.conn.execute(
                "SELECT id, file_path, title FROM sessions WHERE title IS NOT NULL AND title <> ''"
            ).fetchall()

        for row in rows:
            session_id = row["id"]
            file_path = row["file_path"]
            stored_title = str(row["title"] or "").strip()
            if not session_id or not file_path or not stored_title:
                continue
            if self.recall_titles.get_custom_title(session_id):
                continue
            try:
                parsed = self._parse_file_fn(Path(file_path))
            except Exception:
                continue
            if not parsed:
                continue
            parsed_title = str(parsed.get("title") or "").strip()
            if parsed_title and parsed_title != stored_title:
                self.recall_titles.set_custom_title(session_id, stored_title)

        self._local_title_backfill_done = True

    def query_sessions(self, q=None, start_ms=None, end_ms=None, limit=DEFAULT_LIMIT, cwd=None, sort=None, file_path=None):
        terms = []
        if q:
            terms = [t for t in q.split() if t]

        sort_key = str(sort or "start").strip().lower()
        if sort_key == "value":
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, value_score DESC, end_ts_ms DESC"
        elif sort_key == "friction":
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, friction_score DESC, end_ts_ms DESC"
        elif sort_key in ("last", "end", "updated", "update"):
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, end_ts_ms DESC, start_ts_ms DESC"
        else:
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, start_ts_ms DESC, end_ts_ms DESC"

        sql = (
            "SELECT id, start_ts_ms, end_ts_ms, title, message_count, cwd, pinned, "
            "files_touched_json, tool_summary_json, command_intents_json, remote_context_json, "
            "outcome_signal, value_score, friction_score, action_density "
            "FROM sessions WHERE 1=1"
        )
        args = []
        if start_ms is not None:
            sql += " AND start_ts_ms >= ?"
            args.append(int(start_ms))
        if end_ms is not None:
            sql += " AND start_ts_ms <= ?"
            args.append(int(end_ms))
        if cwd:
            sql += " AND cwd = ?"
            args.append(cwd)
        if file_path:
            sql += " AND files_touched_json LIKE ? ESCAPE '\\'"
            args.append("%" + _escape_sql_like(file_path) + "%")
        for term in terms:
            sql += " AND (search_blob LIKE ? OR title LIKE ? OR cwd LIKE ?)"
            like = f"%{term}%"
            args.extend([like, like, like])
        sql += order_clause + " LIMIT ?"
        args.append(int(limit))

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        items = [dict(row) for row in rows]
        if file_path:
            items = [it for it in items if _match_files_touched(it.get("files_touched_json"), file_path)]
        for item in items:
            item.update(deserialize_audit_summary(item))
            _strip_audit_raw_json(item)
        return items

    def list_sessions_page(self, q=None, start_ms=None, end_ms=None, limit=DEFAULT_PAGE_LIMIT, offset=0, cwd=None, sort=None, file_path=None):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        terms = [t for t in str(q or "").split() if t]

        sort_key = str(sort or "start").strip().lower()
        if sort_key == "value":
            order_clause = " ORDER BY value_score DESC, end_ts_ms DESC"
        elif sort_key == "friction":
            order_clause = " ORDER BY friction_score DESC, end_ts_ms DESC"
        elif sort_key in ("last", "end", "updated", "update"):
            order_clause = " ORDER BY end_ts_ms DESC, start_ts_ms DESC"
        else:
            order_clause = " ORDER BY start_ts_ms DESC, end_ts_ms DESC"

        where_sql = " WHERE 1=1"
        args = []
        if start_ms is not None:
            where_sql += " AND start_ts_ms >= ?"
            args.append(int(start_ms))
        if end_ms is not None:
            where_sql += " AND start_ts_ms <= ?"
            args.append(int(end_ms))
        if cwd:
            where_sql += " AND cwd = ?"
            args.append(cwd)
        if file_path:
            where_sql += " AND files_touched_json LIKE ? ESCAPE '\\'"
            args.append("%" + _escape_sql_like(file_path) + "%")
        for term in terms:
            where_sql += " AND (search_blob LIKE ? OR title LIKE ? OR cwd LIKE ?)"
            like = f"%{term}%"
            args.extend([like, like, like])

        select_sql = (
            "SELECT id, start_ts_ms, end_ts_ms, title, message_count, cwd, pinned, "
            "files_touched_json, tool_summary_json, command_intents_json, remote_context_json, "
            "outcome_signal, value_score, friction_score, action_density FROM sessions"
        )
        pinned_rows = []
        with self.lock:
            if clean_offset == 0:
                pinned_rows = self.conn.execute(
                    f"{select_sql}{where_sql} AND COALESCE(pinned,0) = 1{order_clause}",
                    args,
                ).fetchall()

            rows = self.conn.execute(
                f"{select_sql}{where_sql} AND COALESCE(pinned,0) = 0{order_clause} LIMIT ? OFFSET ?",
                [*args, clean_limit + 1, clean_offset],
            ).fetchall()

        def _with_audit(row):
            item = dict(row)
            item.update(deserialize_audit_summary(item))
            return _strip_audit_raw_json(item)

        if file_path:
            matched_pinned = [r for r in pinned_rows if _match_files_touched(r["files_touched_json"], file_path)]
            matched_unpinned = [r for r in rows if _match_files_touched(r["files_touched_json"], file_path)]
            unpinned_items = [_with_audit(r) for r in matched_unpinned[:clean_limit]]
            items = [_with_audit(r) for r in matched_pinned] + unpinned_items
            has_more = len(matched_unpinned) > clean_limit
        else:
            unpinned_items = [_with_audit(row) for row in rows[:clean_limit]]
            items = [_with_audit(row) for row in pinned_rows] + unpinned_items
            has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(unpinned_items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def query_projects(self, q=None, limit=DEFAULT_LIMIT):
        sql = (
            "SELECT cwd AS project, COUNT(*) AS session_count, MAX(start_ts_ms) AS last_ts_ms "
            "FROM sessions WHERE cwd IS NOT NULL AND cwd <> ''"
        )
        args = []
        if q:
            sql += " AND cwd LIKE ?"
            args.append(f"%{q}%")
        sql += " GROUP BY cwd ORDER BY last_ts_ms DESC LIMIT ?"
        args.append(int(limit))
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def list_projects_page(self, q=None, limit=DEFAULT_PAGE_LIMIT, offset=0):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        sql = (
            "SELECT cwd AS project, COUNT(*) AS session_count, MAX(start_ts_ms) AS last_ts_ms "
            "FROM sessions WHERE cwd IS NOT NULL AND cwd <> ''"
        )
        args = []
        if q:
            sql += " AND cwd LIKE ?"
            args.append(f"%{q}%")
        sql += " GROUP BY cwd ORDER BY last_ts_ms DESC LIMIT ? OFFSET ?"
        args.extend([clean_limit + 1, clean_offset])
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        items = [dict(row) for row in rows[:clean_limit]]
        has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def _serialize_message_row(self, row, message_index, include_full_text=False):
        text, char_count, is_truncated = normalize_message_payload(
            row["text"],
            include_full_text=include_full_text,
            char_count=row["char_count"] if "char_count" in row.keys() else None,
            is_truncated=row["is_truncated"] if "is_truncated" in row.keys() else None,
        )
        tool_summary = None
        raw_ts = row["tool_summary_json"] if "tool_summary_json" in row.keys() else None
        if raw_ts:
            try:
                tool_summary = json.loads(raw_ts)
            except (ValueError, TypeError):
                tool_summary = None
        result = {
            "message_index": int(message_index),
            "ts_ms": row["ts_ms"],
            "role": row["role"],
            "kind": row["kind"],
            "text": text,
            "char_count": char_count,
            "is_truncated": bool(is_truncated),
        }
        if tool_summary is not None:
            result["tool_summary"] = tool_summary
        return result

    def get_session_metadata(self, session_id):
        with self.lock:
            session = self.conn.execute(
                "SELECT id, start_ts_ms, end_ts_ms, title, message_count, cwd, pinned FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not session:
                return None
            payload = dict(session)
            total_row = self.conn.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            payload["message_total"] = int(total_row["total"] or 0)
            return payload

    def get_session_messages_page(self, session_id, offset=0, limit=DEFAULT_LIMIT):
        clean_limit, clean_offset = normalize_page_args(limit, offset, default_limit=DEFAULT_LIMIT, max_limit=DEFAULT_LIMIT)
        with self.lock:
            session = self.conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not session:
                return None
            total_row = self.conn.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            total = int(total_row["total"] or 0)
            messages = self.conn.execute(
                """
                SELECT
                    ts_ms,
                    role,
                    kind,
                    CASE
                        WHEN LENGTH(text) > ? THEN SUBSTR(text, 1, ?)
                        ELSE text
                    END AS text,
                    LENGTH(text) AS char_count,
                    CASE
                        WHEN LENGTH(text) > ? THEN 1
                        ELSE 0
                    END AS is_truncated,
                    tool_summary_json
                FROM messages
                WHERE session_id = ?
                ORDER BY ts_ms ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    MESSAGE_PREVIEW_FETCH_CHARS,
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    session_id,
                    clean_limit,
                    clean_offset,
                ),
            ).fetchall()
        return {
            "messages": [
                self._serialize_message_row(row, clean_offset + idx)
                for idx, row in enumerate(messages)
            ],
            "offset": clean_offset,
            "limit": clean_limit,
            "total": total,
        }

    def get_session(self, session_id, include_messages=True):
        session = self.get_session_metadata(session_id)
        if not session:
            return None
        payload = {"session": session}
        if include_messages:
            cached = self._session_preview_cache.get(str(session_id))
            if cached is not None:
                self._session_preview_cache.move_to_end(str(session_id))
                return cached
            page = self.get_session_messages_page(session_id, offset=0, limit=DEFAULT_LIMIT)
            if page is None:
                return None
            payload["messages"] = page["messages"]
            self._remember_session_preview_cache(session_id, payload)
        return payload

    def build_session_audit(self, session_id):
        # BDD: 002 §M4 — `GET /api/sessions/{id}/audit` returns full payload.
        with self.lock:
            row = self.conn.execute(
                "SELECT file_path FROM sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
        if not row or not row["file_path"]:
            return None
        file_path = Path(row["file_path"])
        if not file_path.is_file():
            return None
        payload = build_audit_for_file(file_path, self.source, session_id_hint=str(session_id))
        if payload is None:
            return None
        return payload.to_dict()

    def get_session_message(self, session_id, message_index):
        try:
            offset = int(message_index)
        except (TypeError, ValueError):
            return None
        if offset < 0:
            return None

        with self.lock:
            session = self.conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not session:
                return None
            row = self.conn.execute(
                """
                SELECT ts_ms, role, kind, text, tool_summary_json
                FROM messages
                WHERE session_id = ?
                ORDER BY ts_ms ASC, id ASC
                LIMIT 1 OFFSET ?
                """,
                (session_id, offset),
            ).fetchone()
        if not row:
            return None
        return self._serialize_message_row(row, offset, include_full_text=True)

    def search_session_messages(self, session_id, query, limit=None):
        term = str(query or "").strip()
        result = {
            "query": term,
            "match_count": 0,
            "message_match_count": 0,
            "matches": [],
        }
        if not term:
            return result

        pattern = re.compile(re.escape(term), re.IGNORECASE)

        with self.lock:
            session = self.conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not session:
                return None
            rows = self.conn.execute(
                """
                SELECT ts_ms, role, kind, text, tool_summary_json
                FROM messages
                WHERE session_id = ?
                ORDER BY ts_ms ASC, id ASC
                """,
                (session_id,),
            ).fetchall()

        try:
            clean_limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            clean_limit = None
        if clean_limit is not None and clean_limit <= 0:
            clean_limit = None

        matches = []
        total_hits = 0
        total_message_matches = 0
        for idx, row in enumerate(rows):
            text = str(row["text"] or "")
            found = list(pattern.finditer(text))
            hit_count = len(found)
            if hit_count <= 0:
                continue
            total_hits += hit_count
            total_message_matches += 1
            if clean_limit is None or len(matches) < clean_limit:
                serialized = self._serialize_message_row(row, idx)
                excerpt = build_search_excerpt_text(text, found[0].start(), found[0].end())
                matches.append({
                    "message_index": idx,
                    "ts_ms": row["ts_ms"],
                    "role": row["role"],
                    "kind": row["kind"],
                    "hit_count": hit_count,
                    "char_count": serialized["char_count"],
                    "is_truncated": serialized["is_truncated"],
                    "excerpt_text": excerpt["text"],
                    "excerpt_start": excerpt["start"],
                    "excerpt_end": excerpt["end"],
                    "excerpt_has_more_before": excerpt["has_more_before"],
                    "excerpt_has_more_after": excerpt["has_more_after"],
                })

        result["match_count"] = total_hits
        result["message_match_count"] = total_message_matches
        result["matches"] = matches
        return result

    def rename_session(self, session_id, title):
        title = str(title or "").strip()
        if not title:
            return False
        with self.lock:
            cur = self.conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
            )
            self.conn.commit()
            updated = cur.rowcount > 0

        if updated and self.recall_titles:
            self.recall_titles.set_custom_title(session_id, title)
        if updated:
            with self.lock:
                self._clear_session_preview_cache(session_id)

        return updated

    def archive_session(self, session_id, archived_dir):
        with self.lock:
            row = self.conn.execute(
                "SELECT file_path FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return False, "not_found"
            file_path = Path(row["file_path"])
            if file_path.exists():
                archived_dir = Path(archived_dir)
                archived_dir.mkdir(parents=True, exist_ok=True)
                dest = archived_dir / file_path.name
                if dest.exists():
                    dest = archived_dir / (file_path.stem + f"-{session_id[:8]}" + file_path.suffix)
                shutil.move(str(file_path), str(dest))
            self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self.conn.commit()
            self._clear_session_preview_cache(session_id)
            return True, "archived"

    def _delete_sessions_with_backup(self, rows, deleted_dir, backup_label):
        deleted_dir = Path(deleted_dir)
        backup_dir = deleted_dir / (
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{backup_label}"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)

        session_ids = []
        for row in rows:
            session_id = row["id"]
            session_ids.append(session_id)
            file_path = Path(row["file_path"])
            if not file_path.exists():
                continue
            dest = backup_dir / file_path.name
            if dest.exists():
                dest = backup_dir / (file_path.stem + f"-{session_id[:8]}" + file_path.suffix)
            shutil.move(str(file_path), str(dest))

        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            self.conn.execute(
                f"DELETE FROM messages WHERE session_id IN ({placeholders})",
                session_ids,
            )
            self.conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})",
                session_ids,
            )
            self.conn.commit()
            for session_id in session_ids:
                self._clear_session_preview_cache(session_id)
        return len(session_ids), str(backup_dir)

    def delete_project_sessions(self, project, deleted_dir):
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, file_path FROM sessions WHERE cwd = ? ORDER BY start_ts_ms DESC, id DESC",
                (project,),
            ).fetchall()
            if not rows:
                return False, "not_found", 0, None

            deleted_count, backup_dir = self._delete_sessions_with_backup(
                rows,
                deleted_dir,
                slugify_path_label(project),
            )
            return True, "deleted", deleted_count, backup_dir

    def cleanup_weak_sessions(self, deleted_dir, min_user_messages=5, project=None):
        with self.lock:
            sql = (
                "SELECT s.id, s.file_path, s.title, s.cwd, "
                "COALESCE(SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END), 0) AS user_count "
                "FROM sessions s "
                "LEFT JOIN messages m ON m.session_id = s.id "
            )
            args = []
            if project:
                sql += "WHERE s.cwd = ? "
                args.append(project)
            sql += "GROUP BY s.id, s.file_path, s.title, s.cwd ORDER BY s.start_ts_ms DESC, s.id DESC"
            rows = self.conn.execute(sql, args).fetchall()

            weak_rows = []
            for row in rows:
                user_count = int(row["user_count"] or 0)
                if user_count < int(min_user_messages):
                    weak_rows.append(row)

            if not weak_rows:
                return True, "none", 0, None

            label = "weak-sessions"
            if project:
                label = f"{slugify_path_label(project)}-weak-sessions"
            deleted_count, backup_dir = self._delete_sessions_with_backup(
                weak_rows,
                deleted_dir,
                label,
            )
            return True, "deleted", deleted_count, backup_dir

    def pin_session(self, session_id, pinned):
        with self.lock:
            cur = self.conn.execute(
                "UPDATE sessions SET pinned = ? WHERE id = ?", (1 if pinned else 0, session_id)
            )
            self.conn.commit()
            if cur.rowcount > 0:
                self._clear_session_preview_cache(session_id)
            return cur.rowcount > 0


class HermesStateIndexer:
    def __init__(self, db_path: Path):
        self.source = "hermes"
        self.db_path = Path(db_path).expanduser()
        self.conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._session_preview_cache = OrderedDict()

    def _remember_session_preview_cache(self, session_id, payload):
        key = str(session_id or "")
        if not key:
            return
        self._session_preview_cache[key] = payload
        self._session_preview_cache.move_to_end(key)
        while len(self._session_preview_cache) > SESSION_PREVIEW_CACHE_SIZE:
            self._session_preview_cache.popitem(last=False)

    def maybe_update_index(self, max_age_seconds=None):
        return

    def scan_sessions(self):
        return

    def _project_value(self):
        return "COALESCE(NULLIF(s.source, ''), '(unknown source)')"

    def _project_value_no_alias(self):
        return "COALESCE(NULLIF(source, ''), '(unknown source)')"

    def _session_title(self, row):
        title = str(row["title"] or "").strip()
        if title:
            return title
        model = str(row["model"] or "").strip() or "Hermes"
        source = str(row["source"] or "").strip() or "session"
        return f"{model} - {source} - {str(row['id'])[:8]}"

    def _serialize_session_row(self, row):
        return {
            "id": row["id"],
            "start_ts_ms": parse_ts(row["started_at"]),
            "end_ts_ms": parse_ts(row["ended_at"]),
            "title": self._session_title(row),
            "message_count": int(row["message_count"] or 0),
            "cwd": str(row["source"] or "").strip() or "(unknown source)",
            "pinned": 0,
            **_neutral_audit_summary(),
        }

    def _tool_use_text(self, row):
        raw = str(row["tool_calls"] or "").strip()
        tool_name_fallback = str(row["tool_name"] or "").strip() or "tool"
        reasoning = str(row["reasoning"] or "").strip()
        blocks = []
        calls = None
        if raw:
            try:
                calls = json.loads(raw)
            except json.JSONDecodeError:
                calls = None
        if not isinstance(calls, list):
            calls = [calls] if calls else []

        for idx, call in enumerate(calls):
            function = call.get("function") if isinstance(call, dict) else None
            name = ""
            arguments = None
            if isinstance(function, dict):
                name = str(function.get("name") or "").strip()
                arguments = function.get("arguments")
            if not name and isinstance(call, dict):
                name = str(call.get("name") or call.get("type") or "").strip()
            name = name or tool_name_fallback
            lines = [f"Tool use: {name}"]
            if idx == 0 and reasoning:
                lines.append(f"Description: {reasoning}")
            if arguments not in (None, ""):
                lines.append("Input:")
                if isinstance(arguments, str):
                    formatted = arguments
                    try:
                        parsed = json.loads(arguments)
                    except json.JSONDecodeError:
                        parsed = None
                    if parsed is not None:
                        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
                        lines.append("```json")
                        lines.append(formatted)
                        lines.append("```")
                    else:
                        lines.append(arguments)
                else:
                    lines.append("```json")
                    lines.append(json.dumps(arguments, ensure_ascii=False, indent=2))
                    lines.append("```")
            blocks.append("\n".join(lines).strip())

        if blocks:
            return "\n\n".join(blocks)
        if reasoning:
            return f"Tool use: {tool_name_fallback}\nDescription: {reasoning}"
        return f"Tool use: {tool_name_fallback}"

    def _serialize_message_row(self, row, message_index, include_full_text=False):
        role = str(row["role"] or "").strip() or "assistant"
        content = str(row["content"] or "")
        reasoning = str(row["reasoning"] or "")
        tool_calls = str(row["tool_calls"] or "").strip()
        char_count_hint = None
        is_truncated_hint = None

        if role == "tool":
            mapped_role = "tool"
            kind = "tool_result"
            text = content
            if "content_char_count" in row.keys():
                char_count_hint = row["content_char_count"]
                is_truncated_hint = row["content_is_truncated"]
        elif tool_calls:
            mapped_role = "assistant"
            kind = "tool_use"
            text = self._tool_use_text(row)
        elif content:
            mapped_role = role
            kind = "message"
            text = content
            if "content_char_count" in row.keys():
                char_count_hint = row["content_char_count"]
                is_truncated_hint = row["content_is_truncated"]
        elif reasoning:
            mapped_role = role
            kind = "reasoning_summary"
            text = reasoning
            if "reasoning_char_count" in row.keys():
                char_count_hint = row["reasoning_char_count"]
                is_truncated_hint = row["reasoning_is_truncated"]
        else:
            mapped_role = role
            kind = "message"
            text = ""

        text, char_count, is_truncated = normalize_message_payload(
            text,
            include_full_text=include_full_text,
            char_count=char_count_hint,
            is_truncated=is_truncated_hint,
        )
        return {
            "message_index": int(message_index),
            "ts_ms": parse_ts(row["timestamp"]),
            "role": mapped_role,
            "kind": kind,
            "text": text,
            "char_count": char_count,
            "is_truncated": bool(is_truncated),
        }

    def _session_lookup(self, session_id):
        return self.conn.execute(
            """
            SELECT id, source, user_id, model, started_at, ended_at, message_count, title
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()

    def list_sessions_page(self, q=None, start_ms=None, end_ms=None, limit=DEFAULT_PAGE_LIMIT, offset=0, cwd=None, sort=None):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        terms = [t for t in str(q or "").split() if t]

        sql = (
            "SELECT s.id, s.source, s.user_id, s.model, s.started_at, s.ended_at, s.message_count, s.title "
            "FROM sessions s WHERE 1=1"
        )
        args = []
        if start_ms is not None:
            sql += " AND s.started_at >= ?"
            args.append(int(start_ms) / 1000)
        if end_ms is not None:
            sql += " AND s.started_at <= ?"
            args.append(int(end_ms) / 1000)
        if cwd:
            sql += f" AND {self._project_value()} = ?"
            args.append(str(cwd))
        for term in terms:
            like = f"%{term}%"
            sql += (
                " AND ("
                "COALESCE(s.title, '') LIKE ? OR COALESCE(s.source, '') LIKE ? OR COALESCE(s.user_id, '') LIKE ? "
                "OR COALESCE(s.model, '') LIKE ? OR s.id LIKE ? "
                "OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id AND COALESCE(m.content, '') LIKE ?) "
                "OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id AND COALESCE(m.reasoning, '') LIKE ?)"
                ")"
            )
            args.extend([like, like, like, like, like, like, like])

        sort_key = str(sort or "start").strip().lower()
        if sort_key in ("last", "end", "updated", "update"):
            sql += " ORDER BY COALESCE(s.ended_at, s.started_at) DESC, s.started_at DESC"
        else:
            sql += " ORDER BY s.started_at DESC, COALESCE(s.ended_at, s.started_at) DESC"
        sql += " LIMIT ? OFFSET ?"
        args.extend([clean_limit + 1, clean_offset])

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        items = [self._serialize_session_row(row) for row in rows[:clean_limit]]
        has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def list_projects_page(self, q=None, limit=DEFAULT_PAGE_LIMIT, offset=0):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        project_expr = self._project_value_no_alias()
        sql = (
            f"SELECT {project_expr} AS project, COUNT(*) AS session_count, MAX(started_at) AS last_started_at "
            "FROM sessions WHERE 1=1"
        )
        args = []
        if q:
            sql += f" AND {project_expr} LIKE ?"
            args.append(f"%{q}%")
        sql += " GROUP BY project ORDER BY last_started_at DESC LIMIT ? OFFSET ?"
        args.extend([clean_limit + 1, clean_offset])

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        items = [
            {
                "project": row["project"],
                "session_count": int(row["session_count"] or 0),
                "last_ts_ms": parse_ts(row["last_started_at"]),
            }
            for row in rows[:clean_limit]
        ]
        has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def get_session_metadata(self, session_id):
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            payload = self._serialize_session_row(session)
            total_row = self.conn.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            payload["message_total"] = int(total_row["total"] or 0)
            return payload

    def get_session_messages_page(self, session_id, offset=0, limit=DEFAULT_LIMIT):
        clean_limit, clean_offset = normalize_page_args(limit, offset, default_limit=DEFAULT_LIMIT, max_limit=DEFAULT_LIMIT)
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            total_row = self.conn.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            total = int(total_row["total"] or 0)
            messages = self.conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    role,
                    CASE
                        WHEN LENGTH(content) > ? THEN SUBSTR(content, 1, ?)
                        ELSE content
                    END AS content,
                    LENGTH(content) AS content_char_count,
                    CASE
                        WHEN LENGTH(content) > ? THEN 1
                        ELSE 0
                    END AS content_is_truncated,
                    tool_calls,
                    tool_name,
                    CASE
                        WHEN LENGTH(reasoning) > ? THEN SUBSTR(reasoning, 1, ?)
                        ELSE reasoning
                    END AS reasoning,
                    LENGTH(reasoning) AS reasoning_char_count,
                    CASE
                        WHEN LENGTH(reasoning) > ? THEN 1
                        ELSE 0
                    END AS reasoning_is_truncated
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    MESSAGE_PREVIEW_FETCH_CHARS,
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    MESSAGE_PREVIEW_FETCH_CHARS,
                    MESSAGE_INLINE_FULL_THRESHOLD,
                    session_id,
                    clean_limit,
                    clean_offset,
                ),
            ).fetchall()
        return {
            "messages": [
                self._serialize_message_row(row, clean_offset + idx)
                for idx, row in enumerate(messages)
            ],
            "offset": clean_offset,
            "limit": clean_limit,
            "total": total,
        }

    def get_session(self, session_id, include_messages=True):
        session = self.get_session_metadata(session_id)
        if not session:
            return None
        payload = {"session": session}
        if include_messages:
            cached = self._session_preview_cache.get(str(session_id))
            if cached is not None:
                self._session_preview_cache.move_to_end(str(session_id))
                return cached
            page = self.get_session_messages_page(session_id, offset=0, limit=DEFAULT_LIMIT)
            if page is None:
                return None
            payload["messages"] = page["messages"]
            self._remember_session_preview_cache(session_id, payload)
        return payload

    def get_session_message(self, session_id, message_index):
        try:
            offset = int(message_index)
        except (TypeError, ValueError):
            return None
        if offset < 0:
            return None

        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            row = self.conn.execute(
                """
                SELECT id, timestamp, role, content, tool_calls, tool_name, reasoning
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC, id ASC
                LIMIT 1 OFFSET ?
                """,
                (session_id, offset),
            ).fetchone()
        if not row:
            return None
        return self._serialize_message_row(row, offset, include_full_text=True)

    def search_session_messages(self, session_id, query, limit=None):
        term = str(query or "").strip()
        result = {
            "query": term,
            "match_count": 0,
            "message_match_count": 0,
            "matches": [],
        }
        if not term:
            return result

        pattern = re.compile(re.escape(term), re.IGNORECASE)

        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            rows = self.conn.execute(
                """
                SELECT id, timestamp, role, content, tool_calls, tool_name, reasoning
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id,),
            ).fetchall()

        try:
            clean_limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            clean_limit = None
        if clean_limit is not None and clean_limit <= 0:
            clean_limit = None

        matches = []
        total_hits = 0
        total_message_matches = 0
        for idx, row in enumerate(rows):
            serialized = self._serialize_message_row(row, idx, include_full_text=True)
            text = str(serialized["text"] or "")
            found = list(pattern.finditer(text))
            if not found:
                continue
            total_hits += len(found)
            total_message_matches += 1
            if clean_limit is None or len(matches) < clean_limit:
                excerpt = build_search_excerpt_text(text, found[0].start(), found[0].end())
                matches.append({
                    "message_index": idx,
                    "ts_ms": serialized["ts_ms"],
                    "role": serialized["role"],
                    "kind": serialized["kind"],
                    "hit_count": len(found),
                    "char_count": serialized["char_count"],
                    "is_truncated": serialized["char_count"] > MESSAGE_INLINE_FULL_THRESHOLD,
                    "excerpt_text": excerpt["text"],
                    "excerpt_start": excerpt["start"],
                    "excerpt_end": excerpt["end"],
                    "excerpt_has_more_before": excerpt["has_more_before"],
                    "excerpt_has_more_after": excerpt["has_more_after"],
                })

        result["match_count"] = total_hits
        result["message_match_count"] = total_message_matches
        result["matches"] = matches
        return result

    def rename_session(self, session_id, title):
        return False

    def archive_session(self, session_id, archived_dir):
        return False, "unsupported"

    def delete_project_sessions(self, project, deleted_dir):
        return False, "unsupported", 0, None

    def cleanup_weak_sessions(self, deleted_dir, min_user_messages=5, project=None):
        return False, "unsupported", 0, None

    def pin_session(self, session_id, pinned):
        return False


class OpenCodeIndexer:
    """Read-only indexer for the OpenCode local SQLite state DB.

    Schema (relevant tables in ``~/.local/share/opencode/opencode.db``):
      - ``session``: id, project_id, directory (cwd), title, time_created (ms),
        time_updated, agent, model (JSON), cost, tokens_*
      - ``message``: id, session_id, time_created, data (JSON envelope)
      - ``part``:    id, message_id, session_id, time_created,
        data (JSON; type ∈ text|reasoning|tool|step-start|step-finish|patch)
      - ``project``: id, worktree, name, ...
    """

    GLOBAL_PROJECT_ID = "global"

    def __init__(self, db_path: Path):
        self.source = "opencode"
        self.db_path = Path(db_path).expanduser()
        self.conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            check_same_thread=False,
            timeout=30.0,
        )
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._session_preview_cache = OrderedDict()

    def _remember_session_preview_cache(self, session_id, payload):
        key = str(session_id or "")
        if not key:
            return
        self._session_preview_cache[key] = payload
        self._session_preview_cache.move_to_end(key)
        while len(self._session_preview_cache) > SESSION_PREVIEW_CACHE_SIZE:
            self._session_preview_cache.popitem(last=False)

    def maybe_update_index(self, max_age_seconds=None):
        return

    def scan_sessions(self):
        return

    def _project_value(self):
        return "COALESCE(NULLIF(s.directory, ''), '(unknown directory)')"

    def _project_value_no_alias(self):
        return "COALESCE(NULLIF(directory, ''), '(unknown directory)')"

    def _session_title(self, row):
        title = str(row["title"] or "").strip()
        if title:
            return title[:80]
        model = ""
        raw_model = row["model"]
        if raw_model:
            try:
                model_obj = json.loads(raw_model) if isinstance(raw_model, str) else raw_model
                if isinstance(model_obj, dict):
                    model = str(model_obj.get("id") or model_obj.get("modelID") or "").strip()
            except (json.JSONDecodeError, TypeError):
                model = ""
        model = model or "OpenCode"
        return f"{model} - {str(row['id'])[:8]}"

    def _serialize_session_row(self, row):
        cwd = str(row["directory"] or "").strip() or "(unknown directory)"
        return {
            "id": row["id"],
            "start_ts_ms": parse_ts(row["time_created"]),
            "end_ts_ms": parse_ts(row["time_updated"]),
            "title": self._session_title(row),
            "message_count": int(row["message_count"] or 0),
            "cwd": cwd,
            "pinned": 0,
            **_neutral_audit_summary(),
        }

    @staticmethod
    def _parse_data(raw):
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8", errors="replace")
            except Exception:
                return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _format_tool_text(tool_name, state):
        name = str(tool_name or "").strip() or "tool"
        lines = [f"Tool use: {name}"]
        if isinstance(state, dict):
            arguments = state.get("input")
            if arguments not in (None, ""):
                lines.append("Input:")
                if isinstance(arguments, str):
                    try:
                        parsed = json.loads(arguments)
                    except json.JSONDecodeError:
                        parsed = None
                    if parsed is not None:
                        lines.append("```json")
                        lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))
                        lines.append("```")
                    else:
                        lines.append(arguments)
                else:
                    lines.append("```json")
                    lines.append(json.dumps(arguments, ensure_ascii=False, indent=2))
                    lines.append("```")
            output = state.get("output")
            if output not in (None, ""):
                lines.append("Output:")
                if isinstance(output, str):
                    lines.append(output)
                else:
                    try:
                        lines.append(json.dumps(output, ensure_ascii=False, indent=2))
                    except (TypeError, ValueError):
                        lines.append(str(output))
            metadata = state.get("metadata")
            if isinstance(metadata, dict) and metadata:
                error = metadata.get("error")
                if error:
                    lines.append(f"Error: {error}")
        return "\n".join(lines).strip()

    @staticmethod
    def _flatten_part(message_role, part_type, part_data, part_time_ms):
        """Flatten one part into (role, kind, text, ts_ms); return None to skip."""
        role = str(message_role or "").strip() or "assistant"
        text = ""
        kind = "message"

        if part_type == "text":
            text = str(part_data.get("text") or "")
            kind = "message"
        elif part_type == "reasoning":
            text = str(part_data.get("text") or "")
            kind = "reasoning_summary"
        elif part_type == "tool":
            tool_name = part_data.get("tool") or ""
            state = part_data.get("state") or {}
            status = str(state.get("status") or "").strip().lower() if isinstance(state, dict) else ""
            text = OpenCodeIndexer._format_tool_text(tool_name, state)
            if status in ("pending", "running"):
                return ("assistant", "tool_use", text, part_time_ms)
            return ("tool", "tool_result", text, part_time_ms)
        else:
            return None  # step-start / step-finish / patch / unknown

        if not text:
            return None
        return (role, kind, text, part_time_ms)

    def _load_flat_messages(self, session_id):
        """Load + flatten all parts for a session, in time order."""
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT
                    p.id            AS part_id,
                    p.message_id    AS message_id,
                    p.time_created  AS part_ts_ms,
                    p.data          AS part_data,
                    m.data          AS message_data,
                    m.time_created  AS message_ts_ms
                FROM part p
                JOIN message m ON m.id = p.message_id
                WHERE p.session_id = ?
                ORDER BY m.time_created ASC, p.time_created ASC, p.id ASC
                """,
                (session_id,),
            ).fetchall()

        flat = []
        for row in rows:
            message_data = self._parse_data(row["message_data"])
            if not message_data:
                continue
            message_role = message_data.get("role") or "assistant"
            part_data = self._parse_data(row["part_data"]) or {}
            part_type = str(part_data.get("type") or "").strip()
            if not part_type:
                continue
            part_time_ms = parse_ts(row["part_ts_ms"]) or parse_ts(row["message_ts_ms"])
            flat_part = self._flatten_part(message_role, part_type, part_data, part_time_ms)
            if flat_part is None:
                continue
            role, kind, text, ts_ms = flat_part
            flat.append({"ts_ms": ts_ms, "role": role, "kind": kind, "text": text})
        return flat

    def _serialize_flat_message(self, flat_msg, message_index, include_full_text=False):
        text = str(flat_msg.get("text") or "")
        text, char_count, is_truncated = normalize_message_payload(
            text,
            include_full_text=include_full_text,
        )
        return {
            "message_index": int(message_index),
            "ts_ms": flat_msg.get("ts_ms"),
            "role": str(flat_msg.get("role") or "assistant"),
            "kind": str(flat_msg.get("kind") or "message"),
            "text": text,
            "char_count": char_count,
            "is_truncated": bool(is_truncated),
        }

    def _session_lookup(self, session_id):
        return self.conn.execute(
            """
            SELECT id, project_id, parent_id, slug, directory, title, version,
                   share_url, summary_additions, summary_deletions, summary_files,
                   summary_diffs, time_created, time_updated, agent, model,
                   cost, tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write,
                   (SELECT COUNT(*) FROM message m WHERE m.session_id = session.id) AS message_count
            FROM session
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()

    def _session_message_count(self, session_id):
        """Count of flat (rendered) messages for a session."""
        flat = self._load_flat_messages(session_id)
        return len(flat)

    def list_sessions_page(self, q=None, start_ms=None, end_ms=None, limit=DEFAULT_PAGE_LIMIT, offset=0, cwd=None, sort=None):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        terms = [t for t in str(q or "").split() if t]

        sql = (
            "SELECT s.id, s.project_id, s.directory, s.title, s.time_created, "
            "s.time_updated, s.model, s.agent, "
            "(SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) AS message_count "
            "FROM session s WHERE 1=1"
        )
        args = []
        if start_ms is not None:
            sql += " AND s.time_created >= ?"
            args.append(int(start_ms))
        if end_ms is not None:
            sql += " AND s.time_created <= ?"
            args.append(int(end_ms))
        if cwd:
            sql += f" AND {self._project_value()} = ?"
            args.append(str(cwd))
        for term in terms:
            like = f"%{term}%"
            sql += (
                " AND ("
                "COALESCE(s.title, '') LIKE ? OR COALESCE(s.directory, '') LIKE ? "
                "OR COALESCE(s.agent, '') LIKE ? OR COALESCE(s.model, '') LIKE ? "
                "OR s.id LIKE ? "
                "OR EXISTS (SELECT 1 FROM message m WHERE m.session_id = s.id AND m.data LIKE ?) "
                "OR EXISTS (SELECT 1 FROM part p WHERE p.session_id = s.id AND p.data LIKE ?)"
                ")"
            )
            args.extend([like, like, like, like, like, like, like])

        sort_key = str(sort or "start").strip().lower()
        if sort_key in ("last", "end", "updated", "update"):
            sql += " ORDER BY s.time_updated DESC, s.time_created DESC"
        else:
            sql += " ORDER BY s.time_created DESC, s.time_updated DESC"
        sql += " LIMIT ? OFFSET ?"
        args.extend([clean_limit + 1, clean_offset])

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        items = [self._serialize_session_row(row) for row in rows[:clean_limit]]
        has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def list_projects_page(self, q=None, limit=DEFAULT_PAGE_LIMIT, offset=0):
        clean_limit, clean_offset = normalize_page_args(limit, offset)
        project_expr = self._project_value_no_alias()
        sql = (
            f"SELECT {project_expr} AS project, COUNT(*) AS session_count, "
            "MAX(time_created) AS last_started_at "
            "FROM session WHERE 1=1 "
            f"AND (project_id IS NULL OR project_id != '{self.GLOBAL_PROJECT_ID}')"
        )
        args = []
        if q:
            sql += f" AND {project_expr} LIKE ?"
            args.append(f"%{q}%")
        sql += " GROUP BY project ORDER BY last_started_at DESC LIMIT ? OFFSET ?"
        args.extend([clean_limit + 1, clean_offset])

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        items = [
            {
                "project": row["project"],
                "session_count": int(row["session_count"] or 0),
                "last_ts_ms": parse_ts(row["last_started_at"]),
            }
            for row in rows[:clean_limit]
        ]
        has_more = len(rows) > clean_limit
        next_offset = clean_offset + len(items) if has_more else None
        return {
            "items": items,
            "limit": clean_limit,
            "offset": clean_offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    def get_session_metadata(self, session_id):
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            payload = self._serialize_session_row(session)
            payload["message_total"] = self._session_message_count(session_id)
            return payload

    def get_session_messages_page(self, session_id, offset=0, limit=DEFAULT_LIMIT):
        clean_limit, clean_offset = normalize_page_args(
            limit, offset, default_limit=DEFAULT_LIMIT, max_limit=DEFAULT_LIMIT
        )
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            flat = self._load_flat_messages(session_id)
        total = len(flat)
        window = flat[clean_offset:clean_offset + clean_limit]
        return {
            "messages": [
                self._serialize_message_row(row, clean_offset + idx)
                for idx, row in enumerate(messages)
            ],
            "offset": clean_offset,
            "limit": clean_limit,
            "total": total,
        }

    def get_session(self, session_id, include_messages=True):
        session = self.get_session_metadata(session_id)
        if not session:
            return None
        payload = {"session": session}
        if include_messages:
            cached = self._session_preview_cache.get(str(session_id))
            if cached is not None:
                self._session_preview_cache.move_to_end(str(session_id))
                return cached
            page = self.get_session_messages_page(session_id, offset=0, limit=DEFAULT_LIMIT)
            if page is None:
                return None
            payload["messages"] = page["messages"]
            self._remember_session_preview_cache(session_id, payload)
        return payload

    def get_session_message(self, session_id, message_index):
        try:
            offset = int(message_index)
        except (TypeError, ValueError):
            return None
        if offset < 0:
            return None
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            flat = self._load_flat_messages(session_id)
        if offset >= len(flat):
            return None
        return self._serialize_flat_message(flat[offset], offset, include_full_text=True)

    def search_session_messages(self, session_id, query, limit=None):
        term = str(query or "").strip()
        result = {
            "query": term,
            "match_count": 0,
            "message_match_count": 0,
            "matches": [],
        }
        if not term:
            return result

        pattern = re.compile(re.escape(term), re.IGNORECASE)
        with self.lock:
            session = self._session_lookup(session_id)
            if not session:
                return None
            flat = self._load_flat_messages(session_id)

        try:
            clean_limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            clean_limit = None
        if clean_limit is not None and clean_limit <= 0:
            clean_limit = None

        matches = []
        total_hits = 0
        total_message_matches = 0
        for idx, msg in enumerate(flat):
            text = str(msg.get("text") or "")
            found = list(pattern.finditer(text))
            if not found:
                continue
            total_hits += len(found)
            total_message_matches += 1
            if clean_limit is None or len(matches) < clean_limit:
                excerpt = build_search_excerpt_text(text, found[0].start(), found[0].end())
                matches.append({
                    "message_index": idx,
                    "ts_ms": msg.get("ts_ms"),
                    "role": msg.get("role"),
                    "kind": msg.get("kind"),
                    "hit_count": len(found),
                    "char_count": len(text),
                    "is_truncated": len(text) > MESSAGE_INLINE_FULL_THRESHOLD,
                    "excerpt_text": excerpt["text"],
                    "excerpt_start": excerpt["start"],
                    "excerpt_end": excerpt["end"],
                    "excerpt_has_more_before": excerpt["has_more_before"],
                    "excerpt_has_more_after": excerpt["has_more_after"],
                })

        result["match_count"] = total_hits
        result["message_match_count"] = total_message_matches
        result["matches"] = matches
        return result

    def rename_session(self, session_id, title):
        return False

    def archive_session(self, session_id, archived_dir):
        return False, "unsupported"

    def delete_project_sessions(self, project, deleted_dir):
        return False, "unsupported", 0, None

    def cleanup_weak_sessions(self, deleted_dir, min_user_messages=5, project=None):
        return False, "unsupported", 0, None

    def pin_session(self, session_id, pinned):
        return False


class WslBootstrapper:
    def __init__(self, distro):
        self.distro = str(distro or "").strip()
        self.lock = threading.Lock()
        self.last_ok = 0.0

    def ensure(self, max_age_seconds=15):
        if not self.distro:
            return
        now = time.time()
        if now - self.last_ok < max_age_seconds:
            return
        with self.lock:
            now = time.time()
            if now - self.last_ok < max_age_seconds:
                return
            try:
                subprocess.run(
                    ["wsl.exe", "-d", self.distro, "--", "true"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=True,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"Failed to start WSL distro {self.distro}: {exc}") from exc
            self.last_ok = time.time()


class SourceBackend:
    def __init__(
        self,
        *,
        system,
        source,
        root_dir,
        sessions_dir,
        data_dir,
        db_filename,
        parse_file_fn,
        parser_version,
        scan_interval,
        archived_dir,
        deleted_dir,
        recall_db_path,
        file_filter_fn=None,
        ensure_fn=None,
        indexer_factory=None,
        read_only=False,
    ):
        self.system = system
        self.source = source
        self.root_dir = Path(root_dir)
        self.sessions_dir = Path(sessions_dir)
        self.archived_dir = Path(archived_dir)
        self.deleted_dir = Path(deleted_dir)
        self.ensure_fn = ensure_fn
        self.read_only = bool(read_only)
        self.scan_interval = max(1, int(scan_interval))
        if indexer_factory is not None:
            self.indexer = indexer_factory()
        else:
            self.indexer = Indexer(
                sessions_dir=self.sessions_dir,
                data_dir=Path(data_dir),
                source=source,
                db_filename=db_filename,
                scan_interval=scan_interval,
                parse_file_fn=parse_file_fn,
                file_filter_fn=file_filter_fn,
                parser_version=parser_version,
                recall_db_path=recall_db_path,
            )
        if self.ensure_fn is None:
            self.indexer.maybe_update_index(max_age_seconds=0)
        self._start_background_refresh(run_immediately=self.ensure_fn is not None)

    def ensure_ready(self):
        if self.ensure_fn:
            self.ensure_fn()

    def _refresh_index_once(self):
        self.ensure_ready()
        self.indexer.maybe_update_index(max_age_seconds=0)

    def _background_refresh_loop(self, run_immediately=False):
        if not run_immediately:
            time.sleep(self.scan_interval)
        while True:
            try:
                self._refresh_index_once()
            except Exception:
                pass
            time.sleep(self.scan_interval)

    def _start_background_refresh(self, run_immediately=False):
        thread = threading.Thread(
            target=self._background_refresh_loop,
            kwargs={"run_immediately": run_immediately},
            name=f"history-viewer-scan-{self.system}-{self.source}",
            daemon=True,
        )
        thread.start()
        self._refresh_thread = thread


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, source_backends=None, wsl_distro=None, runtime_system="windows", **kwargs):
        self._source_backends = source_backends or {}
        self._wsl_distro = wsl_distro
        self._runtime_system = str(runtime_system or "windows").strip() or "windows"
        super().__init__(*args, directory=directory, **kwargs)

    def _resolve_source_request(self, path):
        if path == "/api/claude" or path.startswith("/api/claude/"):
            backend = self._source_backends.get((self._runtime_system, "claude"))
            subpath = path[len("/api/claude"):] or "/"
            return backend, subpath

        if path == "/api/openclaw" or path.startswith("/api/openclaw/"):
            backend = self._source_backends.get((self._runtime_system, "openclaw"))
            subpath = path[len("/api/openclaw"):] or "/"
            return backend, subpath

        match = re.match(r"^/api/([^/]+)/([^/]+)(/.*)?$", path)
        if match:
            system = match.group(1)
            source = match.group(2)
            backend = self._source_backends.get((system, source))
            subpath = match.group(3) or "/"
            return backend, subpath

        if path == "/api" or path.startswith("/api/"):
            backend = self._source_backends.get((self._runtime_system, "codex"))
            subpath = path[len("/api"):] or "/"
            return backend, subpath

        return None, None

    def _ensure_backend_ready(self, backend):
        if backend is None:
            self.send_json({"error": "not found"}, status=404)
            return False
        try:
            backend.ensure_ready()
        except RuntimeError as exc:
            self.send_json({"error": "source_unavailable", "detail": str(exc)}, status=503)
            return False
        return True

    def _extract_session_id(self, source_path, suffix=""):
        if not source_path or not source_path.startswith("/session/"):
            return None
        end = -len(suffix) if suffix else None
        return unquote(source_path[len("/session/"):end])

    def _extract_session_message_request(self, source_path):
        if not source_path or not source_path.startswith("/session/"):
            return None, None
        match = re.match(r"^/session/([^/]+)/message/(\d+)$", source_path)
        if not match:
            return None, None
        return unquote(match.group(1)), int(match.group(2))

    def _extract_session_messages_request(self, source_path, suffix="/messages"):
        if not source_path or not source_path.startswith("/session/"):
            return None
        if not source_path.endswith(suffix):
            return None
        start = len("/session/")
        end = -len(suffix)
        return unquote(source_path[start:end])

    def _extract_session_audit_request(self, source_path):
        suffix = "/audit"
        if not source_path or not source_path.startswith("/session/"):
            return None
        if not source_path.endswith(suffix):
            return None
        start = len("/session/")
        end = -len(suffix)
        return unquote(source_path[start:end])

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/sources":
            return self.handle_sources()

        backend, source_path = self._resolve_source_request(path)
        if backend or path.startswith("/api/"):
            if not self._ensure_backend_ready(backend):
                return
            if source_path == "/sessions":
                return self.handle_sessions(parsed, backend)
            if source_path == "/projects":
                return self.handle_projects(parsed, backend)
            if source_path and source_path.endswith("/messages/search"):
                session_id = self._extract_session_messages_request(source_path, "/messages/search")
                return self.handle_session_messages_search(session_id, parsed, backend)
            if source_path and source_path.endswith("/messages"):
                session_id = self._extract_session_messages_request(source_path, "/messages")
                return self.handle_session_messages(session_id, parsed, backend)
            if source_path and "/message/" in source_path:
                session_id, message_index = self._extract_session_message_request(source_path)
                return self.handle_session_message(session_id, message_index, backend)
            if source_path and source_path.endswith("/search"):
                session_id = self._extract_session_id(source_path, "/search")
                return self.handle_session_search(session_id, parsed, backend)
            if source_path and source_path.endswith("/audit"):
                session_id = self._extract_session_audit_request(source_path)
                return self.handle_session_audit(session_id, parsed, backend)
            if source_path and source_path.startswith("/session/"):
                session_id = self._extract_session_id(source_path)
                return self.handle_session(session_id, backend, parsed)
            if source_path == "/reindex":
                backend.indexer.scan_sessions()
                return self.send_json({"ok": True})
            return self.send_json({"error": "not found"}, status=404)

        if parsed.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        backend, source_path = self._resolve_source_request(path)
        if not backend or not source_path:
            return self.send_json({"error": "not found"}, status=404)
        if not self._ensure_backend_ready(backend):
            return
        if getattr(backend, "read_only", False):
            return self.send_json({"error": "read_only_source"}, status=405)

        def _rename():
            title = data.get("title", "").strip()
            if not title:
                return self.send_json({"error": "title required"}, status=400)
            session_id = self._extract_session_id(source_path, "/rename")
            ok = backend.indexer.rename_session(session_id, title)
            return self.send_json({"ok": ok})

        def _archive():
            session_id = self._extract_session_id(source_path, "/archive")
            ok, detail = backend.indexer.archive_session(session_id, backend.archived_dir)
            if not ok:
                return self.send_json({"error": detail}, status=404)
            return self.send_json({"ok": True})

        def _pin():
            pinned = data.get("pinned", True)
            session_id = self._extract_session_id(source_path, "/pin")
            ok = backend.indexer.pin_session(session_id, pinned)
            return self.send_json({"ok": ok})

        def _delete_project():
            project = data.get("project", "").strip()
            if not project:
                return self.send_json({"error": "project required"}, status=400)
            ok, detail, deleted_count, backup_dir = backend.indexer.delete_project_sessions(project, backend.deleted_dir)
            if not ok:
                return self.send_json({"error": detail}, status=404)
            return self.send_json({
                "ok": True,
                "deleted_count": deleted_count,
                "backup_dir": backup_dir,
            })

        def _cleanup_weak():
            project = data.get("project", "").strip() or None
            try:
                min_user_messages = int(data.get("min_user_messages", 5))
            except Exception:
                min_user_messages = 5
            ok, detail, deleted_count, backup_dir = backend.indexer.cleanup_weak_sessions(
                backend.deleted_dir,
                min_user_messages=min_user_messages,
                project=project,
            )
            return self.send_json({
                "ok": ok,
                "detail": detail,
                "deleted_count": deleted_count,
                "backup_dir": backup_dir,
            })

        if source_path == "/project/delete":
            return _delete_project()
        if source_path == "/cleanup/weak-sessions":
            return _cleanup_weak()
        if source_path.startswith("/session/"):
            if source_path.endswith("/rename"):
                return _rename()
            if source_path.endswith("/archive"):
                return _archive()
            if source_path.endswith("/pin"):
                return _pin()

        return self.send_json({"error": "not found"}, status=404)

    def handle_sources(self):
        items = []
        for (system, source), backend in sorted(self._source_backends.items()):
            items.append({
                "system": system,
                "source": source,
                "root_dir": str(backend.root_dir),
                "sessions_dir": str(backend.sessions_dir),
                "archived_dir": str(backend.archived_dir),
                "deleted_dir": str(backend.deleted_dir),
                "read_only": bool(getattr(backend, "read_only", False)),
            })
        return self.send_json({
            "sources": items,
            "wsl_distro": self._wsl_distro,
            "runtime_system": self._runtime_system,
        })

    def handle_sessions(self, parsed, backend):
        params = parse_qs(parsed.query)
        q = params.get("q", [""])[0].strip() or None
        start = params.get("start", [None])[0]
        end = params.get("end", [None])[0]
        project = params.get("project", [""])[0].strip() or None
        sort = params.get("sort", [""])[0].strip() or None
        limit = params.get("limit", [DEFAULT_PAGE_LIMIT])[0]
        offset = params.get("offset", [0])[0]
        file_path = (params.get("file", [""])[0].strip() or None)

        start_ms = parse_date_param(start, end=False)
        end_ms = parse_date_param(end, end=True)

        page = backend.indexer.list_sessions_page(
            q=q,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
            offset=offset,
            cwd=project,
            sort=sort,
            file_path=file_path,
        )
        return self.send_json({
            "sessions": page["items"],
            "limit": page["limit"],
            "offset": page["offset"],
            "has_more": page["has_more"],
            "next_offset": page["next_offset"],
        })

    def handle_projects(self, parsed, backend):
        params = parse_qs(parsed.query)
        q = params.get("q", [""])[0].strip() or None
        limit = params.get("limit", [DEFAULT_PAGE_LIMIT])[0]
        offset = params.get("offset", [0])[0]
        page = backend.indexer.list_projects_page(q=q, limit=limit, offset=offset)
        return self.send_json({
            "projects": page["items"],
            "limit": page["limit"],
            "offset": page["offset"],
            "has_more": page["has_more"],
            "next_offset": page["next_offset"],
        })

    def handle_session(self, session_id, backend, parsed=None):
        include_messages = False
        if parsed is not None:
            params = parse_qs(parsed.query)
            include_messages = params.get("include_messages", ["0"])[0] in ("1", "true", "yes")
        data = backend.indexer.get_session(session_id, include_messages=include_messages)
        if not data:
            return self.send_json({"error": "not_found"}, status=404)
        return self.send_json(data)

    def handle_session_audit(self, session_id, parsed, backend):
        if session_id is None:
            return self.send_json({"error": "not_found"}, status=404)
        builder = getattr(backend.indexer, "build_session_audit", None)
        audit = builder(session_id) if builder else None
        if audit is None:
            return self.send_json({"error": "audit_unavailable"}, status=404)
        return self.send_json({"audit": audit})

    def handle_session_messages(self, session_id, parsed, backend):
        if session_id is None:
            return self.send_json({"error": "not_found"}, status=404)
        params = parse_qs(parsed.query)
        offset = params.get("offset", [0])[0]
        limit = params.get("limit", [DEFAULT_LIMIT])[0]
        data = backend.indexer.get_session_messages_page(session_id, offset=offset, limit=limit)
        if data is None:
            return self.send_json({"error": "not_found"}, status=404)
        return self.send_json(data)

    def handle_session_message(self, session_id, message_index, backend):
        if session_id is None or message_index is None:
            return self.send_json({"error": "not_found"}, status=404)
        data = backend.indexer.get_session_message(session_id, message_index)
        if not data:
            return self.send_json({"error": "not_found"}, status=404)
        return self.send_json({"message": data})

    def handle_session_search(self, session_id, parsed, backend):
        if session_id is None:
            return self.send_json({"error": "not_found"}, status=404)
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0]
        limit = params.get("limit", [None])[0]
        data = backend.indexer.search_session_messages(session_id, query, limit=limit)
        if data is None:
            return self.send_json({"error": "not_found"}, status=404)
        return self.send_json(data)

    def handle_session_messages_search(self, session_id, parsed, backend):
        return self.handle_session_search(session_id, parsed, backend)

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description="Codex + Claude + OpenClaw history viewer")
    parser.add_argument("--codex-dir", default=os.path.expanduser("~/.codex"))
    parser.add_argument("--claude-dir", default=os.path.expanduser("~/.claude"))
    parser.add_argument("--openclaw-dir", default=os.path.expanduser("~/.openclaw"))
    parser.add_argument("--hermes-state-db", default=None)
    parser.add_argument("--opencode-state-db", default=None)
    parser.add_argument("--wsl-distro", default="Ubuntu-22.04")
    parser.add_argument("--wsl-user", default="muqiao")
    parser.add_argument("--wsl-codex-dir", default=None)
    parser.add_argument("--wsl-claude-dir", default=None)
    parser.add_argument("--wsl-openclaw-dir", default=None)
    parser.add_argument("--data-dir", default=None, help="Directory for index.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--scan-interval", type=int, default=5)
    args = parser.parse_args()

    codex_dir = Path(args.codex_dir).expanduser()
    claude_dir = Path(args.claude_dir).expanduser()
    openclaw_dir = Path(args.openclaw_dir).expanduser()
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else Path(__file__).resolve().parent
    data_dir.mkdir(parents=True, exist_ok=True)
    runtime_system = detect_runtime_system()
    source_backends = {}

    def detect_hermes_state_db(explicit_path):
        candidates = []
        if explicit_path:
            candidates.append(Path(explicit_path).expanduser())
        if runtime_system != "windows":
            candidates.extend(
                [
                    Path(__file__).resolve().parent.parent / "hermes-agent" / ".hermes-home" / "state.db",
                    Path("~/.hermes/state.db").expanduser(),
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def detect_opencode_state_db(explicit_path):
        candidates = []
        if explicit_path:
            candidates.append(Path(explicit_path).expanduser())
        if runtime_system != "windows":
            candidates.append(Path("~/.local/share/opencode/opencode.db").expanduser())
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def register_source(
        system,
        source,
        root_dir,
        sessions_dir,
        db_filename,
        parse_file_fn,
        parser_version,
        *,
        file_filter_fn=None,
        ensure_fn=None,
        indexer_factory=None,
        read_only=False,
    ):
        recall_db_path = None
        if system in ("windows", "linux") and source in ("codex", "claude"):
            recall_db_path = Path(root_dir).parent / ".recall.db"
        source_backends[(system, source)] = SourceBackend(
            system=system,
            source=source,
            root_dir=root_dir,
            sessions_dir=sessions_dir,
            data_dir=data_dir,
            db_filename=db_filename,
            parse_file_fn=parse_file_fn,
            parser_version=parser_version,
            scan_interval=args.scan_interval,
            archived_dir=Path(root_dir) / "archived_sessions",
            deleted_dir=Path(root_dir) / "deleted_projects",
            recall_db_path=recall_db_path,
            file_filter_fn=file_filter_fn,
            ensure_fn=ensure_fn,
            indexer_factory=indexer_factory,
            read_only=read_only,
        )

    openclaw_filter = lambda p: p.parent.name == "sessions"
    claude_filter = lambda p: not p.name.startswith("agent-")
    if runtime_system == "windows":
        wsl_home = Path(f"\\\\wsl$\\{args.wsl_distro}\\home\\{args.wsl_user}")
        wsl_codex_dir = Path(args.wsl_codex_dir) if args.wsl_codex_dir else (wsl_home / ".codex")
        wsl_claude_dir = Path(args.wsl_claude_dir) if args.wsl_claude_dir else (wsl_home / ".claude")
        wsl_openclaw_dir = Path(args.wsl_openclaw_dir) if args.wsl_openclaw_dir else (wsl_home / ".openclaw")
        wsl_bootstrapper = WslBootstrapper(args.wsl_distro)

        register_source("windows", "codex", codex_dir, codex_dir / "sessions", "index.sqlite", parse_codex_session_file, 4)
        register_source("windows", "claude", claude_dir, claude_dir / "projects", "index_claude.sqlite", parse_claude_session_file, 3, file_filter_fn=claude_filter)
        register_source("windows", "openclaw", openclaw_dir, openclaw_dir / "agents", "index_openclaw.sqlite", parse_openclaw_session_file, 1, file_filter_fn=openclaw_filter)
        register_source("wsl", "codex", wsl_codex_dir, wsl_codex_dir / "sessions", "index_wsl_codex.sqlite", parse_codex_session_file, 4, ensure_fn=wsl_bootstrapper.ensure)
        register_source("wsl", "claude", wsl_claude_dir, wsl_claude_dir / "projects", "index_wsl_claude.sqlite", parse_claude_session_file, 3, file_filter_fn=claude_filter, ensure_fn=wsl_bootstrapper.ensure)
        register_source("wsl", "openclaw", wsl_openclaw_dir, wsl_openclaw_dir / "agents", "index_wsl_openclaw.sqlite", parse_openclaw_session_file, 1, file_filter_fn=openclaw_filter, ensure_fn=wsl_bootstrapper.ensure)
    else:
        register_source("linux", "codex", codex_dir, codex_dir / "sessions", "index_linux.sqlite", parse_codex_session_file, 4)
        register_source("linux", "claude", claude_dir, claude_dir / "projects", "index_linux_claude.sqlite", parse_claude_session_file, 3, file_filter_fn=claude_filter)
        register_source("linux", "openclaw", openclaw_dir, openclaw_dir / "agents", "index_linux_openclaw.sqlite", parse_openclaw_session_file, 1, file_filter_fn=openclaw_filter)

    hermes_state_db = detect_hermes_state_db(args.hermes_state_db)
    if hermes_state_db:
        hermes_root = hermes_state_db.parent
        register_source(
            runtime_system,
            "hermes",
            hermes_root,
            hermes_root,
            "index_hermes.sqlite",
            parse_codex_session_file,
            1,
            indexer_factory=lambda: HermesStateIndexer(hermes_state_db),
            read_only=True,
        )

    opencode_state_db = detect_opencode_state_db(args.opencode_state_db)
    if opencode_state_db:
        opencode_root = opencode_state_db.parent
        register_source(
            runtime_system,
            "opencode",
            opencode_root,
            opencode_root,
            "index_opencode.sqlite",
            parse_codex_session_file,
            1,
            indexer_factory=lambda: OpenCodeIndexer(opencode_state_db),
            read_only=True,
        )

    static_dir = Path(__file__).resolve().parent / "static"

    def handler(*inner_args, **inner_kwargs):
        return Handler(
            *inner_args,
            directory=str(static_dir),
            source_backends=source_backends,
            wsl_distro=args.wsl_distro if runtime_system == "windows" else None,
            runtime_system=runtime_system,
            **inner_kwargs,
        )

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"History viewer running on http://{args.host}:{args.port}")
    for key in sorted(source_backends):
        backend = source_backends[key]
        print(f"{backend.system}/{backend.source}: {backend.root_dir}")
        print(f"  sessions: {backend.sessions_dir}")
        print(f"  index:    {backend.indexer.db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
