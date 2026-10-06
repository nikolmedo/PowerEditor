from importlib.metadata import version
from typing import cast

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from powereditor import doctor, settings_store
from powereditor.api.routes_settings import get_service
from powereditor.api.routes_settings import router as settings_router
from powereditor.paths import AppPaths
from powereditor.settings_store import SettingsService


def _validation_error_without_input(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {key: value for key, value in error.items() if key != "input"} for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


def create_app(
    settings_service: SettingsService | None = None,
    paths: AppPaths | None = None,
    openai_transport: httpx.BaseTransport | None = None,
    doctor_runner: doctor.Runner | None = None,
) -> FastAPI:
    if settings_service is None:
        settings_service = SettingsService(
            paths=paths or AppPaths.from_env(),
            secrets=settings_store.default_secret_store(),
            env=settings_store.default_env_settings(),
        )
    app = FastAPI(title="PowerEditor", version=version("powereditor"))
    app.state.settings_service = settings_service
    app.state.openai_transport = openai_transport
    app.state.doctor_runner = doctor_runner
    app.add_exception_handler(RequestValidationError, _validation_error_without_input)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": version("powereditor")}

    @app.get("/api/doctor")
    def run_doctor(request: Request) -> doctor.DoctorReport:
        service = get_service(request)
        runner = cast(doctor.Runner | None, request.app.state.doctor_runner)
        return doctor.run_checks(runner=runner, locate=service.locate_executable)

    app.include_router(settings_router)
    return app
