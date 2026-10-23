"""Application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import appointments, doctors, health, patients
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter, parse_rate

DESCRIPTION = """
Book, cancel and reschedule 30-minute appointments with the clinic's doctors.

* Times are ISO-8601 **with an offset**; responses use clinic time (`Africa/Nairobi`).
* Every error uses one envelope:
  `{"error": {"code", "message", "details", "request_id"}}`.
* No authentication yet (see README §1.8): appointment and patient ids are random UUIDs.
"""


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Clinic Booking API", version="1.0.0", description=DESCRIPTION)
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.write_limiter = (
        RateLimiter(*parse_rate(settings.rate_limit_writes))
        if settings.rate_limit_enabled
        else None
    )

    # RequestContextMiddleware is added last, so it is outermost: even CORS preflight
    # responses get a request id and security headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_body_bytes,
        hsts=settings.environment == "production",
    )
    register_exception_handlers(app)

    for module in (health, doctors, appointments, patients):
        app.include_router(module.router)
    return app


app = create_app()
