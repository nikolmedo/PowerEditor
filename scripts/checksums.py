"""Write `SHA256SUMS.txt` for release files, in the format `sha256sum --check` reads.

Usage: python scripts/checksums.py --output dist/release/SHA256SUMS.txt FILE [FILE ...]

The desktop updater (`desktop/src/updater.ts`) reads the same format to verify the
installer it downloads.
"""

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256sums(paths: Sequence[Path]) -> str:
    """`<hex>  <file name>` per file, sorted by name, LF line endings."""
    return "".join(
        f"{sha256_of(path)}  {path.name}\n" for path in sorted(paths, key=lambda p: p.name)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    args.output.write_bytes(sha256sums(args.files).encode("utf-8"))
    print(args.output.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
