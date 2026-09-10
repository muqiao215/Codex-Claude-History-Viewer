"""Daily work briefing: deterministic aggregation of session audits.

Session-plans 004 §P0-2. The briefing is built only from deterministic audit
summaries plus stored AI-audit fields — the raw transcript never leaves the
machine and no LLM is required. An optional LLM narrative (``mode=llm`` on the
briefing endpoint) reuses the AI-audit provider configuration but still only
sees the compact briefing payload, never transcripts.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

BRIEFING_VERSION = 1
# Overview aggregates every session the caller passes; this cap only bounds
# how many the briefing endpoint will page through as a runaway safeguard.
BRIEFING_MAX_SESSIONS = 2000
BRIEFING_AUDIT_ENRICH_LIMIT = 12
BRIEFING_HIGHLIGHT_LIMIT = 5
BRIEFING_BLOCKED_LIMIT = 8
BRIEFING_DELIVERABLE_LIMIT = 15
MERGE_JACCARD_THRESHOLD = 0.5

_OUTCOME_LABELS = {
    "completed": "completed",
    "partially_completed": "partially completed",
    "errored": "errored",
    "interrupted": "interrupted",
    "incomplete": "incomplete",
    "exploration": "exploration",
    "unknown": "unknown",
}


def _compact(text: Any, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _file_set(item: Dict[str, Any]) -> set:
    ft = item.get("files_touched") or {}
    paths = set()
    for bucket in ("local", "remote"):
        for entry in ft.get(bucket) or []:
            path = str((entry or {}).get("path") or "").strip()
            if path:
                paths.add(path)
    return paths


def _similar(files_a: set, files_b: set) -> bool:
    if not files_a or not files_b:
        return False
    union = files_a | files_b
    return len(files_a & files_b) / len(union) >= MERGE_JACCARD_THRESHOLD


def _merge_sessions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge near-duplicate sessions (same project + overlapping file sets).

    Sessions are considered duplicates when they touch the same working
    directory and their touched-file Jaccard similarity clears the threshold —
    typically retry/continue attempts on the same task. The higher-value
    session survives and absorbs the other's count.
    """
    kept: List[Dict[str, Any]] = []
    for item in sorted(items, key=lambda it: int(it.get("value_score") or 0), reverse=True):
        files = _file_set(item)
        merged = False
        for keep in kept:
            if keep.get("cwd") != item.get("cwd"):
                continue
            if _similar(_file_set(keep), files):
                keep["_merged_count"] = int(keep.get("_merged_count") or 0) + 1
                merged = True
                break
        if not merged:
            copy = dict(item)
            copy["_merged_count"] = 0
            kept.append(copy)
    return kept


def build_briefing(
    items: List[Dict[str, Any]],
    *,
    audits: Optional[Dict[str, Dict[str, Any]]] = None,
    date_label: str = "",
    source: str = "",
) -> Dict[str, Any]:
    """Build the deterministic briefing from day-filtered session summaries.

    Callers pass *all* sessions for the period; nothing is truncated here.
    Near-duplicate merging only de-duplicates the highlights section — blocked
    sessions and deliverables are built from the full list so a failed or
    unique-file session never disappears because it merged into a
    higher-value duplicate.

    ``audits`` maps session_id → ``{"audit": <payload dict>, "ai_audit": <dict>}``
    for enrichment of highlights/blocked entries; missing entries degrade to
    summary-only fields.
    """
    audits = audits or {}
    sessions = [it for it in (items or []) if isinstance(it, dict)]
    kept = _merge_sessions(sessions)

    outcome_counts: Dict[str, int] = {}
    projects = set()
    friction_total = 0
    tokens_total = 0
    has_tokens = False
    for item in sessions:
        outcome = str(item.get("outcome_signal") or "unknown")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        if item.get("cwd"):
            projects.add(str(item["cwd"]))
        friction_total += int(item.get("friction_score") or 0)
        tokens = item.get("tokens_total")
        if isinstance(tokens, (int, float)) and tokens > 0:
            tokens_total += int(tokens)
            has_tokens = True

    overview = {
        "session_count": len(sessions),
        "merged_count": len(sessions) - len(kept),
        "project_count": len(projects),
        "outcomes": outcome_counts,
        "friction_total": friction_total,
    }
    if has_tokens:
        overview["tokens_total"] = tokens_total

    highlights = []
    for item in sorted(kept, key=lambda it: int(it.get("value_score") or 0), reverse=True):
        if len(highlights) >= BRIEFING_HIGHLIGHT_LIMIT:
            break
        sid = str(item.get("id") or "")
        bundle = audits.get(sid) or {}
        audit = bundle.get("audit") or {}
        ai_audit = bundle.get("ai_audit") or {}
        goal = (
            ai_audit.get("user_intent")
            or audit.get("first_user_prompt")
            or item.get("title")
            or ""
        )
        highlights.append({
            "session_id": sid,
            "title": _compact(item.get("title"), 120),
            "project": str(item.get("cwd") or ""),
            "value_score": int(item.get("value_score") or 0),
            "outcome_signal": str(item.get("outcome_signal") or "unknown"),
            "goal": _compact(goal, 200),
            "next_action": _compact(ai_audit.get("next_action"), 200),
            "tokens_total": int(item.get("tokens_total") or 0),
            "merged_count": int(item.get("_merged_count") or 0),
        })

    blocked = []
    for item in sorted(
        [it for it in sessions if str(it.get("outcome_signal")) in ("errored", "interrupted")],
        key=lambda it: int(it.get("friction_score") or 0),
        reverse=True,
    ):
        if len(blocked) >= BRIEFING_BLOCKED_LIMIT:
            break
        sid = str(item.get("id") or "")
        bundle = audits.get(sid) or {}
        audit = bundle.get("audit") or {}
        errors = audit.get("errors") or {}
        samples = errors.get("samples") or []
        error_sample = _compact(samples[0], 160) if samples else ""
        blocked.append({
            "session_id": sid,
            "title": _compact(item.get("title"), 120),
            "project": str(item.get("cwd") or ""),
            "outcome_signal": str(item.get("outcome_signal") or "unknown"),
            "friction_score": int(item.get("friction_score") or 0),
            "error_sample": error_sample,
        })

    deliverable_counts: Dict[str, Dict[str, int]] = {}
    for item in sessions:
        ft = item.get("files_touched") or {}
        for entry in (ft.get("local") or []):
            path = str((entry or {}).get("path") or "").strip()
            if not path:
                continue
            stats = deliverable_counts.setdefault(path, {"write_count": 0, "edit_count": 0})
            stats["write_count"] += int(entry.get("write_count") or 0)
            stats["edit_count"] += int(entry.get("edit_count") or 0)
    deliverables = [
        {"path": path, **counts}
        for path, counts in sorted(
            deliverable_counts.items(),
            key=lambda kv: (kv[1]["write_count"] + kv[1]["edit_count"], kv[0]),
            reverse=True,
        )[:BRIEFING_DELIVERABLE_LIMIT]
    ]

    return {
        "version": BRIEFING_VERSION,
        "date": date_label,
        "source": source,
        "overview": overview,
        "highlights": highlights,
        "blocked": blocked,
        "deliverables": deliverables,
    }


def render_briefing_markdown(briefing: Dict[str, Any]) -> str:
    overview = briefing.get("overview") or {}
    lines = [
        f"# Agent work briefing — {briefing.get('date') or '(date)'}"
        + (f" ({briefing['source']})" if briefing.get("source") else ""),
        "",
        "## Overview",
        f"- Sessions: {overview.get('session_count', 0)}"
        + (f" ({overview['merged_count']} merged as duplicates)" if overview.get("merged_count") else ""),
        f"- Projects: {overview.get('project_count', 0)}",
    ]
    outcomes = overview.get("outcomes") or {}
    if outcomes:
        pretty = ", ".join(
            f"{count} {_OUTCOME_LABELS.get(outcome, outcome)}"
            for outcome, count in sorted(outcomes.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"- Outcomes: {pretty}")
    if overview.get("tokens_total"):
        lines.append(f"- Tokens (total): {overview['tokens_total']:,}")
    lines.append(f"- Friction: {overview.get('friction_total', 0)}")

    highlights = briefing.get("highlights") or []
    lines += ["", "## Highlights"]
    if not highlights:
        lines.append("- No sessions recorded for this period.")
    for item in highlights:
        head = f"### {item.get('title') or '(untitled)'}"
        if item.get("project"):
            head += f" — `{item['project']}`"
        lines += ["", head]
        stats = [f"value {item.get('value_score', 0)}", str(item.get("outcome_signal") or "unknown")]
        if item.get("tokens_total"):
            stats.append(f"{item['tokens_total']:,} tokens")
        if item.get("merged_count"):
            stats.append(f"+{item['merged_count']} merged")
        lines.append(f"- {' · '.join(stats)}")
        if item.get("goal"):
            lines.append(f"- goal: {item['goal']}")
        if item.get("next_action"):
            lines.append(f"- next: {item['next_action']}")

    blocked = briefing.get("blocked") or []
    lines += ["", "## Blocked"]
    if not blocked:
        lines.append("- Nothing blocked.")
    for item in blocked:
        line = f"- {item.get('title') or '(untitled)'} ({item.get('project') or '?'}) — {item.get('outcome_signal')}, friction {item.get('friction_score', 0)}"
        if item.get("error_sample"):
            line += f": {item['error_sample']}"
        lines.append(line)

    deliverables = briefing.get("deliverables") or []
    lines += ["", "## Deliverables"]
    if not deliverables:
        lines.append("- No file changes observed.")
    for item in deliverables:
        ops = []
        if item.get("write_count"):
            ops.append(f"w{item['write_count']}")
        if item.get("edit_count"):
            ops.append(f"e{item['edit_count']}")
        lines.append(f"- {item['path']} ({', '.join(ops) or 'touched'})")

    return "\n".join(lines)


_BRIEFING_LLM_SYSTEM_PROMPT = (
    "You are summarizing an AI coding agent's work day for its owner. "
    "Given a compact, deterministic briefing payload (never raw transcripts), "
    "write a short narrative a busy reader can scan in 30 seconds. "
    "Return STRICT JSON only — no markdown fences, no commentary.\n\n"
    "Schema:\n"
    "{\n"
    '  "narrative": "4-8 sentences: what got done, what is blocked, what to look at next",\n'
    '  "suggestions": ["0-3 concrete follow-up actions"]\n'
    "}\n\n"
    "Be honest about failures and unfinished work. Do not invent facts that "
    "are not in the payload."
)


def build_briefing_llm_messages(briefing: Dict[str, Any]) -> List[Dict[str, str]]:
    payload_str = json.dumps(briefing, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": _BRIEFING_LLM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Daily briefing payload:\n\n{payload_str}"},
    ]


def parse_briefing_llm_response(raw: str, model: Optional[str] = None) -> Dict[str, Any]:
    if not raw or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ValueError("briefing narrative must be a JSON object")
    narrative = str(obj.get("narrative") or "").strip()
    if not narrative:
        raise ValueError("briefing narrative is empty")
    suggestions = obj.get("suggestions") or []
    if not isinstance(suggestions, list):
        suggestions = []
    return {
        "narrative": narrative[:2000],
        "suggestions": [str(s).strip()[:300] for s in suggestions if str(s).strip()][:3],
        "model": model,
        "source": "llm",
    }


def generate_heuristic_briefing_narrative(briefing: Dict[str, Any]) -> Dict[str, Any]:
    """Zero-config fallback narrative composed from the deterministic overview."""
    overview = briefing.get("overview") or {}
    outcomes = overview.get("outcomes") or {}
    completed = outcomes.get("completed", 0) + outcomes.get("partially_completed", 0)
    errored = outcomes.get("errored", 0)
    interrupted = outcomes.get("interrupted", 0)
    merged = overview.get("merged_count", 0)
    parts = [
        f"{overview.get('session_count', 0)} session(s) across {overview.get('project_count', 0)} project(s)"
    ]
    if merged:
        parts.append(f"{merged} near-duplicate session(s) were merged")
    parts.append(f"{completed} finished cleanly")
    if errored:
        parts.append(f"{errored} ended in errors")
    if interrupted:
        parts.append(f"{interrupted} were interrupted")
    narrative = ". ".join(parts) + "."
    blocked = briefing.get("blocked") or []
    suggestions = []
    for item in blocked[:2]:
        suggestions.append(f"Revisit blocked session: {item.get('title') or item.get('session_id')}")
    return {"narrative": narrative, "suggestions": suggestions, "model": None, "source": "heuristic"}


__all__ = [
    "BRIEFING_VERSION",
    "build_briefing",
    "build_briefing_llm_messages",
    "generate_heuristic_briefing_narrative",
    "parse_briefing_llm_response",
    "render_briefing_markdown",
]
