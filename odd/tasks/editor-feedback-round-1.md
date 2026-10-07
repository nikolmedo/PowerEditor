# Feature: editor-feedback-round-1

Locator: `odd/tasks/editor-feedback-round-1.md` · Engram mirror: `odd/editor-feedback-round-1/tasks`

## Objective
Fix three issues found while using the app on the project "Primera prueba": repeated takes and fragments in the draft, a hard-to-navigate timeline, and the render browser download failing on Windows ARM64.

## Problem
1. The draft keeps fragments and earlier partial attempts of a line next to the chosen take, so the viewer sees flashes of words already said. Root causes:
   - `pipeline/clustering.py`: texts under 3 tokens use Jaccard (~0.1 against a full line), groups never merge, and the window is 6 takes / 120s.
   - `pipeline/takes.py:150-173`: the whole group is emitted at its first take's position, and singletons are always kept.
   - No split of a segment that holds two full attempts of the same line (273.86-303.40).
   - `pipeline/draft_builder.py:247`: no minimum length or "has words" filter, so 0.24s wordless clips survive.
2. The timeline cannot be zoomed or scrolled, the playhead cannot be dragged, and small clips are hard to select.
3. On Windows ARM64 with an arm64 Node on PATH, setup reports Node as present, does not fetch the pinned x64 Node, and the render browser install fails ("hace falta un Node.js x64").

## Scope
- T1 backend take pipeline. T2 web timeline. T3 runtime/setup on ARM64.
- Out of scope: new AI providers, render pipeline changes.

## Constraints
- English in code, comments, docs and commits. Conventional Commits, no AI attribution.
- Test-first where a deterministic runner exists (pytest, web tests).
- Checks: README "Checks" section.

## Delivery
- Strategy: ask-on-risk (user asked not to be interrupted: slices recorded, PR decisions left to the user). Forecast ~900 authored lines. Branch `feat/editor-feedback-round-1` from `main` at `db6963c`.

## Tasks
T1 is split into four commits.
- [x] T1a Group fragments and partial attempts with their line, and drop wordless trimmed segments. Route: delegated writer. Commit `9db1464`.
- [ ] T1b Leftover ordering: a later attempt's tail or remainder, or an earlier attempt's tail, can still be kept beside the chosen take. Real-data cases (source seconds):
  - 162.00 sits after grp-0019's chosen take at 167.12; the two score 0.69.
  - 190.42 sits after grp-0026's take; they score 0.49.
  - 464.00 sits after grp-0044's take; they score 0.63.
  - 506.64, the closing call to action, is placed before grp-0047's take at 544.20.

  The root cause is in `takes.py:150-173`, which emits each group at the position of its first take. Fix options to weigh:
  - Emit the group at its chosen take's position.
  - Treat a kept singleton just before or after the chosen take as part of that take's attempt.
  Route: delegated writer.
- [ ] T1c Split a segment that holds two full attempts of the same line. The real-data case is 273.98-303.28, the "Como madre primeriza" segment. Each part should then go through clustering on its own. Files: `segmentation.py`, possibly `features.py`. Route: delegated writer.
- [ ] T1d Check on the real project: re-run analyze on "Primera prueba" in the app, then watch the draft and confirm there are no repeated words. The stage version bumps (segments v2, takes v4) invalidate the cache.
- [ ] T2 Timeline navigation: zoom in and out with horizontal scroll, a draggable playhead, and easier clip selection. Route: delegated writer. The user asked for this second.
- [ ] T3 ARM64 render runtime: on Windows ARM64 with an arm64 Node on PATH, setup shows Node as present and does not fetch the pinned x64 Node, so the render browser install fails. Fetch or use the x64 Node when the host Node cannot render. Route: delegated writer. The user asked for this last.

## Progress
- Diagnosis is done on the real project (see Problem). Branch `feat/editor-feedback-round-1` exists.
- T1a (`9db1464`):
  - **Containment similarity:** a text under 3 tokens scores 1.0 when its tokens appear as one contiguous run inside the other take and it has at least one non-function word.
  - **Window:** the 6-take window counts only full takes (3+ tokens).
  - **Merging:**
    - A full take merges lone earlier takes by the usual rule.
    - It merges multi-take groups only at a score of 0.8 or more.
    - Fragments never merge groups.
  - **Wordless segments:** a segment whose trimmed span holds none of its words is dropped.
  - Stage versions: segments 2, takes 4.
  - On real data, the kept timeline went from 27 entries to 15.
- Watch items from T1a:
  - grp-0036 and grp-0039 (the Oscar lines) merged through a 4-word bridge take. As a result, 356.40 is now a removed alternative of 387.46. It is plausibly a paraphrase of the same line; check it in the app.
  - In the grey zone, a model engine now sees more `same_take` calls.

## Verification evidence
- T1a RED: 4 failing tests before the change, for example `test_cluster_takes_absorbs_fragments_and_partial_attempts_of_a_line` with `[0, 1, 2, 5] != [0, 1, 2, 3, 4, 5, 6]`.
- T1a GREEN, run by the writer:

  | Check | Result |
  | --- | --- |
  | `ruff check` | passed |
  | `ruff format --check` | passed |
  | `mypy` | passed |
  | `schema_gen --check` | passed |
  | `pytest -q` | 738 passed, 2 skipped |
  | `eval-takes` | unchanged at 100% clustering and 100% best take |
- Parent spot check: only the commit is on the branch, and the tree is clean apart from this doc.
- Native review: T1a has not been assessed yet. Run `gentle-ai review assess --cwd <repo> --agent claude-code --base-ref db6963c --committed-only --json` on resume.

## Next step
1. Run the pending review assessment for `9db1464`, as noted under Verification evidence.
2. Do T1b, then T1c and T1d.
3. Then T2, then T3.

To restart the dev servers, run `uv run powereditor serve --dev` in `backend/` and `corepack pnpm --filter @powereditor/web dev` at the root, then open `http://localhost:5173`.
