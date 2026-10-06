# PowerEditor: development plan

PowerEditor is a local Windows app that edits talking-head videos almost fully automatically. It picks the best take when a phrase was recorded several times, removes silences, applies transitions, generates subtitles, and lets the user make simple adjustments from a graphical interface. It ships as a downloadable installer anyone can use.

Progress, decisions and review history live in `odd/tasks/powereditor-app.md`. This file is the product and architecture plan.

## Development conventions

- All documentation is written in **English**, always: this plan, the README, docstrings, comments.
- All code, identifiers, types, commits and comments are **100% English**. Code stays tidy and easy to read: small functions, descriptive names, no dead code, comments only where the reason is not obvious.
- The UI may show Spanish text, loaded from a strings file, never hardcoded.
- Commits follow Conventional Commits.
- Python: `uv`, Python 3.12 (x86_64 build, also on ARM64 hosts), strict type hints, `pydantic` models, `ruff` + `mypy --strict`.
- TypeScript: `strict: true`, pnpm workspaces run through `corepack pnpm` only, ESLint + Prettier.
- Every pipeline stage writes its output as cached JSON; a stage never recomputes when its inputs did not change (hash of inputs + params + stage version).
- FFmpeg and every other external tool are called with `subprocess` and an argument list, never a shell string, because Windows paths contain spaces and accents.
- Tests never touch the real user data dir or keyring: they set `POWEREDITOR_DATA_DIR` to a temp dir and use an in-memory secret store.
- A phase is not done until its acceptance criteria are met.

## Goals and non-goals

**Goals**

- Automatic processing: takes, silences, transitions, subtitles, audio and color with good defaults.
- Simple 3-step UI: Load → Review/Adjust → Export.
- Minimal paid-model usage: deterministic heuristics first; AI models only for semantic judgments; local Whisper by default.
- Bring your own model: API keys or already-logged-in local CLI clients, chosen per feature (Phase 4).
- Preview = render (WYSIWYG).
- A downloadable installer with in-app updates (Phases 10 and 11).

**Non-goals (v1)**

- Multicamera / audio-based sync.
- Keyframes, masks, chroma key, LUTs (.cube).
- More than one video track.
- Free dragging of clips on the timeline.

Packaging as an installer was a non-goal in the first draft. It is now in scope (Phase 10).

## Stack

| Layer | Technology |
|---|---|
| Backend / analysis | Python 3.12, FastAPI, uvicorn, pydantic, pydantic-settings, typer (CLI), rich |
| Settings and secrets | `platformdirs` user data dir + `keyring` (Windows Credential Locker) |
| Transcription | `faster-whisper` (local) or OpenAI `whisper-1` (API) |
| VAD | Silero VAD (ONNX model bundled with faster-whisper, no torch) + dB floor; energy detector fallback |
| Take similarity | `rapidfuzz` + local embeddings (`intfloat/multilingual-e5-small` via `sentence-transformers`) (planned, Phase 3) |
| Visual features | OpenCV + MediaPipe (face, sharpness) (planned, Phase 3; ARM64 availability to verify) |
| Decisions | Heuristic engine (default) or a registered AI provider per feature (Phase 4) |
| Media | FFmpeg / ffprobe 7.0+ (filter script files via `-/filter_complex`; NVENC when an NVIDIA GPU with CUDA is present) |
| Preview and render | Remotion (`@remotion/player` in the UI, `@remotion/renderer` for the video render) |
| Audio render | FFmpeg rebuilds the voice track sample-accurately; Remotion renders muted video |
| Frontend | React + Vite + TypeScript, zustand + zundo (undo/redo) (planned, Phase 6) |
| Desktop shell | Electron with the Python backend as a PyInstaller sidecar (Phase 10) |
| NLE export (optional) | OpenTimelineIO → FCPXML |

**Remotion license:** free for individuals and companies of up to 3 people. Public distribution needs a license review before the first release.

**FFmpeg license:** the gyan.dev `full_build` is GPL. Do not bundle it; prefer an LGPL build or a first-run download.

## Architecture

```
web/ (React UI + @remotion/player)                         [Phase 6 done: 3 steps, settings]
   │  REST + WebSocket (job progress), loopback 127.0.0.1:8765
backend/ (FastAPI): settings, ingest, transcription, VAD, clustering, decisions, media serving
   │  subprocess
packages/composition (Remotion) → muted MP4
   │
FFmpeg final pass: rebuilt voice track + two-pass loudnorm → export
```

- **Source of truth:** `<data dir>/projects/<project_id>/project.json`. Python builds the automatic draft, the UI edits it, Remotion renders it.
- **Types:** Pydantic models in `backend/powereditor/models.py` are the source of truth → JSON Schema (`packages/composition/schema/project.schema.json`) → generated TS types (`packages/composition/src/types.generated.ts`). Both generators have a `--check` mode.
- The Remotion composition lives in a shared package: the UI imports it for the Player and the backend runs `packages/composition/scripts/render.mjs` with the project as input props.
- **Timeline contract:** a clip lasts `round((outSec - inSec) / speed * fps)` frames, rounding half to even, in both `backend/powereditor/timeline.py` and `packages/composition/src/timeline.ts`.
- **Audio:** Remotion only changes volume at video-frame boundaries, which clicks at cuts. The backend rebuilds the voice with ffmpeg (`atrim`/`atempo`/`afade`/`concat`, batches of 40 clips through filter script files to stay under the Windows command-line limit), mixes the music under it with a sample-accurate ducking envelope, and muxes the result with the muted video.
- **Shell:** v1 runs as a local web app (FastAPI serves the React build). Phase 10 wraps it in Electron, which already carries the Node runtime Remotion needs.

### Runtime data and configuration

- Runtime data lives in `platformdirs.user_data_dir("PowerEditor")`: `projects/`, `models/`, `bin/`, `logs/`, `settings.json`. `POWEREDITOR_DATA_DIR` overrides the location. The app never writes to its install folder.
- Users set everything from the UI (today through the settings API). Settings are layered: code defaults ← `.env` (development only) ← user `settings.json`. The user file wins.
- API keys live in the OS keyring (service `PowerEditor`), never in plain files. The API reports whether a key is set and where it comes from, never its value.
- `.env` (read from the repo root or the working directory) is a developer override, never the user path.
- ffmpeg, ffprobe and Node paths are settings, auto-detected (configured path → `<data dir>/bin/<name>-<version>/` downloaded at first run → `<app>/runtime/` shipped with the app → `PATH`), see `resources.py` and `runtime/`.
- Whisper default depends on the runtime: GPU → `large-v3-turbo`, CPU → `small`.

## Repository layout

```
PowerEditor/
  backend/
    pyproject.toml           # package and CLI `powereditor`
    powereditor/
      config.py              # pydantic-settings: .env developer overrides
      settings_store.py      # settings layering, user settings file, keyring secrets
      paths.py               # user data dir layout, executable resolution
      doctor.py              # dependency checks (ffmpeg, ffprobe, node, pnpm, cuda)
      models.py              # Project, Clip, Word, Segment, Take, TakeCluster, ...
      schema_gen.py          # Project JSON Schema generator (--check)
      timeline.py            # clip frame layout shared with the composition
      cli.py                 # typer: doctor, serve, ingest, transcribe, analyze, render
      api/
        app.py               # FastAPI app: /api/health, /api/doctor
        routes_settings.py   # /api/settings, /api/secrets/{name}, key test
        routes_projects.py   # projects, ETag saves, subtitle rebuild and text edit
        routes_jobs.py       # analyze/render/subtitle jobs, WebSocket progress, cancel
        routes_media.py      # range-request serving for proxies and exports, reveal
        routes_setup.py      # first-run checklist, Whisper model download
      pipeline/
        runner.py            # stage orchestration + cache
        ffmpeg.py            # tool resolution and subprocess helpers
        ingest.py            # ffprobe, CFR mezzanine, proxy, audio extraction
        transcription.py     # transcription stage
        vad.py
        segmentation.py
        loudness.py          # LUFS measurement
        color_stats.py       # per-source luma/balance stats
        draft_builder.py     # builds the initial project.json
        analyze.py           # full analysis pipeline
        clustering.py        # planned (Phase 3)
        features.py          # planned: deterministic take features
      transcribe/
        base.py              # Transcriber protocol, filler-word prompts
        factory.py
        local_whisper.py     # faster-whisper
        openai_whisper.py    # whisper-1, verbose_json, word granularity
      decide/
        base.py              # DecisionEngine protocol
        heuristic.py
        prompts.py           # feature prompts as typed questions
        model_engine.py      # per-feature model routing with heuristic fallback
        factory.py
      providers/             # ModelProvider registry, API/CLI adapters, questions, Jev
      render/
        base.py
        job.py               # voice rebuild → video render → final pass → export
        audio_mix.py         # sample-accurate voice rebuild
        remotion_render.py   # runs scripts/render.mjs with the right Node
        node_runtime.py      # finds an x64 Node on Windows
        media_server.py      # loopback media server for the renderer
        final_pass.py        # mux + two-pass loudnorm
      export/
        subtitles.py         # word remap, rebuilds, text edits, line grouping
        subtitle_files.py    # SRT/ASS writers
        otio_export.py       # OTIO → FCPXML (optional `nle` extra)
    tests/
  packages/
    composition/             # Remotion composition (shared)
      schema/project.schema.json
      scripts/               # gen-types.mjs, render.mjs
      src/
        Root.tsx
        ProjectVideo.tsx
        timeline.ts          # mirrors backend timeline.py
        types.generated.ts   # generated from the JSON Schema
        clips/
        transitions/
        subtitles/
        overlays/            # LowerThird, Title, Cta, Logo, ProgressBar, ImageOverlay
        color/               # CSS/SVG filter builders
      test/
  web/                       # React UI (Phase 6)
    src/
      steps/                 # LoadStep, ReviewStep, ExportStep
      settings/              # Settings, Providers and Features screens
      timeline/
      panels/                # Clip, Transitions, Subtitles, Audio, Color, Graphics
      store/                 # zustand + zundo
      i18n/es.json
  odd/tasks/                 # feature progress documents
  pnpm-workspace.yaml
  .env.example               # developer overrides only
```

## Configuration

Users configure PowerEditor from the UI. The values below are the defaults; the same names work as developer overrides in `.env`.

```env
TRANSCRIBER=local            # local | openai
WHISPER_MODEL=               # empty = runtime default (GPU large-v3-turbo, CPU small)
WHISPER_DEVICE=auto          # auto | cuda | cpu
WHISPER_LANGUAGE=es
OPENAI_API_KEY=              # dev only; users store keys in the OS keyring

DECISION_ENGINE=heuristic    # legacy, ignored: features are routed per model (Phase 4)
TYPESAFE_API_KEY=            # legacy fallback key for a `typesafe` provider without its own key
JEV_MODEL=jev-1.13
JEV_MIN_CONFIDENCE=0.8       # legacy name of MODEL_MIN_CONFIDENCE (setting `modelMinConfidence`)

SILENCE_PADDING_MS=120
AUDIO_CROSSFADE_MS=15
TARGET_LUFS=-14
PUNCH_IN_SCALE=1.1

FFMPEG_PATH=                 # empty = auto-detect
FFPROBE_PATH=
```

The Node path (`nodePath`) is a user setting only.

## Pipeline

Each stage: input → output JSON in `<project>/cache/<stage>.json`. The cache key is a SHA-256 over the stage name, stage version, input file identities (path + size + SHA-256 for files up to 1 MiB, otherwise mtime) and params. The record is deleted before computing and written only after every declared output exists and validates.

1. **Ingest**
   - `ffprobe` each file.
   - Build a high-quality H.264 CFR **mezzanine** (for render) and a 540p H.264 **proxy** (for preview). Phones record VFR, and HEVC/ProRes do not play well in the browser.
   - Extract mono 16 kHz WAV audio.
2. **Transcribe** → `Word{text, start, end, prob | None}`, normalized for both providers.
   - Initial prompt with filler words ("Eh, este, mmm...") so Whisper keeps them.
3. **VAD** → speech ranges, configurable padding.
4. **Segmentation** → phrases split by long pauses + punctuation.
5. **Clustering** of repeated takes (Phase 3):
   - Similarity ≥ 0.8 → same part.
   - 0.5–0.8 → grey zone: the configured model decides (or the heuristic with a 0.7 threshold).
6. **Deterministic features per take** (all in code):
   - Completeness against the script (if any) or the longest take of the group.
   - Filler-word count, repetitions, cut-off phrase (regex/heuristic).
   - Speaking rate, mean Whisper confidence (if present).
   - Loudness, clipping.
   - Centered face, sharpness (sampled frames).
   - Bonus for being the last take.
7. **Decisions** (`DecisionEngine`): see "AI decisions" below.
8. **Color stats and loudness** per source file → starting values for matching.
9. **Draft builder** → `project.json` with clips, transitions, subtitles remapped to the timeline, audio tracks and initial color.

### Subtitles

- Never re-transcribe the final video: remap word timestamps from source time to timeline time using the clips (including `speed`).
- Editing text in the UI keeps each word's timing.
- Optional extra export: SRT/ASS.
- Source words are stored per source in `project.json` (`subtitles.sourceWords`); timeline words are rebuilt from them after every edit, and text edits are applied to them.

### Default transitions

- Between phrases of the same block: `punch_in` (alternate scale 1.0 / `PUNCH_IN_SCALE`).
- Between blocks with a topic change: `fade` or `slide`.
- Audio crossfade of `AUDIO_CROSSFADE_MS` at every cut.
- Transitions never overlap clips: `fade` rises from black and `slide` enters over the start of the incoming clip, so the timeline length and the rebuilt audio are unchanged.

## Transcription providers

```python
class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str | None) -> Transcript: ...
```

| Provider | Word timestamps | Notes |
|---|---|---|
| `local` (faster-whisper) | Yes | Default. GPU needs CUDA 12 + cuDNN 9 on PATH. Runs on CPU on Windows ARM64 (x64 Python under emulation). |
| `openai` (`whisper-1`) | Yes, `response_format=verbose_json` + `timestamp_granularities=["word"]` | For PCs without a GPU. Not a quality gain over `large-v3-turbo`. |
| `gpt-4o-transcribe` / `mini` | No (`json` only) | Out of v1. Future option: text + local forced alignment. |

- The API limit is 25 MB per file (verified). Audio is sent as mono 16 kHz MP3 and split at silences when it exceeds the limit; each chunk is retried on its own.
- `whisper-1` gives no per-word probability: that feature is `None` and scoring tolerates it.

## AI decisions

```python
class DecisionEngine(Protocol):
    def same_take(self, first: Take, second: Take, similarity: float) -> SameTakeDecision: ...
    def decide_cluster(self, cluster: TakeCluster, takes: list[Take], features: list[TakeFeatures]) -> ClusterDecision: ...
    def classify_segment(self, segment: Segment) -> SegmentFlags: ...
    def transition_between(self, prev: Segment, next: Segment) -> TransitionDecision: ...
```

`decide_cluster` receives the takes (with their text), not only the ids, so a model-backed engine has the minimal state it needs. `same_take` answers the clustering grey zone. The `HeuristicEngine` is the default and the fallback that is always available. Phase 4 replaces the single engine switch with per-feature model selection across providers (see Phase 4).

### AI features

Each question below is one selectable feature. The primitive column uses Jev's vocabulary; other providers answer the same question with a validated JSON output.

| Feature | Primitive | Minimal state |
|---|---|---|
| Audience content or out-of-take remark ("cut", "again", "is it recording?") | Noul | Segment text |
| Does the take end with the idea complete? | Noul | Take text |
| Are A and B attempts at the same part? (grey zone only) | Noul | Two texts |
| Fluency / naturalness | Score (described levels) | Take text |
| Best take of the group | Choice, **asked twice with reversed order** | Group texts |
| Topic change between A and B? | Noul | Two consecutive segments |
| Does the segment contain a call to action? (auto CTA) | Noul | Segment text |
| Subtitle cleanup (future) | Structured output | Segment words |

### Rules for every model

These started as Jev rules (documented limits of jev-1.13) and now apply to every LLM provider.

- No arithmetic, counting, dates or numeric comparison in the model: all of it lives in code.
- Minimal state: only what the question needs.
- Batch the questions for one cluster into one call where the provider supports it.
- Literal, precise instructions; criteria aligned with the instruction.
- Choices are biased toward the first option → ask again with reversed order and require agreement.
- Outputs are structured JSON validated with Pydantic; an invalid output counts as low confidence.

### Confidence gating

- Apply automatically when confidence ≥ `modelMinConfidence` (default 0.8; formerly `jevMinConfidence`) **and** both Choice orders agree.
- Otherwise apply the best heuristic and set a low `decisionConfidence` → highlighted in the UI for review.
- Final take score = weights in code × (deterministic features + model scores). Weights live in config, never in prompts.

### Jev

**Jev docs:** https://docs.typesafe.ai/llms.txt (index) and https://docs.typesafe.ai/agent-skill.md (agent skill). Read them before implementing the Jev adapter; do not guess the `Choice` and `Score` signatures.

Example verified in the docs (Noul):

```python
from typesafe_sdk import Noul, TypeSafeClient

client = TypeSafeClient(model="jev-1.13")
result = client.system_one(
    {"segment_text": text},
    {"is_audience_content": Noul(instructions="...")},
)
probability = result.nouls["is_audience_content"].noul
```

Uncertainties:

- Jev's Spanish support is not documented. Measure it against the benchmark before enabling it by default.
- Jev is in early access: `heuristic` stays the default.

## Data model (`project.json`)

Defined in Pydantic (`backend/powereditor/models.py`, camelCase aliases). The TS types are generated from its JSON Schema; never edit them by hand.

```ts
interface Project {
  version: 1;
  preset: "reel_9x16" | "landscape_16x9";
  fps: number;
  sources: Source[];
  clips: Clip[];                 // ordered single video track
  audioTracks: AudioTrack[];
  subtitles: { style: SubtitleStyle; words: TimelineWord[] };
  overlays: Overlay[];
  colorGrade: ColorGrade;        // global; clips can override
  normalizeSources?: boolean;    // match source loudness before mixing
}

interface Source {
  id: string;
  originalPath: string;
  mezzaninePath: string;
  proxyPath: string;
  displayColor: string;          // timeline color showing which source is used when
  loudnessLufs: number;
  colorStats: { meanLuma: number; meanR: number; meanG: number; meanB: number };
  colorCorrection?: { redGain: number; greenGain: number; blueGain: number } | null; // auto match
}

interface Clip {
  id: string;
  sourceId: string;
  inSec: number;
  outSec: number;
  speed: number;                 // 0.5 - 2.0
  volume: number;                // 0 - 2
  transitionIn: { type: "cut" | "punch_in" | "fade" | "slide"; durationFrames: number };
  takeGroupId?: string;
  alternativeTakeIds: string[];
  decisionConfidence?: number;
  colorOverride?: Partial<ColorGrade>;
  removed: boolean;              // soft delete, restorable
}

interface AudioTrack {
  id: string;
  kind: "voice" | "music" | "sfx";
  sourcePath?: string;           // music/sfx file
  volume: number;
  duckingEnabled: boolean;       // music ducks under speech (timeline words)
  duckingDb?: number;            // how far it drops, default 12
}

interface TimelineWord { text: string; startFrame: number; endFrame: number; clipId: string }

interface SubtitleStyle {
  preset: "karaoke_highlight" | "clean" | "bold_pop" | "minimal";
  fontSize: number;
  position: "bottom" | "center" | "top";
  highlightColor: string;
  maxWordsPerLine: number;
}

interface Overlay {
  id: string;
  templateId: "title" | "lower_third" | "cta" | "logo" | "progress_bar" | "image";
  startFrame: number;
  endFrame: number;
  props: Record<string, unknown>;
  autoGenerated: boolean;
}

interface ColorGrade {
  preset: "natural" | "warm" | "cool" | "bw";
  brightness: number;
  contrast: number;
  saturation: number;
  temperature: number;           // via SVG feColorMatrix
}
```

## Interface (3 steps)

### 1. Load

- Drag & drop videos; preset (Reel 9:16 / YouTube 16:9); language; optional script (textarea).
- "Process" button → per-stage progress over WebSocket.

### 2. Review and adjust

- **Player** (`@remotion/player`) on top + **contextual side panel**.
- **Timeline** at the bottom, tracks: Video · Subtitles · Graphics · Music.
  - Clips use their source file's color + a legend (which file is used when).
  - "N takes" badge on clips with alternatives → click to switch.
  - Yellow border when `decisionConfidence` < threshold.
  - Removed clips (silences/out-of-take) stay visible, dimmed and restorable.
- **Allowed interactions:** select, switch take, trim ±0.1 s, remove/restore, drag overlays. Nothing else.
- **Panels:**

| Panel | Automatic | Manual |
|---|---|---|
| Clip | - | Speed, volume, trim, take |
| Transitions | Punch-in / fade by topic | Type and duration per cut or global preset |
| Subtitles | Generated, karaoke | Style preset, size, position, text editing |
| Audio | -14 LUFS, ducking | Volume per track and per clip, load music |
| Color | Matched across sources | Preset + 4 sliders, "apply to all" |
| Graphics | Auto CTA (optional, AI feature) | Templates with editable props |

- Global undo/redo (zustand + zundo). Debounced autosave of `project.json`.

### 3. Export

- Resolution and quality → Remotion render (muted) → FFmpeg final pass (rebuilt voice + loudnorm) → "Open folder".
- Optional: SRT, FCPXML (OTIO).

### Settings screens

- **Settings:** transcription, language, silence padding, loudness target, tool paths, first-run setup check.
- **Providers** and **Features:** see Phase 4.

## Phases and acceptance criteria

### Phase 0: Setup (done)

- Monorepo (uv + pnpm), lint, typecheck, tests running, `.env.example`.
- Dependency check: FFmpeg, ffprobe, Node, pnpm, CUDA (optional).
- **Acceptance (met):** `uv run powereditor doctor` reports the status of each dependency.

### Phase 1: Ingest and transcription (done)

- Ingest (mezzanine, proxy, WAV) + both transcribers, settings store, settings API, schema-generated TS types.
- **Acceptance:** both providers produce a valid `Transcript` with the same schema. **Met** with fake providers (schema parity test).
- The comparison test on the same real audio against the OpenAI API (approximate WER, count of timestamped words) was **waived by user decision**.

### Phase 2: Silences and minimal render (done)

- VAD, segmentation, silence cut, draft `project.json`.
- Minimal Remotion composition: clips in sequence + audio crossfade.
- **Acceptance (met):** `powereditor render <project>` produces an MP4 with no silences, no clicks at cuts, A/V in sync, and the render speed is measured.
- Measurements (Windows ARM64 host, no GPU, x64 Node + Chrome under emulation, 1080p30, 12.1 s output):
  - Render speed: 114 s wall = 0.11x realtime (~30 s fixed startup + ~0.17 s/frame).
  - A/V sync: 17 ms. Loudness: -14.0 LUFS.
  - Clicks at cuts first **failed**: Remotion changes volume only at frame boundaries (cut jump up to 3.4x the steady level). Fixed by rebuilding the voice with ffmpeg and rendering Remotion muted: cut jump 0.96–0.99x.
- Decision: **Remotion stays the render engine** (WYSIWYG with the Player). Plan B (FFmpeg-only render) is not needed.
- ARM64 notes: Remotion ships no win32-arm64 compositor, so renders use an x64 Node (`nodePath` setting, `<data dir>/bin/node-x64`, or `PATH`); pnpm installs x64 optional dependencies next to the host ones. faster-whisper (ctranslate2) works on CPU.
- Known limit: the Player preview still uses frame-level fades, so preview (not export) can click at cuts.

### Phase 3: Takes (heuristic) (done, synthetic benchmark)

- Clustering + features + `HeuristicEngine`.
- Benchmark: 20–30 hand-labelled clusters (`backend/tests/fixtures/takes_benchmark.json`); a synthetic set is allowed while real footage is missing, clearly labelled synthetic.
- **Acceptance (met on synthetic data):** `powereditor eval-takes` reports take-choice accuracy. On the 25 synthetic clusters the heuristic scores 100% clustering, 100% best take and 100% off-take remarks, with 72% of decisions above confidence 0.6. The set was written together with the heuristic, so these numbers are optimistic; a hand-labelled set from real footage is still needed.
- Embedding similarity (`takeSimilarity: "embeddings"`, `embeddings` extra) and OpenCV visual features (`vision` extra) are optional; the defaults are rapidfuzz text similarity and no visual features.

### Phase 4: AI providers and per-feature model selection

**Status:** 4a (provider registry) done: `backend/powereditor/providers/` with API adapters (OpenAI, Gemini, Anthropic, DeepSeek over plain `httpx`) and local CLI adapters (Codex, Gemini CLI, Claude Code), per-provider keys in the secret store, `providers` and `featureModels` settings, and `/api/providers*` + `/api/features/models` routes. 4b done: feature prompts as typed questions (`decide/prompts.py`), `ModelDecisionEngine` routing each feature to its model with the heuristic as fallback, confidence gating with `modelMinConfidence`, double-order best-take Choice, model scores weighted in code, per-feature call and token counts in `cache/model_usage.json`, the Jev adapter (`typesafe` kind, System One HTTP API), and the `providers list` / `features` CLI commands. Pending: the benchmark per provider (needs real, opt-in model calls and hand-labelled footage) and cost in money (only tokens are tracked).

Users bring their own models. Some subscriptions cannot be used through an API, so a provider can be reached in two ways: an **API key**, or a **local subscription client** (a CLI app already logged in on the machine).

**Supported providers**

| Provider | API | Local client |
|---|---|---|
| OpenAI | Yes | Codex CLI |
| Google Gemini | Yes | Gemini CLI |
| Anthropic Claude | Yes | Claude Code CLI |
| DeepSeek | Yes | - |
| TypeSafe Jev | Yes (decision engine: Noul, Score, Choice) | - |
| Heuristic engine | Built in, no model | - |

The deterministic heuristic engine stays the default and the always-available fallback.

**Open provider registry**

- A `ModelProvider` interface declares its capabilities (text judgment, structured JSON judgment, maybe audio) and its transport kind: `api` or `local_cli`.
- Providers register themselves in a registry; features ask the registry for "a model that can do X" and never import a provider directly. Adding a provider never touches feature code.
- Local CLI transports run the client as a subprocess (argument list, timeout, kill tree), pass the prompt on stdin, and parse a JSON answer.
- Credentials go to the OS keyring. The current secrets (`openai_api_key`, `typesafe_api_key`) and the single `decision_engine` setting widen into per-provider credentials and per-feature selections.

**Screens** (backend and API land in this phase; the screens ship with the UI in Phase 6)

- **Providers:** register a provider with its credentials or detect and test its local client; choose which of that company's models to enable (the list is fetched from the provider when it offers one).
- **Features:** pick which registered model handles each AI feature (out-of-take detection, idea completeness, same-take grouping in the grey zone, fluency score, best-take choice, topic change, CTA detection; later subtitle cleanup). Each feature falls back to the heuristic.

**Rules:** the "Rules for every model" and "Confidence gating" sections apply to every provider. Token use and cost are tracked per feature and per video.

**Acceptance**

- Jev adapter with confidence gating and double-order Choice.
- At least one API provider and one local CLI provider pass the same feature contract tests (fakes in CI, real calls opt-in).
- On the benchmark: accuracy vs % of automatic decisions per provider, compared against the heuristic, with token cost per video.
- Removing every provider leaves the app fully working on heuristics.

**To verify (not decisions)**

- Terms of use of each local CLI client when driven by another app.
- Stability of each CLI's output format and flags across versions; pin and detect versions.
- Which providers expose a model list endpoint (Jev: `GET /v1/models` exists but its body is undocumented; the adapter falls back to `jev-latest` and `jev-1.13.0`).

### Phase 5: Subtitles and transitions

- Word remap to the timeline, style presets, topic transitions, SRT/ASS + OTIO export.
- **Acceptance:** subtitles stay in sync after changing a clip's speed and after switching takes.

### Phase 6: Basic UI

- Steps 1 and 3 + step 2 with player and read-only timeline (source colors, badges).
- Settings screen (keys + test connection), first-run setup check, Providers and Features screens, jobs WebSocket, media range serving.
- **Acceptance:** full flow load → process → view → export without the CLI; no setting requires editing a file.
- **Status:** 6a (backend API for the UI) done: projects (create from paths or uploads, list, ETag-guarded save, delete, subtitle rebuild and text edit), job manager with WebSocket progress and cancel, media Range serving, exports list and reveal, first-run setup with a Whisper download job, web app serving with SPA fallback, `serve --open`. Render quality is not wired yet: the Remotion render script has no quality option. 6b-1 done: `web/` (React + Vite + TypeScript, zustand, zundo prepared) with the app shell (Load → Review → Export header, projects home, settings sidebar), first-run setup checklist with the Whisper download job over WebSocket, General settings with 422 field messages, Providers (create/edit/delete, write-only API key, CLI path, confirmed custom base URL, test connection, model list, terms notices for local clients) and Features screens, Spanish/English strings in `web/src/i18n/`, light and dark themes; the local API refuses foreign `Host` headers and cross-site writes and WebSockets. 6b-2 done: Load (drag and drop or file picker with XHR upload progress, or local paths; preset, language, script; live stage list with cancel; error messages that link to the screen that fixes them), Review (Player on proxies with the shared composition, read-only timeline with source colors, legend, take badges, low-confidence outline, removed clips as marks at their cut, playhead synced both ways, clip details panel), Export (render with progress and cancel, SRT/ASS, exports list with play, download and open folder), project cards with status and delete. **Acceptance exercised** through the HTTP API exactly as the UI calls it (upload of two silent lavfi clips → analyze 3 s → project with two sources → render 25 s → SRT → exports list → reveal), and the built pages load from `serve` in Chrome; Player playback could not be watched because the automated Chrome tab was hidden (media loading deferred), so preview playback still needs a manual look with real footage. The analysis still downloads a missing Whisper model silently; the Load step warns and links to Setup first.

### Phase 7: Editing

- Switch take, trim, remove/restore, transitions, subtitle editing, undo/redo.
- **Status:** done. Pure edit operations in `web/src/edit/operations.ts` (take switch keeps the timeline position and carries the incoming transition and the take list to the new take; trims in 0.1 s steps clamped to the start of the file, a 0.1 s minimum and the furthest known point of the file, because the project does not store file lengths; speed 0.5–2, volume 0–2; per-cut and global transitions, instant cut/punch-in, fade/slide capped at the clip length; subtitle text and style), each recomputing the timeline words with the shared `remapWords`. `retimeWords`/`editSubtitleText` ported to the composition package, pinned by the shared fixture on both sides. Undo/redo with zundo (100 steps, bursts of one edge grouped), keyboard shortcuts (←/→, Delete, `[`/`]` and Shift, Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y), toolbar buttons, debounced autosave with `If-Match` and a conflict banner (reload or keep mine), flush on leaving the step and, best effort, on page close (a `keepalive` request is capped at 64 KiB, which a long project exceeds). Panels: Clip (trim, speed, volume, remove/restore, takes with their words), Transitions, Subtitles. No backend change was needed: the client sends recomputed words. Phase 5 acceptance re-checked in the web tests with the backend fixture numbers (speed 1.5 and take switch). Overlay dragging waits for Phase 9 (graphics).

### Phase 8: Audio and color

- Volume per track/clip, ducking, normalization, color matching, presets and sliders.
- **Status:** done. Audio is mixed by ffmpeg (Remotion renders muted): the voice graph multiplies each clip's volume by the voice track's volume and, with `normalizeSources`, a per-source gain toward the mean source loudness (±12 dB cap). A music track (uploaded with `POST /api/projects/{id}/music` into `media/`) is looped, trimmed to the exact voice length, faded in and out and ducked under speech by a deterministic envelope (timeline words merged across short gaps, 0.15 s attack, 0.4 s release, `duckingDb` deep), then mixed with `amix=normalize=0`; the final pass normalizes the mix. Color is one `feColorMatrix` per clip in the composition (source correction, then the global grade with the clip override), so Player and render match; the draft builder stores per-source `colorCorrection` gains that move each source's mean RGB to the project mean. Audio and Color panels with undoable edits; the Player plays the music with the same envelope per frame. Phase 7 follow-ups fixed: "keep mine" reports a failed reload, number fields accept partial input and clamp on blur, a manual take switch sets confidence 1.
- **Measured** (synthetic two-source project, 7.93 s, 660 Hz music tone under 220 Hz voice tones, warm preset): the music sits 12.0 dB lower relative to the voice with ducking than without (11.9–12.5 dB across windows); audio and video both 7.933333 s; −14.0 LUFS. Warm vs natural on the same frames: red +0.022 and blue −0.022 (mean, 0–1) on the darker source, +0.001 and −0.010 on the brighter one, whose saturated pixels clip.
- **Limits:** the preview changes volume once per video frame (the export is sample-accurate); ducking needs transcribed words (a project without words never ducks); color matching is first order on gamma-encoded means and cannot fix uneven light within a frame; sfx tracks are not mixed yet.

### Phase 9: Graphics

- Overlay templates + auto CTA.
- **Status:** done. Six templates in the composition (`title`, `lower_third`, `cta`, `logo`, `progress_bar`, `image`) with typed props, defaults and a runtime normalizer shared with the editor's forms, entrance (0.4 s damped spring) and exit (0.3 s accelerating fade), Inter, the project accent, and placement inside the preset's safe area clear of the subtitle band; drawn over the video and under the subtitles, clamped to the timeline so the video length never changes. Overlay images are uploaded to `media/` (`POST /api/projects/{id}/overlay-assets`, PNG/JPEG/WebP checked by signature, no SVG) and served to the Player by the media route and to the render by the loopback media server; a missing image stops the render before it starts. Auto CTA: segments flagged `has_cta` (model or a wider keyword list) get an automatic `cta` overlay over their kept clip when the draft is built (setting `autoCta`, on by default). Graphics panel (template thumbnails, add at the playhead, props form, image upload or reuse, remove, automatic ones marked) and a Graphics track whose blocks drag to move, drag at the edges to resize, snap to frames, nudge with the arrow keys, and undo as one step. Phase 8 follow-ups fixed: older projects with out-of-range color values load clamped, music mixing on a timeline too short for fades, a clear `invalid_music` message for files without audio, the newest music upload wins, `error.music_not_found`.
- **Measured** (landscape test project, 238 frames): title, lower third (above the bottom subtitles), CTA, progress bar and logo added through the API, rendered with `powereditor render`; every graphic shows at its time in the extracted frames and the export stays 238 frames / 7.933 s.
- **Limits:** centered subtitles reserve no band, so a centered graphic can sit behind them (subtitles stay on top); text does not shrink to fit, so very long titles wrap; the Player preview of a drag updates on release; overlays keep absolute frames, so trimming or removing clips before one (an automatic CTA included) leaves it where it was.

### Phase 9b: More looks (inspired by HyperFrames)

Design ideas from [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0), ported to Remotion components as designs, not copied code. Any copied file keeps its Apache-2.0 header, is marked as modified and is listed in `THIRD_PARTY_NOTICES`.

- Overlay variants from its registry: lower thirds (clean bar, kicker + name, mask reveal, soft pill), CTA lockup and close, count-up number, progress ring, headline slam.
- Subtitle presets: pill karaoke, kinetic slam, emoji pop, editorial emphasis (one emphasized word per line, never every line).
- Export quality presets: draft, standard, high (resolution, CRF and render concurrency).
- RAM-aware render concurrency: workers = min(CPU cores - 2, 50% of free RAM / per-browser budget, frames-based cap), passed to Remotion's `concurrency`.
- **Status:** done. Looks as `props.variant` on existing templates (schema unchanged, first look is the default so older projects keep theirs): title `classic`/`headline_slam`, lower third `clean_bar`/`kicker_name`/`mask_reveal`/`soft_pill`, CTA `pill`/`lockup`/`close`; new templates `count_up` (0 → value in 1.2 s, locale-free formatting) and `progress_ring` (fills over its span). Entrances are pure frame functions with key-frame tests; every look shares the exit and lays out inside the preset's safe area. Subtitle presets `pill_karaoke`, `kinetic_slam`, `emoji_pop` (only emoji already in the text) and `editorial_emphasis` (at most one word per line: longest non-stopword of 4+ letters, es and en stopwords together because the project stores no language, none on lines under 3 words); ASS falls back to karaoke, bold pop, clean, clean. Export quality `draft` (scale 0.5, CRF 28, veryfast, JPEG 60, AAC 128k), `standard` (Remotion defaults, 192k), `high` (CRF 15, slow, JPEG 95, 256k) from the Export step, the API (`quality`) and the CLI (`--quality`). Render tabs `min(cores - 2, 50 % of available RAM / 1536 MB, frames // 30, 8)` from `GlobalMemoryStatusEx` or `/proc/meminfo`, setting `renderMaxConcurrency` (0 = automatic). Phase 9 follow-ups fixed: dropped uploads no longer leave a progress bar, probe internals no longer reach the `invalid_music` message, `null` overlay props fall back to defaults, a cancelled drag or lost pointer capture drops the drag without an edit.
- **Measurements** (7.93 s landscape scratch project, 238 frames, 12 cores, ~38 GB free, x64 Node emulated on ARM64): automatic concurrency picks 7 (the frames cap; RAM allows 12, cores 10). Standard quality at 6 tabs (Remotion's default, cores / 2) vs 7: render 24.8 s vs 24.8–26.4 s, no measurable gain on a clip this short; the cap matters for long timelines and low-memory machines. Draft vs standard: render 14.7 s vs 24.8 s (−41 %), wall 21.2 s vs 31.4 s, 960×540 and 0.67 MB vs 1920×1080 and 5.2 MB.

### Phase 10: Packaging

- Electron shell with the Python backend as a PyInstaller sidecar and an x64 Node for Remotion.
- First-run onboarding: ffmpeg (LGPL build or download), Whisper model download, providers.
- Windows installer.
- Clear error messages when the render browser times out or runs out of memory, with a per-render memory ceiling.
- A project `LICENSE` and a `THIRD_PARTY_NOTICES` file before the first public build.
- **Acceptance:** a user without Python, Node or ffmpeg installs the app, finishes onboarding and exports a video.
- **Status (10a, standalone backend): done.** `resources.py` resolves the web build, the Remotion composition (prebuilt bundle) and tools from source or frozen. `runtime/` downloads pinned runtimes with SHA-256 checks into `<data dir>/bin/<name>-<version>/`: LGPL FFmpeg 8.1.3 (BtbN month-end autobuild), Node 24.21.0 x64 (nodejs.org) and Remotion's Chrome Headless Shell (`ensure-browser.mjs`); `GET /api/setup` lists them, `POST /api/setup/runtime/{name}` and `powereditor runtime install` install them. Ingest falls back to OpenH264 when FFmpeg has no libx264. `scripts/bundle.mjs` bundles the composition once (renders skip webpack), `stage-renderer.mjs` stages `@remotion/renderer` with only the x64 compositor. `scripts/build_backend.py` builds a PyInstaller onedir with a console and a windowed exe. `serve --port 0 --parent-pid` prints `POWEREDITOR_READY {"port", "token"}` for the shell.
- **Status (10b, desktop app and installer): done, pending a public release (Phase 11).** `desktop/` is an Electron 44 shell (TypeScript, sandboxed window with context isolation, only the sidecar's loopback origin, external links through an https allowlist, single instance, splash with a 90 s timeout and an error dialog naming the log folder, window bounds kept, sidecar tree killed on quit, logs in `%APPDATA%\PowerEditor\logs`). The sidecar token is enforced with `--port 0`: header `X-PowerEditor-Token` or an HttpOnly cookie set by a one-time `/?token=` redirect. A guided first run (`/welcome`: tools, transcription, optional AI models) opens while runtimes are missing. electron-builder writes a per-user NSIS installer for win x64 (`scripts/build_installer.py`, `dist/installer/`). 10a follow-ups fixed: symlinked zip members refused, a lock file per runtime, rename retried on Windows, READY only after the lifespan startup (already true, now pinned by tests), parent watched through its process handle, bounded smoke test, no `.env` in frozen builds, web types for runtimes.
- **TODO (license):** the project license is not decided. The packages say `UNLICENSED` and the installer shows no license page; add `LICENSE`, `THIRD_PARTY_NOTICES` (Electron/Chromium, FFmpeg LGPL, PyAV, Remotion, fonts) and an NSIS license page before the first public build.

### Phase 11: Docs, CI/CD, releases and auto-update

- **Docs:** the README serves humans and AI agents and is kept current at the end of every phase. Screenshots are added once the UI exists.
- **CI:** GitHub Actions on every pull request and push to `main`: lint, format check, typecheck, tests, schema/type freshness (`.github/workflows/ci.yml`, added with this plan revision).
- **Release workflow:** on a version tag (`v*`), build the installer and publish a GitHub Release with the artifacts (`.github/workflows/release.yml`, to be created in this phase). The job runs on `windows-latest` (x64): `python scripts/build_installer.py --smoke`, then upload `dist/installer/*.exe`. Code signing is still to decide (unsigned installers trigger SmartScreen).
- **Versioning:** semantic versioning with a single version source that feeds the backend package, the npm packages and the installer.
- **Auto-update:** the app checks the GitHub Releases "latest release" API, notifies the user of a newer version, and offers download and install.
- **Acceptance:** pushing a tag produces a GitHub Release with an installer; an older installed build detects it and updates.

### Backlog (after v1)

- **Render speed:** render only the graphics and subtitle layer as transparent video and composite it over the source clips with ffmpeg, instead of decoding every video frame in the browser (the pattern behind HyperFrames' `videoFrameInjector`). Expected to be the largest speed-up on slow machines.
- **Transcription:** optional NVIDIA Parakeet with Whisper as the fallback, plus language detection.
- **Audio:** "carve" ducking that removes only the voice's frequency bands from the music instead of lowering it whole.
- **Transitions:** WebGL shader transitions (need overlapping clips, so the duration contract has to change first).
- **Captions behind the speaker:** need person segmentation; single-subject only.

## Risks and items to verify

- [x] GPU available → none on the dev host (Windows ARM64). CPU Whisper (`small`) works; GPU path stays untested.
- [x] Remotion render speed on this PC (Phase 2): 0.11x realtime at 1080p30 under x64 emulation.
- [x] OpenAI transcription API file size limit: 25 MB, handled by splitting at silences.
- [x] Clicks at cuts: fixed by rebuilding audio with ffmpeg.
- [x] `playbackRate` pitch and per-frame volume in Remotion: moot for export (ffmpeg `atempo` and filters own the audio); still relevant for Player preview.
- [x] Per-frame volume API in Remotion for preview ducking: `<Audio volume={(frame) => ...}>` drives the preview envelope; exports never depend on it because ffmpeg builds their audio.
- [ ] TypeSafe SDK environment variable name and `Choice`/`Score` signatures.
- [ ] Jev quality in Spanish.
- [ ] CUDA/cuDNN setup for faster-whisper on Windows (no GPU host available).
- [ ] MediaPipe availability on Windows ARM64.
- [ ] Proxy playback in the browser (served with range requests).
- [ ] Remotion license for public distribution.
- [x] FFmpeg build licensing for distribution → first-run download of a pinned LGPL build (BtbN `win64-lgpl`); no libx264, so ingest uses OpenH264. Still to check: OpenH264 patent terms for a source-built (not Cisco binary) encoder, and LGPL notices in `THIRD_PARTY_NOTICES`.
- [ ] Terms of use and output stability of local CLI clients (Phase 4).
