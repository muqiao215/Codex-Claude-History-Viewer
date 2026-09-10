# Native OpenCode continuity

Goal: expose native OpenCode resume from a selected Viewer session, without requiring TaskHub adoption or equating transcripts with SpecMesh files.

Scope: native command generation, live resume validation, explicit layer ownership. Preserve existing working-tree changes. CM PR #26 merge is separately delegated to a native OpenCode worker.

Acceptance: valid source IDs produce native session commands on Linux/WSL/Windows; malformed IDs cannot inject shell syntax; existing sources remain unchanged; actual selected history reaches a model response. Record quota and runtime failures separately.

Phases: command implementation complete; tests/native-history/browser acceptance complete; documentation complete.
Next: use native session continuation; TaskHub adoption remains optional follow-up.
