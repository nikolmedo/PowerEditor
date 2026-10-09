# Feature: in-app-updates

Locator: `odd/tasks/in-app-updates.md` · Engram mirror: `odd/in-app-updates/tasks`

## Objective
Let the user update PowerEditor from inside the app: the update check in Settings → About downloads the new installer, installs it and asks to restart. When the automatic check finds a new version on its own, a native system notification announces it.

## Problem
- `web/src/settings/About.tsx` "Check now" only shows a status line and a "What's new" link; it cannot download or install.
- `UpdateBanner` downloads and verifies, but "Install and restart" runs the interactive NSIS wizard and quits; the app is not relaunched.
- An update found by the automatic check is only visible as a banner inside the window; nothing reaches the system.

## Scope
- T1 desktop shell: silent install with relaunch, Windows AppUserModelId, `updates:notify` IPC that shows a native `Notification` (deduped per version, click focuses the window).
- T2 web app: shared download/install hook and action used by both the banner and About; the banner asks the shell to notify for an automatic (non-forced, non-dismissed) find; periodic re-check while the app is open.
- Out of scope: delta updates, code signing, macOS/Linux.

## Constraints
- English in code, comments, docs and commits. Conventional Commits, no AI attribution.
- Keep the renderer's `notifications` permission denied (`ALLOWED_PERMISSIONS`); the toast comes from the main process.
- Keep the existing download verification (allowlisted URLs + SHA256SUMS).
- Installer flags verified in electron-builder 26.15.3 `templates/nsis/installSection.nsh`: the assisted installer starts the app after install only when `${Silent}` and `--force-run`; `--updated` marks an update. Shortcuts carry AUMID `${APP_ID}` = `build.appId`.
- Checks: README "Checks" section (desktop + web lint, typecheck, tests).

## Delivery
- Strategy: ask-on-risk. Forecast ~350 authored lines. Branch `feat/in-app-updates` from `main` at `a95063f`.

## Tasks
- [x] T1 Desktop: silent install + relaunch, AUMID, native update notification. Route: delegated writer (2+ non-trivial files). Commit `e248a60`. RED observed first (3 failing desktop tests: `SILENT_UPDATE_ARGS`, `UpdateAnnouncements`/`isReleaseVersion`, AUMID equals `build.appId`), then green.
- [x] T2 Web: About can download/install; banner triggers the notification on automatic finds; periodic re-check. Route: delegated writer (same worker). Commit `d961186`. RED observed first (3 failing web tests: notify once on automatic find, six-hour re-check, About download/install), then green.

## Acceptance criteria
- About → "Check now" with an update available shows Download → progress → "Restart and update"; clicking it quits, installs silently and relaunches the new version.
- An automatic check that finds a new version shows one native notification per version; clicking it brings the window forward. A forced check or a dismissed version does not notify.

## Progress
- Exploration done; tasks created.
- T1 + T2 implemented. Desktop: `SILENT_UPDATE_ARGS` (`--updated /S --force-run`) in `lifecycle.ts`; `APP_USER_MODEL_ID`, `isReleaseVersion`, `UpdateAnnouncements` in `updater.ts`; `updates:notify` IPC in `main.ts`; `notifyAvailable` in the preload. Web: `useUpdateDownload` + `DownloadAction` shared by the banner and About; install copy is now "Restart and update" / "Reiniciar y actualizar".
- Verification (repo root, after both commits): `corepack pnpm typecheck` pass; `corepack pnpm lint` pass; `corepack pnpm -r test` pass (desktop 75, composition 94, web 204); `corepack pnpm format:check` pass.
- Not verified: a real packaged install (silent upgrade + relaunch, toast attribution via AUMID) needs a manual test with two published releases.

## Next step
- Manual check on a packaged build, then native review / PR per the user's decision.
