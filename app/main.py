"""Application factory."""

from fastapi import FastAPI

from app.api import health
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Clinic Booking API",
        version="0.1.0",
        description="Book, cancel and reschedule 30-minute appointments with the clinic's doctors.",
    )
    app.state.settings = settings
    app.include_router(health.router)
    return app


app = create_app()
