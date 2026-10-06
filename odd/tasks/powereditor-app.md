# Feature: powereditor-app

Locator: `odd/tasks/powereditor-app.md` · Engram mirror: `odd/powereditor-app/tasks`

## Objective
Build the rest of PowerEditor (PLAN.md Phases 1–10) as a downloadable, user-friendly Windows app.

## User decisions (2026-10-05)
- Phase 1 real-API comparison test (local vs OpenAI on the same audio) is **skipped by user decision**. The schema half stays: both transcribers must produce the same `Transcript` schema, verified with fakes.
- API keys and all settings are configured from the UI, never by editing `.env`. `.env` remains a dev-only override.
- Packaging (Phase 10) is now **in scope**: anyone can download and start using the app.
- Delivery: `feature-branch-chain`, one branch per slice stacked on the previous one.

## Architecture decisions
- Settings layering: code defaults ← `.env` (dev only) ← user settings file in `platformdirs.user_data_dir("PowerEditor")`. Secrets live in the OS keyring (Windows Credential Locker) via `keyring`, never in plain files.
- Runtime data (projects, models, downloaded binaries) lives in the user data dir. The app never writes to its install folder.
- ffmpeg/ffprobe paths are settings (auto-detected, later bundled or downloaded at first run).
- Runtime-aware Whisper default: GPU → `large-v3-turbo`, CPU → `small`.
- Types: Pydantic models are the source of truth → JSON Schema → generated TS types (closes review follow-up R2-types-mirror-claim).

## Constraints
- English code/comments/commits; Conventional Commits; no AI attribution.
- subprocess with argument lists only.
- `corepack pnpm` only. Python 3.12 x86_64 (emulated on ARM64).

## Risks / report items
- Host: Windows ARM64, no NVIDIA. faster-whisper/ctranslate2 and mediapipe availability must be verified, not assumed.
- Remotion license: free up to 3 people; public distribution needs a license review (PLAN line 45).
- gyan.dev ffmpeg `full_build` is GPL; bundling it affects licensing → prefer an LGPL build or first-run download.
- Phase 2 render-speed measurement is still required (not waived).
- Remotion ships no win32-arm64 compositor (only win32-x64). On this host server-side render needs x64 Node under emulation; Electron x64 build would carry it. Plan B (FFmpeg render, Remotion Player preview only) decided by measured speed.

## Slices (branches) and tasks
Reviewed boundary: `f35332a` (phase-0).

### Slice 1 — `feat/phase-1-core`
- [x] 1a Models + JSON Schema → TS types generation; settings store (platformdirs + keyring); FastAPI app with settings API. Route: delegated writer.
- [x] 1b Pipeline runner + cache, ingest (ffprobe, mezzanine, proxy, WAV) with lavfi fixtures; transcribers (local, openai) + fakes; CLI commands. Route: delegated writer.

### Slice 2 — `feat/phase-2-render`
- [x] 2a VAD, segmentation, silence cut, draft builder.
- [ ] 2b Remotion composition (clips + audio crossfade), render CLI + loudnorm final pass, render-speed measurement.

### Slice 3 — `feat/phase-3-takes`
- [ ] 3a Clustering, deterministic features, HeuristicEngine, synthetic benchmark (clearly labelled synthetic) + eval script.

### Slice 4 — `feat/phase-4-jev`
- [ ] 4a JevEngine with confidence gating and double-order Choice (from TypeSafe docs).

### Slice 5 — `feat/phase-5-subtitles`
- [ ] 5a Word remap to timeline, subtitle presets, topic transitions, SRT/ASS + OTIO export.

### Slice 6 — `feat/phase-6-ui`
- [ ] 6a Web app: settings page (keys + test connection), first-run setup check, Load/Review(read-only)/Export steps, jobs WebSocket, media range serving.

### Slice 7–9 — `feat/phase-7-editing`, `feat/phase-8-audio-color`, `feat/phase-9-graphics`
- [ ] 7a Editing: change take, trim, remove/restore, transitions, subtitle edit, undo/redo.
- [ ] 8a Audio & color panels.
- [ ] 9a Overlay templates + auto CTA.

### Slice 10 — `feat/phase-10-packaging`
- [ ] 10a Electron shell + PyInstaller backend sidecar, first-run onboarding (ffmpeg, Whisper model download, API key), installer.

## Progress
- Branch `feat/phase-1-core` created on top of `feat/phase-0-setup`.
- 1a done (delegated): models + schema-generated TS types, paths (platformdirs), settings store (layering + keyring WinVault verified), FastAPI settings/secrets/doctor API, `powereditor serve`. Evidence: pytest 62 passed (parent re-run); ruff/mypy clean; `schema_gen --check` 0 (parent re-run); pnpm typecheck/lint/check:types/prettier pass; serve smoke returned masked secrets only. RED observed for models/schema/settings/api; not observed for CRLF check and late-added isolation tests. Added `.gitattributes` (eol=lf).
- Follow-ups: invalid settings.json discards whole file (needs per-key migration later); Starlette TestClient httpx deprecation warning.

- 1b done (delegated): settings fixes (per-key load, update lock) closing R3 warnings; pipeline runner + cache; ingest (ffprobe, mezzanine libx264 CFR, 540p proxy, 16 kHz WAV) with lavfi fixtures; transcribers local (faster-whisper 1.2.1 / ctranslate2 4.8.2 installs on this host, 0 CUDA devices) and openai (whisper-1, MP3 upload, 25 MB limit verified, silence split); schema parity test with fakes; CLI ingest/transcribe. Evidence: pytest 104 passed / 1 slow deselected (parent re-run); ruff/mypy clean; ingest smoke 3.97 s then cache hit 1.77 s. RED: strong for settings fixes; weak (import error) for new modules.
- Notes: gyan.dev ffmpeg lists h264_nvenc without GPU → encoder choice also checks CUDA. Encoder not in ingest cache key (label may go stale).

- Rename AutoCut → PowerEditor (user request, 2026-10-05): commit `045420e`; Python package `powereditor`, CLI `powereditor`, data dir/keyring service `PowerEditor`, env `POWEREDITOR_DATA_DIR`, npm scope `@powereditor`. Verified: pytest 104 passed, ruff/mypy clean, schema/types checks, `git grep -i autocut` empty.

## Review log
- `1601302` (1a): medium, granted, 1 lens approved + acknowledged. Advisories: clip range invariants, keyring 503 untested, settings wipe/race (fixed in 1b).
- `ee5a6b1` (1b): high; combined 1b+rename candidate hit `lens_context_budget_exceeded`; re-reviewed 1b alone in a detached worktree: granted, 4 lenses approved + acknowledged. WARNING advisories → follow-ups: encoder missing from ingest cache key; WAV not a tracked/validated output; CLI transcribe doesn't catch ffmpeg/transcriber errors; no per-chunk retry for OpenAI; stale cache possible on crash (runner.py:110-124).
- `045420e` (rename): unavailable — mechanical rename counted as 4399 lines, exceeds native review budget; verified by full suite instead.
- `f78a4fd` (2a): high, granted, 4 lenses approved + acknowledged. WARNING advisories → follow-ups: vad.py:179-182 and :144-152 (full WAV in memory), ingest.py:275-276, OpenAI retry on non-idempotent timeouts (openai_whisper.py:140-148), zero-length segment padded into a clip (draft_builder.py:96-99).
- Reviewed boundary: `f78a4fd`.

- 2a done (delegated): 1b follow-ups fixed (encoder in cache key, WAV tracked output, atomic stage outputs, CLI error codes, OpenAI per-chunk retry); VAD (Silero ONNX bundled in faster-whisper, no torch, + dB floor; EnergyDetector fallback); segmentation; LUFS (ebur128) + color stats; draft builder + `export/subtitles.remap_words`; `analyze_project` + `powereditor analyze`. Evidence: pytest 156 passed (parent re-run); ruff/mypy clean; smoke on gated-tone clip kept 5.18 of 10 s, second run fully cached. RED strong for follow-ups, weak for new modules.
- Contract for 2b: clip frames = round((out-in)/speed*fps); composition must match.
- Known limits: fps from first source only; zero-length segment after VAD split may become a padded clip; Silero only tested on silence/noise (no speech fixture).

## Next step
2b: Remotion composition + render + loudnorm + render-speed measurement.
