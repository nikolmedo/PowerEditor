import platform
import shutil
import subprocess
from collections.abc import Callable, Sequence

from pydantic import BaseModel

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

VERSION_TIMEOUT_SECONDS = 15


class DependencyCheck(BaseModel):
    name: str
    required: bool
    found: bool
    version: str | None = None
    detail: str | None = None


class DoctorReport(BaseModel):
    system: str
    machine: str
    python_version: str
    checks: list[DependencyCheck]

    @property
    def ok(self) -> bool:
        return all(check.found for check in self.checks if check.required)


class _Probe(BaseModel):
    name: str
    executable: str
    args: list[str]
    required: bool


PROBES: tuple[_Probe, ...] = (
    _Probe(name="ffmpeg", executable="ffmpeg", args=["-version"], required=True),
    _Probe(name="ffprobe", executable="ffprobe", args=["-version"], required=True),
    _Probe(name="node", executable="node", args=["--version"], required=True),
    _Probe(name="pnpm", executable="corepack", args=["pnpm", "--version"], required=True),
    _Probe(name="cuda", executable="nvidia-smi", args=["--version"], required=False),
)


def default_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=VERSION_TIMEOUT_SECONDS,
        check=False,
    )


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _version_from(result: subprocess.CompletedProcess[str]) -> str | None:
    line = _first_line(result.stdout) or _first_line(result.stderr)
    if line is None:
        return None
    return line.split(" Copyright", 1)[0]


def check_dependency(probe: _Probe, runner: Runner) -> DependencyCheck:
    path = shutil.which(probe.executable)
    if path is None:
        return DependencyCheck(
            name=probe.name,
            required=probe.required,
            found=False,
            detail=f"'{probe.executable}' not found on PATH",
        )
    try:
        result = runner([path, *probe.args])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DependencyCheck(
            name=probe.name, required=probe.required, found=False, detail=str(exc)
        )
    if result.returncode != 0:
        return DependencyCheck(
            name=probe.name,
            required=probe.required,
            found=False,
            detail=_first_line(result.stderr) or f"exit code {result.returncode}",
        )
    return DependencyCheck(
        name=probe.name,
        required=probe.required,
        found=True,
        version=_version_from(result),
        detail=path,
    )


def run_checks(runner: Runner | None = None) -> DoctorReport:
    active_runner = runner if runner is not None else default_runner
    return DoctorReport(
        system=platform.system(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        checks=[check_dependency(probe, active_runner) for probe in PROBES],
    )
