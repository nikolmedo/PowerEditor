# AGENTS.md

Read the [For AI agents](README.md#for-ai-agents) section of `README.md` first: repo map, contracts, conventions and check commands.

Product plan and phases: `PLAN.md`. Progress and decisions: `odd/tasks/powereditor-app.md`.

All documentation, code and comments are in English. The app is called PowerEditor.

Before every `git push`, check whether the branch needs a version bump and, if it does, make it yourself without asking: compare the Conventional Commits since the last `v*` tag with `VERSION` (breaking → major, minor while 0.x; `feat` → minor; `fix`/`perf` → patch), run `python scripts/version.py set x.y.z` and `python scripts/version.py check`, and commit `chore: release x.y.z` on the branch. That script updates every place the version lives: `VERSION`, `backend/pyproject.toml`, `backend/powereditor/__init__.py`, `backend/uv.lock`, `packages/composition/package.json`, `web/package.json` and `desktop/package.json`. Full rule: README › For AI agents › Versioning and releases.
