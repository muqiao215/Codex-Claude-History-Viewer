"""Deterministic, compact context capsules for continuing a session elsewhere."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .command_classifier import classify_command


def _text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _unique(values: Iterable[str], limit: int) -> List[str]:
    result: List[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def _handoff_status(audit: Dict[str, Any]) -> str:
    outcome = str(audit.get("outcome_signal") or "unknown")
    if outcome in ("completed", "exploration") and audit.get("has_assistant_after_last_user"):
        return "completed"
    if outcome in ("errored", "interrupted") and not audit.get("last_assistant_reply"):
        return "blocked"
    return "partial"


def _is_referential_confirmation(text: str) -> bool:
    clean = " ".join(str(text or "").lower().split())
    if len(clean) > 180:
        return False
    markers = (
        "根据这个需求", "按这个", "就这个", "继续吧", "开始吧",
        "go ahead", "proceed", "do that", "continue",
    )
    return any(marker in clean for marker in markers)


def _is_verification_command(command: str) -> bool:
    intents = set(classify_command(command))
    if intents.intersection({"TEST", "BUILD"}):
        return True
    return bool(re.search(r"\b(?:py_compile|compileall|node\s+--check|bash\s+-n)\b", command, re.IGNORECASE))


def _verification_status(run: Dict[str, Any]) -> str:
    status = str(run.get("status") or "unknown")
    if status != "unknown":
        return status
    if run.get("result_shared"):
        return "unknown"
    result = str(run.get("result_summary") or "")
    success_markers = (
        r"\bOK\b",
        r"\b\d+/\d+ tests? passed\b",
        r"\b\d+/\d+ passed\b",
        r"\b\d+ passed\b",
    )
    if any(re.search(pattern, result, re.IGNORECASE) for pattern in success_markers):
        return "pass"
    return "unknown"


def _git_state(cwd: str) -> Dict[str, Any]:
    from .git_snapshot import legacy_git_state
    return legacy_git_state(cwd)


def build_handoff_payload(
    audit: Dict[str, Any],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    ai_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = metadata or {}
    ai_audit = ai_audit or {}
    last_prompt = str(audit.get("last_user_prompt") or "").strip()
    referential_context = audit.get("last_assistant_before_last_user") if _is_referential_confirmation(last_prompt) else ""
    goal = _text(ai_audit.get("user_intent") or referential_context or audit.get("first_user_prompt"), 600)

    prompts = list(audit.get("important_user_prompts") or [])
    if last_prompt and last_prompt != str(audit.get("first_user_prompt") or "").strip():
        prompts.append(last_prompt)
    constraints = [_text(value, 360) for value in _unique(prompts, 5)]

    files = audit.get("files_touched") or {}
    changed: List[Dict[str, Any]] = []
    for scope in ("local", "remote"):
        for item in files.get(scope) or []:
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            changed.append({
                "path": path,
                "scope": scope,
                "edit_count": int(item.get("edit_count") or 0),
                "write_count": int(item.get("write_count") or 0),
                "confidence": str(item.get("confidence") or "high"),
            })

    verified = []
    seen_commands = set()
    for run in reversed(audit.get("commands") or []):
        command = _text(run.get("command"), 280)
        if not command or command in seen_commands or not _is_verification_command(command):
            continue
        seen_commands.add(command)
        verified.append({
            "command": command,
            "status": _verification_status(run),
            "exit_code": run.get("exit_code"),
            "evidence_id": run.get("evidence_id"),
        })
        if len(verified) >= 8:
            break
    verified.reverse()

    remaining = [_text(value, 320) for value in _unique(ai_audit.get("gaps") or [], 5)]
    status = _handoff_status(audit)
    if not remaining and status != "completed":
        remaining = [f"Session outcome is {audit.get('outcome_signal') or 'unknown'}; verify unresolved work before continuing."]

    next_action = _text(ai_audit.get("next_action"), 360)
    if not next_action and remaining:
        next_action = remaining[0]

    evidence_refs = []
    allowed_types = {"user_prompt", "tool_call", "file", "file_mutation", "error"}
    for item in audit.get("evidence") or []:
        if item.get("type") not in allowed_types:
            continue
        evidence_refs.append({
            "id": item.get("id"),
            "message_index": item.get("message_index"),
            "line_no": (item.get("raw_ref") or {}).get("line_no"),
            "summary": _text(item.get("summary"), 180),
        })
        if len(evidence_refs) >= 10:
            break

    git_state = _git_state(str(metadata.get("cwd") or ""))
    dirty_paths = set(git_state.pop("_paths", []))
    cwd = Path(git_state["root"]) if git_state.get("available") else None
    touched_dirty = []
    for item in changed:
        path = Path(item["path"])
        try:
            relative = str(path.relative_to(cwd)) if path.is_absolute() and cwd is not None else str(path)
        except ValueError:
            relative = str(path)
        if relative in dirty_paths:
            touched_dirty.append(item)
    if touched_dirty:
        changed = touched_dirty

    source = str(audit.get("source") or "")
    session_id = str(audit.get("session_id") or metadata.get("id") or "")
    return {
        "version": 1,
        "session": f"{source}:{session_id}" if source else session_id,
        "cwd": str(metadata.get("cwd") or ""),
        "goal": goal,
        "constraints": constraints,
        "decisions": [],
        "status": status,
        "changed": changed,
        "verified": verified,
        "remaining": remaining,
        "blockers": remaining if status == "blocked" else [],
        "next_action": next_action,
        "evidence": evidence_refs,
        "git": git_state,
    }


def render_handoff(payload: Dict[str, Any], detail: str = "standard") -> str:
    compact = detail == "compact"
    lines = [
        "[HANDOFF]",
        f"session: {payload.get('session') or '-'}",
        f"cwd: {payload.get('cwd') or '-'}",
        f"goal: {_text(payload.get('goal'), 280 if compact else 600) or '-'}",
    ]
    constraints = payload.get("constraints") or []
    if constraints:
        lines.append("constraints:")
        for item in constraints[:2 if compact else 5]:
            lines.append(f"- {_text(item, 220 if compact else 360)}")
    lines.append(f"status: {payload.get('status') or 'partial'}")

    changed = payload.get("changed") or []
    lines.append("\nchanged:")
    if not changed:
        lines.append("- none observed")
    for item in changed[:5 if compact else 15]:
        ops = []
        if item.get("write_count"):
            ops.append(f"write {item['write_count']}")
        if item.get("edit_count"):
            ops.append(f"edit {item['edit_count']}")
        detail_text = ", ".join(ops) or "touched"
        lines.append(f"- {item.get('path')}: {detail_text} ({item.get('scope')})")

    verified = payload.get("verified") or []
    lines.append("\nverified:")
    if not verified:
        lines.append("- none observed")
    for item in verified[:3 if compact else 10]:
        code = item.get("exit_code")
        suffix = f", exit {code}" if code is not None else ""
        lines.append(f"- {item.get('command')} -> {item.get('status')}{suffix}")

    remaining = payload.get("remaining") or []
    lines.append("\nremaining:")
    if not remaining:
        lines.append("- none recorded")
    for item in remaining[:2 if compact else 5]:
        lines.append(f"- {_text(item, 220 if compact else 320)}")
    if payload.get("next_action"):
        lines.append(f"next_action: {_text(payload.get('next_action'), 240 if compact else 360)}")

    evidence = payload.get("evidence") or []
    lines.append("\nevidence:")
    if not evidence:
        lines.append("- none recorded")
    for item in evidence[:3 if compact else 8]:
        index = item.get("message_index")
        line_no = item.get("line_no")
        location = f"message {index}" if isinstance(index, int) else str(item.get("id") or "evidence")
        if isinstance(line_no, int):
            location += f" / JSONL line {line_no}"
        lines.append(f"- {location}: {_text(item.get('summary'), 160 if compact else 220)}")
    git_state = payload.get("git") or {}
    if git_state.get("available"):
        lines.append(f"- git: commit {git_state.get('commit') or '-'}, workspace {git_state.get('workspace') or 'unknown'}")
        lines.append(f"- git observation: export-time {git_state.get('observed_at') or 'unknown'}; historical verification baseline: unknown")
    elif git_state.get("reason"):
        lines.append(f"- git unavailable: {git_state['reason']}")
    return "\n".join(lines)


def build_handoff_bundle(
    audit: Dict[str, Any],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    ai_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = build_handoff_payload(audit, metadata=metadata, ai_audit=ai_audit)
    return {
        "payload": payload,
        "compact": render_handoff(payload, "compact"),
        "standard": render_handoff(payload, "standard"),
    }


__all__ = ["build_handoff_bundle", "build_handoff_payload", "render_handoff"]
