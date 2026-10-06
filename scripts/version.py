"""Keep every version string in step with the root `VERSION` file (semver, `x.y.z`).

Usage (from the repo root, any Python 3.12+):

    python scripts/version.py show
    python scripts/version.py set 0.2.0
    python scripts/version.py check [--tag v0.2.0]

`set` writes the version into each file below; `check` fails when one of them (or the
release tag, with `--tag`) disagrees with `VERSION`. Only the version field is touched, so
formatting and line endings stay as they were. `pnpm-lock.yaml` stores no workspace versions.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = "VERSION"
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

_PACKAGE_JSON = re.compile(r'(?m)^  "version": "(?P<version>[^"]*)"')
SPOTS: dict[str, re.Pattern[str]] = {
    "backend/pyproject.toml": re.compile(
        r'(?ms)^\[project\]\r?\n(?:(?!^\[).)*?^version = "(?P<version>[^"]*)"'
    ),
    "backend/powereditor/__init__.py": re.compile(r'(?m)^__version__ = "(?P<version>[^"]*)"'),
    "backend/uv.lock": re.compile(r'(?m)^name = "powereditor"\r?\nversion = "(?P<version>[^"]*)"'),
    "packages/composition/package.json": _PACKAGE_JSON,
    "web/package.json": _PACKAGE_JSON,
    "desktop/package.json": _PACKAGE_JSON,
}
"""Each file that carries the version, with a pattern whose `version` group is the value."""


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")  # bytes keep CRLF line endings intact


def read_version(repo: Path = REPO) -> str:
    return _read(repo / VERSION_FILE).strip()


def validate(version: str) -> str:
    if not SEMVER.fullmatch(version):
        raise ValueError(f"{version!r} is not a semver version like 1.2.3")
    return version


def found_version(repo: Path, relative: str) -> str | None:
    match = SPOTS[relative].search(_read(repo / relative))
    return match["version"] if match else None


def mismatches(repo: Path = REPO) -> list[str]:
    """One line per file whose version differs from `VERSION`; empty when all agree."""
    expected = read_version(repo)
    problems = []
    for relative in sorted(SPOTS):
        found = found_version(repo, relative)
        if found is None:
            problems.append(f"{relative}: no version found")
        elif found != expected:
            problems.append(f"{relative}: {found} (expected {expected})")
    return problems


def set_version(repo: Path, version: str) -> None:
    validate(version)
    updates: dict[Path, str] = {}
    for relative, pattern in SPOTS.items():
        text = _read(repo / relative)
        match = pattern.search(text)
        if match is None:
            raise ValueError(f"{relative}: no version found")
        updates[repo / relative] = (
            text[: match.start("version")] + version + text[match.end("version") :]
        )
    for path, text in updates.items():
        path.write_bytes(text.encode("utf-8"))
    (repo / VERSION_FILE).write_bytes(f"{version}\n".encode())


def main(argv: Sequence[str] | None = None, repo: Path = REPO) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print the version")
    setter = commands.add_parser("set", help="write a new version into every file")
    setter.add_argument("version")
    checker = commands.add_parser("check", help="fail when a file disagrees with VERSION")
    checker.add_argument("--tag", help="a release tag that must be v<VERSION>")
    args = parser.parse_args(argv)

    if args.command == "show":
        print(read_version(repo))
        return 0
    if args.command == "set":
        try:
            set_version(repo, args.version)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(f"version set to {args.version}")
        return 0
    problems = mismatches(repo)
    expected = read_version(repo)
    if args.tag is not None and args.tag != f"v{expected}":
        problems.append(f"tag {args.tag} does not match VERSION {expected}")
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"all versions are {expected}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
