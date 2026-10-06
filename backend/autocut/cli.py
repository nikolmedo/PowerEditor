from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn
from rich.table import Table

from autocut import doctor as doctor_module
from autocut.pipeline.ffmpeg import FfmpegError, MediaTools, MissingToolError
from autocut.pipeline.ingest import ingest_files, load_manifest
from autocut.pipeline.runner import ProgressCallback, ProjectLayout
from autocut.pipeline.transcription import transcribe_project
from autocut.settings_store import SettingsService
from autocut.transcribe.base import TranscriptionError
from autocut.transcribe.factory import TranscriberConfigError, create_transcriber

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """AutoCut command line interface."""


@app.command()
def doctor() -> None:
    """Report the status of external dependencies."""
    service = SettingsService.default()
    report = doctor_module.run_checks(locate=service.locate_executable)
    console = Console()
    console.print(f"Platform: {report.system} {report.machine} | Python {report.python_version}")
    table = Table("Dependency", "Required", "Status", "Version", "Detail")
    for check in report.checks:
        status = (
            "[green]found[/green]"
            if check.found
            else ("[red]missing[/red]" if check.required else "[yellow]missing[/yellow]")
        )
        table.add_row(
            check.name,
            "yes" if check.required else "no",
            status,
            check.version or "-",
            check.detail or "-",
        )
    console.print(table)
    if not report.ok:
        console.print("[red]One or more required dependencies are missing.[/red]")
        raise typer.Exit(code=1)


@app.command()
def serve(port: int = typer.Option(DEFAULT_PORT, help="Port to listen on.")) -> None:
    """Start the local API server."""
    uvicorn.run("autocut.api.app:create_app", factory=True, host=DEFAULT_HOST, port=port)


@contextmanager
def _progress_bar(console: Console) -> Iterator[ProgressCallback]:
    tasks: dict[str, TaskID] = {}
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as bar:

        def report(stage: str, fraction: float, message: str) -> None:
            if stage not in tasks:
                tasks[stage] = bar.add_task(stage, total=1.0)
            bar.update(tasks[stage], completed=fraction, description=f"{stage} [{message}]")

        yield report


def _default_project_id() -> str:
    return datetime.now().strftime("p-%Y%m%d-%H%M%S")


@app.command()
def ingest(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, resolve_path=True)],
    project_id: Annotated[str | None, typer.Option(help="Project to create or update.")] = None,
    fps: Annotated[int | None, typer.Option(help="Force the timeline frame rate.")] = None,
) -> None:
    """Probe media and build mezzanine, proxy and WAV files for a project."""
    console = Console()
    service = SettingsService.default()
    try:
        layout = ProjectLayout.for_project(service.paths, project_id or _default_project_id())
        tools = MediaTools.from_settings(service)
        with _progress_bar(console) as report:
            manifest = ingest_files(
                layout,
                files,
                tools,
                cuda_available=service.cuda_available(),
                fps=fps,
                progress=report,
            )
    except (ValueError, MissingToolError, FfmpegError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    for source in manifest.sources:
        console.print(
            f"{source.source_id}: {source.probe.display_width}x{source.probe.display_height} "
            f"@ {source.fps} fps{' (VFR source)' if source.probe.is_vfr else ''}"
            f" <- {source.original_path}"
        )
    console.print(f"Project dir: {layout.root}", soft_wrap=True)


@app.command()
def transcribe(project_id: str) -> None:
    """Transcribe every ingested source of a project into the stage cache."""
    console = Console()
    service = SettingsService.default()
    try:
        layout = ProjectLayout.for_project(service.paths, project_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not load_manifest(layout).sources:
        console.print(f"[red]Project {project_id!r} has no ingested sources.[/red]")
        raise typer.Exit(code=1)
    try:
        transcriber = create_transcriber(service)
        with _progress_bar(console) as report:
            transcripts = transcribe_project(
                layout, transcriber, service.get_effective().language, report
            )
    except (TranscriberConfigError, TranscriptionError) as exc:
        console.print(f"[red]{exc.code}: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    for source_id, transcript in transcripts.items():
        console.print(f"{source_id}: {len(transcript.words)} words ({transcript.model})")
    console.print(f"Project dir: {layout.root}", soft_wrap=True)
