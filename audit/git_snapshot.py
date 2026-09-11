"""Export-time Git observations; historical verification remains unknown."""
from __future__ import annotations
import os
import shutil
import subprocess
import time
from pathlib import Path

class ObservationError(RuntimeError):
    pass

def _git(cwd: Path, *args: str) -> bytes:
    binary = shutil.which("git")
    if not binary:
        raise ObservationError("git_unavailable")
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run([binary, "--no-optional-locks", "-c", "core.fsmonitor=false",
                           "-c", "core.untrackedCache=false", "-C", str(cwd), *args],
                          capture_output=True, check=True, timeout=5, env=env).stdout

def _dirty_paths(raw: bytes) -> list[str]:
    entries = raw.split(b"\0")
    paths, i = [], 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            continue
        paths.append(os.fsdecode(entry[3:]))
        # In -z mode a rename/copy has destination then original path.
        if b"R" in entry[:2] or b"C" in entry[:2]:
            if i < len(entries) and entries[i]:
                paths.append(os.fsdecode(entries[i]))
            i += 1
    return paths

def legacy_git_state(cwd: str) -> dict:
    """Exact legacy keys for audit/handoff.py; does not invent historical verification.

    This compatibility call only accepts a local explicit absolute directory.
    Network-facing callers MUST use observe_repo with separately granted roots.
    """
    observed_at = int(time.time() * 1000)
    if not isinstance(cwd, str) or not cwd.strip():
        return {"available": False, "reason": "missing_session_cwd", "observed_at": observed_at}
    if not Path(cwd).is_absolute():
        return {"available": False, "reason": "relative_session_cwd", "observed_at": observed_at}
    try:
        candidate = Path(cwd).resolve(strict=True)
        if not candidate.is_dir():
            raise ValueError("not_directory")
        root = os.fsdecode(_git(candidate, "rev-parse", "--show-toplevel")).strip()
        before = _git(candidate, "rev-parse", "HEAD").decode().strip()
        status = _git(candidate, "status", "--porcelain=v1", "-z")
        after = _git(candidate, "rev-parse", "HEAD").decode().strip()
        if before != after:
            return {"available": False, "reason": "head_changed", "observed_at": observed_at}
        return {"available": True, "root": root, "commit": after,
                "workspace": "dirty" if status else "clean", "_paths": _dirty_paths(status),
                "observed_at": observed_at, "content_digest": None,
                "consistency": "best_effort_not_atomic", "verification_baseline": "unknown"}
    except (OSError, ValueError, RuntimeError, UnicodeError, subprocess.SubprocessError):
        return {"available": False, "reason": "git_observation_failed", "observed_at": observed_at}
