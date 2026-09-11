# Findings

The roadmap is grounded in repository code, existing contracts and prior recorded acceptance, not the prototype archive alone. Implementation status and remaining gates are in task_plan.md. No new runtime migration or fleet rollout is claimed complete by this plan.

The old CM native revision used the latest message plus part count/max timestamp, which can miss edits to earlier data. v2 hashes all selected SQLite cells and binds the configured device and actual native file identity. The shared Python/TS fixture avoids number/Unicode codec ambiguity by hashing SQLite typeof/hex cells. Reads are bounded to 100,000 rows and 32 MiB; the CLI returns identity metadata, not transcript bodies or an execution grant.

The real TS continuation canary demonstrated the boundary: Viewer returned a context-only native reference, CM independently revalidated it and owned native execution/results, and the provider recalled earlier context while reading changed current project facts. The complete native-reference contract and known locking limits are in `docs/native-session-contract.md`. No Web process or source mutation was required for Viewer access.
