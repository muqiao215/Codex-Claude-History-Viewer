# Findings
- P1: Claude usage repeats across records sharing message.id; real sample 4,034,714 vs 1,283,304 after per-ID maximum.
- P2: Session switch leaves old handoff preview and plans visible.
- P2: Near-duplicate merge drops unique file changes and blocked evidence.
- P2: Briefing silently limits overview to 40 sessions (41/4100 becomes 40/4000).
- P2: WSL Codex parser remains v4, preventing cached usage backfill.
- P2: Date change retains prior briefing narrative; POST has no context guard.
- P2: Plan body is read in full before truncation.
- Existing 172 Python tests and 5 JavaScript test files pass; no sixth JS suite found.
