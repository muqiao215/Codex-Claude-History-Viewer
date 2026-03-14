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
from datetime import datetime, timezone, time as dt_time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

MAX_SEARCH_CHARS = 2_000_000
DEFAULT_LIMIT = 200


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
                            })
                            add_search(text)
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

    def add_message(ts_ms, role, kind, text, count_for_stats=False):
        nonlocal message_count, title
        if not text:
            return
        messages.append({
            "ts_ms": ts_ms,
            "role": role,
            "kind": kind,
            "text": text,
        })
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
                                add_message(ts_ms, "tool", "tool_result", text, count_for_stats=False)
                                continue
                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "user", "message", text.strip(), count_for_stats=True)
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
                                add_message(ts_ms, "tool", "tool_use", text, count_for_stats=False)
                                continue

                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "assistant", "message", text.strip(), count_for_stats=True)
                    continue
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

    def add_message(ts_ms, role, kind, text, count_for_stats=False):
        nonlocal message_count, title
        if not text:
            return
        cleaned = text.strip()
        if not cleaned:
            return
        messages.append({
            "ts_ms": ts_ms,
            "role": role,
            "kind": kind,
            "text": cleaned,
        })
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
                    continue

                if not isinstance(obj, dict):
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
                    continue

                message = obj.get("message")
                if not isinstance(message, dict):
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
                                add_message(ts_ms, "tool", "tool_use", _openclaw_format_tool_use(item), count_for_stats=False)
                                continue
                            text = _claude_extract_text_item(item)
                            if text:
                                add_message(ts_ms, "assistant", "message", text, count_for_stats=True)
                    continue

                if role in ("toolResult", "tool_result", "tool"):
                    add_message(ts_ms, "tool", "tool_result", _openclaw_format_tool_result(message), count_for_stats=False)
                    continue

                if isinstance(content, str):
                    add_message(ts_ms, role, "message", content, count_for_stats=False)
                elif isinstance(content, list):
                    text = extract_text(content)
                    if text:
                        add_message(ts_ms, role, "message", text, count_for_stats=False)
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
        db_filename: str = "index.sqlite",
        scan_interval: int = 5,
        parse_file_fn=None,
        file_filter_fn=None,
        parser_version: int = 1,
    ):
        self.sessions_dir = sessions_dir
        self.db_path = data_dir / db_filename
        self._parse_file_fn = parse_file_fn or parse_codex_session_file
        self._file_filter_fn = file_filter_fn or (lambda p: True)
        self.parser_version = int(parser_version)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.last_scan = 0
        self.scan_interval = max(1, int(scan_interval))
        self._init_db()

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
            self.conn.commit()

    def maybe_update_index(self, max_age_seconds=None):
        if max_age_seconds is None:
            max_age_seconds = self.scan_interval
        now = time.time()
        if now - self.last_scan < max_age_seconds:
            return
        self.scan_sessions()
        self.last_scan = now

    def scan_sessions(self):
        if not self.sessions_dir.exists():
            return
        session_files = [p for p in self.sessions_dir.rglob("*.jsonl") if self._file_filter_fn(p)]
        with self.lock:
            for path in session_files:
                try:
                    mtime = path.stat().st_mtime
                except FileNotFoundError:
                    continue

                row = self.conn.execute(
                    "SELECT id, mtime, parser_version FROM sessions WHERE file_path = ?",
                    (str(path),),
                ).fetchone()
                if (
                    row
                    and row["mtime"] is not None
                    and row["mtime"] >= mtime
                    and row["parser_version"] == self.parser_version
                ):
                    continue

                session = self._parse_file_fn(path)
                if session is None:
                    continue

                if row and row["id"] != session["id"]:
                    self.conn.execute("DELETE FROM messages WHERE session_id = ?", (row["id"],))
                    self.conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))

                self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session["id"],))
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )

                messages = session["messages"]
                if messages:
                    self.conn.executemany(
                        """
                        INSERT INTO messages (session_id, ts_ms, role, kind, text)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                session["id"],
                                int(m["ts_ms"] or session["start_ts_ms"]),
                                m["role"],
                                m["kind"],
                                m["text"],
                            )
                            for m in messages
                        ],
                    )

            self.conn.commit()

    def query_sessions(self, q=None, start_ms=None, end_ms=None, limit=DEFAULT_LIMIT, cwd=None, sort=None):
        terms = []
        if q:
            terms = [t for t in q.split() if t]

        sort_key = str(sort or "start").strip().lower()
        if sort_key in ("last", "end", "updated", "update"):
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, end_ts_ms DESC, start_ts_ms DESC"
        else:
            order_clause = " ORDER BY COALESCE(pinned,0) DESC, start_ts_ms DESC, end_ts_ms DESC"

        sql = (
            "SELECT id, start_ts_ms, end_ts_ms, title, message_count, cwd, pinned "
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
        for term in terms:
            sql += " AND (search_blob LIKE ? OR title LIKE ? OR cwd LIKE ?)"
            like = f"%{term}%"
            args.extend([like, like, like])
        sql += order_clause + " LIMIT ?"
        args.append(int(limit))

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

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

    def get_session(self, session_id):
        with self.lock:
            session = self.conn.execute(
                "SELECT id, start_ts_ms, end_ts_ms, title, message_count, cwd, pinned FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not session:
                return None
            messages = self.conn.execute(
                "SELECT ts_ms, role, kind, text FROM messages WHERE session_id = ? ORDER BY ts_ms ASC, id ASC",
                (session_id,),
            ).fetchall()
        return {
            "session": dict(session),
            "messages": [dict(row) for row in messages],
        }

    def rename_session(self, session_id, title):
        with self.lock:
            cur = self.conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
            )
            self.conn.commit()
            return cur.rowcount > 0

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
            return cur.rowcount > 0


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
        file_filter_fn=None,
        ensure_fn=None,
    ):
        self.system = system
        self.source = source
        self.root_dir = Path(root_dir)
        self.sessions_dir = Path(sessions_dir)
        self.archived_dir = Path(archived_dir)
        self.deleted_dir = Path(deleted_dir)
        self.ensure_fn = ensure_fn
        self.indexer = Indexer(
            sessions_dir=self.sessions_dir,
            data_dir=Path(data_dir),
            db_filename=db_filename,
            scan_interval=scan_interval,
            parse_file_fn=parse_file_fn,
            file_filter_fn=file_filter_fn,
            parser_version=parser_version,
        )
        if self.ensure_fn is None:
            self.indexer.maybe_update_index(max_age_seconds=0)

    def ensure_ready(self):
        if self.ensure_fn:
            self.ensure_fn()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, source_backends=None, wsl_distro=None, **kwargs):
        self._source_backends = source_backends or {}
        self._wsl_distro = wsl_distro
        super().__init__(*args, directory=directory, **kwargs)

    def _resolve_source_request(self, path):
        if path.startswith("/api/windows/") or path.startswith("/api/wsl/"):
            parts = path.split("/")
            if len(parts) >= 5:
                system = parts[2]
                source = parts[3]
                backend = self._source_backends.get((system, source))
                subpath = "/" + "/".join(parts[4:])
                return backend, subpath
            return None, None

        if path == "/api/claude" or path.startswith("/api/claude/"):
            backend = self._source_backends.get(("windows", "claude"))
            subpath = path[len("/api/claude"):] or "/"
            return backend, subpath

        if path == "/api" or path.startswith("/api/"):
            backend = self._source_backends.get(("windows", "codex"))
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
            if source_path and source_path.startswith("/session/"):
                session_id = self._extract_session_id(source_path)
                return self.handle_session(session_id, backend)
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
            })
        return self.send_json({
            "sources": items,
            "wsl_distro": self._wsl_distro,
        })

    def handle_sessions(self, parsed, backend):
        backend.indexer.maybe_update_index()
        params = parse_qs(parsed.query)
        q = params.get("q", [""])[0].strip() or None
        start = params.get("start", [None])[0]
        end = params.get("end", [None])[0]
        project = params.get("project", [""])[0].strip() or None
        sort = params.get("sort", [""])[0].strip() or None
        limit = params.get("limit", [DEFAULT_LIMIT])[0]

        start_ms = parse_date_param(start, end=False)
        end_ms = parse_date_param(end, end=True)

        sessions = backend.indexer.query_sessions(q=q, start_ms=start_ms, end_ms=end_ms, limit=limit, cwd=project, sort=sort)
        return self.send_json({"sessions": sessions})

    def handle_projects(self, parsed, backend):
        backend.indexer.maybe_update_index()
        params = parse_qs(parsed.query)
        q = params.get("q", [""])[0].strip() or None
        limit = params.get("limit", [DEFAULT_LIMIT])[0]
        projects = backend.indexer.query_projects(q=q, limit=limit)
        return self.send_json({"projects": projects})

    def handle_session(self, session_id, backend):
        backend.indexer.maybe_update_index()
        data = backend.indexer.get_session(session_id)
        if not data:
            return self.send_json({"error": "not_found"}, status=404)
        return self.send_json(data)

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

    wsl_home = Path(f"\\\\wsl$\\{args.wsl_distro}\\home\\{args.wsl_user}")
    wsl_codex_dir = Path(args.wsl_codex_dir) if args.wsl_codex_dir else (wsl_home / ".codex")
    wsl_claude_dir = Path(args.wsl_claude_dir) if args.wsl_claude_dir else (wsl_home / ".claude")
    wsl_openclaw_dir = Path(args.wsl_openclaw_dir) if args.wsl_openclaw_dir else (wsl_home / ".openclaw")

    wsl_bootstrapper = WslBootstrapper(args.wsl_distro)
    source_backends = {}

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
    ):
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
            file_filter_fn=file_filter_fn,
            ensure_fn=ensure_fn,
        )

    openclaw_filter = lambda p: p.parent.name == "sessions"
    claude_filter = lambda p: not p.name.startswith("agent-")

    register_source("windows", "codex", codex_dir, codex_dir / "sessions", "index.sqlite", parse_codex_session_file, 4)
    register_source("windows", "claude", claude_dir, claude_dir / "projects", "index_claude.sqlite", parse_claude_session_file, 3, file_filter_fn=claude_filter)
    register_source("windows", "openclaw", openclaw_dir, openclaw_dir / "agents", "index_openclaw.sqlite", parse_openclaw_session_file, 1, file_filter_fn=openclaw_filter)
    register_source("wsl", "codex", wsl_codex_dir, wsl_codex_dir / "sessions", "index_wsl_codex.sqlite", parse_codex_session_file, 4, ensure_fn=wsl_bootstrapper.ensure)
    register_source("wsl", "claude", wsl_claude_dir, wsl_claude_dir / "projects", "index_wsl_claude.sqlite", parse_claude_session_file, 3, file_filter_fn=claude_filter, ensure_fn=wsl_bootstrapper.ensure)
    register_source("wsl", "openclaw", wsl_openclaw_dir, wsl_openclaw_dir / "agents", "index_wsl_openclaw.sqlite", parse_openclaw_session_file, 1, file_filter_fn=openclaw_filter, ensure_fn=wsl_bootstrapper.ensure)

    static_dir = Path(__file__).resolve().parent / "static"

    def handler(*inner_args, **inner_kwargs):
        return Handler(
            *inner_args,
            directory=str(static_dir),
            source_backends=source_backends,
            wsl_distro=args.wsl_distro,
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
