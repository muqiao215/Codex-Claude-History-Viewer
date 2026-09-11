# Progress

## Current

HV-H2/H3 in progress. Headless native-reference v2 is implemented and consumed by CM's TS worker. Full resident-service, platform and continuation-matrix gates remain open.

## Done

Implemented `history_core/native.py` and the explicit `native-reference` CLI command. Identity includes device, native file identity, directory/project and a complete content revision; the source is query-only and bounded. Python/TS share a synthetic byte-protocol fixture. Full Python suite passed 195 tests on 2026-09-11.

Read-only real SpecMesh history inspection agreed with CM's independent native-store check in 192 ms. A separate controlled real OpenCode 1.18.29/MiniMax-M3 acceptance used the TS kernel/worker: first turn stored a marker and read a project file, Viewer retrieved the native reference headlessly, and the second turn resumed the same session, recalled the marker without reinjection and read the updated file. Both execution effects were confirmed. This is scoped same-provider/same-device evidence, not all-provider memory or production TS cutover.

## Remaining

Execute the phase gates in task_plan.md; record concrete tests and released versions.

## Issues

No blocking condition. Native v1 references need explicit reinspection; their weaker content checks must not be silently treated as v2. Standalone native clients do not honor CM advisory locks. Existing unrelated local plan files are preserved.

## Next

Finish the broader handoff envelope, lightweight resident service and independent source boundaries; extend HV-H3 fault cases with the authenticated CM device coordinator. The Web remains optional for machine access.
