"""Versioned local native references. No provider execution, source writes or Web import."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _quote(value):
    return '"' + value.replace('"', '""') + '"'


def content_revision(db, session_id, store_id):
    """SQLite type + hex(value) is identical across Python and TS numeric/Unicode codecs."""
    result = hashlib.sha256((_canonical(["opencode-sqlite-content-v2", store_id]) + "\n").encode())
    count, size = 0, 0
    for table in ("session", "message", "part"):
        columns = sorted(row[1] for row in db.execute("PRAGMA table_info(" + table + ")"))
        if "id" not in columns or len(columns) > 128 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column) for column in columns):
            raise ValueError("unsupported_native_schema")
        predicate = "id" if table == "session" else "session_id"
        lengths = "+".join("length(CAST(%s AS BLOB))" % _quote(column) for column in columns)
        n, byte_count = db.execute("SELECT COUNT(*), COALESCE(SUM(%s),0) FROM %s WHERE %s=?" %
                                   (lengths, table, predicate), (session_id,)).fetchone()
        count += n
        size += byte_count
        if count > 100_000 or size > 32 * 1024 * 1024:
            raise ValueError("native_session_too_large")
        fields = ",".join("typeof(%s),hex(%s)" % (_quote(column), _quote(column)) for column in columns)
        for values in db.execute("SELECT %s FROM %s WHERE %s=? ORDER BY id" % (fields, table, predicate), (session_id,)):
            cells = [[column, values[2 * i], values[2 * i + 1]] for i, column in enumerate(columns)]
            result.update((_canonical([table, cells]) + "\n").encode())
    return result.hexdigest()


def native_reference(source_path, device_id, session_id):
    """Explicit local identity only; an external candidate cannot choose the native store."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,191}", device_id):
        raise ValueError("invalid_device_id")
    if not re.fullmatch(r"ses_[A-Za-z0-9]{1,192}", session_id):
        raise ValueError("invalid_native_session_id")
    supplied = Path(source_path)
    if not supplied.is_absolute():
        raise ValueError("native_store_path_must_be_explicit")
    path = supplied.resolve(strict=True)
    before = path.stat()
    if not path.is_file():
        raise ValueError("native_store_not_regular")
    store_id = hashlib.sha256(_canonical(["opencode-store-v2", device_id, str(path),
                                         str(before.st_dev), str(before.st_ino)]).encode()).hexdigest()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        row = db.execute("SELECT id,directory,project_id,title,time_archived FROM session WHERE id=?", (session_id,)).fetchone()
        if row is None or row["time_archived"]:
            raise ValueError("native_session_missing_or_archived")
        directory = Path(row["directory"])
        if not directory.is_absolute() or not directory.is_dir() or not isinstance(row["project_id"], str):
            raise ValueError("native_directory_unavailable")
        revision = content_revision(db, session_id, store_id)
        latest = db.execute("SELECT data FROM message WHERE session_id=? AND json_valid(data) "
                            "AND json_extract(data,'$.role')='assistant' ORDER BY time_created DESC,id DESC LIMIT 1", (session_id,)).fetchone()
        model = json.loads(latest["data"]) if latest else {}
        after = supplied.stat()
        if supplied.resolve(strict=True) != path or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("native_store_replaced")
        return {"schema_version": "agent.native_session.v2", "provider": "opencode", "device_id": device_id,
                "store_id": store_id, "session_id": session_id, "directory": str(directory.resolve()),
                "project_id": row["project_id"], "revision": revision,
                "model": "%s/%s" % (model["providerID"], model["modelID"]) if isinstance(model, dict)
                and isinstance(model.get("providerID"), str) and isinstance(model.get("modelID"), str) else "",
                "title": (row["title"] or "")[:512]}
