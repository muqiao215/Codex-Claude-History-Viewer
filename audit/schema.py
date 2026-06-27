"""Typed data containers for the Agent Value Audit layer.

These structures are the contract between:
- the deterministic extractor (what actually happened)
- the SQLite cache
- the API / frontend
- the (optional) AI auditor (which only consumes a slimmed view of the payload)

Everything here is JSON-serialisable via ``to_dict`` / ``from_dict`` so it can be
stored in SQLite TEXT columns and shipped over HTTP without extra adapter layers.
The schema intentionally mirrors the plan in ``session-audit-plan..md`` sections
7, 8 and 9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Confidence levels. Keep ordering from low -> high; used by callers that want
# to filter speculative signals (inferred) from authoritative ones (high).
CONFIDENCE_LEVELS = ("low", "medium", "high")

# Outcome enumeration (plan 14.1).
OUTCOME_VALUES = (
    "completed",
    "partially_completed",
    "errored",
    "interrupted",
    "incomplete",
    "exploration",
    "unknown",
)


@dataclass
class Evidence:
    """A single auditable fact that can be referenced by an LLM audit.

    The ``id`` is globally unique (session-scoped, see plan 8.1) so it can be
    used as a frontend anchor target without colliding across sessions.
    """

    id: str
    session_id: str
    type: str  # tool_call | file | command | error | message
    summary: str = ""
    confidence: str = "medium"
    tool_name: Optional[str] = None
    message_index: Optional[int] = None
    raw_ref: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "type": self.type,
            "summary": self.summary,
            "confidence": self.confidence,
            "tool_name": self.tool_name,
            "message_index": self.message_index,
            "raw_ref": dict(self.raw_ref or {}),
        }


@dataclass
class FileFootprint:
    """Per-file mutation summary.

    ``net_value_weight`` is the ghost-modification discount in [0, 1] applied
    when a file was edited many times on an errored/interrupted session
    (plan 10). ``1.0`` means full credit.
    """

    path: str
    edit_count: int = 0
    write_count: int = 0
    confidence: str = "high"  # high (tool) / medium (ssh inferred) / low (text inferred)
    remote: bool = False
    source: str = "tool"  # tool | ssh | inferred
    net_value_weight: float = 1.0
    final_outcome: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "edit_count": self.edit_count,
            "write_count": self.write_count,
            "confidence": self.confidence,
            "remote": self.remote,
            "source": self.source,
            "net_value_weight": self.net_value_weight,
            "final_outcome": self.final_outcome,
        }


@dataclass
class AuditEvent:
    """A normalised, source-agnostic view of one JSONL record.

    Each source parser (codex / claude / openclaw) converts its raw payload
    into a stream of these so the shared extractor only deals with one shape.
    """

    ts_ms: int
    role: str  # user | assistant | system | developer | tool | other
    kind: str  # message | reasoning | tool_use | tool_result | other
    text: str = ""
    tool_name: Optional[str] = None
    tool_args: Any = None  # dict or raw string
    tool_result_error: Optional[bool] = None
    tool_result_text: str = ""
    line_no: Optional[int] = None


@dataclass
class AuditPayload:
    """The full deterministic audit payload for one session."""

    session_id: str
    source: str = ""
    model: str = ""
    started_at: int = 0
    ended_at: int = 0
    duration_ms: int = 0

    first_user_prompt: str = ""
    last_user_prompt: str = ""
    important_user_prompts: List[str] = field(default_factory=list)
    last_assistant_reply: str = ""

    message_count: Dict[str, int] = field(default_factory=dict)
    tools_used: Dict[str, int] = field(default_factory=dict)

    files_touched: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=lambda: {"local": [], "remote": [], "inferred": []}
    )
    file_mutation_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    command_intents: Dict[str, int] = field(default_factory=dict)
    remote_context: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, Any] = field(default_factory=lambda: {"count": 0, "samples": []})

    outcome_signal: str = "unknown"
    value_score: int = 0
    friction_score: int = 0
    action_density: float = 0.0

    parse_errors: int = 0
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "first_user_prompt": self.first_user_prompt,
            "last_user_prompt": self.last_user_prompt,
            "important_user_prompts": list(self.important_user_prompts),
            "last_assistant_reply": self.last_assistant_reply,
            "message_count": dict(self.message_count),
            "tools_used": dict(self.tools_used),
            "files_touched": {
                k: list(v) for k, v in self.files_touched.items()
            } if self.files_touched else {"local": [], "remote": [], "inferred": []},
            "file_mutation_stats": {
                k: dict(v) for k, v in self.file_mutation_stats.items()
            },
            "command_intents": dict(self.command_intents),
            "remote_context": dict(self.remote_context),
            "errors": dict(self.errors),
            "outcome_signal": self.outcome_signal,
            "value_score": int(self.value_score),
            "friction_score": int(self.friction_score),
            "action_density": float(self.action_density),
            "parse_errors": int(self.parse_errors),
            "evidence": [dict(e) for e in self.evidence],
        }


# ---------------------------------------------------------------------------
# Slimmed payload consumed by the (optional) LLM auditor (plan 18.2).
# Kept here so backend + any future AI layer agree on the contract.
# ---------------------------------------------------------------------------

LLM_AUDIT_INPUT_FIELDS = (
    "first_user_prompt",
    "important_user_prompts",
    "last_user_prompt",
    "last_assistant_reply",
    "files_touched",
    "tools_used",
    "command_intents",
    "errors",
    "outcome_signal",
    "evidence",
)


def to_llm_audit_input(payload: AuditPayload) -> Dict[str, Any]:
    """Return the minimal view of the payload that is safe to send to an LLM.

    Full JSONL transcripts are never sent to the model — only this compressed
    evidence view (plan section 5).
    """
    data = payload.to_dict()
    return {k: data.get(k) for k in LLM_AUDIT_INPUT_FIELDS}
