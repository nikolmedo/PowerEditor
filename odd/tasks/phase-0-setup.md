# Feature: phase-0-setup

Locator: `odd/tasks/phase-0-setup.md` · Engram mirror: `odd/phase-0-setup/tasks`

## Objective
Implement PLAN.md Phase 0: monorepo skeleton (uv + pnpm), lint, typecheck, tests, `.env.example`, and `autocut doctor`.

## Acceptance criteria
- `uv run autocut doctor` reports the status of each dependency (FFmpeg, ffprobe, Node, pnpm, CUDA optional).
- `ruff`, `mypy --strict`, `pytest` pass in `backend/`.
- `corepack pnpm install`, `-r typecheck`, `-r lint` pass at the root.

## Constraints
- All code/identifiers/comments/commits in English. Conventional Commits, no AI attribution.
- FFmpeg/subprocess calls use argument lists, never shell strings.
- Repo root acts as the `autocut/` root from PLAN.md (`backend/`, `packages/`, `web/` at top level).
- pnpm invoked as `corepack pnpm` (nvm pnpm shim is broken); `packageManager: pnpm@12.9.1`.
- No Remotion/React deps in Phase 0.

## Decisions
- Python pinned to 3.12 (uv resolved `cpython-3.12-windows-x86_64`, emulated on ARM64). Rationale: x86_64 wheels exist for faster-whisper/ctranslate2, mediapipe, torch; win-arm64 wheels mostly do not. Cost: emulation overhead.

## Risks (carried to later phases)
- Host is Windows ARM64 without NVIDIA GPU: no NVENC, no CUDA. Phase 1 must verify faster-whisper runs (CPU, x86_64 emulation); otherwise `openai` becomes the practical default on this machine.

## Delivery
- Strategy: ask-on-risk. Forecast ~350 authored lines. Baseline boundary: `0b67a1c`.

## Tasks
- [x] T1 Root config: `.gitignore`, `.env.example`, `.python-version`, `.editorconfig`. Route: delegated (writer, part of T2 batch).
- [x] T2 Backend skeleton: `pyproject.toml`, `config.py`, `doctor.py`, `cli.py`, tests (RED→GREEN on doctor missing-dependency). Route: delegated writer (2+ non-trivial files).
- [x] T3 JS workspace: root `package.json`, `pnpm-workspace.yaml`, `tsconfig.base.json`, ESLint + Prettier, `packages/composition` placeholder types. Route: delegated writer.
- [x] T4 Verify acceptance and commit work unit.

## Progress
- Git initialized; baseline commit `0b67a1c`; branch `feat/phase-0-setup`.
- T1–T3 done by one delegated writer; RED observed (`ImportError: cannot import name 'doctor'`) before GREEN.
- Deviations: TypeScript pinned `~6.0.3` (typescript-eslint 8.71 requires <6.1); root scripts call `corepack pnpm -r`; `.prettierignore` added; `web` left out of the workspace until Phase 6.

## Verification evidence
- `uv run pytest -q`: 10 passed (re-run by parent).
- `uv run ruff check . && ruff format --check .`: pass. `uv run mypy autocut tests`: no issues (strict).
- `uv run autocut doctor`: exit 0; ffmpeg 9.0.2, ffprobe 9.0.2, node v24.19.0, pnpm 12.9.1 found; cuda missing (optional) (re-run by parent).
- `corepack pnpm install`, `-r typecheck`, `-r lint`, `prettier --check .`: pass.

## Review
- Work-unit commit `f35332a`: assessed high (process_boundary in doctor.py); consent granted; 4-lens native review approved, lineage `review-465ce6ed9a02fa5a`, acknowledged (authority burned). Reviewed boundary advances to `f35332a`.
- Non-blocking follow-ups: doctor found-semantics (doctor.py:85-91), UnicodeDecodeError on version decode (doctor.py:52), exception path untested (doctor.py:82-86), config tests leak real env (test_config.py:9-27), probe-order coupling in test_doctor.py:109, unexplained media constants (config.py:33-36), env note (config.py:29), types.ts mirror claim.

## Next step
Phase 1 — Ingest and transcription. First verify faster-whisper on this host (CPU, x86_64 emulation).
