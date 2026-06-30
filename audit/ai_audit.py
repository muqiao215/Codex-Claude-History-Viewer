"""Optional AI audit layer (plan 002 §M6 / spec §18).

Two generation paths:
- ``generate_heuristic_audit`` — deterministic, stdlib-only, no network.
  Produces a structured judgment purely from the deterministic audit signals.
- ``generate_llm_audit`` — calls an OpenAI-compatible chat completions
  endpoint (via :mod:`audit.llm_client`) and parses the model's JSON response.

Both paths return the same ``audit_json`` schema so the storage + UI layer
treats them identically. The ``source`` field ("heuristic" | "llm") keeps the
UI honest about which path produced the judgment.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# BDD: 002 §M6 acceptance — value_score threshold below which we refuse to audit.
VALUE_SCORE_THRESHOLD = 20

AI_AUDIT_SCHEMA_VERSION = 1

CHECKLIST_STATUSES = ("done", "partial", "skipped", "failed")

# Outcome → default checklist status when no per-item signal exists.
_OUTCOME_DEFAULT_STATUS = {
    "completed": "done",
    "partially_completed": "partial",
    "errored": "failed",
    "interrupted": "skipped",
    "incomplete": "partial",
    "exploration": "skipped",
    "unknown": "skipped",
}

_COMMAND_INTENT_LABELS = {
    "TEST": "Run tests",
    "BUILD": "Build the project",
    "DEPLOY": "Deploy or ship changes",
    "REMOTE": "Run remote/SSH commands",
    "NETWORK": "Fetch from network",
    "DEBUG": "Debug or diagnose",
    "SEARCH": "Search the codebase",
    "READ": "Read files",
    "UNKNOWN": "Run shell commands",
}


# ---------------------------------------------------------------------------
# Heuristic path (deterministic, no LLM)
# ---------------------------------------------------------------------------

def generate_heuristic_audit(llm_input: Dict[str, Any]) -> Dict[str, Any]:
    """Build an audit_json dict purely from the deterministic signals.

    Never calls a network or model — this is the zero-config default that
    makes the feature useful out of the box. When an LLM provider is
    configured, :func:`generate_llm_audit` replaces this output.
    """
    outcome = str(llm_input.get("outcome_signal") or "unknown")
    default_status = _OUTCOME_DEFAULT_STATUS.get(outcome, "skipped")
    errors = llm_input.get("errors") or {}
    err_count = int(errors.get("count") or 0)
    err_samples = errors.get("samples") or []

    intent = _derive_intent(llm_input)
    checklist = _derive_checklist(llm_input, default_status)
    deliverables = _derive_deliverables(llm_input)
    gaps = _derive_gaps(llm_input, outcome, err_count, err_samples)
    next_action = _derive_next_action(outcome, err_count)

    return _wrap_audit(
        source="heuristic",
        model=None,
        user_intent=intent,
        checklist=checklist,
        deliverables=deliverables,
        gaps=gaps,
        next_action=next_action,
    )


def _derive_intent(llm_input: Dict[str, Any]) -> str:
    prompt = str(llm_input.get("first_user_prompt") or "").strip()
    if not prompt:
        prompt = str(llm_input.get("last_user_prompt") or "").strip()
    if not prompt:
        prompts = llm_input.get("important_user_prompts") or []
        if prompts:
            prompt = str(prompts[0]).strip()
    if not prompt:
        return "(No user prompt recorded — intent could not be inferred.)"
    # Collapse whitespace + cap for readability.
    compact = " ".join(prompt.split())
    return compact[:280] + ("…" if len(compact) > 280 else "")


def _derive_checklist(llm_input: Dict[str, Any], default_status: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    evidence = llm_input.get("evidence") or []

    ft = llm_input.get("files_touched") or {}
    for bucket in ("local", "remote", "inferred"):
        for fp in (ft.get(bucket) or []):
            if not isinstance(fp, dict):
                continue
            path = str(fp.get("path") or "").strip()
            if not path:
                continue
            writes = int(fp.get("write_count") or 0)
            edits = int(fp.get("edit_count") or 0)
            if writes > 0 and edits == 0:
                verb = "Create"
            elif edits > 0 and writes == 0:
                verb = "Modify"
            else:
                verb = "Touch"
            ev_id = _find_file_evidence_id(evidence, path)
            items.append({
                "item": f"{verb} {path}",
                "status": default_status,
                "evidence_ids": [ev_id] if ev_id else [],
            })
            if len(items) >= 12:
                return items

    intents = llm_input.get("command_intents") or {}
    for key, count in sorted(intents.items(), key=lambda kv: (kv[1] or 0), reverse=True):
        n = int(count or 0)
        if n <= 0:
            continue
        label = _COMMAND_INTENT_LABELS.get(str(key).upper(), f"Run {key} commands")
        items.append({
            "item": f"{label} ({n}×)",
            "status": default_status,
            "evidence_ids": [],
        })
        if len(items) >= 12:
            break

    return items


def _find_file_evidence_id(evidence: List[Any], path: str) -> Optional[str]:
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "file" and str(ev.get("summary") or "").endswith(path):
            return ev.get("id")
        raw = ev.get("raw_ref") or {}
        if isinstance(raw, dict) and str(raw.get("path") or "") == path:
            return ev.get("id")
    return None


def _derive_deliverables(llm_input: Dict[str, Any]) -> List[str]:
    ft = llm_input.get("files_touched") or {}
    seen = set()
    out: List[str] = []
    for bucket in ("local", "remote"):
        for fp in (ft.get(bucket) or []):
            if not isinstance(fp, dict):
                continue
            p = str(fp.get("path") or "").strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out[:20]


def _derive_gaps(
    llm_input: Dict[str, Any],
    outcome: str,
    err_count: int,
    err_samples: List[Any],
) -> List[str]:
    gaps: List[str] = []
    if err_count > 0:
        sample = ""
        if err_samples:
            sample = str(err_samples[0])[:120].replace("\n", " ")
        gaps.append(f"{err_count} error(s) recorded" + (f": {sample}" if sample else ""))
    if outcome in ("interrupted", "incomplete", "unknown"):
        gaps.append(f"Session ended {outcome} — deliverables may be incomplete.")
    if outcome == "errored":
        gaps.append("Primary task likely failed; review before relying on output.")
    value = int(llm_input.get("outcome_signal") and 0 or 0)
    reply = str(llm_input.get("last_assistant_reply") or "").strip()
    if not reply:
        gaps.append("No assistant reply recorded — final state uncertain.")
    return gaps or ["No significant gaps detected from deterministic signals."]


def _derive_next_action(outcome: str, err_count: int) -> str:
    if outcome == "errored" or err_count > 0:
        return "Investigate and resolve the recorded errors before retrying."
    if outcome in ("partially_completed", "incomplete"):
        return "Complete the remaining work items and re-verify."
    if outcome == "completed":
        return "Consider archiving this session or documenting the outcome."
    return "Review the session transcript for concrete next steps."


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = (
    "You are an expert code reviewer auditing an AI coding agent's session. "
    "Given the session's deterministic audit signals (extracted from the transcript), "
    "produce a structured judgment of whether the user's intent was delivered. "
    "Return STRICT JSON only — no markdown fences, no commentary.\n\n"
    "Schema:\n"
    "{\n"
    '  "user_intent": "1-2 sentences: what the user actually wanted",\n'
    '  "checklist": [{"item": "concrete verifiable task", '
    '"status": "done|partial|skipped|failed", "evidence_ids": ["id from provided evidence"]}],\n'
    '  "deliverables": ["file path or concrete artifact"],\n'
    '  "gaps": ["what is missing, incomplete, or broken"],\n'
    '  "next_action": "one actionable sentence"\n'
    "}\n\n"
    "Use the evidence_ids provided in the input. Keep items concise. "
    "Be honest — if the session failed, say so in gaps and next_action."
)


def build_llm_messages(llm_input: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build the OpenAI-style messages list for the LLM audit call."""
    payload_str = json.dumps(llm_input, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Session audit signals:\n\n{payload_str}"},
    ]


def parse_llm_json_response(raw: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Extract + validate an audit_json dict from the model's raw text response.

    Tolerates markdown code fences and leading/trailing prose. Raises
    ``ValueError`` with a useful message if no valid JSON object can be
    recovered or the schema is wrong.
    """
    if not raw or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()
    # Strip markdown fences if present (```json ... ``` or ``` ... ```).
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Fallback: grab the outermost {...} block.
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc.msg}") from exc
    validated = validate_audit_json(obj)
    validated["source"] = "llm"
    validated["model"] = model
    return validated


# ---------------------------------------------------------------------------
# Shared validation + wrapping
# ---------------------------------------------------------------------------

def validate_audit_json(obj: Any) -> Dict[str, Any]:
    """Check required fields + normalise statuses. Raises ValueError on violation."""
    if not isinstance(obj, dict):
        raise ValueError("audit_json must be a JSON object")
    for field in ("user_intent", "checklist", "deliverables", "gaps", "next_action"):
        if field not in obj:
            raise ValueError(f"audit_json missing required field: {field}")
    intent = str(obj["user_intent"] or "").strip()
    if not intent:
        raise ValueError("audit_json.user_intent is empty")
    next_action = str(obj["next_action"] or "").strip()
    if not next_action:
        raise ValueError("audit_json.next_action is empty")

    checklist = obj["checklist"]
    if not isinstance(checklist, list):
        raise ValueError("audit_json.checklist must be an array")
    clean_cl: List[Dict[str, Any]] = []
    for item in checklist:
        if not isinstance(item, dict):
            continue
        text = str(item.get("item") or "").strip()
        if not text:
            continue
        status = str(item.get("status") or "skipped").strip().lower()
        if status not in CHECKLIST_STATUSES:
            status = "skipped"
        ev_ids = item.get("evidence_ids") or []
        if not isinstance(ev_ids, list):
            ev_ids = []
        clean_cl.append({
            "item": text[:200],
            "status": status,
            "evidence_ids": [str(e) for e in ev_ids if e][:10],
        })
    obj["checklist"] = clean_cl or [{"item": "(No checklist items derived.)", "status": "skipped", "evidence_ids": []}]

    for field in ("deliverables", "gaps"):
        val = obj[field]
        if not isinstance(val, list):
            obj[field] = [str(val)] if val else []
        else:
            obj[field] = [str(v).strip() for v in val if str(v).strip()][:30]
    obj["user_intent"] = intent[:500]
    obj["next_action"] = next_action[:300]
    return obj


def _wrap_audit(
    *,
    source: str,
    model: Optional[str],
    user_intent: str,
    checklist: List[Dict[str, Any]],
    deliverables: List[str],
    gaps: List[str],
    next_action: str,
) -> Dict[str, Any]:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "source": source,
        "model": model,
        "generated_at": int(time.time() * 1000),
        "user_intent": user_intent,
        "checklist": checklist,
        "deliverables": deliverables,
        "gaps": gaps,
        "next_action": next_action,
    }


def meets_cost_guard(value_score: int, threshold: int = VALUE_SCORE_THRESHOLD) -> Tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok."""
    if int(value_score) < int(threshold):
        return False, f"value_score {value_score} below threshold {threshold} — not worth auditing."
    return True, ""
