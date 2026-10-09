# Feature: timeline-zoom-video-audio

Locator: `odd/tasks/timeline-zoom-video-audio.md` · Engram mirror: `odd/timeline-zoom-video-audio/tasks`

## Objective
Make the review timeline navigable on small screens and long videos with zoom and horizontal scroll (like Premiere / After Effects), and give the video's own audio (the voice) its own timeline lane, separate from the picture but linked to it, where it can be selected, muted and leveled.

## Problem
- `web/src/review/Timeline.tsx` positions everything as a percent of the total width; there is no zoom, no scroll and the ruler shows only two labels, so long videos become unreadable slivers.
- The timeline has a music lane but no lane for the video's audio. Voice level lives only in the Audio tab and the clip panel; nothing can be muted (no `muted` field anywhere).

## Scope
- T1 Zoom + horizontal scroll (web): scroll container with inner width `zoom × 100%`, sticky track labels, playhead inside the scrolled content, `+` / `−` / fit buttons, Ctrl+wheel and trackpad pinch anchored at the cursor, Shift+wheel horizontal scroll, `=` / `-` keys through `editorKeys`, playhead follow during playback, ruler ticks with a nice-interval picker. Pure helpers in `timelineModel.ts`.
- T2 `muted` on `AudioTrack` (backend model → schema → generated types), applied in preview and render for voice (`voiceGains`, `_source_factors`) and music (`Music.tsx`, music render path).
- T3 Voice lane + track selection (web): `voice` segments derived from the kept video clips (follows takes because `swapTake` replaces source and range); clicking the voice or music lane selects that track and opens the Audio tab focused on it; a clicked voice segment also selects its clip so its level can be set; mute buttons on lane labels and a mute switch per track in `AudioPanel`; `swapTake` keeps the slot's `volume` so a level set on a segment survives a take change.
- Out of scope: waveform drawing, detaching audio from video (J/L cuts), per-clip mute flag (a clip's level 0 already silences it).

## Constraints
- English in code, comments, docs and commits. Conventional Commits, no AI attribution.
- Never hand-edit `project.schema.json` or `types.generated.ts`; regenerate them.
- Preview (TS) and render (Python) audio gains stay in parity.
- Ducking stays word-driven when the voice is muted (deterministic envelope, not a sidechain).
- React `onWheel` is passive: Ctrl+wheel zoom uses a native non-passive listener.
- Checks: README "Checks" section, run from this worktree.

## Delivery
- Strategy: ask-on-risk. Forecast ~650 authored lines (T1 ~300, T2 ~120, T3 ~230). Worktree `PowerEditor-worktrees/timeline-zoom`, branch `feat/timeline-zoom-video-audio` from `origin/main` at `9936874`.

## Tasks
- [x] T1 Timeline zoom + horizontal scroll. Route: delegated writer (3+ non-trivial files). RED: 9 failing (timelineModel zoom/ruler, editorKeys zoom keys), then green. Zoom ×1.5 per step, cap min(200 px/s, 64×); Ctrl/Cmd+wheel and pinch zoom about the pointer; Shift+wheel scrolls; `=`/`+`/`-`/`\` keys; playhead follow pages the view when the frame moves; ruler ticks at round intervals ≥ 75 px apart. Sticky labels need flex rows (a sticky grid item stays in its grid area).
- [ ] T2 `AudioTrack.muted` in model, preview and render. Route: delegated writer (backend + composition).
- [ ] T3 Voice lane, track selection and mute UI; `swapTake` keeps volume. Route: delegated writer (3+ non-trivial files).

## Acceptance criteria
- `+` / `−` / Ctrl+wheel / pinch zoom the timeline; the time under the cursor stays put; the lanes scroll horizontally; labels stay visible; the ruler shows readable ticks at every zoom; "fit" returns to the whole video; the playhead stays in view while playing.
- A "Voice" lane shows one segment per kept clip, aligned with the video lane; after swapping a take it shows the new take's segment.
- Clicking the voice or music lane opens the Audio tab on that track; both can be muted from the lane label or the panel; a muted track is silent in the preview and in the export.

## Progress
- Exploration done (timeline is percent-based; voice audio is each clip's own media with gain = voice track volume × normalize gain × clip volume; no mute anywhere; ClipPanel already edits clip volume).
- T1 verification (worktree root): `corepack pnpm typecheck` pass; `corepack pnpm lint` pass; web tests 208 pass; web build pass; `format:check` pass. Not yet checked in a real browser.
