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


class StageOutputError(RuntimeError):
    def __init__(self, stage: str, missing: Sequence[Path]) -> None:
        names = ", ".join(path.name for path in missing) or "result validation"
        super().__init__(f"stage {stage} did not produce valid outputs: {names}")
        self.code = "stage_output_missing"


type StageOutputs[T] = Sequence[Path] | Callable[[T], Sequence[Path]]


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


def _invalid_outputs[T: BaseModel](result: T, outputs: StageOutputs[T]) -> list[Path]:
    paths = outputs(result) if callable(outputs) else outputs
    return [path for path in paths if not path.is_file() or path.stat().st_size == 0]


def run_stage[T: BaseModel](
    layout: ProjectLayout,
    stage: str,
    version: int,
    inputs: Sequence[Path],
    params: Mapping[str, Any],
    result_type: type[T],
    compute: Callable[[], T],
    *,
    outputs: StageOutputs[T] = (),
    validate: Callable[[T], bool] | None = None,
    progress: ProgressCallback = no_progress,
) -> T:
    """Run `compute` unless a cached result exists for the same stage inputs.

    The cache record is removed before computing and written only after every
    declared output exists, is non-empty and passes `validate`, so a crash can
    never leave a record that points at partial outputs.
    """
    key = cache_key(stage, version, inputs, params)
    cache_path = layout.cache_file(stage)
    cached = _load_cached(cache_path, key, result_type)
    if (
        cached is not None
        and not _invalid_outputs(cached, outputs)
        and (validate is None or validate(cached))
    ):
        progress(stage, 1.0, "cached")
        return cached
    cache_path.unlink(missing_ok=True)
    progress(stage, 0.0, "running")
    result = compute()
    invalid = _invalid_outputs(result, outputs)
    if invalid or (validate is not None and not validate(result)):
        raise StageOutputError(stage, invalid)
    record = {
        "stage": stage,
        "version": version,
        "key": key,
        "result": result.model_dump(by_alias=True, mode="json"),
    }
    write_text_atomic(cache_path, json.dumps(record, indent=2) + "\n")
    progress(stage, 1.0, "done")
    return result
