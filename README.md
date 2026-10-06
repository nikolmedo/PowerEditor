# PowerEditor

Record your video, say the line again when you trip over it, and let PowerEditor do the boring part. It finds every repeated take, keeps the best one, cuts the silences, adds transitions and subtitles, levels the audio, and hands you a finished MP4. You review the result in three steps instead of scrubbing a timeline for an hour.

PowerEditor runs on your own Windows PC. Your footage never leaves it unless you choose a cloud model.

> **Status:** early development. The analysis pipeline and the render engine work today from the command line (Phases 0–2 of [PLAN.md](PLAN.md)). The graphical app, take selection and the installer are planned. Features below are marked **planned** when they do not exist yet.

## Why PowerEditor

Talking-head videos (reels, tutorials, course lessons, YouTube) are cheap to record and expensive to edit. Most of the editing time goes into the same mechanical work: finding the good take, trimming dead air, syncing captions. PowerEditor automates that work with deterministic rules first and AI only where judgment is needed, so it stays fast, cheap and predictable.

- **Less editing time.** Drop in the raw files, get a cut you only need to check.
- **Local first.** Transcription runs on your machine with Whisper by default.
- **No surprise bills.** Heuristics do most of the work; paid models are optional and chosen per feature.
- **What you see is what you export.** The preview and the final render use the same composition.

## Features

| Feature                                                                                                         | Status    |
| --------------------------------------------------------------------------------------------------------------- | --------- |
| Ingest any phone or camera file (VFR to CFR mezzanine, 540p preview proxy)                                      | Available |
| Word-level transcription: local Whisper or OpenAI `whisper-1`                                                   | Available |
| Silence detection and removal (Silero VAD + loudness floor)                                                     | Available |
| Draft project built automatically from the analysis                                                             | Available |
| MP4 render with click-free cuts and -14 LUFS loudness normalization                                             | Available |
| Best-take selection when a phrase was recorded several times                                                    | Planned   |
| Bring your own AI model per feature: OpenAI, Gemini, Claude, DeepSeek, Jev, by API key or a logged-in local CLI | Planned   |
| Animated subtitles (karaoke, clean, bold pop, minimal) + SRT/ASS export                                         | Planned   |
| Automatic transitions (punch-in within a topic, fade or slide between topics)                                   | Planned   |
| Color matching across sources, presets and sliders                                                              | Planned   |
| Music with automatic ducking under the voice                                                                    | Planned   |
| Titles, lower thirds, logo, progress bar, automatic call-to-action                                              | Planned   |
| 3-step app: Load → Review/Adjust → Export, with undo/redo                                                       | Planned   |
| Windows installer with automatic updates                                                                        | Planned   |
| FCPXML export for other editors (via OpenTimelineIO)                                                            | Planned   |

## How it works

1. **Ingest.** Each file is probed, converted to a constant-frame-rate master for rendering, a light proxy for preview, and a 16 kHz audio track for analysis.
2. **Transcribe.** Whisper writes down every word with its start and end time, filler words included.
3. **Find speech.** A voice detector marks where you speak; everything else is a candidate cut.
4. **Split into phrases** using pauses and punctuation.
5. **Group repeated takes and pick the best one** (planned). Similar phrases are clustered; each take is scored in code (completeness, filler words, pace, loudness, framing) and, if you enable it, by an AI model for semantic questions such as "is this idea complete?".
6. **Build the draft.** Clips, transitions, subtitles, audio and color go into one `project.json`.
7. **Render.** Remotion draws the video, ffmpeg rebuilds the voice sample by sample so cuts never click, and a final pass normalizes loudness.

## Screenshots

Screenshots will be added when the graphical app lands (Phase 6). There is no UI to show yet.

## Requirements

- Windows 10/11 (x64 or ARM64). CI also runs the test suite on Linux.
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you).
- Node.js 24 with Corepack (ships with Node 24).
- FFmpeg and ffprobe 7.0 or newer on `PATH`, or set their paths in settings.
- On Windows ARM64, rendering needs an x64 Node.js build (set its path as `nodePath` in settings); Remotion has no ARM64 Windows compositor.
- Optional: an NVIDIA GPU with CUDA 12 + cuDNN 9 for faster transcription. Without a GPU, Whisper runs on the CPU with the `small` model.

## Quick start (developers)

```bash
# Backend
cd backend
uv sync
uv run powereditor doctor          # checks ffmpeg, ffprobe, node, pnpm, cuda

# Composition (from the repo root)
cd ..
corepack pnpm install

# Analyze a recording into a draft project, then render it
cd backend
uv run powereditor analyze path/to/video.mp4 --project-id demo
uv run powereditor render demo     # writes <data dir>/projects/demo/exports/final.mp4
```

`analyze` downloads the Whisper model on first use. Other commands: `ingest`, `transcribe`, `serve` (local API on `127.0.0.1:8765`). Run `uv run powereditor --help` for the full list.

## Configuration

You should never need to edit a file to configure PowerEditor.

- **Settings** (transcriber, Whisper model and device, language, silence padding, loudness target, tool paths) are stored in `settings.json` inside the user data dir: `%LOCALAPPDATA%\PowerEditor` on Windows. Today they are set through the local API (`PATCH /api/settings`); the settings screen comes with the UI.
- **API keys** are stored in the OS keyring (Windows Credential Locker), never in plain files.
- **`.env`** is a developer override only. The accepted variables are the fields of `Settings` in `backend/powereditor/config.py`; `.env.example` is the template.
- `POWEREDITOR_DATA_DIR` moves the data dir (projects, models, downloaded binaries, logs, settings).

## Privacy

- Video, audio and transcripts stay on your machine. Projects live in your user data dir.
- Whisper runs locally by default. Audio is sent to OpenAI only if you pick the `openai` transcriber.
- AI decision features are off by default (the heuristic engine needs no model). When per-feature models arrive (planned), a cloud model receives only the minimal text its question needs.

## Licenses to know about

- **Remotion** is free for individuals and companies of up to 3 people. Larger teams need a [Remotion company license](https://www.remotion.dev/license).
- **FFmpeg** is not bundled. Popular Windows builds (for example gyan.dev `full_build`) are GPL; the packaged app will use an LGPL build or download FFmpeg at first run.

---

## For AI agents

Dense reference for coding agents. Read this before exploring; it should save most of the discovery work.

### Repo map

| Path                                      | Responsibility                                                                                                                                   |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/powereditor/cli.py`              | Typer CLI: `doctor`, `serve`, `ingest`, `transcribe`, `analyze`, `render`                                                                        |
| `backend/powereditor/api/`                | FastAPI app (`app.py`: `/api/health`, `/api/doctor`) and settings/secrets routes (`routes_settings.py`)                                          |
| `backend/powereditor/models.py`           | Pydantic models, single source of truth for `project.json` and stage results                                                                     |
| `backend/powereditor/schema_gen.py`       | Writes `packages/composition/schema/project.schema.json` from `Project`                                                                          |
| `backend/powereditor/config.py`           | `.env` developer overrides (pydantic-settings), `REPO_ROOT`                                                                                      |
| `backend/powereditor/settings_store.py`   | Settings layering, user `settings.json`, keyring and in-memory secret stores                                                                     |
| `backend/powereditor/paths.py`            | User data dir layout, executable resolution (configured → `<data dir>/bin` → `PATH`)                                                             |
| `backend/powereditor/doctor.py`           | Dependency probes                                                                                                                                |
| `backend/powereditor/timeline.py`         | Clip frame layout; mirrored by `packages/composition/src/timeline.ts`                                                                            |
| `backend/powereditor/pipeline/`           | Stage runner + cache (`runner.py`), ffmpeg helpers, ingest, transcription, VAD, segmentation, loudness, color stats, draft builder, `analyze.py` |
| `backend/powereditor/transcribe/`         | `Transcriber` protocol, factory, faster-whisper and OpenAI implementations                                                                       |
| `backend/powereditor/render/`             | Render job: voice rebuild (`audio_mix.py`), Remotion runner, Node resolution, loopback media server, final pass                                  |
| `backend/powereditor/export/subtitles.py` | Source-time words → timeline words                                                                                                               |
| `backend/tests/`                          | pytest suite; `conftest.py` isolates data dir, env and secrets; `media.py` builds lavfi fixtures                                                 |
| `packages/composition/src/`               | Remotion composition (`ProjectVideo.tsx`, `Root.tsx`, `timeline.ts`, clips, transitions, subtitles, overlays, color)                             |
| `packages/composition/scripts/`           | `gen-types.mjs` (schema → TS), `render.mjs` (CLI render, NDJSON progress)                                                                        |
| `packages/composition/test/`              | vitest                                                                                                                                           |
| `PLAN.md`                                 | Product plan, architecture, phases                                                                                                               |
| `odd/tasks/powereditor-app.md`            | Progress log, decisions, measurements, review history                                                                                            |

Not yet present: `web/` (UI), `backend/powereditor/decide/`, provider registry.

### Data flow

```
files → ingest (mezzanine, proxy, WAV) → transcribe → vad → segmentation
      → loudness + color stats → draft_builder → <data dir>/projects/<id>/project.json
project.json → render/job.py:
   audio_mix (ffmpeg voice rebuild) → remotion_render (muted MP4 via render.mjs)
   → final_pass (mux + two-pass loudnorm) → exports/<name>.mp4
```

Per-project layout (`ProjectLayout` in `pipeline/runner.py`): `media/`, `cache/<stage>.json`, `project.json`, `exports/`.

### Source of truth and generated files

1. Edit models in `backend/powereditor/models.py`.
2. `cd backend && uv run python -m powereditor.schema_gen` regenerates `packages/composition/schema/project.schema.json`.
3. `corepack pnpm --filter @powereditor/composition gen:types` regenerates `packages/composition/src/types.generated.ts`.
4. Check freshness with `uv run python -m powereditor.schema_gen --check` and `corepack pnpm -r check:types`.

Never hand-edit the schema or `types.generated.ts`. Both are in `.prettierignore`.

### Key contracts

- **Frame rounding:** clip frames = `round((outSec - inSec) / speed * fps)`, ties to even. Python `round()` in `timeline.py`, `roundHalfEven` in `timeline.ts`. Change both or neither.
- **Audio:** Remotion renders **muted** video. The voice is rebuilt by ffmpeg in `render/audio_mix.py` (atrim/atempo/afade/concat, cumulative frame→sample boundaries, batches of `BATCH_CLIPS = 40` via filter script files to respect the Windows 32767-char command line).
- **Stage cache:** `run_stage()` keys on SHA-256 of stage name, stage version, input identities (path + size + SHA-256 if ≤ 1 MiB, else mtime) and params. The record is deleted before computing and written only after declared outputs exist, are non-empty and validate. Bump the stage version when its logic changes.
- **Composition id:** single source `packages/composition/src/composition.json`.
- **Secrets:** API responses report `set`/`source`, never values. Validation errors strip the `input` field.

### Conventions

- English everywhere: docs, code, comments, commits (Conventional Commits). Tidy, readable code.
- Python: strict mypy, ruff, Pydantic `CamelModel` (camelCase aliases, `extra="forbid"`).
- `subprocess` with argument lists only, never `shell=True`.
- Node tooling only through `corepack pnpm`.
- Tests: `conftest.py` sets `POWEREDITOR_DATA_DIR` to a temp dir, clears env overrides and swaps the keyring for `InMemorySecretStore`. Markers: `ffmpeg` (needs ffmpeg/ffprobe, skipped when missing), `slow` (model downloads, deselected by default; run with `-m slow`).

### Checks

Run from `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy powereditor tests
uv run python -m powereditor.schema_gen --check
uv run pytest -q
```

Run from the repo root:

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm -r test
corepack pnpm -r check:types
corepack pnpm format:check
```

CI (`.github/workflows/ci.yml`) runs the same commands on Windows and Linux.

### How to extend

- **Pipeline stage:** add a module under `pipeline/`, compute through `run_stage(layout, stage, version, inputs, params, ResultModel, compute, outputs=...)`, put the result model in `models.py` (or the module), wire it into `pipeline/analyze.py`, add tests with lavfi fixtures from `tests/media.py`.
- **CLI command:** add an `@app.command()` in `cli.py`; get settings with `SettingsService.default()`; catch `PIPELINE_ERRORS` and exit through `_fail()` so errors print a code.
- **API route:** create an `APIRouter(prefix="/api")` module in `api/`, inject the service with the `ServiceDep` pattern from `routes_settings.py`, and `include_router` it in `create_app()`. Test with `create_app(settings_service=...)` and FastAPI's `TestClient`.
- **Model provider (planned, Phase 4):** implement the `ModelProvider` interface (capabilities + transport `api` or `local_cli`) and register it; features never import providers directly. See PLAN.md Phase 4.

### Platform gotchas

- **Windows ARM64:** use x64 Python 3.12 (runs emulated). Remotion has no win32-arm64 compositor, so rendering needs an **x64 Node**: `render/node_runtime.py` tries the `nodePath` setting, then `<data dir>/bin/node-x64/`, then `PATH`, checking each candidate's `process.arch`.
- `pnpm-workspace.yaml` sets `supportedArchitectures.cpu: [current, x64]` so x64 native packages (compositor, esbuild) install next to ARM64 ones. Only `esbuild` may run install scripts (`allowBuilds`).
- **Line endings:** `.gitattributes` forces LF. Generators normalize CRLF before `--check`.
- **`bash` from Python subprocess** on Windows can resolve to WSL's `bash.exe`, not Git Bash. Do not shell out to `bash` from code or tests.
- ffmpeg reports `h264_nvenc` even without a GPU on some builds; encoder choice also checks CUDA.

### Where planning and progress live

- `PLAN.md`: requirements, architecture, phases and acceptance criteria.
- `odd/tasks/powereditor-app.md`: task checklist, decisions, measurements, review log, follow-ups. Update it when you finish a task.
