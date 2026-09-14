"""Shared read model for machine callers and the optional human workspace."""
from datetime import datetime, timezone

from audit.handoff import build_handoff_bundle
from .provenance import selected_audit, validate_native_size


def search(indexer, *, query=None, limit=20, offset=0, cwd=None, stable_order=False):
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("invalid_pagination")
    kwargs = {"stable_order": True} if stable_order else {}
    return indexer.list_sessions_page(q=query, limit=limit, offset=offset, cwd=cwd, sort="last", **kwargs)


def handoff(indexer, session_id, *, include_plans=False):
    validate_native_size(indexer, session_id)
    metadata = indexer.get_session_metadata(session_id)
    if metadata is None:
        raise ValueError("session_not_found")
    audit, provenance = selected_audit(indexer, session_id)
    if audit is None:
        raise ValueError("audit_not_supported_or_unavailable")
    result = build_handoff_bundle(audit, metadata=metadata, provenance=provenance)
    if include_plans:
        from pathlib import Path
        from .sources import scan_plan_files
        from audit.handoff import render_handoff
        cwd = metadata.get("cwd") or ""
        plans = scan_plan_files(cwd) if cwd and Path(cwd).is_absolute() else []
        result["payload"]["specmesh"] = {
            "status": "candidate_context" if plans else "missing", "authority": "unverified_project_files",
            "files": [{"path": p.get("rel_path"), "mtime_ms": p.get("mtime_ms"),
                       "sections": {str(k): str(v)[:600] for k, v in (p.get("sections") or {}).items()}}
                      for p in plans[:3]],
            "max_files": 3, "max_section_chars": 600,
        }
        result["compact"] = render_handoff(result["payload"], "compact")
        result["standard"] = render_handoff(result["payload"], "standard")
    result["schema_version"] = "history.handoff.v1"
    result["authorization"] = "context_only"
    return result


def workspace(indexers, limit=12):
    """History-derived work, never claimed to be live CM task state."""
    candidates, errors = [], []
    for system, source, indexer in indexers:
        try:
            page = search(indexer, limit=limit)
            for row in page["items"]:
                candidates.append((row.get("end_ts_ms") or row.get("start_ts_ms") or 0,
                                   system, source, indexer, row))
        except Exception:
            errors.append({"system": system, "source": source, "error": "source_unavailable"})
    candidates.sort(key=lambda item: item[0], reverse=True)
    work = []
    for updated, system, source, indexer, row in candidates[:limit]:
        item = {"id": row["id"], "system": system, "source": source,
                "title": row.get("title") or row["id"], "project": row.get("cwd") or None,
                "updated_at": updated, "status": "unknown", "goal": None,
                "next_action": "核对当前项目状态后继续", "verified": [], "changed": [], "remaining": [], "blockers": [], "decisions": [], "evidence": [],
                "origin": "historical_evidence", "live_task_state": "unknown"}
        try:
            payload = handoff(indexer, row["id"])["payload"]
            for key in ("goal", "status", "verified", "changed", "remaining", "blockers", "decisions", "evidence"):
                item[key] = payload.get(key, item[key])
            item["next_action"] = payload.get("next_action") or item["next_action"]
        except (ValueError, OSError):
            item["evidence_status"] = "unavailable"
        work.append(item)
    return {"schema_version": "history.workspace.v1", "mode": "history_snapshot",
            "observed_at": datetime.now(timezone.utc).isoformat(), "work": work, "errors": errors}
