import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from powereditor.models import write_text_atomic
from powereditor.paths import AppPaths

logger = logging.getLogger(__name__)

SMALL_FILE_BYTES = 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProgressCallback(Protocol):
    def __call__(self, stage: str, fraction: float, message: str) -> None: ...


def no_progress(stage: str, fraction: float, message: str) -> None:
    return None


@dataclass(frozen=True)
class ProjectLayout:
    root: Path

    @classmethod
    def for_project(cls, paths: AppPaths, project_id: str) -> "ProjectLayout":
        if not _SAFE_ID.fullmatch(project_id) or project_id.strip(".") == "":
            raise ValueError(f"invalid project id: {project_id!r}")
        return cls(root=paths.projects_dir / project_id)

    @property
    def project_id(self) -> str:
        return self.root.name

    @property
    def media_dir(self) -> Path:
        return self.root / "media"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    def cache_file(self, stage: str) -> Path:
        return self.cache_dir / f"{stage}.json"

    def ensure(self) -> None:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


def file_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    identity: dict[str, Any] = {"path": str(path.resolve()), "size": stat.st_size}
    if stat.st_size <= SMALL_FILE_BYTES:
        identity["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        identity["mtimeNs"] = stat.st_mtime_ns
    return identity


def cache_key(stage: str, version: int, inputs: Sequence[Path], params: Mapping[str, Any]) -> str:
    payload = {
        "stage": stage,
        "version": version,
        "inputs": [file_identity(path) for path in inputs],
        "params": params,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_cached[T: BaseModel](path: Path, key: str, result_type: type[T]) -> T | None:
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("key") != key:
            return None
        return result_type.model_validate(record["result"])
    except (OSError, json.JSONDecodeError, KeyError, ValidationError) as exc:
        logger.warning("Discarding unusable cache file %s: %s", path, exc)
        return None


def run_stage[T: BaseModel](
    layout: ProjectLayout,
    stage: str,
    version: int,
    inputs: Sequence[Path],
    params: Mapping[str, Any],
    result_type: type[T],
    compute: Callable[[], T],
    *,
    outputs: Sequence[Path] = (),
    progress: ProgressCallback = no_progress,
) -> T:
    """Run `compute` unless a cached result exists for the same stage inputs."""
    key = cache_key(stage, version, inputs, params)
    cache_path = layout.cache_file(stage)
    cached = _load_cached(cache_path, key, result_type)
    if cached is not None and all(path.is_file() for path in outputs):
        progress(stage, 1.0, "cached")
        return cached
    progress(stage, 0.0, "running")
    result = compute()
    record = {
        "stage": stage,
        "version": version,
        "key": key,
        "result": result.model_dump(by_alias=True, mode="json"),
    }
    write_text_atomic(cache_path, json.dumps(record, indent=2) + "\n")
    progress(stage, 1.0, "done")
    return result
