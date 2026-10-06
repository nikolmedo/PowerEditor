from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
import uvicorn
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn
from rich.table import Table

from powereditor import doctor as doctor_module
from powereditor.eval.takes_eval import DEFAULT_BENCHMARK, evaluate_takes, load_benchmark
from powereditor.models import ProjectPreset
from powereditor.pipeline.analyze import analyze_project
from powereditor.pipeline.ffmpeg import FfmpegError, MediaTools, MissingToolError
from powereditor.pipeline.ingest import ingest_files, load_manifest
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, StageOutputError
from powereditor.pipeline.transcription import transcribe_project
from powereditor.pipeline.vad import EnergyDetector, SileroDetector, SpeechDetector
from powereditor.render import job as render_job
from powereditor.render.node_runtime import NodeRuntimeError
from powereditor.render.remotion_render import RenderError
from powereditor.settings_store import SettingsService
from powereditor.transcribe.base import TranscriptionError
from powereditor.transcribe.factory import TranscriberConfigError, create_transcriber

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

app = typer.Typer(no_args_is_help=True, add_completion=False)

PIPELINE_ERRORS = (
    MissingToolError,
    FfmpegError,
    StageOutputError,
    TranscriberConfigError,
    TranscriptionError,
    NodeRuntimeError,
    RenderError,
    render_job.ProjectNotFoundError,
    render_job.EmptyTimelineError,
)


def _fail(console: Console, exc: Exception) -> typer.Exit:
    code = getattr(exc, "code", "invalid_input")
    console.print(f"[red]{code}: {exc}[/red]", soft_wrap=True)
    return typer.Exit(code=1)


@app.callback()
def main() -> None:
    """PowerEditor command line interface."""


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
    uvicorn.run("powereditor.api.app:create_app", factory=True, host=DEFAULT_HOST, port=port)


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
    except (ValueError, *PIPELINE_ERRORS) as exc:
        raise _fail(console, exc) from exc
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
        raise _fail(console, exc) from exc
    if not load_manifest(layout).sources:
        console.print(f"[red]Project {project_id!r} has no ingested sources.[/red]")
        raise typer.Exit(code=1)
    try:
        transcriber = create_transcriber(service)
        with _progress_bar(console) as report:
            transcripts = transcribe_project(
                layout, transcriber, service.get_effective().language, report
            )
    except PIPELINE_ERRORS as exc:
        raise _fail(console, exc) from exc
    for source_id, transcript in transcripts.items():
        console.print(f"{source_id}: {len(transcript.words)} words ({transcript.model})")
    console.print(f"Project dir: {layout.root}", soft_wrap=True)


VadChoice = Literal["silero", "energy"]
DETECTORS: dict[str, SpeechDetector] = {"silero": SileroDetector(), "energy": EnergyDetector()}


@app.command()
def analyze(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, resolve_path=True)],
    project_id: Annotated[str | None, typer.Option(help="Project to create or update.")] = None,
    preset: Annotated[ProjectPreset | None, typer.Option(help="Force the output format.")] = None,
    vad: Annotated[VadChoice, typer.Option(help="Speech detector.")] = "silero",
    script: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="Script text used to judge completeness."),
    ] = None,
) -> None:
    """Ingest, transcribe, cut silences and pick takes into a draft project.json."""
    console = Console()
    service = SettingsService.default()
    try:
        script_text = script.read_text(encoding="utf-8") if script else None
        layout = ProjectLayout.for_project(service.paths, project_id or _default_project_id())
        with _progress_bar(console) as report:
            result = analyze_project(
                layout,
                service,
                files=files,
                preset=preset,
                detector=DETECTORS[vad],
                script=script_text,
                progress=report,
            )
    except (ValueError, OSError, *PIPELINE_ERRORS) as exc:
        raise _fail(console, exc) from exc
    console.print(
        f"{len(result.project.clips)} clips, kept {result.kept_seconds:.1f}s"
        f" of {result.original_seconds:.1f}s"
    )
    console.print(f"Project file: {result.project_path}", soft_wrap=True)


@app.command("eval-takes")
def eval_takes(
    fixture: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Labelled takes benchmark.")
    ] = DEFAULT_BENCHMARK,
    threshold: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="Confidence for an automatic decision.")
    ] = 0.6,
) -> None:
    """Report take clustering and take-choice accuracy of the heuristic engine."""
    benchmark = load_benchmark(fixture)
    report = evaluate_takes(benchmark, threshold=threshold)
    console = Console()
    if report.synthetic:
        console.print("[yellow]SYNTHETIC benchmark: not real footage.[/yellow]")
    console.print(f"Clusters: {report.clusters}")
    console.print(f"Clustering accuracy: {report.clustering_accuracy:.1%}")
    console.print(f"Best-take accuracy: {report.best_take_accuracy:.1%}")
    console.print(f"Off-take remark accuracy: {report.off_take_accuracy:.1%}")
    console.print(
        f"Automatic (confidence >= {report.threshold:.2f}): {report.automatic_share:.1%}"
        f" of decisions, {report.automatic_accuracy:.1%} correct"
    )


@app.command()
def render(
    project_id: str,
    output: Annotated[
        str, typer.Option(help="Export name under the project's exports/.")
    ] = "final",
) -> None:
    """Render a project to MP4 with loudness normalization."""
    console = Console()
    service = SettingsService.default()
    try:
        layout = ProjectLayout.for_project(service.paths, project_id)
        with _progress_bar(console) as report:
            result = render_job.render_project(layout, service, name=output, progress=report)
    except (ValueError, *PIPELINE_ERRORS) as exc:
        raise _fail(console, exc) from exc
    console.print(f"Output: {result.output}", soft_wrap=True)
    console.print(
        f"Video {result.video_seconds:.2f}s in {result.wall_s:.1f}s wall"
        f" (setup {result.timing.setup_s:.1f}s, render {result.timing.render_s:.1f}s):"
        f" {result.realtime_factor:.2f}x realtime"
    )
