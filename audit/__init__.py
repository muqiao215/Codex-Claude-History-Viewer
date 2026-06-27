"""Agent Value Audit layer (plan ``session-audit-plan..md``).

Public surface:

- :data:`AUDIT_VERSION`         bump to force backfill of cached audits.
- :func:`extract_session_audit` build an :class:`AuditPayload` from a JSONL file.
- :func:`patch_db_for_audit`    idempotent SQLite schema migration.
- :func:`serialize_audit_fields` turn a payload into column-ready values.

The extractor is deterministic — no AI is involved (plan 4.1). AI audit lives
in a future milestone and consumes the slimmed payload view from
``schema.to_llm_audit_input``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from .extractor import extract_session_audit, make_evidence_id
from .schema import AuditPayload, to_llm_audit_input

# Bump when the payload shape / scoring formula changes enough that cached
# audits should be regenerated. The Indexer compares this against the stored
# ``audit_version`` column to decide whether to re-extract.
AUDIT_VERSION = 1

# Audit-related columns added to the existing ``sessions`` table (plan 16.1).
AUDIT_COLUMNS = {
    "files_touched_json": "TEXT",
    "tool_summary_json": "TEXT",
    "command_intents_json": "TEXT",
    "outcome_signal": "TEXT",
    "value_score": "INTEGER DEFAULT 0",
    "friction_score": "INTEGER DEFAULT 0",
    "action_density": "REAL DEFAULT 0",
    "remote_context_json": "TEXT",
    "audit_status": "TEXT DEFAULT 'not_started'",
    "audit_json": "TEXT",
    "audit_updated_at": "INTEGER",
    "audit_version": "INTEGER",
}


def patch_db_for_audit(conn: sqlite3.Connection) -> None:
    """Add the audit columns to ``sessions`` if they are missing.

    Safe to call on every startup. Uses ``PRAGMA table_info`` so it works on
    brand-new and pre-existing databases alike (plan 16.2).
    """
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(sessions)")
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        # Table does not exist yet — the caller's own CREATE will run after us.
        conn.commit()
        return

    existing = {str(row[1]) for row in rows} if rows else set()
    for column, decl in AUDIT_COLUMNS.items():
        if column in existing:
            continue
        try:
            cur.execute(f"ALTER TABLE sessions ADD COLUMN {column} {decl};")
        except sqlite3.OperationalError:
            # Another process may have added it concurrently; ignore.
            pass
    conn.commit()


def serialize_audit_fields(payload: AuditPayload) -> Dict[str, Any]:
    """Flatten an :class:`AuditPayload` into DB-ready column values.

    Scalar fields (``value_score`` etc.) are stored as real columns so the
    session list can sort / filter without JSON parsing. The richer structures
    are stored as JSON TEXT for the detail view + future AI audit.
    """
    data = payload.to_dict()
    return {
        "files_touched_json": json.dumps(data["files_touched"], ensure_ascii=False),
        "tool_summary_json": json.dumps(data["tools_used"], ensure_ascii=False),
        "command_intents_json": json.dumps(data["command_intents"], ensure_ascii=False),
        "remote_context_json": json.dumps(data["remote_context"], ensure_ascii=False),
        "outcome_signal": data["outcome_signal"],
        "value_score": int(data["value_score"]),
        "friction_score": int(data["friction_score"]),
        "action_density": float(data["action_density"]),
        "audit_status": "extracted",
        "audit_updated_at": None,  # filled by the caller with a real timestamp
        "audit_version": AUDIT_VERSION,
        # ``audit_json`` is reserved for the future AI audit layer; left NULL.
    }


def deserialize_audit_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the JSON audit columns back into dicts for API consumption.

    Returns a plain dict with ``files_touched`` / ``tools_used`` /
    ``command_intents`` / ``remote_context`` keys (empty containers on missing
    or malformed data — never raises).
    """
    def _loads(value: Any, default: Any) -> Any:
        if not value:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    return {
        "files_touched": _loads(row.get("files_touched_json"), {"local": [], "remote": [], "inferred": []}),
        "tools_used": _loads(row.get("tool_summary_json"), {}),
        "command_intents": _loads(row.get("command_intents_json"), {}),
        "remote_context": _loads(row.get("remote_context_json"), {}),
        "outcome_signal": row.get("outcome_signal") or "unknown",
        "value_score": int(row.get("value_score") or 0),
        "friction_score": int(row.get("friction_score") or 0),
        "action_density": float(row.get("action_density") or 0.0),
    }


def build_audit_for_file(
    path: Path,
    source: str,
    *,
    session_id_hint: Optional[str] = None,
) -> Optional[AuditPayload]:
    """Thin wrapper used by the Indexer so it can mock the extractor in tests."""
    return extract_session_audit(path, source, session_id_hint=session_id_hint)


__all__ = [
    "AUDIT_VERSION",
    "AUDIT_COLUMNS",
    "AuditPayload",
    "build_audit_for_file",
    "deserialize_audit_summary",
    "extract_session_audit",
    "make_evidence_id",
    "patch_db_for_audit",
    "serialize_audit_fields",
    "to_llm_audit_input",
]
