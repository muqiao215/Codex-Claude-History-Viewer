# Machine handoff and human workspace: first integration

## Human product surface
`/` and `/workspace` show evidence-backed recent progress and items requiring review. Roles, theme, filtering and cleanup remain in the secondary `/history` interface. Each card links to its exact source/session and exposes supporting evidence. The overview describes a historical snapshot; it does not claim live TaskHub completion, blockers or authorization when those facts are unavailable.

`static/workspace.*` reuses the existing visual tokens, system fonts and no-build delivery. `static/app.js` accepts encoded system/source/session links. Historical paths are shortened for the card but retained in the data. Human first-use research can be useful later; it is not the gate replacing the user's primary Agent handoff objective.

## Independent machine interface
The existing source parsers/indexers moved from `app.py` to `history_core/sources.py`; `app.py` reexports symbols for compatibility and retains HTTP/platform bootstrap. `history_core/service.py` exposes search, handoff and workspace assembly without importing the Web server. `audit/git_snapshot.py` records current Git observations with full HEAD and explicit unavailable/unknown states. Export-time Git state is not historical validation evidence.

```sh
python -B -m history_core --source codex --source-path /absolute/sessions --data-dir /absolute/separate-cache refresh
python -B -m history_core --source codex --source-path /absolute/sessions --data-dir /absolute/separate-cache search --query specmesh
python -B -m history_core --source codex --source-path /absolute/sessions --data-dir /absolute/separate-cache handoff SESSION_ID
python -B -m history_core --source opencode --source-path /absolute/opencode.db health
```

JSONL sources require a separate derived-cache directory; OpenCode/Hermes databases are opened through existing read-only adapters. No automatic HOME scan, Web launch, provider run or background thread is started by this CLI. Refresh is explicit; health reports readability and unknown freshness. Search may initialize derived cache, not source records. Existing Indexer internals still expose legacy mutation methods: this is not yet a capability-isolated service API.

Handoff is context-only. Native resume and current SpecMesh files complement each other, and neither an exported summary nor a copied resume command proves successful provider continuation. Hermes remains limited by its existing adapter's evidence capabilities.

## Verification and remaining work
Regression coverage includes existing parsers/audits/UI, subprocess imports without app/http.server, real JSONL parsing through CLI and source preservation. Synthetic browser verification covers the new homepage, mobile layout and deep link to the selected historical session. Real two-Agent takeover, long-running incremental headless service, Windows acceptance and live CM state integration are not established by these checks. No existing destructive cleanup policy was changed by moving its entry point.
