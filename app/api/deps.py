"""FastAPI dependencies wiring settings, clock, session, auth and services."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.mailer import Mailer
from app.db.models import User
from app.db.session import get_session
from app.services.auth import AuthService
from app.services.booking import BookingService
from app.services.notifications import Notifier
from app.services.patients import PatientService

SESSION_COOKIE = "__Host-session"  # __Host-: Secure, Path=/, no Domain; can't be set by subdomains
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def get_notifier(request: Request, settings: SettingsDep, background: BackgroundTasks) -> Notifier:
    mailer: Mailer = request.app.state.mailer
    return Notifier(mailer, settings, background)


NotifierDep = Annotated[Notifier, Depends(get_notifier)]


def get_auth_service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    notifier: NotifierDep,
) -> AuthService:
    return AuthService(session, settings, clock, notifier, request.app.state.login_failures)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def check_origin(request: Request, settings: SettingsDep) -> None:
    """Global CSRF guard: a write that says it comes from a foreign site is refused.

    (Cookie-authenticated writes must also *prove* their origin; see `current_user`.)
    """
    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin and origin not in settings.trusted_origins:
        raise ForbiddenError("CSRF_FAILED", "Cross-site request refused.")


def request_token(request: Request) -> tuple[str | None, bool]:
    """(token, came_from_cookie). An Authorization header wins over the cookie."""
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip(), False
    return request.cookies.get(SESSION_COOKIE), True


# Documents the bearer scheme in OpenAPI (Swagger's "Authorize" button); the token itself
# is read by request_token, which also accepts the browser cookie.
bearer_scheme = HTTPBearer(
    auto_error=False, description="Token from POST /auth/token. Browsers use the session cookie."
)


def current_user(
    request: Request,
    auth: AuthServiceDep,
    settings: SettingsDep,
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    token, from_cookie = request_token(request)
    user = auth.authenticate(token) if token else None
    if user is None:
        raise UnauthorizedError("NOT_AUTHENTICATED", "Sign in to continue.")
    if from_cookie and request.method in UNSAFE_METHODS:
        # Cookies are sent automatically, so the request must show it came from us.
        # (SameSite=Strict already blocks this in modern browsers; this is defence in depth.)
        source = request.headers.get("origin") or _origin_of(request.headers.get("referer", ""))
        if source not in settings.trusted_origins:
            raise ForbiddenError("CSRF_FAILED", "Cross-site request refused.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def staff_user(user: CurrentUser) -> User:
    if not user.is_staff:
        # 404 rather than 403: don't advertise staff-only routes to patients.
        raise NotFoundError("NOT_FOUND", "Not found.")
    return user


StaffUser = Annotated[User, Depends(staff_user)]


def get_booking_service(
    session: SessionDep, settings: SettingsDep, clock: ClockDep, notifier: NotifierDep
) -> BookingService:
    return BookingService(session, settings, clock, notifier)


def get_patient_service(session: SessionDep, clock: ClockDep) -> PatientService:
    return PatientService(session, clock)


BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]
