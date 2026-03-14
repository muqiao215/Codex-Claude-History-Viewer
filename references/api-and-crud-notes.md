# API And CRUD Notes

## Upstream Read API (Observed)

`app.py` exposes `do_GET` endpoints:

- `/api/sessions`
- `/api/projects`
- `/api/session/{id}`
- `/api/reindex`
- `/api/claude/sessions`
- `/api/claude/projects`
- `/api/claude/session/{id}`
- `/api/claude/reindex`

No `do_POST`, `do_PUT`, or `do_DELETE` handlers are present in current upstream.

## Why It Feels "Almost CRUD"

The app updates SQLite index tables while reindexing:

- `INSERT OR REPLACE INTO sessions`
- `INSERT INTO messages`
- `DELETE FROM messages` / `DELETE FROM sessions` during index refresh

This is internal index lifecycle management, not user-facing session CRUD.

## Recommended Local CRUD Upgrade Path

### Phase 1 (Safe): Metadata CRUD

Add table:

```sql
CREATE TABLE IF NOT EXISTS session_meta (
  session_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,           -- codex|claude
  custom_title TEXT,
  tags_json TEXT,                 -- JSON array string
  archived INTEGER DEFAULT 0,
  notes TEXT,
  updated_at INTEGER
);
```

Add endpoints:

- `POST /api/meta/session/{id}` create metadata if absent
- `PUT /api/meta/session/{id}` update metadata fields
- `GET /api/meta/session/{id}` read metadata
- `DELETE /api/meta/session/{id}` delete metadata only

Behavior:

- Keep raw JSONL immutable.
- Merge metadata into session response for UI rendering.

### Phase 2 (Optional, Destructive): Source Session Delete

Add explicit endpoint only if user confirms:

- `DELETE /api/source/session/{id}?source=codex|claude`

Safety controls:

1. Resolve file path from indexed `sessions.file_path`.
2. Backup original file to a timestamped backup directory.
3. Delete file only after backup succeeds.
4. Reindex and return backup path + deletion result.

## Windows Smoke Tests

```powershell
curl http://127.0.0.1:8787/api/sessions
curl http://127.0.0.1:8787/api/projects
curl http://127.0.0.1:8787/api/claude/projects
```

If all return JSON, service is healthy.
