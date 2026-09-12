# Findings

The roadmap is grounded in repository code, existing contracts and prior recorded acceptance, not the prototype archive alone. Implementation status and remaining gates are in task_plan.md. No new runtime migration or fleet rollout is claimed complete by this plan.

The old CM native revision used the latest message plus part count/max timestamp, which can miss edits to earlier data. v2 hashes all selected SQLite cells and binds the configured device and actual native file identity. The shared Python/TS fixture avoids number/Unicode codec ambiguity by hashing SQLite typeof/hex cells. Reads are bounded to 100,000 rows and 32 MiB; the CLI returns identity metadata, not transcript bodies or an execution grant.

The real TS continuation canary demonstrated the boundary: Viewer returned a context-only native reference, CM independently revalidated it and owned native execution/results, and the provider recalled earlier context while reading changed current project facts. The complete native-reference contract and known locking limits are in `docs/native-session-contract.md`. No Web process or source mutation was required for Viewer access.

Claude Code 2.1.263 on the local machine stores main sessions in project JSONL files. Records
include assistant content blocks, attachments, system messages and metadata without message UUIDs.
A SQLite-shaped revision cannot describe that store. The new raw-byte revision includes every
record and unknown field, avoiding JS rounding of large JSON numbers. Claude native references
are stricter than display parsing and reject incomplete or changing source snapshots.

Real read-only inspection of an existing local Claude/MiniMax-M3 history agreed with CM's
independent implementation in 197 ms. Source bytes and mtime were unchanged; no provider/model
call occurred. This proves source agreement only, not resumed execution or provider readiness.

Codex history search was already supported, but native-reference explicitly rejected
Codex. codex_native.py now exposes a strict context-only reference from one configured
rollout file. CM must still choose the registered path, independently validate it,
check completed/idle lineage and issue task authority. Python/TS use identical
codex-rollout-store-v1, codex-project-v1 and codex-rollout-content-v1 namespaces;
content edits and inode replacement invalidate earlier references.
