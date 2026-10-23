"""Liveness and readiness probes. Neither is rate limited; both are quiet in logs."""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep, SettingsDep
from app.core.errors import ServiceUnavailableError
from app.schemas.common import error_responses

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe (no DB access)")
def health(settings: SettingsDep) -> dict[str, str]:
    # `version` lets the deploy pipeline tell the new release from the old one.
    return {"status": "ok", "version": settings.git_commit}


@router.get(
    "/ready", summary="Readiness probe (checks the database)", responses=error_responses(503)
)
def ready(session: SessionDep) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise ServiceUnavailableError("NOT_READY", "Database is not reachable.") from None
    return {"status": "ready"}
