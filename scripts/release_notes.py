"""Write release notes from the Conventional Commit subjects since the previous tag.

Usage (from the repo root, any Python 3.12+):

    python scripts/release_notes.py [--since <ref>] [--until <ref>] [--output notes.md]

`--since` defaults to the newest tag before `--until` (default `HEAD`), or the whole history
when there is none. Commits are grouped into Features (`feat`), Fixes (`fix`) and Docs
(`docs`); other types (chore, test, refactor, ...) are left out.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GROUPS = {"feat": "Features", "fix": "Fixes", "docs": "Docs"}
SUBJECT = re.compile(r"(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<text>.+)")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout.strip()


def previous_tag(until: str) -> str | None:
    try:
        return git("describe", "--tags", "--abbrev=0", f"{until}^") or None
    except subprocess.CalledProcessError:
        return None  # no earlier tag, or `until` is the first commit


def commit_subjects(since: str | None, until: str) -> list[str]:
    """Subjects of the commits after `since` up to `until`, newest first, merges left out."""
    span = f"{since}..{until}" if since else until
    output = git("log", "--no-merges", "--format=%s", span)
    return output.splitlines() if output else []


def entry(subject: str) -> tuple[str, str] | None:
    match = SUBJECT.fullmatch(subject.strip())
    if match is None or match["type"] not in GROUPS:
        return None
    text = match["text"]
    if match["scope"]:
        text = f"**{match['scope']}:** {text}"
    if match["breaking"]:
        text += " (breaking)"
    return GROUPS[match["type"]], text


def render_notes(version: str, subjects: Sequence[str], previous_tag: str | None) -> str:
    grouped: dict[str, list[str]] = {title: [] for title in GROUPS.values()}
    for subject in subjects:
        found = entry(subject)
        if found is not None:
            grouped[found[0]].append(found[1])
    lines = [f"## PowerEditor {version}", ""]
    for title, entries in grouped.items():
        if entries:
            lines += [f"### {title}", "", *(f"- {text}" for text in entries), ""]
    if not any(grouped.values()):
        lines += ["No feature, fix or documentation changes.", ""]
    since = f"Changes since {previous_tag}." if previous_tag else "First release."
    lines.append(f"{since} Check the installer against `SHA256SUMS.txt`.")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="start after this ref (default: the previous tag)")
    parser.add_argument("--until", default="HEAD", help="end at this ref (default: HEAD)")
    parser.add_argument("--version", help="version in the heading (default: VERSION)")
    parser.add_argument("--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)
    since = args.since or previous_tag(args.until)
    version = args.version or (REPO / "VERSION").read_text(encoding="utf-8").strip()
    notes = render_notes(version, commit_subjects(since, args.until), previous_tag=since)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8")
    else:
        sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
