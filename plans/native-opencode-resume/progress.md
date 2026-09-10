## Current
Native OpenCode command path implemented and verified in the running local Viewer.
## Done
- Command generation tests passed across Linux, Windows and WSL, including invalid session ID rejection and existing-source regression.
- node --check static/app.js and all 17 insight-panel tests passed.
- Real selected-session resume with the configured MiniMax model persisted an answer correctly recalling qiao-wechat, six phases, R01–R12 and the historical not-implemented state. The answers were absent from the probe prompt; no file tools were permitted.
- Browser selected the original SpecMesh session and displayed both native resume commands and the newly persisted answer.
- Existing dirty working-tree changes preserved; only the six-line OpenCode command branch plus this task's test/docs were added.
- OpenCode MiniMax worker merged ControlMesh PR #26 after green CI; root independently verified MERGED and merge SHA aa6b6decf5f1b76da012629373282fd58cd5c79f.
## Remaining
No remaining work for the local copy-command integration. TaskHub managed execution is a separate optional layer, not claimed implemented.
## Issues
ZAI logs prove current quota exhaustion. Native noninteractive resume produced no stdout and did not exit before the test deadline despite persisting a response; therefore command-process completion is not claimed. Earlier fork tests' absence of stdout did not prove failure: native history now shows created forks. Native TUI launch command was checked against installed help; browser display and actual native history response were verified separately.
## Next
Use the selected-session native command; track noninteractive streaming/exit behavior separately if needed for CM supervision.

## Subsequent CM closure (2026-09-11)

CM v0.42.2 now provides explicit local TaskHub adoption. Its native `--dir` handling fixed noninteractive output/exit; real same-session terminal completion passed. The earlier timeout above is historical evidence, not the current CM status. Native copy-command usage still does not require CM.
