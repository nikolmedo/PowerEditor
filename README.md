# PowerEditor

Record your video, say the line again when you trip over it, and let PowerEditor do the boring part. It finds every repeated take, keeps the best one, cuts the silences, adds transitions and subtitles, levels the audio, and hands you a finished MP4. You review the result in three steps instead of scrubbing a timeline for an hour.

PowerEditor runs on your own Windows PC. Your footage never leaves it unless you choose a cloud model.

> **Status:** early development. The analysis pipeline and the render engine work today from the command line (Phases 0–3 of [PLAN.md](PLAN.md)). Take selection is heuristic by default; AI models can answer individual decisions from the command line (Phase 4). The graphical app and the installer are planned. Features below are marked **planned** when they do not exist yet.

## Why PowerEditor

Talking-head videos (reels, tutorials, course lessons, YouTube) are cheap to record and expensive to edit. Most of the editing time goes into the same mechanical work: finding the good take, trimming dead air, syncing captions. PowerEditor automates that work with deterministic rules first and AI only where judgment is needed, so it stays fast, cheap and predictable.

- **Less editing time.** Drop in the raw files, get a cut you only need to check.
- **Local first.** Transcription runs on your machine with Whisper by default.
- **No surprise bills.** Heuristics do most of the work; paid models are optional and chosen per feature.
- **What you see is what you export.** The preview and the final render use the same composition.

## Features

| Feature                                                                                                         | Status                |
| --------------------------------------------------------------------------------------------------------------- | --------------------- |
| Ingest any phone or camera file (VFR to CFR mezzanine, 540p preview proxy)                                      | Available             |
| Word-level transcription: local Whisper or OpenAI `whisper-1`                                                   | Available             |
| Silence detection and removal (Silero VAD + loudness floor)                                                     | Available             |
| Draft project built automatically from the analysis                                                             | Available             |
| MP4 render with click-free cuts and -14 LUFS loudness normalization                                             | Available             |
| Best-take selection when a phrase was recorded several times (heuristic, or an AI model per feature)            | Available             |
| Bring your own AI model per feature: OpenAI, Gemini, Claude, DeepSeek, Jev, by API key or a logged-in local CLI | Available (no UI yet) |
| Animated subtitles (karaoke, clean, bold pop, minimal) + SRT/ASS export                                         | Planned               |
| Automatic transitions (punch-in within a topic, fade or slide between topics)                                   | Planned               |
| Color matching across sources, presets and sliders                                                              | Planned               |
| Music with automatic ducking under the voice                                                                    | Planned               |
| Titles, lower thirds, logo, progress bar, automatic call-to-action                                              | Planned               |
| 3-step app: Load → Review/Adjust → Export, with undo/redo                                                       | Planned               |
| Windows installer with automatic updates                                                                        | Planned               |
| FCPXML export for other editors (via OpenTimelineIO)                                                            | Planned               |

## How it works

1. **Ingest.** Each file is probed, converted to a constant-frame-rate master for rendering, a light proxy for preview, and a 16 kHz audio track for analysis.
2. **Transcribe.** Whisper writes down every word with its start and end time, filler words included.
3. **Find speech.** A voice detector marks where you speak; everything else is a candidate cut.
4. **Split into phrases** using pauses and punctuation.
5. **Group repeated takes and pick the best one.** Remarks like "cut, again" are dropped, similar phrases are clustered, and each take is scored in code (completeness, filler words, stutters, pace, loudness, framing). Rejected takes stay in the project as removed clips, so you can swap them back. Semantic questions such as "is this idea complete?" can go to an AI model you choose per feature; an answer below the confidence minimum keeps the heuristic result and flags the decision for review.
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

`analyze` downloads the Whisper model on first use; pass `--script script.txt` to judge take completeness against your script. Other commands: `ingest`, `transcribe`, `eval-takes` (take-choice accuracy on the benchmark), `providers list` and `features` (registered models and which one answers each feature), `serve` (local API on `127.0.0.1:8765`). Run `uv run powereditor --help` for the full list.

## Configuration

You should never need to edit a file to configure PowerEditor.

- **Settings** (transcriber, Whisper model and device, language, silence padding, loudness target, tool paths) are stored in `settings.json` inside the user data dir: `%LOCALAPPDATA%\PowerEditor` on Windows. Today they are set through the local API (`PATCH /api/settings`); the settings screen comes with the UI.
- **API keys** are stored in the OS keyring (Windows Credential Locker), never in plain files.
- **`.env`** is a developer override only. The accepted variables are the fields of `Settings` in `backend/powereditor/config.py`; `.env.example` is the template.
- `POWEREDITOR_DATA_DIR` moves the data dir (projects, models, downloaded binaries, logs, settings).

## Privacy

- Video, audio and transcripts stay on your machine. Projects live in your user data dir.
- Whisper runs locally by default. Audio is sent to OpenAI only if you pick the `openai` transcriber.
- AI decision features are off by default (the heuristic engine needs no model). A feature you assign to a cloud model sends it only the minimal text its question needs (one segment, or the takes of one group).

## Subscriptions and terms of use

Each AI provider's own terms apply to how PowerEditor reaches it. Check them before you assign a feature:

- **Claude:** PowerEditor never handles Claude sign-in. Use an Anthropic API key, or the official Claude Code CLI signed in by you. Anthropic does not let third-party apps route requests through Free, Pro or Max plan credentials on their users' behalf, and plan limits assume ordinary individual use ([Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). An API key is the safe choice for PowerEditor.
- **Gemini CLI:** signing in with a personal Google account has a free quota of 1000 model requests per user per day ([Gemini CLI quotas](https://geminicli.com/docs/resources/quota-and-pricing/)). A long recording can use many requests.
- **Codex CLI:** usage counts against your ChatGPT plan's limits and OpenAI's terms ([Codex pricing](https://learn.chatgpt.com/docs/pricing)).

## Licenses to know about

- **Remotion** is free for individuals and companies of up to 3 people. Larger teams need a [Remotion company license](https://www.remotion.dev/license).
- **FFmpeg** is not bundled. Popular Windows builds (for example gyan.dev `full_build`) are GPL; the packaged app will use an LGPL build or download FFmpeg at first run.

---

## For AI agents

Dense reference for coding agents. Read this before exploring; it should save most of the discovery work.

### Repo map

| Path                                      | Responsibility                                                                                                                                                                                                   |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/powereditor/cli.py`              | Typer CLI: `doctor`, `serve`, `ingest`, `transcribe`, `analyze`, `render`, `eval-takes`, `providers list`, `features`                                                                                            |
| `backend/powereditor/api/`                | FastAPI app (`app.py`: `/api/health`, `/api/doctor`), settings/secrets routes (`routes_settings.py`), providers and feature models (`routes_providers.py`)                                                       |
| `backend/powereditor/models.py`           | Pydantic models, single source of truth for `project.json` and stage results                                                                                                                                     |
| `backend/powereditor/schema_gen.py`       | Writes `packages/composition/schema/project.schema.json` from `Project`                                                                                                                                          |
| `backend/powereditor/config.py`           | `.env` developer overrides (pydantic-settings), `REPO_ROOT`                                                                                                                                                      |
| `backend/powereditor/settings_store.py`   | Settings layering, user `settings.json`, keyring and in-memory secret stores                                                                                                                                     |
| `backend/powereditor/paths.py`            | User data dir layout, executable resolution (configured → `<data dir>/bin` → `PATH`)                                                                                                                             |
| `backend/powereditor/doctor.py`           | Dependency probes                                                                                                                                                                                                |
| `backend/powereditor/timeline.py`         | Clip frame layout; mirrored by `packages/composition/src/timeline.ts`                                                                                                                                            |
| `backend/powereditor/pipeline/`           | Stage runner + cache (`runner.py`), ffmpeg helpers, ingest, transcription, VAD, segmentation, loudness, color stats, takes, draft builder, `analyze.py`                                                          |
| `backend/powereditor/providers/`          | `ModelProvider` contract (`base.py`), settings types and base-URL trust (`config.py`), `registry.py`, typed questions (`questions.py`), Jev (`jev.py`), API adapters (`api/`), local CLI adapters (`local_cli/`) |
| `backend/powereditor/decide/`             | `DecisionEngine` protocol (`base.py`), `HeuristicEngine`, feature prompts (`prompts.py`), per-feature `ModelDecisionEngine` (`model_engine.py`), `create_engine` factory                                         |
| `backend/powereditor/eval/takes_eval.py`  | Take benchmark evaluator behind `powereditor eval-takes`                                                                                                                                                         |
| `backend/powereditor/transcribe/`         | `Transcriber` protocol, factory, faster-whisper and OpenAI implementations                                                                                                                                       |
| `backend/powereditor/render/`             | Render job: voice rebuild (`audio_mix.py`), Remotion runner, Node resolution, loopback media server, final pass                                                                                                  |
| `backend/powereditor/export/subtitles.py` | Source-time words → timeline words                                                                                                                                                                               |
| `backend/tests/`                          | pytest suite; `conftest.py` isolates data dir, env and secrets; `media.py` builds lavfi fixtures                                                                                                                 |
| `packages/composition/src/`               | Remotion composition (`ProjectVideo.tsx`, `Root.tsx`, `timeline.ts`, clips, transitions, subtitles, overlays, color)                                                                                             |
| `packages/composition/scripts/`           | `gen-types.mjs` (schema → TS), `render.mjs` (CLI render, NDJSON progress)                                                                                                                                        |
| `packages/composition/test/`              | vitest                                                                                                                                                                                                           |
| `PLAN.md`                                 | Product plan, architecture, phases                                                                                                                                                                               |
| `odd/tasks/powereditor-app.md`            | Progress log, decisions, measurements, review history                                                                                                                                                            |

Not yet present: `web/` (UI).

### Data flow

```
files → ingest (mezzanine, proxy, WAV) → transcribe → vad → segmentation
      → loudness + color stats → takes → draft_builder → <data dir>/projects/<id>/project.json
project.json → render/job.py:
   audio_mix (ffmpeg voice rebuild) → remotion_render (muted MP4 via render.mjs)
   → final_pass (mux + two-pass loudnorm) → exports/<name>.mp4
```

Per-project layout (`ProjectLayout` in `pipeline/runner.py`): `media/`, `cache/<stage>.json`, `cache/model_usage.json` (model calls and tokens per feature of the last takes computation that called a model), `project.json`, `exports/`.

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
- **Secrets:** API responses report `set`/`source`, never values. Validation errors strip the `input` field. Provider API keys live in the secret store as `provider:<id>:api_key`, never in `settings.json`.

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
- **Takes stage** (`pipeline/takes.py`, cached as `cache/takes.json`): `engine.classify_segment` drops out-of-take remarks, `clustering.py` groups retakes inside a window (rapidfuzz text similarity, or `sentence-transformers` embeddings with `takeSimilarity: "embeddings"` and the `embeddings` extra; grey zone 0.5–0.8 goes to `engine.same_take`), `features.py` scores each take in code, `engine.decide_cluster` picks one. The result is an ordered `TakeEntry` list. `draft_builder` turns it into clips: a group keeps its chosen clip, the other takes become `removed` clips with the same `takeGroupId`, and `alternativeTakeIds` lists those clip ids. Remarks become `removed` clips without a group. Weights live in the `takeWeights` user setting. Visual features need the `vision` extra (OpenCV); without it they are `None`.
- **Decision engine:** implement the `DecisionEngine` protocol in `decide/base.py` (`same_take`, `decide_cluster`, `classify_segment`, `transition_between`, plus `name` and a `fingerprint()` that goes into the stage cache key). Each method is one feature with Pydantic inputs and outputs, so an engine can delegate any method to `HeuristicEngine`. Return it from `decide/factory.py`. Check it with `uv run powereditor eval-takes` (heuristic engine); the bundled benchmark is **synthetic** (`tests/fixtures/takes_benchmark.json`), not real footage.
- **Model provider:** implement the `ModelProvider` protocol in `providers/base.py` (`kind`, `transport`, `check()`, `list_models()`, `judge(JudgmentRequest) -> JudgmentResult`). Raise `ProviderError` with one of its codes (`provider_unauthorized`, `provider_unavailable`, `provider_bad_output`, `provider_timeout`, `cli_not_found`) and return answers through `build_result`, which validates them against the request's JSON Schema. For an HTTP API subclass `api/base.ApiProvider` (bounded retry on 429/5xx/529 and failed connections; a POST whose connection broke after sending is not retried; auth mapping) or reuse `OpenAICompatibleProvider` with a base URL; for a local client subclass `local_cli/base.LocalCliProvider` (argument list, prompt on stdin, empty temp cwd, kill tree on timeout). Register a factory `(ProviderConfig, ProviderContext) -> ModelProvider` for a `(kind, transport)` pair in `registry.default_registry()`; kinds are open strings, so routes and settings need no changes. Test API adapters with `httpx.MockTransport` and CLI adapters with `tests/fixtures/fake_cli.py`; never call a real model in tests. Features ask for a provider through `SettingsService.feature_model()` and the registry, never by importing an adapter.

- **How a feature is routed:** `decide/factory.create_engine(service)` reads `featureModels` (`SettingsService.feature_model()`). With no assignment it returns the plain `HeuristicEngine`. Otherwise it builds each assigned provider once through the registry and returns `ModelDecisionEngine`, which answers only the assigned features and delegates the rest to the heuristic. Feature → method: `off_take_detection`, `idea_completeness`, `cta_detection` → `classify_segment` (one call per segment when they share a provider and model); `same_take_grey_zone` → `same_take`; `topic_change` → `transition_between`; `fluency_score` and `idea_completeness` → per-take scores inside `decide_cluster`; `best_take_choice` → a Choice asked twice with the takes in reversed order. An answer is applied only when its confidence is at least `modelMinConfidence` (formerly `jevMinConfidence`, still accepted) and, for the best take, when both orders pick the same take. Otherwise the heuristic answer is kept with a lowered confidence. A provider error other than bad output disables that provider for the rest of the run. Model scores enter `take_score` through `TakeWeights` (for example `fluency`); weights never go into prompts. The engine fingerprint (provider id, kind, transport, model, prompt version per feature, minimum confidence) is part of the takes cache key.
- **Feature prompt:** prompts are data in `decide/prompts.py`: a `FeaturePrompt(question_id, question, version)` whose question is a `NoulQuestion` (yes/no), `ChoiceQuestion` (one of labelled options) or `ScoreQuestion` (ordered levels, low to high), with the minimal state its method passes. Jev receives the question natively (`providers/jev.py`); every other provider gets a strict JSON Schema derived by `providers/questions.judgment_request` (enum labels plus a `certainty` of low/medium/high, `additionalProperties: false`, no numeric or length constraints) and the answer is validated with Pydantic and mapped to a probability or confidence in code. Never ask the model to count or compute. Bump `version` when the wording changes so cached decisions are recomputed. A new feature also needs a `FeatureId` in `providers/config.py` and a branch in `ModelDecisionEngine`; test it with a scripted fake provider as in `tests/test_model_engine.py`.
- **Provider trust:** a `baseUrl` other than the provider's official host needs `customBaseUrlConfirmed: true`, and plain `http` is only accepted for localhost (`providers/config.base_url_problem`, checked by the routes and the registry). A local client `cliPath` must name the expected executable (`codex`, `gemini`, `claude`, optionally `.exe`, `.cmd` or `.bat`).

### Platform gotchas

- **Windows ARM64:** use x64 Python 3.12 (runs emulated). Remotion has no win32-arm64 compositor, so rendering needs an **x64 Node**: `render/node_runtime.py` tries the `nodePath` setting, then `<data dir>/bin/node-x64/`, then `PATH`, checking each candidate's `process.arch`.
- `pnpm-workspace.yaml` sets `supportedArchitectures.cpu: [current, x64]` so x64 native packages (compositor, esbuild) install next to ARM64 ones. Only `esbuild` may run install scripts (`allowBuilds`).
- **Line endings:** `.gitattributes` forces LF. Generators normalize CRLF before `--check`.
- **`bash` from Python subprocess** on Windows can resolve to WSL's `bash.exe`, not Git Bash. Do not shell out to `bash` from code or tests.
- The `vision` extra pins `opencv-python-headless<5`: OpenCV 5 moved the Haar face cascade out of the main package.
- ffmpeg reports `h264_nvenc` even without a GPU on some builds; encoder choice also checks CUDA.

### Where planning and progress live

- `PLAN.md`: requirements, architecture, phases and acceptance criteria.
- `odd/tasks/powereditor-app.md`: task checklist, decisions, measurements, review log, follow-ups. Update it when you finish a task.
