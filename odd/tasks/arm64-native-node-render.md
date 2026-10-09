# Feature: arm64-native-node-render

Locator: `odd/tasks/arm64-native-node-render.md` · Engram mirror: `odd/arm64-native-node-render/tasks`

## Objective
On Windows ARM64, render (and install the render browser) with the native arm64 Node the user already has, instead of requiring an emulated x64 Node. x64 hosts and other platforms keep today's behaviour unchanged.

## Problem
- `resolve_render_node` rejects every non-x64 Node on Windows, so an ARM64 machine with only an arm64 Node gets `missing_node_x64` when "Download all" installs the render browser, and the guided setup reappears on every launch.
- Setup marks Node as present (it is on PATH) while the render path refuses it, so the screens contradict each other.

## Why
Benchmark on a Snapdragon (300 frames, 1080x1920, concurrency 8): x64 Node ~181 ms/frame vs arm64 Node + x64 compositor via `binariesDirectory` ~172 ms/frame, pixel-identical output (SSIM 1.0). Edge arm64 as browser was 35-45% slower and slightly different, so it is out. The x64 compositor and x64 headless shell keep running emulated as they do today.

## Scope
- Backend: on `win32`, accept a Node whose `process.arch` is `arm64` in addition to `x64` (x64 stays preferred in candidate order as today; arm64 only exists on ARM64 hosts).
- Composition scripts: when `process.platform === "win32"` and `process.arch === "arm64"`, pass `binariesDirectory` pointing at the installed `@remotion/compositor-win32-x64-msvc` package to `selectComposition` and `renderMedia`. No change for any other platform/arch.
- Copy: setup hint / docs that say ARM64 needs an x64 Node.
- Out of scope: native arm64 browser, arm64 compositor, x64 behaviour.

## Constraints
- English in code, comments, docs and commits. Conventional Commits, no AI attribution.
- x64 Windows, macOS and Linux paths must be byte-for-byte unchanged in behaviour.

## Delivery
- Strategy: ask-on-risk. Forecast ~120 authored lines. Branch `fix/arm64-native-node-render` from `main` at `f1cb67d`.

## Tasks
- [x] T1 Accept arm64 Node on Windows and point Remotion at the x64 compositor under arm64. Route: delegated writer (2+ non-trivial files: `node_runtime.py`, `render.mjs`, tests, copy).

## Acceptance criteria
- On ARM64 with only an arm64 Node, "Download all" installs the render browser and an export completes.
- On x64 Windows nothing changes: same Node selection, no `binariesDirectory` passed.

## Progress
- Exploration and benchmark done (scratchpad `arm64-bench`).
- T1 done (route: delegated writer). `node_runtime.resolve_render_node` accepts `x64` or `arm64` on `win32` (first in the unchanged candidate order wins; other arches still raise `missing_node_x64`); `render.mjs` spreads `binariesDirectory` (the `@remotion/compositor-win32-x64-msvc` folder, resolved from `@remotion/renderer` like Remotion does under x64) into `selectComposition` and `renderMedia` only when `process.platform === "win32" && process.arch === "arm64"`. `ensure-browser.mjs` unchanged (Remotion downloads the `win64` headless shell for any win32 arch). Copy: `setup.hint.node` (en/es), README, `pnpm-workspace.yaml` comment, `runtime/manifest.py` docstring. Helper kept inline: composition tests cover `src/` only and tsc cannot type an `.mjs` import from `test/`.

## Verification evidence (T1)
- RED: `uv run pytest -q tests/test_render.py -k render_node` → 2 failed (`accepts_a_system_arm64_node_on_windows`, `skips_other_arches_on_windows`: `missing_node_x64`), 8 passed.
- GREEN: same command → 10 passed.
- `ruff check .`: all checks passed; `ruff format --check .`: 173 files formatted; `mypy powereditor tests`: no issues (171 files); `schema_gen --check`: exit 0.
- `pytest -q`: 742 passed, 2 skipped, 1 failed: `test_cli_version::test_package_constant_matches_the_installed_version` (venv metadata 0.1.1 vs 0.2.0). Environmental: `uv sync` cannot replace `.venv/Scripts/powereditor.exe` while a PowerEditor process holds it, so tests ran with `--no-sync`; unrelated to this change.
- `corepack pnpm typecheck`, `lint`, `format:check`: pass. `corepack pnpm -r test`: desktop 75, composition 94, web 204 passed.
- Smoke on this ARM64 machine: `resolve_render_node(None, <empty bin>)` → `C:\Program Files\nodejs\node.EXE` (arm64). `render.mjs --bundle packages/composition/dist/bundle` with that Node (cwd = scratchpad x64home, draft quality) rendered the full project: rc 0, 5177 frames in 563 s, 20.5 MB MP4, empty stderr.
- Commit: `fix(render): render with a native arm64 Node on Windows ARM64` on `fix/arm64-native-node-render` (the commit that adds this line). Native review: pending parent (RDD).
