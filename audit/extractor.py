"""Deterministic session audit extractor (plan sections 5, 6, 9, 12, 13).

Reads a raw JSONL transcript independently from the display parser. This is
deliberate: the display parser flattens tool calls into human readable text,
which destroys the structured ``file_path`` / ``command`` arguments the audit
layer needs (plan section 6).

Design constraints (plan 13 / risk 6):

* Head/tail reconnaissance for cheap duration / outcome hints.
* String pre-scan before ``json.loads`` on large lines; oversized uninteresting
  lines are skipped so a multi-MB webpack log never stalls the scan.
* A single malformed JSON line increments ``parse_errors`` but never aborts the
  session.

The extractor is source-aware (codex / claude / openclaw): each source has its
own normaliser that yields :class:`AuditEvent`. Everything downstream is shared.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .command_classifier import classify_command, extract_remote_file_paths
from . import scoring
from .schema import (
    AuditEvent,
    AuditPayload,
    Evidence,
    FileFootprint,
)


# ---------------------------------------------------------------------------
# Tunable limits (plan 13.4).
# ---------------------------------------------------------------------------

MAX_LINE_BYTES = 1_000_000
MAX_ERROR_SAMPLE_CHARS = 300
MAX_COMMAND_CHARS = 500
MAX_ASSISTANT_REPLY_CHARS = 2000
MAX_PROMPT_CHARS = 800
MAX_IMPORTANT_PROMPTS = 6
MAX_ERROR_SAMPLES = 5
MAX_EVIDENCE_PER_TYPE = 200

# Substrings that, if present in a huge line, make it worth parsing (plan 13.3).
INTERESTING_HINTS = (
    '"role"',
    '"tool_calls"',
    '"tool_use"',
    '"tool_result"',
    '"function_call"',
    '"name"',
    '"file_path"',
    '"command"',
    '"error"',
    "traceback",
    "turn_aborted",
    "turn_interrupted",
    "isError",
)

# Markers that terminate an ssh session's remote context (plan 12.2).
_REMOTE_EXIT_MARKERS = ("exit", "logout", "connection closed", "connection to ", "closed by remote host")


# ---------------------------------------------------------------------------
# Source normalizers — each yields AuditEvent from raw JSONL records.
# ---------------------------------------------------------------------------

def _coerce_args(raw: Any) -> Any:
    """Codex stores function arguments as a JSON string; normalise to dict."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                return json.loads(text)
            except Exception:
                return text
        return text
    return raw


def _codex_events(obj: Dict[str, Any], line_no: int) -> Iterator[AuditEvent]:
    ts_ms = _parse_ts(obj.get("timestamp")) or 0
    obj_type = obj.get("type")
    if obj_type == "session_meta":
        # Meta carries no audit event of its own; timing is folded in elsewhere.
        return
    if obj_type != "response_item":
        return
    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        return
    payload_type = payload.get("type")

    if payload_type == "message":
        role = str(payload.get("role") or "unknown")
        text = _extract_text(payload.get("content"))
        yield AuditEvent(
            ts_ms=ts_ms,
            role=_normalise_role(role),
            kind="message",
            text=text,
            line_no=line_no,
        )
        return
    if payload_type == "reasoning":
        text = _join_reasoning(payload.get("summary"))
        if text:
            yield AuditEvent(
                ts_ms=ts_ms,
                role="assistant",
                kind="reasoning",
                text=text,
                line_no=line_no,
            )
        return
    if payload_type in ("function_call", "custom_tool_call"):
        name = str(payload.get("name") or "tool")
        if name == "update_plan":
            return
        args = _coerce_args(payload.get("arguments") if payload_type == "function_call" else payload.get("input"))
        yield AuditEvent(
            ts_ms=ts_ms,
            role="tool",
            kind="tool_use",
            tool_name=name,
            tool_args=args,
            text="",
            line_no=line_no,
        )
        return
    if payload_type in ("function_call_output", "custom_tool_call_output"):
        raw_output = payload.get("output")
        text, is_error = _format_tool_output(raw_output)
        yield AuditEvent(
            ts_ms=ts_ms,
            role="tool",
            kind="tool_result",
            tool_result_text=text,
            tool_result_error=is_error,
            line_no=line_no,
        )
        return


def _claude_events(obj: Dict[str, Any], line_no: int) -> Iterator[AuditEvent]:
    if not isinstance(obj, dict):
        return
    ts_ms = _parse_ts(obj.get("timestamp")) or 0
    obj_type = obj.get("type")
    if obj_type == "summary":
        return
    if obj_type == "file-history-snapshot":
        return
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return
    role = str(msg.get("role") or obj_type or "other")
    content = msg.get("content")

    if isinstance(content, str):
        yield AuditEvent(
            ts_ms=ts_ms,
            role=_normalise_role(role),
            kind="message",
            text=content,
            line_no=line_no,
        )
        return

    if not isinstance(content, list):
        return

    tool_use_result = obj.get("toolUseResult") if isinstance(obj.get("toolUseResult"), dict) else None
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            text = item.get("text") or ""
            if isinstance(text, str) and text.strip():
                yield AuditEvent(
                    ts_ms=ts_ms,
                    role=_normalise_role(role),
                    kind="message",
                    text=text,
                    line_no=line_no,
                )
            continue
        if item_type == "thinking":
            text = item.get("thinking") or ""
            if isinstance(text, str) and text.strip():
                yield AuditEvent(
                    ts_ms=ts_ms,
                    role="assistant",
                    kind="reasoning",
                    text=text,
                    line_no=line_no,
                )
            continue
        if item_type == "tool_use":
            yield AuditEvent(
                ts_ms=ts_ms,
                role="tool",
                kind="tool_use",
                tool_name=str(item.get("name") or "tool"),
                tool_args=item.get("input"),
                text="",
                line_no=line_no,
            )
            continue
        if item_type == "tool_result":
            text, is_error = _format_claude_tool_result(item, tool_use_result)
            yield AuditEvent(
                ts_ms=ts_ms,
                role="tool",
                kind="tool_result",
                tool_result_text=text,
                tool_result_error=is_error,
                line_no=line_no,
            )
            continue


def _openclaw_events(obj: Dict[str, Any], line_no: int) -> Iterator[AuditEvent]:
    # OpenClaw's transcript is Anthropic-flavoured; reuse the claude normaliser
    # and add the OpenClaw-specific message envelope if present.
    if not isinstance(obj, dict):
        return
    msg = obj.get("message")
    if isinstance(obj.get("content"), list) and not isinstance(msg, dict):
        # OpenClaw sometimes puts content at the top level.
        msg = {"role": obj.get("role") or obj.get("type"), "content": obj.get("content")}
        obj = dict(obj)
        obj["message"] = msg
    yield from _claude_events(obj, line_no)


_NORMALISERS = {
    "codex": _codex_events,
    "claude": _claude_events,
    "openclaw": _openclaw_events,
}


# ---------------------------------------------------------------------------
# Small parsing helpers shared by normalisers.
# ---------------------------------------------------------------------------

_TS_FORMATS = (
    # ISO 8601 with milliseconds / Zulu handled by fromisoformat after stripping Z.
)


def _parse_ts(value: Any) -> Optional[int]:
    """Best-effort ms-epoch extraction from a timestamp field."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Detect seconds vs milliseconds.
        n = float(value)
        if n < 1e12:
            return int(n * 1000)
        return int(n)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_ts(int(text))
        iso = text.replace("Z", "+00:00")
        try:
            import datetime as _dt

            dt = _dt.datetime.fromisoformat(iso)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None
    return None


def _normalise_role(role: str) -> str:
    r = str(role or "other").strip().lower()
    if r in ("user", "human"):
        return "user"
    if r in ("assistant", "agent", "ai"):
        return "assistant"
    if r in ("system",):
        return "system"
    if r in ("developer",):
        return "developer"
    if r in ("tool", "function", "function_call", "tool_result", "tool_use"):
        return "tool"
    return "other"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
                elif isinstance(item.get("content"), str):
                    parts.append(str(item["content"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _join_reasoning(summary: Any) -> str:
    if not isinstance(summary, list):
        return ""
    parts: List[str] = []
    for item in summary:
        if isinstance(item, dict):
            text = item.get("text") or item.get("summary_text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _format_tool_output(raw: Any) -> Tuple[str, bool]:
    """Render a codex/openclaw tool output into (summary_text, is_error)."""
    if raw is None:
        return "", False
    if isinstance(raw, str):
        return _truncate(raw, MAX_ERROR_SAMPLE_CHARS * 2), _looks_like_error(raw)
    if isinstance(raw, dict):
        text = raw.get("output") or raw.get("text") or raw.get("content")
        is_error = raw.get("is_error") is True or raw.get("error") is True
        if isinstance(text, str):
            return _truncate(text, MAX_ERROR_SAMPLE_CHARS * 2), (is_error or _looks_like_error(text))
        # Fall through to JSON dump for structured payloads.
        try:
            dumped = json.dumps(raw, ensure_ascii=False)
        except Exception:
            dumped = str(raw)
        return _truncate(dumped, MAX_ERROR_SAMPLE_CHARS * 2), is_error
    try:
        dumped = json.dumps(raw, ensure_ascii=False)
    except Exception:
        dumped = str(raw)
    return _truncate(dumped, MAX_ERROR_SAMPLE_CHARS * 2), _looks_like_error(dumped)


def _format_claude_tool_result(item: Dict[str, Any], tool_use_result: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    is_error = bool(item.get("is_error")) is True
    if isinstance(item.get("content"), str):
        text = str(item["content"])
        return _truncate(text, MAX_ERROR_SAMPLE_CHARS * 2), (is_error or _looks_like_error(text))
    if isinstance(item.get("content"), list):
        parts: List[str] = []
        for sub in item["content"]:
            if isinstance(sub, dict):
                t = sub.get("text")
                if isinstance(t, str):
                    parts.append(t)
        text = "\n".join(parts)
        return _truncate(text, MAX_ERROR_SAMPLE_CHARS * 2), (is_error or _looks_like_error(text))
    if tool_use_result is not None:
        text, is_error = _format_tool_output(tool_use_result)
        return text, (is_error or _looks_like_error(text))
    return "", is_error


def _looks_like_error(text: str) -> bool:
    from .scoring import _looks_like_error as _impl  # local to avoid re-import cycles

    return _impl(text)


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


# ---------------------------------------------------------------------------
# Line streaming with head/tail reconnaissance + large line tolerance.
# ---------------------------------------------------------------------------

def _iter_jsonl(path: Path) -> Iterator[Tuple[int, Optional[Dict[str, Any]]]]:
    """Yield ``(line_no, obj)`` for every parseable line.

    Oversized uninteresting lines are skipped silently (they still increment
    the line number). Malformed lines yield ``(line_no, None)`` so the caller
    can count ``parse_errors``.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, raw in enumerate(f, start=1):
                if len(raw) > MAX_LINE_BYTES:
                    if not any(hint in raw for hint in INTERESTING_HINTS):
                        continue
                    # Truncate before parsing so json.loads stays bounded.
                    raw = raw[:MAX_LINE_BYTES]
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except Exception:
                    yield (line_no, None)
                    continue
                if isinstance(obj, dict):
                    yield (line_no, obj)
                # Bare arrays / scalars are ignored (not audit-relevant).
    except FileNotFoundError:
        return
    except OSError:
        return


# ---------------------------------------------------------------------------
# Tool arg helpers — pull file paths and shell commands out of structured args.
# ---------------------------------------------------------------------------

_PATH_KEYS = ("file_path", "path", "filePath", "filename", "notebook_path", "target_file", "file")


def _extract_paths_from_args(args: Any) -> List[str]:
    if not args:
        return []
    if isinstance(args, str):
        return []
    if isinstance(args, dict):
        paths: List[str] = []
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
        # MultiEdit / multi-file tools sometimes carry a list under "edits".
        edits = args.get("edits")
        if isinstance(edits, list):
            for edit in edits:
                if isinstance(edit, dict):
                    for key in _PATH_KEYS:
                        value = edit.get(key)
                        if isinstance(value, str) and value.strip() and value.strip() not in paths:
                            paths.append(value.strip())
        return paths
    return []


_COMMAND_KEYS = ("command", "cmd", "commands", "script", "shell_command", "raw_command")


def _extract_command_from_args(args: Any) -> Optional[str]:
    if not args:
        return None
    if isinstance(args, str):
        # Codex sometimes hands the raw command as the arguments string.
        if any(c in args for c in (" ", "\n")) or "/" in args or "_" in args:
            return args[:MAX_COMMAND_CHARS]
        return None
    if isinstance(args, dict):
        for key in _COMMAND_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:MAX_COMMAND_CHARS]
            if isinstance(value, list):
                joined = "\n".join(str(part) for part in value if part)
                if joined.strip():
                    return joined.strip()[:MAX_COMMAND_CHARS]
    return None


# ---------------------------------------------------------------------------
# Evidence ID helper — every id is session-scoped (plan 8.1).
# ---------------------------------------------------------------------------

def _safe_segment(text: str, limit: int = 80) -> str:
    text = str(text or "").strip()
    if not text:
        return "_"
    # collapse path separators / spaces so the id stays DOM-friendly
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", text)
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = "_"
    return cleaned[:limit]


def make_evidence_id(session_id: str, kind: str, *parts: Any) -> str:
    seg = ":".join(_safe_segment(str(p)) for p in parts if p is not None and str(p) != "")
    prefix = f"{session_id}:{kind}"
    return f"{prefix}:{seg}" if seg else prefix


# ---------------------------------------------------------------------------
# Remote context tracker (plan 12).
# ---------------------------------------------------------------------------

_SSH_TARGET_RE = re.compile(r"(?:ssh\s+(?:-[A-Za-z]+\s+)*[\w.-]*\s+)?([\w._-]+@[\w.-]+)")
_SCP_TARGET_RE = re.compile(r"\b([\w._-]+@[\w.-]+):")


class _RemoteContext:
    __slots__ = ("active", "targets", "last_seen_index", "remote_command_count")

    def __init__(self) -> None:
        self.active = False
        self.targets: set = set()
        self.last_seen_index: Optional[int] = None
        self.remote_command_count = 0

    def update_from_command(self, command: str, intents: List[str], index: int) -> None:
        text = str(command or "")
        if not text:
            return
        lowered = text.lower()
        if any(marker in lowered for marker in _REMOTE_EXIT_MARKERS):
            # exit / logout / connection drop turns the context off.
            if "exit" == lowered.strip() or lowered.strip().startswith("exit ") or "logout" in lowered:
                if self.active:
                    self.active = False
        if "REMOTE" in intents:
            self.active = True
            self.last_seen_index = index
            self.remote_command_count += 1
            for pat in (_SSH_TARGET_RE, _SCP_TARGET_RE):
                for m in pat.finditer(text):
                    self.targets.add(m.group(1))


# ---------------------------------------------------------------------------
# Main payload builder.
# ---------------------------------------------------------------------------

def extract_session_audit(
    path: Path,
    source: str,
    *,
    session_id_hint: Optional[str] = None,
) -> Optional[AuditPayload]:
    """Build the deterministic AuditPayload for one transcript file.

    Returns ``None`` only when the file cannot be opened at all. Any in-file
    parsing problem is recorded in ``payload.parse_errors`` instead of raising
    (plan 13.5).
    """
    normaliser = _NORMALISERS.get(str(source or "").lower())
    if normaliser is None:
        # Unknown sources fall back to the codex shape which is the most common.
        normaliser = _codex_events

    events: List[AuditEvent] = []
    parse_errors = 0
    session_id = session_id_hint or f"file-{path.stem}"
    started_at: Optional[int] = None
    ended_at: Optional[int] = None
    model = ""

    for line_no, obj in _iter_jsonl(path):
        if obj is None:
            parse_errors += 1
            continue
        # session_id / timing / model are picked up from any source that exposes them.
        if not session_id or session_id.startswith("file-"):
            sid = _detect_session_id(obj, source)
            if sid:
                session_id = sid
        ts = _parse_ts(obj.get("timestamp")) if isinstance(obj, dict) else None
        if ts is not None:
            if started_at is None or ts < started_at:
                started_at = ts
            if ended_at is None or ts > ended_at:
                ended_at = ts
        if not model:
            model = _detect_model(obj, source) or ""
        for ev in normaliser(obj, line_no):
            events.append(ev)

    if started_at is None:
        started_at = ended_at or 0
    if ended_at is None:
        ended_at = started_at

    return _build_payload(
        events=events,
        session_id=session_id,
        source=source,
        model=model,
        started_at=started_at or 0,
        ended_at=ended_at or 0,
        parse_errors=parse_errors,
    )


def _detect_session_id(obj: Dict[str, Any], source: str) -> Optional[str]:
    if source == "codex":
        if obj.get("type") == "session_meta":
            payload = obj.get("payload") or {}
            sid = payload.get("id")
            if isinstance(sid, str) and sid:
                return sid
    sid = obj.get("sessionId") if isinstance(obj, dict) else None
    if isinstance(sid, str) and sid:
        return sid
    return None


def _detect_model(obj: Dict[str, Any], source: str) -> Optional[str]:
    for key in ("model", "provider_model"):
        value = obj.get(key) if isinstance(obj, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------------------
# Payload assembly.
# ---------------------------------------------------------------------------

def _build_payload(
    *,
    events: List[AuditEvent],
    session_id: str,
    source: str,
    model: str,
    started_at: int,
    ended_at: int,
    parse_errors: int,
) -> AuditPayload:
    payload = AuditPayload(
        session_id=session_id,
        source=source,
        model=model,
        started_at=int(started_at),
        ended_at=int(ended_at),
        duration_ms=max(0, int(ended_at) - int(started_at)),
        parse_errors=int(parse_errors),
    )

    # message_count + tools_used + prompts -----------------------------------
    first_user = ""
    last_user = ""
    last_assistant = ""
    message_count: Dict[str, int] = {"user": 0, "assistant": 0, "tool": 0, "other": 0}
    tools_used: Dict[str, int] = {}
    important_prompts: List[str] = []

    # per-file mutation tracking
    file_stats: Dict[str, Dict[str, Any]] = {}
    inferred_files: List[str] = []
    # bash command history for intent classification + repeat detection
    all_commands: List[str] = []

    # evidence collection (capped per type to avoid huge payloads)
    evidence: List[Dict[str, Any]] = []
    file_evidence_seen: set = set()
    tool_evidence_count = 0
    error_evidence: List[Evidence] = []

    remote_ctx = _RemoteContext()

    # outcome helpers
    has_interrupt_marker = False
    recent_results: List[bool] = []  # True = success, False = error (last N)
    last_tool_success = False

    write_ops = 0
    edit_ops = 0
    successful_bash_count = 0
    failed_bash_count = 0

    for idx, ev in enumerate(events):
        message_count[ev.role] = message_count.get(ev.role, 0) + 1

        # Interrupt detection works on any text-bearing event.
        if ev.text and scoring.looks_interrupted(ev.text):
            has_interrupt_marker = True
        if ev.tool_result_text and scoring.looks_interrupted(ev.tool_result_text):
            has_interrupt_marker = True

        if ev.kind == "message":
            text = ev.text or ""
            if ev.role == "user":
                if not first_user:
                    first_user = text[:MAX_PROMPT_CHARS]
                last_user = text[:MAX_PROMPT_CHARS]
                # collect short pivots / new asks as "important"
                stripped = text.strip()
                if stripped and stripped not in (first_user, last_user) and len(important_prompts) < MAX_IMPORTANT_PROMPTS:
                    if len(stripped) < MAX_PROMPT_CHARS and (stripped.endswith("?") or stripped.lower().startswith(("now ", "next", "actually", "instead", "please", "can you", "let's"))):
                        important_prompts.append(stripped[:MAX_PROMPT_CHARS])
            elif ev.role == "assistant":
                last_assistant = text[:MAX_ASSISTANT_REPLY_CHARS]
            continue

        if ev.kind == "tool_use":
            tool_name = str(ev.tool_name or "tool")
            key = tool_name.lower()
            tools_used[key] = tools_used.get(key, 0) + 1

            # evidence for the tool call
            if tool_evidence_count < MAX_EVIDENCE_PER_TYPE:
                summary = _summarise_tool_use(tool_name, ev.tool_args)
                evidence.append(
                    Evidence(
                        id=make_evidence_id(session_id, "tool", tool_name, idx),
                        session_id=session_id,
                        type="tool_call",
                        summary=summary,
                        confidence="high",
                        tool_name=tool_name,
                        message_index=idx,
                        raw_ref={"line_no": ev.line_no},
                    ).to_dict()
                )
                tool_evidence_count += 1

            # local file mutation (plan 9.1)
            if key in scoring.LOCAL_FILE_TOOLS:
                paths = _extract_paths_from_args(ev.tool_args)
                for p in paths:
                    _record_file(file_stats, p, op=key, remote=False, source="tool", confidence="high")
                    _record_file_evidence(
                        evidence, file_evidence_seen, session_id, p, remote=False,
                    )
                    if key in ("write", "create_file"):
                        write_ops += 1
                    else:
                        edit_ops += 1

            # shell command → classify
            if key in scoring.SHELL_COMMAND_TOOLS:
                command = _extract_command_from_args(ev.tool_args) or ""
                if command:
                    all_commands.append(command)
                    intents = classify_command(command)
                    remote_ctx.update_from_command(command, intents, idx)
                    # remote file extraction (plan 9.2)
                    if remote_ctx.active:
                        for rpath in extract_remote_file_paths(command):
                            _record_file(file_stats, rpath, op="ssh", remote=True, source="ssh", confidence="medium")
                            _record_file_evidence(
                                evidence, file_evidence_seen, session_id, rpath, remote=True,
                            )
            continue

        if ev.kind == "tool_result":
            is_error = bool(ev.tool_result_error) is True
            text = ev.tool_result_text or ""
            recent_results.append(not is_error)
            if len(recent_results) > 8:
                recent_results.pop(0)
            last_tool_success = not is_error
            if is_error:
                payload_errors = payload.errors
                payload_errors["count"] = int(payload_errors.get("count", 0)) + 1
                if len(payload_errors["samples"]) < MAX_ERROR_SAMPLES:
                    payload_errors["samples"].append(_truncate(text, MAX_ERROR_SAMPLE_CHARS))
                failed_bash_count += 1
                if len(error_evidence) < MAX_EVIDENCE_PER_TYPE:
                    error_evidence.append(
                        Evidence(
                            id=make_evidence_id(session_id, "error", "tool", idx),
                            session_id=session_id,
                            type="error",
                            summary=_truncate(text, MAX_ERROR_SAMPLE_CHARS),
                            confidence="high",
                            message_index=idx,
                            raw_ref={"line_no": ev.line_no},
                        )
                    )
            else:
                successful_bash_count += 1
            # inferred file paths from build/test output (plan 9.3)
            for inferred in _extract_inferred_paths(text):
                if inferred not in inferred_files:
                    inferred_files.append(inferred)
            continue

    # Attach error evidence at the end so it stays bounded.
    for ev_err in error_evidence:
        evidence.append(ev_err.to_dict())

    # Command intents ---------------------------------------------------------
    command_intents: Dict[str, int] = {}
    for cmd in all_commands:
        for label in classify_command(cmd):
            command_intents[label] = command_intents.get(label, 0) + 1
    # REMOTE context propagation (plan 12.2): commands after an active ssh
    # that did not contain an explicit ssh token are still REMOTE at medium
    # confidence. We approximate by counting remote_command_count once the
    # context was opened (cheap heuristic: use the explicit REMOTE labels plus
    # the post-context indices captured in remote_ctx).
    if remote_ctx.active and remote_ctx.remote_command_count == 0:
        command_intents.setdefault("REMOTE", 0)

    # Build files_touched + file_mutation_stats -------------------------------
    # ghost modification weighting needs the session outcome first, so compute
    # outcome below and then back-fill the weights.

    # Outcome signal ----------------------------------------------------------
    recent_errors = sum(1 for ok in recent_results if not ok)
    is_exploration_only = (
        not file_stats
        and write_ops == 0
        and edit_ops == 0
        and command_intents.get("DEPLOY", 0) == 0
        and command_intents.get("TEST", 0) == 0
        and command_intents.get("BUILD", 0) == 0
        and command_intents.get("INSTALL", 0) == 0
        and (tools_used.get("read", 0) + tools_used.get("grep", 0) + tools_used.get("glob", 0)) > 0
    )
    outcome = scoring.compute_outcome_signal(
        has_interrupt_marker=has_interrupt_marker,
        recent_tool_errors=recent_errors,
        last_tool_success=last_tool_success,
        has_final_assistant_reply=bool(last_assistant),
        has_write_like_tools=bool(file_stats),
        has_test_or_build=bool(command_intents.get("TEST") or command_intents.get("BUILD")),
        is_exploration_only=is_exploration_only,
    )

    # Back-fill file outcomes + ghost weights now that we know the session outcome.
    for stats in file_stats.values():
        stats["final_outcome"] = outcome
    scoring.apply_ghost_modification_weights(file_stats)

    local_files: List[Dict[str, Any]] = []
    remote_files: List[Dict[str, Any]] = []
    for fpath, stats in file_stats.items():
        entry = FileFootprint(
            path=fpath,
            edit_count=int(stats.get("edit_count", 0)),
            write_count=int(stats.get("write_count", 0)),
            confidence=str(stats.get("confidence", "high")),
            remote=bool(stats.get("remote", False)),
            source=str(stats.get("source", "tool")),
            net_value_weight=float(stats.get("net_value_weight", 1.0)),
            final_outcome=str(stats.get("final_outcome", "unknown")),
        ).to_dict()
        if entry["remote"]:
            remote_files.append(entry)
        else:
            local_files.append(entry)

    inferred_entries = [{"path": p, "confidence": "low", "source": "inferred"} for p in inferred_files]

    # Scoring -----------------------------------------------------------------
    weighted_local = scoring.weighted_file_count(file_stats, remote=False)
    weighted_remote = scoring.weighted_file_count(file_stats, remote=True)
    repeated_commands = scoring.count_repeated_commands(all_commands)
    tool_call_count = sum(tools_used.values())

    value_score = scoring.compute_value_score(
        weighted_local_files=weighted_local,
        weighted_remote_files=weighted_remote,
        write_ops=write_ops,
        edit_ops=edit_ops,
        successful_bash_count=successful_bash_count,
        command_intents=command_intents,
        error_count=int(payload.errors.get("count", 0)),
        interrupted=(outcome == "interrupted"),
    )
    friction_score = scoring.compute_friction_score(
        error_count=int(payload.errors.get("count", 0)),
        failed_bash_count=failed_bash_count,
        repeated_command_count=repeated_commands,
        interrupted=(outcome == "interrupted"),
    )
    action_density = scoring.compute_action_density(
        tool_call_count=tool_call_count,
        duration_ms=payload.duration_ms,
    )

    # Assemble payload --------------------------------------------------------
    payload.first_user_prompt = first_user
    payload.last_user_prompt = last_user
    payload.important_user_prompts = important_prompts
    payload.last_assistant_reply = last_assistant
    payload.message_count = message_count
    payload.tools_used = tools_used
    payload.files_touched = {"local": local_files, "remote": remote_files, "inferred": inferred_entries}
    payload.file_mutation_stats = {k: dict(v) for k, v in file_stats.items()}
    payload.command_intents = command_intents
    payload.remote_context = {
        "has_remote": bool(remote_ctx.targets) or remote_ctx.remote_command_count > 0,
        "targets": sorted(t for t in remote_ctx.targets if t),
        "remote_command_count": int(remote_ctx.remote_command_count),
    }
    payload.outcome_signal = outcome
    payload.value_score = value_score
    payload.friction_score = friction_score
    payload.action_density = action_density
    payload.evidence = evidence
    return payload


# ---------------------------------------------------------------------------
# File footprint helpers.
# ---------------------------------------------------------------------------

def _record_file(
    file_stats: Dict[str, Dict[str, Any]],
    path: str,
    *,
    op: str,
    remote: bool,
    source: str,
    confidence: str,
) -> None:
    if not path:
        return
    stats = file_stats.get(path)
    if stats is None:
        stats = {
            "edit_count": 0,
            "write_count": 0,
            "remote": remote,
            "source": source,
            "confidence": confidence,
            "net_value_weight": 1.0,
            "final_outcome": "unknown",
        }
        file_stats[path] = stats
    if op in ("write", "create_file"):
        stats["write_count"] = int(stats.get("write_count", 0)) + 1
    else:
        stats["edit_count"] = int(stats.get("edit_count", 0)) + 1
    # Keep the highest-confidence source seen.
    if confidence == "high":
        stats["confidence"] = "high"
        stats["source"] = source


def _record_file_evidence(
    evidence: List[Dict[str, Any]],
    seen: set,
    session_id: str,
    path: str,
    *,
    remote: bool,
) -> None:
    if path in seen:
        return
    seen.add(path)
    evidence.append(
        Evidence(
            id=make_evidence_id(session_id, "file", path),
            session_id=session_id,
            type="file",
            summary=f"{'remote' if remote else 'local'} file touched: {path}",
            confidence="medium" if remote else "high",
            raw_ref={"path": path},
        ).to_dict()
    )


# Regex for paths that appear inside build/test error output (plan 9.3).
_INFERRED_PATH_RE = re.compile(r"(?<![A-Za-z0-9])((?:\.{0,2}/)?[\w.\-]+(?:/[\w.\-]+)+\.[A-Za-z]{1,6})(?![A-Za-z0-9])")


def _extract_inferred_paths(text: str) -> List[str]:
    if not text or len(text) > 200_000:
        return []
    matches = _INFERRED_PATH_RE.findall(text)
    seen: List[str] = []
    for match in matches:
        cleaned = match.strip()
        if not cleaned or len(cleaned) < 3:
            continue
        # Skip obvious noise (URLs, version strings).
        if "://" in cleaned or cleaned.startswith("http"):
            continue
        if cleaned not in seen:
            seen.append(cleaned)
    return seen[:50]


def _summarise_tool_use(tool_name: str, args: Any) -> str:
    name = str(tool_name or "tool")
    if isinstance(args, dict):
        path = None
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                path = value.strip()
                break
        if path:
            return f"{name} -> {path}"
        for key in _COMMAND_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return f"{name}: {value.strip()[:120]}"
        query = args.get("query") or args.get("pattern") or args.get("q")
        if isinstance(query, str) and query.strip():
            return f"{name}: {query.strip()[:120]}"
    elif isinstance(args, str) and args:
        return f"{name}: {args[:120]}"
    return name


# Public re-exports for callers that want granular helpers.
__all__ = [
    "extract_session_audit",
    "make_evidence_id",
]
