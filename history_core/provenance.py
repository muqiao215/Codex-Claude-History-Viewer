"""Bounded selected-source snapshots for ordinary context-only handoffs."""
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from audit import extract_session_audit_bytes

MAX_SOURCE_BYTES = 2 * 1024 * 1024


def validate_native_size(indexer, session_id):
    """Bound the actual joined row text loaded by OpenCode's audit reader."""
    if getattr(indexer, 'source', '') != 'opencode':
        return
    with indexer.lock:
        row = indexer.conn.execute(
            "SELECT COALESCE(SUM(length(CAST(p.data AS BLOB)) + length(CAST(m.data AS BLOB))), 0), COUNT(*) "
            "FROM part p JOIN message m ON m.id = p.message_id WHERE p.session_id = ?",
            (str(session_id),)).fetchone()
    if int(row[0]) > MAX_SOURCE_BYTES or int(row[1]) > 10000:
        raise ValueError('handoff_source_limit_exceeded')


def selected_audit(indexer, session_id):
    """Read only the chosen JSONL, and extract from precisely the hashed bytes."""
    source = getattr(indexer, 'source', '')
    root = getattr(indexer, 'sessions_dir', None)
    if root is None or source not in ('codex', 'claude', 'openclaw'):
        validate_native_size(indexer, session_id)
        build = getattr(indexer, 'build_session_audit', None)
        return (build(session_id) if build else None), {
            'status': 'unknown', 'reason': 'native_database_revision_not_captured',
            'source': source or 'unknown', 'session_id': str(session_id),
            'locator': {'session_id': str(session_id)},
            'content_revision': 'unknown', 'truncated': False,
        }
    with indexer.lock:
        row = indexer.conn.execute('SELECT * FROM sessions WHERE id = ?', (str(session_id),)).fetchone()
    if not row:
        return None, {}
    path = Path(row['file_path'])
    root = Path(root).absolute()
    if root not in path.absolute().parents:
        raise ValueError('cached_source_path_outside_selection')
    current = path.absolute()
    while True:
        if current.is_symlink():
            raise ValueError('source_symlink_not_allowed')
        if current == root:
            break
        current = current.parent
    if root.resolve(strict=True) not in path.resolve(strict=True).parents:
        raise ValueError('cached_source_path_outside_selection')
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        signature = json.dumps([before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_dev, before.st_ino])
        if 'file_signature' in row.keys() and row['file_signature'] and row['file_signature'] != signature:
            raise ValueError('source_changed_since_index: refresh required')
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('source_regular_file_required')
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    truncated = len(raw) > MAX_SOURCE_BYTES
    raw = raw[:MAX_SOURCE_BYTES]
    # Exclude the incomplete trailing JSONL record, preserving line references.
    if truncated:
        raw = raw[:raw.rfind(b'\n') + 1]
    stable = (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    extracted = extract_session_audit_bytes(raw, source, session_id_hint=str(session_id))
    audit = extracted.to_dict() if extracted else None
    if audit is not None and (truncated or not stable):
        audit['outcome_signal'] = 'unknown'
        audit['has_assistant_after_last_user'] = False
    digest = hashlib.sha256(raw).hexdigest()
    return audit, {
        'status': 'captured' if stable else 'unknown',
        'reason': 'source_changed_during_read' if not stable else ('bounded_prefix' if truncated else None),
        'source': source, 'session_id': str(session_id),
        'locator': {'path': str(path), 'format': 'jsonl', 'line_numbering': 'one_based'},
        'content_revision': 'sha256:' + digest if stable and not truncated else 'unknown',
        'context_revision': 'sha256:' + digest, 'bytes_captured': len(raw),
        'byte_limit': MAX_SOURCE_BYTES, 'truncated': truncated,
        'observed_at': datetime.now(timezone.utc).isoformat(),
    }
