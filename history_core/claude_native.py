"""Strict Claude JSONL identity for native continuation; separate from tolerant display parsing."""
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .native import _canonical

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def claude_content_revision(store_id, raw):
    return hashlib.sha256((_canonical(["claude-jsonl-content-v2", store_id]) + "\n").encode() + raw).hexdigest()


def claude_native_reference(source_path, device_id, session_id):
    """The caller supplies one canonical transcript file, never a filename from a candidate."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,191}", device_id):
        raise ValueError("invalid_device_id")
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError("invalid_native_session_id")
    path = Path(source_path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("native_store_path_must_be_canonical")
    if path.name != session_id + ".jsonl":
        raise ValueError("native_session_path_mismatch")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("native_store_not_regular")
    if before.st_size > MAX_BYTES:
        raise ValueError("native_session_too_large")
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            raise ValueError("native_store_changed")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > MAX_BYTES:
        raise ValueError("native_session_too_large")
    if _identity(before) != _identity(after) or _identity(path.lstat()) != _identity(before) or path.resolve(strict=True) != path:
        raise ValueError("native_store_changed")
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("native_transcript_incomplete")
    lines = raw.decode("utf-8", errors="strict").split("\n")[:-1]
    if len(lines) > MAX_ROWS:
        raise ValueError("native_session_too_large")
    rows = [json.loads(line) for line in lines]
    directory, model, title, messages = None, "", "", 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("unsupported_native_schema")
        if "sessionId" in row and row["sessionId"] != session_id:
            raise ValueError("native_session_mismatch")
        if row.get("type") in ("user", "assistant"):
            message = row.get("message")
            if row.get("sessionId") != session_id or row.get("isSidechain") is True or not isinstance(message, dict) or message.get("role") != row["type"]:
                raise ValueError("unsupported_native_lineage")
            cwd = row.get("cwd")
            if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
                raise ValueError("native_directory_unavailable")
            current = str(Path(cwd).resolve(strict=True))
            if directory is not None and directory != current:
                raise ValueError("native_directory_changed")
            directory = current
            messages += 1
            if row["type"] == "assistant" and isinstance(message.get("model"), str) and not message["model"].startswith("<"):
                model = message["model"]
        value = row.get("customTitle") if row.get("type") == "custom-title" else row.get("aiTitle") if row.get("type") == "ai-title" else None
        if isinstance(value, str):
            title = value[:512]
    if not messages or directory is None:
        raise ValueError("native_session_missing")
    store_id = hashlib.sha256(_canonical(["claude-jsonl-store-v2", device_id, str(path), str(before.st_dev), str(before.st_ino)]).encode()).hexdigest()
    revision = claude_content_revision(store_id, raw)
    project_id = hashlib.sha256(_canonical(["claude-project-v2", directory]).encode()).hexdigest()
    return {"schema_version": "agent.native_session.v2", "provider": "claude", "device_id": device_id,
            "store_id": store_id, "session_id": session_id, "directory": directory, "project_id": project_id,
            "revision": revision, "model": model, "title": title}
