"""Explicit local source access; no Web, background thread or model startup."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .service import handoff, search
from .sources import (Indexer, OpenCodeIndexer, HermesStateIndexer, parse_codex_session_file,
                      parse_claude_session_file, parse_openclaw_session_file)


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
    transfer = commands.add_parser("handoff")
    transfer.add_argument("session_id")
    native = commands.add_parser("native-reference", help="Read a content-bound reference for explicit native continuation")
    native.add_argument("session_id")
    native.add_argument("--device-id", required=True, help="Stable local device identity from the coordinator configuration")
    args = parser.parse_args(argv)
    indexer = None
    try:
        source = args.source_path.resolve(strict=True)
        if args.command == "native-reference":
            if args.source != "opencode":
                raise ValueError("native_reference_provider_unsupported")
            from .native import native_reference
            result = {"schema_version": "history.native_candidate.v2", "authorization": "context_only",
                      "observed_at": datetime.now(timezone.utc).isoformat(),
                      "reference": native_reference(source, args.device_id, args.session_id)}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.source in ("opencode", "hermes"):
            if not source.is_file():
                raise ValueError("native_database_file_required")
            indexer = (OpenCodeIndexer if args.source == "opencode" else HermesStateIndexer)(source)
        else:
            if not source.is_dir() or args.data_dir is None:
                raise ValueError("sessions_directory_and_data_dir_required")
            data = args.data_dir.resolve()
            if data == source or source in data.parents:
                raise ValueError("cache_must_be_outside_source_tree")
            data.mkdir(parents=True, exist_ok=True)
            parsers = {"codex": parse_codex_session_file, "claude": parse_claude_session_file,
                       "openclaw": parse_openclaw_session_file}
            filters = {"codex": None, "claude": lambda p: not p.name.startswith("agent-"),
                       "openclaw": lambda p: p.parent.name == "sessions"}
            indexer = Indexer(source, data, args.source, db_filename="index_%s.sqlite" % args.source,
                              parse_file_fn=parsers[args.source], file_filter_fn=filters[args.source],
                              parser_version=1 if args.source == "openclaw" else 5)
        if args.command == "refresh":
            indexer.maybe_update_index(max_age_seconds=0)
            result = {"source": args.source, "status": "refreshed", "native_source_read_only": True}
        elif args.command == "search":
            result = search(indexer, query=args.query, limit=args.limit, offset=args.offset, cwd=args.project)
        elif args.command == "handoff":
            result = handoff(indexer, args.session_id)
        else:
            indexer.conn.execute("SELECT 1").fetchone()
            result = {"source": args.source, "status": "readable", "freshness": "unknown",
                      "background_refresh": False, "refresh_policy": "explicit"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if indexer is not None:
            indexer.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
