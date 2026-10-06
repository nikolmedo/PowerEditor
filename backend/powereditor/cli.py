import os
import secrets
import threading
import time
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
import typer
import uvicorn
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn
from rich.table import Table

from powereditor import COPYRIGHT, app_version, sidecar
from powereditor import doctor as doctor_module
from powereditor.api.app import ENV_DEV_CORS, ENV_SESSION_TOKEN
from powereditor.api.session_token import TOKEN_HEADER, TOKEN_QUERY
from powereditor.decide.model_engine import ModelUsageReport
from powereditor.eval.takes_eval import DEFAULT_BENCHMARK, evaluate_takes, load_benchmark
from powereditor.export.subtitle_files import SubtitleFormat, write_subtitles
from powereditor.export.subtitles import rebuild_subtitles
from powereditor.models import ProjectPreset, load_project, write_text_atomic
from powereditor.pipeline.analyze import analyze_project
from powereditor.pipeline.ffmpeg import FfmpegError, MediaTools, MissingToolError
from powereditor.pipeline.ingest import ingest_files, load_manifest
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, StageOutputError
from powereditor.pipeline.transcription import transcribe_project
from powereditor.pipeline.vad import EnergyDetector, SileroDetector, SpeechDetector
from powereditor.providers.config import FEATURE_IDS
from powereditor.render import job as render_job
from powereditor.render.node_runtime import NodeRuntimeError
from powereditor.render.quality import RenderQuality
from powereditor.render.remotion_render import RenderError
from powereditor.resources import Resources
from powereditor.runtime.manager import (
    BrowserPathTooLongError,
    RuntimeInstallError,
    RuntimeManager,
    UnknownRuntimeError,
    manager_for,
)
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
    render_job.MusicNotFoundError,
    BrowserPathTooLongError,
)


def _fail(console: Console, exc: Exception) -> typer.Exit:
    code = getattr(exc, "code", "invalid_input")
    console.print(f"[red]{code}: {exc}[/red]", soft_wrap=True)
    return typer.Exit(code=1)


def _print_version(requested: bool) -> None:
    if not requested:
        return
    typer.echo(f"PowerEditor {app_version()}")
    typer.echo(COPYRIGHT)
    raise typer.Exit()


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and copyright, then exit.",
        ),
    ] = False,
) -> None:
    """PowerEditor command line interface."""


@app.command()
def doctor() -> None:
    """Report the status of external dependencies."""
    service = SettingsService.default()
    report = doctor_module.run_checks(
        locate=service.locate_executable, frozen=Resources.current().frozen
    )
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


def open_when_ready(
    base_url: str, token: str | None = None, timeout_s: float = 30.0
) -> threading.Thread:
    """Open the browser once the server answers its health check (in the background)."""
    headers = {TOKEN_HEADER: token} if token else {}

    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/api/health", headers=headers, timeout=1.0).is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        webbrowser.open(f"{base_url}/?{TOKEN_QUERY}={token}" if token else f"{base_url}/")

    thread = threading.Thread(target=wait_and_open, daemon=True)
    thread.start()
    return thread


@app.command()
def serve(
    port: Annotated[
        int, typer.Option(help="Port to listen on; 0 picks a free one (see the READY line).")
    ] = DEFAULT_PORT,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the app in the default browser.")
    ] = False,
    dev: Annotated[
        bool, typer.Option(help="Allow the Vite dev server origin (CORS) for UI development.")
    ] = False,
    parent_pid: Annotated[
        int | None, typer.Option(help="Shut down when this process exits (desktop shell).")
    ] = None,
) -> None:
    """Start the local server: the API under /api and the built web app at /.

    Once listening it prints `POWEREDITOR_READY {"port": N, "token": ...}` on stdout. With
    `--port 0` (the desktop sidecar) the API requires that token; on a fixed port it is null.
    """
    if dev:
        os.environ[ENV_DEV_CORS] = "1"
    try:
        sock = sidecar.bind_loopback(DEFAULT_HOST, port)
    except OSError as exc:
        console = Console(stderr=True)
        console.print(f"[red]port_unavailable: cannot listen on port {port}: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    bound = int(sock.getsockname()[1])
    token = secrets.token_urlsafe(32) if port == 0 else None
    if token:
        os.environ[ENV_SESSION_TOKEN] = token
    else:
        os.environ.pop(ENV_SESSION_TOKEN, None)
    if open_browser:
        open_when_ready(f"http://{DEFAULT_HOST}:{bound}", token)
    config = uvicorn.Config(
        "powereditor.api.app:create_app",
        factory=True,
        host=DEFAULT_HOST,
        port=bound,
        # The access log goes to stdout, which the shell reads; it would also show the token.
        access_log=token is None,
    )
    server = sidecar.AnnouncingServer(
        config, on_started=lambda: sidecar.announce(sidecar.ready_line(bound, token))
    )
    if parent_pid is not None:

        def stop() -> None:
            server.should_exit = True

        sidecar.watch_parent(parent_pid, stop)
    server.run(sockets=[sock])


runtime_app = typer.Typer(no_args_is_help=True, help="Runtimes downloaded at first run.")
app.add_typer(runtime_app, name="runtime")


def runtime_manager(service: SettingsService) -> RuntimeManager:
    return manager_for(service)


@runtime_app.command("status")
def runtime_status() -> None:
    """List the downloadable runtimes (ffmpeg, Node, render browser) and where they are."""
    console = Console()
    table = Table("Runtime", "Version", "Status", "Path")
    for status in runtime_manager(SettingsService.default()).statuses():
        if not status.supported:
            state = "[yellow]unsupported[/yellow]"
        else:
            state = "[green]installed[/green]" if status.installed else "[red]missing[/red]"
        table.add_row(status.name, status.version or "-", state, status.path or "-")
    console.print(table)


@runtime_app.command("install")
def runtime_install(name: str) -> None:
    """Download, verify and install one runtime into the data dir."""
    console = Console()
    manager = runtime_manager(SettingsService.default())
    try:
        with _progress_bar(console) as report:
            installed = manager.install(name, lambda fraction: report(name, fraction, "download"))
    except (RuntimeInstallError, UnknownRuntimeError) as exc:
        raise _fail(console, exc) from exc
    version = f" {installed.version}" if installed.version else ""
    console.print(f"{name}{version} installed: {installed.path}", soft_wrap=True)


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
    if result.model_usage is not None:
        _print_model_usage(console, result.model_usage)


def _print_model_usage(console: Console, report: ModelUsageReport) -> None:
    table = Table("Feature", "Model", "Calls", "Failed", "Heuristic used", "Tokens in/out")
    for feature, usage in report.features.items():
        table.add_row(
            feature,
            f"{usage.provider_id}/{usage.model}",
            str(usage.calls),
            str(usage.failures),
            str(usage.fallbacks),
            f"{usage.input_tokens}/{usage.output_tokens}",
        )
    console.print(table)


providers_app = typer.Typer(no_args_is_help=True, help="Registered model providers.")
app.add_typer(providers_app, name="providers")


@providers_app.command("list")
def list_providers() -> None:
    """List registered providers and whether their credentials are set."""
    service = SettingsService.default()
    console = Console()
    configs = service.get_effective().providers
    if not configs:
        console.print("No providers registered; every feature uses the heuristic engine.")
        return
    table = Table("Id", "Kind", "Transport", "Label", "Credentials", "Enabled models")
    for config in configs:
        if config.transport == "local_cli":
            credentials = "local client sign-in"
        else:
            credentials = "set" if service.provider_api_key(config.id) else "missing"
        table.add_row(
            config.id,
            config.kind,
            config.transport,
            config.label,
            credentials,
            ", ".join(config.enabled_models) or "-",
        )
    console.print(table)


@app.command()
def features() -> None:
    """Show which model answers each AI feature (heuristic when none)."""
    service = SettingsService.default()
    console = Console()
    settings = service.get_effective()
    table = Table("Feature", "Provider", "Model")
    for feature in FEATURE_IDS:
        assigned = service.feature_model(feature)
        if assigned is None:
            table.add_row(feature, "heuristic", "-")
        else:
            config, model = assigned
            table.add_row(feature, config.id, model)
    console.print(table)
    console.print(f"Minimum model confidence: {settings.model_min_confidence:.2f}")


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
    quality: Annotated[
        RenderQuality, typer.Option(help="draft (half size, fast), standard, or high.")
    ] = "standard",
) -> None:
    """Render a project to MP4 with loudness normalization."""
    console = Console()
    service = SettingsService.default()
    try:
        layout = ProjectLayout.for_project(service.paths, project_id)
        with _progress_bar(console) as report:
            result = render_job.render_project(
                layout, service, name=output, progress=report, quality=quality
            )
    except (ValueError, *PIPELINE_ERRORS) as exc:
        raise _fail(console, exc) from exc
    console.print(f"Output: {result.output}", soft_wrap=True)
    console.print(
        f"Video {result.video_seconds:.2f}s in {result.wall_s:.1f}s wall"
        f" (setup {result.timing.setup_s:.1f}s, render {result.timing.render_s:.1f}s):"
        f" {result.realtime_factor:.2f}x realtime"
    )
    console.print(f"Quality {result.quality}, {result.concurrency} render tabs")


@app.command("export-subtitles")
def export_subtitles(
    project_id: str,
    file_format: Annotated[
        SubtitleFormat, typer.Option("--format", help="srt, or ass (karaoke tags for karaoke).")
    ] = "srt",
    output: Annotated[
        str, typer.Option(help="File name (without extension) under the project's exports/.")
    ] = "subtitles",
) -> None:
    """Write the project's subtitles as SRT or ASS, timed on the edited timeline."""
    console = Console()
    service = SettingsService.default()
    try:
        layout = ProjectLayout.for_project(service.paths, project_id)
        if not layout.project_file.is_file():
            raise render_job.ProjectNotFoundError(f"project {project_id!r} has no project.json")
        project = rebuild_subtitles(load_project(layout.project_file))
        target = layout.root / "exports" / f"{Path(output).name}.{file_format}"
        write_text_atomic(target, write_subtitles(project, file_format))
    except (ValueError, OSError, *PIPELINE_ERRORS) as exc:
        raise _fail(console, exc) from exc
    console.print(f"Output: {target}", soft_wrap=True)
