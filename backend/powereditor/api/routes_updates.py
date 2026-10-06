from typing import cast

import httpx
from fastapi import APIRouter, Request

from powereditor import app_version
from powereditor.api.routes_settings import ServiceDep
from powereditor.updates import CACHE_FILE_NAME, UpdateChecker, UpdateStatus

router = APIRouter(prefix="/api")


@router.get("/updates")
def check_for_updates(request: Request, service: ServiceDep, force: bool = False) -> UpdateStatus:
    """The newest published release against the running version. With the
    `checkForUpdates` setting off only `force` (the user's "Check now") asks GitHub."""
    enabled = service.get_effective().check_for_updates
    if not enabled and not force:
        return UpdateStatus(current=app_version(), enabled=False)
    checker = UpdateChecker(
        service.paths.data_dir / CACHE_FILE_NAME,
        transport=cast(httpx.BaseTransport | None, request.app.state.update_transport),
    )
    status = checker.status(app_version(), force=force)
    status.enabled = enabled
    return status
