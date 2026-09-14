# v1.2.0 — Linux independent delivery

## Scope

Linux is the validated release target, per the user's explicit scope change. Python 3.11+
standard library runtime, no build step. Windows/WSL compatibility remains unverified in
this release. Optional live LLM calls and CM native execution are not acceptance dependencies.

- Public read-only machine reader, atomic incremental indexing, source-bound caches and
  revision-bound pagination; stale page requests fail explicitly.
- Bounded ordinary handoff with source content revision or unknown, historical project
  claim, evidence baseline, explicit context_only authority and optional plan candidates.
- Default human workspace with six sections, evidence navigation and honest demo/missing/
  stale/failure states. Historical self-report is separate from current verification.
- Weak-session bulk cleanup disabled (HTTP 405). Demo source discovery and caches are
  isolated. Source content and native databases remain unchanged by the reader.

## Validate

```bash
python3 -B -m unittest discover -s tests
node --test tests/test_*.js
python3 scripts/verify_release.py --report /tmp/cchv-verification.json
python3 scripts/build_release.py --output /tmp/cchv-linux-1.2.0.zip
python3 scripts/verify_release.py --artifact /tmp/cchv-linux-1.2.0.zip --report /tmp/cchv-artifact-verification.json
```

Build only from the reviewed commit. `BUILD_INFO.json` identifies that commit and every
packaged file's SHA256; the adjacent `.sha256` binds the entire archive. `/api/version`
returns the running artifact's version and source commit. A checkout without BUILD_INFO
reports source_commit unknown rather than guessing. Build output is not an installation.

## Upgrade and rollback

Back up Viewer-owned caches before switching versions. New JSONL stat signatures are
backfilled by explicit refresh; existing logs stay untouched. Preserve the old release
folder and cache backup. To roll back, stop the Viewer process, launch the previous release
with its saved cache directory, and verify `/api/version` / `--version`. Do not restore a
Viewer cache over any provider-owned history or database. `verify_release.py --previous-root`
exercises v1.1.0 cache upgrade and rollback against synthetic data in isolated temporary folders.

## Evidence boundaries

Five sources have local synthetic read-only matrix coverage; Hermes ordinary audit is
explicitly unsupported, not synthesized. Native database full content revision is unknown
in ordinary handoff; native-reference v2 remains the separate content-bound path. Stat
signatures are not cryptographic history baselines. Performance claims apply only to the
frozen 1k/10k fixtures and recorded Linux host, not arbitrarily large single files.

## Published verification — 2026-09-15

Release source/tag: `eb99792dadc46ca2b352be8b56ea16daa2138c6c` / `v1.2.0`.
ZIP SHA256: `d9b015eef4f7687b14e00e8014e1c3180f36d4cec686f9d6ed9b55a6f7f9268e`.
[Published assets](https://github.com/muqiao215/Codex-Claude-History-Viewer/releases/tag/v1.2.0) match local digests.
[CI 34902276767](https://github.com/muqiao215/Codex-Claude-History-Viewer/actions/runs/34902276767) passed Linux Python 3.11/3.12 and frontend jobs. Local verification: 256 Python passed, 1 optional CM configuration skip; seven Node test files passed.

Clean artifact installation, v1.1.0 cache upgrade/rollback, launcher rollback and actual HTTP runtime identity passed. Test processes were stopped. Post-publication plan closure is documentation only and does not move the release tag.
