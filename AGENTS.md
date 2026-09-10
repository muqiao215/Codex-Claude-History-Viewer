# Project Instructions

This repository follows [SpecMesh v1.1](https://github.com/muqiao215/specmesh).

## Start Here

First read:

1. `PROJECT.md`

Then read only what the task requires:

- Architecture → `docs/ARCHITECTURE.md`
- Historical decisions → `docs/DECISIONS.md`
- Active work → `plans/<task>/`

Do not load unrelated documentation by default.

## Project Memory

Conversation history is not project memory.

Update `PROJECT.md` when confirmed user intent, priorities, constraints, or rejected directions change.

Update `docs/ARCHITECTURE.md` when durable knowledge about how the system works changes.

Update `docs/DECISIONS.md` when an important decision is made that future agents may otherwise revisit.

For substantial work, maintain `task_plan.md`, `findings.md`, and `progress.md` under `plans/<task>/`.

## Development

- Preserve the local-first, dependency-free runtime unless the user explicitly changes that constraint.
- Treat user transcripts as sensitive data; do not add uploads or remote processing by default.
- Keep deterministic evidence extraction separate from optional AI interpretation.
- Use the repository's existing Python and JavaScript tests and verify changes before completion.
- Do not introduce process or infrastructure unless the task requires it.
- Do not silently reinterpret or weaken user requirements.

## Documentation

Keep documentation concise and prefer links over duplicated explanations.

Code explains implementation. Documentation explains intent, structure, decisions, and current work.
