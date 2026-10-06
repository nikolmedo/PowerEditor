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
- [x] 3a Clustering, deterministic features, HeuristicEngine, synthetic benchmark (clearly labelled synthetic) + eval script.

### Slice 4 — `feat/phase-4-providers`
- [x] 4a Provider registry (`ModelProvider`, transports `api` / `local_cli`): OpenAI (API + Codex CLI), Gemini (API + Gemini CLI), Claude (API + Claude Code CLI), DeepSeek (API), Jev; per-feature model assignment with heuristic fallback; settings/API for providers and feature mapping.
- [x] 4b LLM decision engine (structured JSON + Pydantic, double-order choice, confidence gating, token/cost tracking) wired into take/segment/transition decisions.

### Slice 5 — `feat/phase-5-subtitles`
- [x] 5a Word remap to timeline, subtitle presets, topic transitions, SRT/ASS + OTIO export.

### Slice 6 — `feat/phase-6-ui`
- [x] 6a Web app: settings page (keys + test connection), first-run setup check, Load/Review(read-only)/Export steps, jobs WebSocket, media range serving.

### Slice 7–9 — `feat/phase-7-editing`, `feat/phase-8-audio-color`, `feat/phase-9-graphics`
- [x] 7a Editing: change take, trim, remove/restore, transitions, subtitle edit, undo/redo.
- [x] 8a Audio & color panels.
- [x] 9a Overlay templates + auto CTA.

### Slice 11 — docs, CI/CD, releases, auto-update
- [x] 11a PLAN.md rewritten in English with new Phases 4 and 11; README.md (humans + agents); CLAUDE.md/AGENTS.md pointers; `.github/workflows/ci.yml` (windows + ubuntu). Branch `docs/plan-readme`.
- [ ] 11b Release workflow on `v*` tags (build installer, GitHub Release), single version source, in-app update check (GitHub latest release API) — after packaging.
- [x] 11c Screenshots in README once the UI lands; README kept current every phase.

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
- `f6cf249` (2b): high, granted, 4 lenses approved + acknowledged. WARNING advisories → follow-ups: pnpm-workspace supportedArchitectures/allowBuilds scope (R1-001), composition id duplicated in render.mjs, empty-edit mismatch (job.py:63), partial/non-atomic export on final-pass failure (job.py:75-84), Remotion renderer untested (remotion_render.py:73-134), loudnorm on silent audio (final_pass.py:34-46).
- `5c4afe5` (2c): high, granted, 4 lenses → `correction_required` (CRITICAL R4-voice-argv-length: per-clip `-i` + inline filtergraph exceeds the Windows 32767-char command line at ~100 clips). One bounded correction `02bf674`: render voice in batches of 40 clips with `-/filter_complex` script files, join exact-length PCM parts with the concat demuxer; tests for batching and renumbering. Targeted validation approved + acknowledged. Follow-ups: POSIX kill-tree for render timeout (remotion_render.py:88-94), voice rendered before media check (job.py:54-62), decode from start per clip (audio_mix.py:133).
- `02bf674`..`9f89392` (#4+#5 accumulated, stop-hook candidate): approved + acknowledged.
- Slice 3: single commit hit `lens_context_budget_exceeded` twice (uv.lock is byte-heavy); with user approval split and force-pushed as `d21459a` (deps), `3913292` (code), `a5a0e20` (tests/docs). Each reviewed in a detached worktree: medium, granted, 1 lens, approved + acknowledged. Follow-ups: eval doesn't validate one `best` per group (takes_eval.py:118), pyproject extras notes.
- Reviewed boundary: `a5a0e20`.
- Lesson: commit lockfile changes separately from code so each review candidate fits the native budget.

- 2a done (delegated): 1b follow-ups fixed (encoder in cache key, WAV tracked output, atomic stage outputs, CLI error codes, OpenAI per-chunk retry); VAD (Silero ONNX bundled in faster-whisper, no torch, + dB floor; EnergyDetector fallback); segmentation; LUFS (ebur128) + color stats; draft builder + `export/subtitles.remap_words`; `analyze_project` + `powereditor analyze`. Evidence: pytest 156 passed (parent re-run); ruff/mypy clean; smoke on gated-tone clip kept 5.18 of 10 s, second run fully cached. RED strong for follow-ups, weak for new modules.
- Contract for 2b: clip frames = round((out-in)/speed*fps); composition must match.
- Known limits: fps from first source only; zero-length segment after VAD split may become a padded clip; Silero only tested on silence/noise (no speech fixture).

- 2b done (delegated) with one acceptance failure: Remotion composition (Series/OffthreadVideo, shared timeline contract with roundHalfEven, injectable media resolver), `scripts/render.mjs`, backend render (x64 Node runtime probe, loopback media server, Remotion render, two-pass loudnorm final pass), `powereditor render`. pnpm `supportedArchitectures cpu [current, x64]` + `allowBuilds esbuild`. Evidence: pytest 172 passed, vitest 15 passed (parent re-run).
- Phase 2 measurement (ARM64 host, x64 Node+Chrome emulated, 1080p30, 12.1 s output): 114 s wall = 0.11x realtime (~30 s fixed startup + ~0.17 s/frame). A/V sync pass (17 ms). Loudness pass (-14.0 LUFS). **Clicks at cuts FAIL**: Remotion volume callbacks only change gain at video-frame boundaries.
- Fix path for clicks (needed under any render engine): rebuild audio sample-accurately with ffmpeg in the final pass (atrim/atempo/afade/concat) and drop Remotion audio.

- User decision (2026-10-06): keep Remotion as render engine (WYSIWYG); fix clicks by rebuilding audio with ffmpeg in the final pass.
- Delivery: PRs #1 (phase-0), #2 (slice 1), #3 (slice 2) created and merged into `main` in order with merge commits (retargeted to main before each merge). Next slices branch from `main`.

### Slice 2c — `feat/phase-2c-audio`
- [x] 2c Sample-accurate audio rebuild in final pass (drop Remotion audio) + 2b WARNING follow-ups.

- 2c done (delegated): `render/audio_mix.py` rebuilds voice audio sample-accurately (atrim/atempo/afade/apad/concat, cumulative frame→sample boundaries, anullsrc for silent sources); Remotion renders muted; final pass muxes video copy + rebuilt voice with two-pass loudnorm (skips silent audio). 2b follow-ups fixed: empty_timeline error, atomic export (.part + cleanup), composition id single source (composition.json), renderer tests with fake node + timeout (taskkill tree), pnpm-workspace comments. Evidence: pytest 201 passed, vitest 15 passed (parent re-run). Click test: cut jump 0.96–0.99x steady (was up to 3.4x); A/V 2.666667 s both; -14.0 LUFS. Phase 2 acceptance now met.
- Note: Player preview still uses frame-level fades (can click in preview only).

- User requests (2026-10-06): all docs in English; tidy readable code; README for humans (marketing, screenshots) and agents (token-saving guide); release workflow + in-app update check; multi-provider AI (API or local subscription CLIs: OpenAI, Gemini, Claude; DeepSeek API only), extensible registry, Providers screen + Features screen for per-feature model choice. Added to PLAN.md as Phase 4 (providers, absorbs Jev) and Phase 11 (docs/CI/release/update).
- Follow-up: `.env.example` lacks `FFMPEG_PATH`/`FFPROBE_PATH` (present in `config.py`).

- PR #4 (2c) and #5 (docs/CI) merged into `main` (user approved, 2026-10-06). First CI run green on windows + ubuntu. Accumulated #4+#5 range review approved; follow-ups: POSIX kill-tree on render timeout, per-clip voice decode from file start, crossfade naming, VoiceGraph dual representation, fade on short source audio.
- 3a done (delegated): text clustering (rapidfuzz, window of 6 takes; optional `embeddings` extra), deterministic features (fillers, restarts, cut-off, rate, prob, RMS dBFS, last-take bonus; optional `vision` extra with OpenCV <5), `decide/` with `DecisionEngine` protocol (+ `same_take`, `name`, `fingerprint`) and `HeuristicEngine`, takes stage cached, draft builder keeps best take and stores alternatives as removed clips sharing `takeGroupId` (no schema change), `powereditor eval-takes`. Evidence: pytest 246 passed / 1 skipped (vision extra) (parent re-run); SYNTHETIC benchmark 25 clusters: clustering 100%, best take 100%, off-take 100%, 72% automatic decisions (optimistic: fixture written with the heuristic).
- Follow-ups: takes stage loads whole WAV; proxies not in cache key; zero-length chosen clip vanishes; eval doesn't validate one `best` per group.

- PR #6 (phase 3) merged after green CI. User (2026-10-06): standing consent for every review (answer `granted`), merge PRs after green CI, do not stop until all phases are done.
- 4a done (delegated): `providers/` registry (open kinds, transports api/local_cli), API adapters OpenAI/DeepSeek (OpenAI-compatible), Gemini, Anthropic; local CLI adapters Codex/Gemini CLI/Claude Code (stdin prompt, temp cwd, kill tree, safe model-name pattern for .cmd shims); settings `providers` + `feature_models` (7 features), keys in keyring `provider:<id>:api_key`; routes `/api/providers*`, `/api/features/models`. Evidence: pytest 303 passed (parent re-run). Local detection: gemini 0.61.0 found, claude 2.1.289 signed in, codex not installed.
- Commits: `9b06c8b` deps (not due, under budget), `1d82aec` registry+adapters (high, 4 lenses approved), `8328d70` settings+routes (medium, approved). Follow-ups for 4b: base_url can leak API key to arbitrary host; cli_path executes arbitrary binary; overbroad auth hints; anthropic model list KeyError; CLI timeout hang; ReadError retry on POST; provider delete order; test endpoint for CLI untested.
- **Terms risk (reported to user):** Anthropic (Feb 2026) allows consumer subscription OAuth only in Claude Code/Claude.ai, not routed by third-party apps; Gemini CLI personal terms with 1000 req/day; Codex under ChatGPT terms. Must be surfaced in docs/UI.

- 4b done (delegated): 4a follow-ups (base URL trust per kind + `customBaseUrlConfirmed`, CLI basename check, auth regex, anthropic bad output, CLI kill/close, no POST ReadError retry, delete under lock); `model_min_confidence` (legacy `jev_min_confidence` accepted); typed questions (Noul/Choice/Score) over any provider with strict schemas; `ModelDecisionEngine` routing per feature with heuristic fallback, double-order best-take, confidence gating, usage report `cache/model_usage.json`; Jev provider (`typesafe`, HTTP `POST /v1/systemone`); CLI `providers list`, `features`; README terms section. Evidence: pytest 369 passed (parent re-run); eval-takes unchanged.
- Commits `139c9a9` (hardening, high, 4 lenses approved), `5c5734f` (engine, medium, approved). Follow-ups: Jev score div-by-zero (jev.py:119), bad-output retry not memoized (model_engine.py:272), base URL check only at write time for stored configs, `.env.example` needs `MODEL_MIN_CONFIDENCE`/`FFMPEG_PATH`/`FFPROBE_PATH` (file not readable by agent), per-provider benchmark pending real footage.

- PR #7 (phase 4) merged; it merged before CI registered (gh race) but main CI was green afterwards; now merging via a helper that waits for checks.
- Phase 5 done (delegated): follow-ups (Jev single-level score, bad-output memo, stored base URL rejected at build); `Subtitles.sourceWords` + `TimelineWord.wordIndex` schema change; `rebuild_subtitles`, `retime_words`, `edit_subtitle_text`, `group_lines` with TS mirror and shared fixture; 4 presets in Inter (bundled, OFL) with reel safe areas; heuristic topic transitions (new source → slide, long pause → fade) alternating cut/punch_in, all non-overlapping; SRT/ASS (karaoke `\k`), optional `nle` extra for OTIO/FCPXML (speed dropped in FCPXML). Acceptance: after speed 1.5 + take swap, word starts within half a frame of audio (−2..−15 ms); render 0.10–0.19x realtime. Evidence: pytest 397 passed, vitest 29 passed (parent re-run).
- Commits `7cb75ea` deps (not due), `ec45214` backend (approved, no findings), `fae43e7` composition (approved; follow-up: font load not awaited in font.ts).

- PR #8 (phase 5) merged after green CI.
- Phase 6 done on `feat/phase-6-ui` (delegated, 3 writers):
  - 6a backend API: ProjectStore (ETag saves), JobManager (cancellable process scopes), routes for projects/upload/media (Range)/jobs (WebSocket)/setup (Whisper download), SPA serving, `serve --open/--dev`. Commits c49fb80..75befbd, reviewed.
  - 6b-1: LocalOriginGuard (Host/Origin check, closes review R1), React+Vite web app (`web/`), typed API client, i18n es/en, shell, Setup/General/Providers/Features screens, CI web build. Commits a8a92e1..2e6e411, reviewed (security commit force-reviewed).
  - 6b-2: Load/Review/Export steps, Remotion Player on proxies, timeline from `timelineLayout`, follow-ups (client JSON errors, useResource race, watchJob polling fallback, save/analyze lock, bounded shutdown). Commits ee5af27..29c79f3, reviewed.
  - Evidence: pytest 481 passed, vitest 93 passed; full flow create → analyze → render → exports exercised through the API with silent sources; UI pages verified in Chrome.
  - Player playback not observable in the automated (hidden) Chrome tab; the UI and media URL are correct (206). Needs a manual check with real footage.
- README screenshots: real UI captures (review, load, providers, features, setup) and real render frames of a synthetic demo project, in `docs/screenshots/`.
- Follow-ups: upload.ts untested; LoadStep swallows analyze failure / upload failed dispatch (LoadStep.tsx:83-110); Remotion license prop on Player.

- PR #9 (phase 6) merged after green CI.
- Phase 7 done (delegated): pure edit ops (`web/src/edit/operations.ts`: swapTake, trimClip ±0.1 s, setRemoved, speed/volume, transitions + preset, subtitle edits/style), TS `retimeWords`/`editSubtitleText` mirrored with shared fixture, zundo undo/redo (100 steps, grouped trims, Ctrl+Z/Shift+Z/Y), debounced autosave with ETag + 409 conflict banner, Clip/Transitions/Subtitles panels, timeline keys. Follow-ups from 6b-2 fixed (LoadStep failures, upload tests). Evidence: pytest 482, vitest 142 (parent re-run); Phase 5 sync acceptance re-asserted after UI edits; manual API + Chrome check.
- Commits 71e3887, a01ac22, f532972, a70a0bb (all approved), 4cd1408 docs. Follow-ups: keepalive 64 KiB limit on page-close save; "keep mine" error handling (useAutosave.ts:42-45); number inputs clamp while typing; overlay drag deferred to Phase 9; swap keeps old decision confidence.

- PR #10 (phase 7) merged after green CI.
- Phase 8 done (delegated): music track (upload route, looped/trimmed, faded, deterministic ducking envelope driven by subtitle words, `amix`), per-source loudness matching (`Project.normalizeSources`, ±12 dB toward the mean), `AudioTrack.duckingDb`; color grade feColorMatrix per clip (presets natural/warm/cool/bw + 4 sliders, clip overrides), automatic source color match stored in `Source.colorCorrection`; Player preview music mirrors the ducking (shared fixture); Audio and Color panels; Phase 7 follow-ups (NumberField, swap confidence, keep-mine errors). Evidence: pytest 517, vitest 184 (parent re-run); manual render: ducking 12.0 dB, -14.0 LUFS, exact 7.933 s, warm shifts red +0.022 / blue -0.022.
- Commits 8c35a82, fa148ed, c2b23d1, 9745e4d (approved), e511c63 docs. Follow-ups: model bounds on color fields may reject old projects (models.py:57-72); mix with short voice (music_mix.py:36-44); music file without audio stream message (ingest.py:117-124); music upload race (AudioPanel.tsx:73-86); orphaned replaced music files; no re-match action for pre-phase-8 projects; sfx not mixed; `error.music_not_found` i18n key.

- PR #11 (phase 8) merged after green CI.
- Phase 9 done (delegated): six overlay templates (title, lower_third, cta, logo, progress_bar, image) with typed props, spring entrance/fade exit, safe areas clear of subtitles, layer order video < graphics < subtitles; overlay image upload route (PNG/JPEG/WebP by signature, no SVG, 20 MB); auto CTA from `has_cta` (setting `autoCta`); Graphics panel + draggable/resizable overlay track (one undo step per drag); Phase 8 follow-ups (lenient load of legacy color values, music edge cases, newest upload wins). Evidence: pytest 546, vitest 216 (parent re-run); manual render shows every overlay at its time, duration unchanged (238 frames).
- Commits a3100ca, 4310f1c, cc7873b, 741b5ea (approved), 717056c docs. Follow-ups: useLatestUpload stale state, ValueError leak in routes_audio.py:60-61, null overlay props (templates.ts:156), pointer capture loss on drag (OverlayBlock.tsx:75-93); overlays keep absolute frames after trims.
- HyperFrames research (user request): Apache-2.0; adopted as Phase 9b (overlay/caption looks, export quality presets, RAM-aware concurrency), Phase 10 additions (error hints, memory ceiling, LICENSE + THIRD_PARTY_NOTICES), and a backlog (overlay-only render + ffmpeg composite, Parakeet, carve ducking, shader transitions, matted captions). Open user decision: project license.

### Slice 9b — `feat/phase-9b-looks`
- [ ] 9c Retake README screenshots with the UI in English (user rule: docs and screenshots in English) after 9b merges.
- [x] 9b Overlay variants and caption presets inspired by HyperFrames, export quality presets, RAM-aware render concurrency, Phase 9 follow-ups.

- PR #12 (phase 9) merged after green CI.
- 9b done (delegated): overlay variants (title headline_slam; lower third kicker_name/mask_reveal/soft_pill; CTA lockup/close) + new templates count_up and progress_ring; subtitle presets pill_karaoke, kinetic_slam, emoji_pop, editorial_emphasis (ASS fallbacks); export quality draft/standard/high; RAM-aware concurrency (7 on this machine, frames cap); Phase 9 follow-ups (upload reset, typed invalid audio errors, null overlay props, drag cancel). No HyperFrames code copied (designs ported). Evidence: pytest 568, vitest 246 (parent re-run); draft render -41% vs standard; concurrency 6 vs 7 no measurable change on an 8 s clip.
- Follow-ups: kinetic_slam landing overlap; re-measure concurrency on long/low-RAM timelines; optional `Project.language` for stopwords.

## Next step
PR for 9b, then 9c (English screenshots); Phase 10 needs the license decision.
