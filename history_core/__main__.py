"""Explicit local source access; no Web, background thread or model startup."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .reader import HistoryReader


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("codex", "claude", "openclaw", "opencode", "hermes"), required=True)
    parser.add_argument("--source-path", type=Path, required=True, help="Explicit sessions directory or native SQLite file")
    parser.add_argument("--data-dir", type=Path, help="Required separate cache directory for JSONL sources")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh")
    commands.add_parser("health")
    query = commands.add_parser("search")
    query.add_argument("--query", default=None)
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    query.add_argument("--project", default=None)
    query.add_argument("--index-revision", default=None, help="Previous page revision; required for offset > 0 in a new process")
    transfer = commands.add_parser("handoff")
    transfer.add_argument("session_id")
    transfer.add_argument("--include-plans", action="store_true", help="Explicitly include bounded project-file candidates; not verified decisions")
    native = commands.add_parser("native-reference", help="Read a content-bound reference for explicit native continuation")
    native.add_argument("session_id")
    native.add_argument("--device-id", required=True, help="Stable local device identity from the coordinator configuration")
    args = parser.parse_args(argv)
    reader = None
    try:
        source = args.source_path.resolve(strict=True)
        if args.command == "native-reference":
            if args.source not in ("opencode", "claude", "codex"):
                raise ValueError("native_reference_provider_unsupported")
            from .native import native_reference
            from .claude_native import claude_native_reference
            from .codex_native import codex_native_reference
            reference = {"opencode": native_reference, "claude": claude_native_reference, "codex": codex_native_reference}[args.source]
            result = {"schema_version": "history.native_candidate.v2", "authorization": "context_only",
                      "observed_at": datetime.now(timezone.utc).isoformat(),
                      "reference": reference(args.source_path, args.device_id, args.session_id)}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        reader = HistoryReader(args.source, source, args.data_dir)
        if args.command == "refresh":
            result = reader.refresh()
        elif args.command == "search":
            result = reader.search(query=args.query, limit=args.limit, offset=args.offset, cwd=args.project, index_revision=args.index_revision)
        elif args.command == "handoff":
            result = reader.handoff(args.session_id, include_plans=args.include_plans)
        else:
            result = reader.health()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if reader is not None:
            reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
