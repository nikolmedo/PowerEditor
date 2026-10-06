import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from powereditor import app_version, doctor, settings_store
from powereditor.api.origin_guard import LocalOriginGuard
from powereditor.api.routes_audio import router as audio_router
from powereditor.api.routes_jobs import router as jobs_router
from powereditor.api.routes_media import contained_file
from powereditor.api.routes_media import router as media_router
from powereditor.api.routes_overlays import router as overlays_router
from powereditor.api.routes_projects import router as projects_router
from powereditor.api.routes_providers import router as providers_router
from powereditor.api.routes_settings import get_service
from powereditor.api.routes_settings import router as settings_router
from powereditor.api.routes_setup import router as setup_router
from powereditor.api.services import Pipelines, Revealer, default_revealer
from powereditor.api.session_token import SessionTokenGuard
from powereditor.jobs import JobManager
from powereditor.paths import AppPaths
from powereditor.projects import ProjectStore
from powereditor.providers.registry import ProviderRegistry, default_registry
from powereditor.resources import Resources
from powereditor.runtime.manifest import RuntimeDownload
from powereditor.settings_store import SettingsService


def _validation_error_without_input(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {key: value for key, value in error.items() if key != "input"} for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


ENV_DEV_CORS = "POWEREDITOR_DEV_CORS"
ENV_SESSION_TOKEN = "POWEREDITOR_SESSION_TOKEN"
"""Set by `serve --port 0` (sidecar mode): the API then requires this token."""
VITE_DEV_ORIGIN = "http://localhost:5173"


def resolve_web_dir() -> Path:
    """`POWEREDITOR_WEB_DIR`, then a bundled build, then the repo's `web/dist`."""
    return Resources.current().web_dir()


def dev_cors_enabled() -> bool:
    return os.environ.get(ENV_DEV_CORS, "").lower() in ("1", "true", "yes")


def _mount_web_app(app: FastAPI, web_dir: Path) -> None:
    """Serve the built UI at `/`; unknown paths get `index.html` (client-side routing)."""

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        index = web_dir / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=404,
                detail=(
                    "The web app is not built: run `corepack pnpm --filter @powereditor/web build`."
                ),
            )
        folder, _, name = path.rpartition("/")
        asset = contained_file(web_dir / folder, name) if name and ".." not in path else None
        if asset is not None and asset.is_relative_to(web_dir.resolve()):
            return FileResponse(asset)
        return FileResponse(index, media_type="text/html")


def create_app(
    settings_service: SettingsService | None = None,
    paths: AppPaths | None = None,
    openai_transport: httpx.BaseTransport | None = None,
    doctor_runner: doctor.Runner | None = None,
    provider_registry: ProviderRegistry | None = None,
    provider_transport: httpx.BaseTransport | None = None,
    pipelines: Pipelines | None = None,
    revealer: Revealer | None = None,
    web_dir: Path | None = None,
    dev_cors: bool | None = None,
    runtime_downloads: Sequence[RuntimeDownload] | None = None,
    runtime_transport: httpx.BaseTransport | None = None,
    session_token: str | None = None,
) -> FastAPI:
    if settings_service is None:
        settings_service = SettingsService(
            paths=paths or AppPaths.from_env(),
            secrets=settings_store.default_secret_store(),
            env=settings_store.default_env_settings(),
        )
    jobs = JobManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.shutdown()

    app = FastAPI(title="PowerEditor", version=app_version(), lifespan=lifespan)
    dev = dev_cors if dev_cors is not None else dev_cors_enabled()
    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[VITE_DEV_ORIGIN],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["ETag"],
        )
    token = session_token if session_token is not None else os.environ.get(ENV_SESSION_TOKEN)
    if token:
        app.add_middleware(SessionTokenGuard, token=token)
    # Added last, so it runs first: a refused request never reaches CORS or a route.
    app.add_middleware(
        LocalOriginGuard, extra_origins=frozenset({VITE_DEV_ORIGIN} if dev else set())
    )
    app.state.settings_service = settings_service
    app.state.openai_transport = openai_transport
    app.state.doctor_runner = doctor_runner
    app.state.provider_registry = provider_registry or default_registry()
    app.state.provider_transport = provider_transport
    app.state.runtime_downloads = runtime_downloads
    app.state.runtime_transport = runtime_transport
    app.state.project_store = ProjectStore(settings_service.paths)
    app.state.jobs = jobs
    app.state.pipelines = pipelines or Pipelines()
    app.state.revealer = revealer or default_revealer()
    app.add_exception_handler(RequestValidationError, _validation_error_without_input)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app_version()}

    @app.get("/api/doctor")
    def run_doctor(request: Request) -> doctor.DoctorReport:
        service = get_service(request)
        runner = cast(doctor.Runner | None, request.app.state.doctor_runner)
        return doctor.run_checks(
            runner=runner, locate=service.locate_executable, frozen=Resources.current().frozen
        )

    app.include_router(settings_router)
    app.include_router(providers_router)
    app.include_router(projects_router)
    app.include_router(jobs_router)
    app.include_router(media_router)
    app.include_router(audio_router)
    app.include_router(overlays_router)
    app.include_router(setup_router)
    _mount_web_app(app, web_dir or resolve_web_dir())
    return app
