"""PowerEditor: a local automatic video editor."""

from importlib import metadata

__version__ = "0.2.0"
"""Kept equal to `version` in pyproject.toml (a test checks it); used when the installed
package metadata cannot be read, as can happen in a frozen build."""

COPYRIGHT = "Copyright 2026 Nicolás Olmedo (https://nolmedo.dev)"
"""The copyright notice the license requires; shown by `powereditor --version`."""


def app_version() -> str:
    try:
        return metadata.version("powereditor")
    except metadata.PackageNotFoundError:
        return __version__
