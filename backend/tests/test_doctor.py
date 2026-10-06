import shutil
import subprocess
from collections.abc import Callable, Sequence

import pytest
from typer.testing import CliRunner

from autocut import doctor
from autocut.cli import app


def _fake_runner(output: str) -> doctor.Runner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 0, stdout=output, stderr="")

    return run


def _which_only(*names: str) -> Callable[[str], str | None]:
    def which(cmd: str) -> str | None:
        return f"/usr/bin/{cmd}" if cmd in names else None

    return which


def test_missing_required_dependency_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)

    report = doctor.run_checks(runner=_fake_runner("unused"))

    ffmpeg = next(check for check in report.checks if check.name == "ffmpeg")
    assert ffmpeg.required
    assert not ffmpeg.found
    assert ffmpeg.version is None
    assert not report.ok


def test_found_dependency_reports_first_version_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    report = doctor.run_checks(runner=_fake_runner("tool version 7.1\nmore details\n"))

    assert all(check.found for check in report.checks)
    assert {check.version for check in report.checks} == {"tool version 7.1"}
    assert report.ok


def test_missing_optional_cuda_does_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", _which_only("ffmpeg", "ffprobe", "node", "corepack"))

    report = doctor.run_checks(runner=_fake_runner("v1.0.0"))

    cuda = next(check for check in report.checks if check.name == "cuda")
    assert not cuda.required
    assert not cuda.found
    assert report.ok


def test_failing_version_command_marks_dependency_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    def broken(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="boom")

    report = doctor.run_checks(runner=broken)

    assert not report.ok
    assert all(not check.found for check in report.checks)


def test_report_includes_platform_and_python() -> None:
    report = doctor.run_checks(runner=_fake_runner("v1"))

    assert report.system
    assert report.machine
    assert report.python_version.startswith("3.")


def test_cli_doctor_exits_non_zero_when_required_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "ffmpeg" in result.output


def test_cli_doctor_exits_zero_when_all_required_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", _which_only("ffmpeg", "ffprobe", "node", "corepack"))
    monkeypatch.setattr(doctor, "default_runner", _fake_runner("v1.2.3"))

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "v1.2.3" in result.output


def test_version_drops_copyright_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    report = doctor.run_checks(
        runner=_fake_runner("ffmpeg version 9.0.2 Copyright (c) 2000-2026 the FFmpeg developers")
    )

    assert report.checks[0].version == "ffmpeg version 9.0.2"
