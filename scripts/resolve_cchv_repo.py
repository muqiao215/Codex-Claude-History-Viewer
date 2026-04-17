#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path


REPO_NAME = "Codex-Claude-History-Viewer"


def is_repo_dir(path: Path) -> bool:
    try:
        candidate = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return (candidate / "app.py").is_file() and (candidate / "static").is_dir()


def iter_probe_candidates(script_dir: Path, cwd: Path, home: Path):
    roots = []
    for root in (script_dir, cwd):
        if not root:
            continue
        root = Path(root).expanduser()
        roots.append(root)
        roots.extend(root.parents)

    seen_roots = set()
    for root in roots:
        try:
            resolved_root = root.resolve()
        except (OSError, RuntimeError):
            continue
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)
        yield resolved_root
        yield resolved_root / REPO_NAME
        yield resolved_root / "repos" / REPO_NAME

    if home:
        home = Path(home).expanduser()
        yield home / ".ductor" / "workspace" / "repos" / REPO_NAME
        yield home / "web" / "tools" / REPO_NAME

    yield Path("/mnt/e/web/tools") / REPO_NAME


def resolve_repo_dir(hint=None, script_dir=None, cwd=None, env=None, home=None):
    env = dict(os.environ if env is None else env)
    script_dir = Path(script_dir).expanduser() if script_dir else Path(__file__).resolve().parent
    cwd = Path(cwd).expanduser() if cwd else Path.cwd()
    home = Path(home).expanduser() if home else Path.home()

    candidates = []
    for value in (
        hint,
        env.get("REPO_DIR"),
        env.get("CCHV_REPO_DIR"),
        env.get("CCHV_WORKSPACE_ROOT") and Path(env["CCHV_WORKSPACE_ROOT"]) / "repos" / REPO_NAME,
    ):
        if value:
            candidates.append(Path(value).expanduser())

    candidates.extend(iter_probe_candidates(script_dir=script_dir, cwd=cwd, home=home))

    seen = set()
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_repo_dir(resolved):
            return resolved
    return None


def main():
    parser = argparse.ArgumentParser(description="Resolve the Codex Claude History Viewer repo directory")
    parser.add_argument("--hint", default="")
    parser.add_argument("--script-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--cwd", default=str(Path.cwd()))
    args = parser.parse_args()

    repo_dir = resolve_repo_dir(hint=args.hint, script_dir=args.script_dir, cwd=args.cwd)
    if not repo_dir:
        print("CCHV repo not found. Set REPO_DIR or CCHV_REPO_DIR.", file=sys.stderr)
        return 1
    print(repo_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
