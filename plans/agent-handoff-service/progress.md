# Progress

## Current

HV-H2/H3 in progress. OpenCode native-reference v2 is consumed by CM. Current increment adds
Claude JSONL native identity and independent CM revalidation. It does not claim Claude runtime
execution, resident-service or full continuation-matrix acceptance.

## Done

Claude source increment: strict main-session JSONL reference, shared byte fixture and headless
CLI support; CM independently implements the same revision and revalidates the candidate.
Python suite passed **201 tests**. Real existing-source inspection agreed in **197 ms**, with
unchanged source bytes/mtime and zero model calls. No Web or index cache was started. Full native
Claude execution/preflight/recovery remains pending; no universal memory guarantee is asserted.

Implemented `history_core/native.py` and the explicit `native-reference` CLI command. Identity includes device, native file identity, directory/project and a complete content revision; the source is query-only and bounded. Python/TS share a synthetic byte-protocol fixture. Full Python suite passed 195 tests on 2026-09-11.

Read-only real SpecMesh history inspection agreed with CM's independent native-store check in 192 ms. A separate controlled real OpenCode 1.18.29/MiniMax-M3 acceptance used the TS kernel/worker: first turn stored a marker and read a project file, Viewer retrieved the native reference headlessly, and the second turn resumed the same session, recalled the marker without reinjection and read the updated file. Both execution effects were confirmed. This is scoped same-provider/same-device evidence, not all-provider memory or production TS cutover.

## Remaining

Execute the phase gates in task_plan.md; record concrete tests and released versions.

## Issues

No blocking condition. Native v1 references need explicit reinspection; their weaker content checks must not be silently treated as v2. Standalone native clients do not honor CM advisory locks. Existing unrelated local plan files are preserved.

## Next

Finish the broader handoff envelope, lightweight resident service and independent source boundaries; extend HV-H3 fault cases with the authenticated CM device coordinator. The Web remains optional for machine access.
