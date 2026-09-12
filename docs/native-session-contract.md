# Native session reference v2

The explicit headless command `python -m history_core --source opencode --source-path /absolute/opencode.db native-reference <session-id> --device-id <configured-device>` returns a `history.native_candidate.v2` envelope with `authorization: context_only`, an informational UTC `observed_at`, and a `reference`. The content revision, not that timestamp, is the revalidation boundary. No Web server, index cache, provider process or source mutation is required. Claude JSONL is also supported as described below; other providers return an explicit unsupported error.

The reference has `schema_version: agent.native_session.v2`, `provider: opencode`, and string fields `device_id`, `store_id`, `session_id`, `directory`, `project_id`, `revision`, `model`, `title`. Title is limited to 512 Unicode code points. Empty model means unknown. Paths stay local. The caller must obtain device and source path from its own trusted configuration; history cannot select credentials, grant permissions or redirect execution to another device.

CM's `packages/controlmesh-runtime-core/src/providers/history-client.ts` consumes this command, validates the envelope and independently rereads its locally configured native store. Search metadata is a suggestion until that validation passes. v1 references need explicit reinspection; no automatic conversion claims to preserve their weaker revision semantics.

`store_id` is SHA-256 of compact UTF-8 JSON `["opencode-store-v2", device_id, resolved_store_path, decimal_st_dev, decimal_st_ino]`. File replacement, path redirection or another device invalidates identity. Cross-device continuation requires that device's explicit native mapping, never copying a private SQLite file as the protocol.

The content digest starts with compact UTF-8 JSON `["opencode-sqlite-content-v2", store_id]` and LF. For `session`, `message`, `part` in that order, select rows for the session, ordered by ID. Each record is compact JSON `[table, cells]` and LF, with cells `[column_name, SQLite_typeof_value, SQLite_hex_value]` ordered by ASCII column name. All columns participate. This avoids differences in Python/JS floating-point and Unicode formatting; unknown columns also affect the revision. The identical synthetic fixture in both repositories pins the byte protocol, including REAL, null and Unicode values.

Reads use one query-only SQLite transaction and reject archived/missing sessions, unavailable directories, unsupported schemas, more than 100,000 total rows or 32 MiB of selected values. The reference contains no transcript body. Source permission text is hashed to notice changes, never adopted as CM authorization.

This is snapshot validation, not a universal native lock. Standalone OpenCode clients do not honor CM's advisory exclusion. CM must revalidate at admission, preserve process/episode evidence and reject unexplained concurrent lineage before reporting a successful continuation. A valid reference alone does not prove context recall, current project checks or accepted task completion.

## Claude JSONL reference

Use `--source claude --source-path /absolute/<session-uuid>.jsonl` with the same
`native-reference <session-uuid> --device-id <configured-device>` command. This selects one
canonical transcript file, unlike Claude search/refresh commands whose source is a directory.
It requires no index/cache directory. `history_core/claude_native.py` is the strict continuation
reader; the existing tolerant display parser is unchanged. The reference shape is identical,
with `provider: claude`; it does not certify that a provider process is idle or ready.

The UUID must match the filename and every recorded `sessionId`. User/assistant records must
belong to the main session, have matching roles and refer to one canonical existing directory.
Sidechains, mixed directories, malformed/non-object rows, invalid UTF-8, incomplete final lines,
path aliases and files changing during inspection reject. Reads are bounded to 32 MiB/100,000
lines, check regular-file identity before/after opening and reading, and never follow a candidate
to a different source file. File/source identity is not transported to a different device.

`store_id` hashes compact UTF-8 JSON `["claude-jsonl-store-v2", device_id, canonical_file_path,
decimal_st_dev, decimal_st_ino]`. `project_id` hashes `["claude-project-v2", canonical_directory]`.
The revision hashes `["claude-jsonl-content-v2", store_id]`, LF, then the **exact original file
bytes**, including unknown metadata, whitespace and all previous records. This avoids rounding
large integers through JS/Python codecs. The shared `claude-native-v2.json` fixture includes a
number greater than JavaScript's safe-integer range. Latest non-synthetic assistant model and
explicit custom/AI title are informational; no prompt text is emitted as a fallback title.

CM's `ClaudeSessionStore` independently implements this byte protocol. `ClaudeHistoryClient`
invokes the bounded CLI against its configured source file and revalidates the resulting
context-only reference locally. This is an integration seam for the native Claude runtime;
the existing CM one-shot Claude command remains ephemeral. Real native execution, current
grant enforcement, preflight and retained-turn recovery are separate required gates.
