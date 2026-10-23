"""Application factory."""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import appointments, auth, doctors, health, patients
from app.api.deps import check_origin
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.mailer import Mailer, SmtpMailer
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter, parse_rate

STATIC = Path(__file__).parent / "static"

DESCRIPTION = """
Book, cancel and reschedule 30-minute appointments with the clinic's doctors.

* Times are ISO-8601 **with an offset**; responses use clinic time (`Africa/Nairobi`).
* Every error uses one envelope:
  `{"error": {"code", "message", "details", "request_id"}}`.
* Sign in with `POST /auth/login` (browser cookie) or `POST /auth/token` (bearer token).
  Patients see and change only their own appointments; staff manage everyone's.
"""


def create_app(
    settings: Settings | None = None, clock: Clock | None = None, mailer: Mailer | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Clinic Booking API",
        version="2.0.0",
        description=DESCRIPTION,
        dependencies=[Depends(check_origin)],
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.mailer = mailer or SmtpMailer(settings)
    enabled = settings.rate_limit_enabled
    app.state.write_limiter = (
        RateLimiter(*parse_rate(settings.rate_limit_writes)) if enabled else None
    )
    app.state.auth_limiter = RateLimiter(*parse_rate(settings.rate_limit_auth)) if enabled else None
    # Account lockout is a security control, not traffic shaping: always on.
    app.state.login_failures = RateLimiter(
        settings.login_max_failures, settings.login_lockout_minutes * 60
    )

    # RequestContextMiddleware is added last, so it is outermost: even CORS preflight
    # responses get a request id and security headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_credentials=False,  # the UI is same-origin; no cross-site cookie use
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_body_bytes,
        hsts=settings.environment == "production",
    )
    register_exception_handlers(app)

    for module in (health, auth, doctors, appointments, patients):
        app.include_router(module.router)

    # The booking UI: one static page plus its assets, same origin as the API.
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
