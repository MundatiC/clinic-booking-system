"""Pure-ASGI middleware: request id, access log, security headers, body-size limit.

Pure ASGI (rather than BaseHTTPMiddleware) keeps contextvars intact for the
request and avoids buffering responses.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import internal_error_response
from app.core.logging import request_id_var

log = logging.getLogger("app.access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Probe endpoints are hit by platform health checks and the keep-alive pinger.
QUIET_PATHS = frozenset({"/health", "/ready"})
# Swagger UI / ReDoc load assets from a CDN; they get no CSP from us.
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

# The booking UI: own-origin scripts, styles and fonts only; no inline code at all.
PAGE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)

_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",  # flagged by ZAP (90004)
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int, hsts: bool) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        path: str = scope["path"]
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in _BASE_SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
                content_type = headers.get("content-type", "")
                if content_type.startswith("text/html") and not path.startswith(_DOC_PATHS):
                    headers.setdefault("Content-Security-Policy", PAGE_CSP)
                    # Same-origin assets only, so full cross-origin isolation is free (ZAP 90004).
                    headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
                if content_type.startswith("application/json") and not (
                    path.startswith(_DOC_PATHS)
                ):
                    headers.setdefault(
                        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                    )
                    # Appointment data is personal; keep it out of shared caches.
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send_wrapper(message)

        try:
            await self.app(scope, self._limited(scope, receive), tracking_send)
        except Exception as exc:
            # Handled here rather than via an `Exception` handler: Starlette runs that
            # handler in ServerErrorMiddleware, *outside* this middleware, where the
            # request id is gone and our headers are not applied.
            log.exception("unhandled error", extra={"error_type": type(exc).__name__})
            if response_started:
                raise
            await internal_error_response()(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            log.log(
                logging.DEBUG if path in QUIET_PATHS else logging.INFO,
                "request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)

    def _limited(self, scope: Scope, receive: Receive) -> Receive:
        limit = self.max_body_bytes
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            too_large = True
        else:
            too_large = False
        received = 0

        async def wrapped() -> Message:
            nonlocal received
            if too_large:
                raise _too_large(limit)
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:  # chunked bodies without Content-Length
                    raise _too_large(limit)
            return message

        return wrapped


def _too_large(limit: int) -> HTTPException:
    # Must be an HTTPException: FastAPI turns any other exception raised while it
    # reads the body into a generic 400 ("error parsing the body").
    return HTTPException(413, f"Request body is too large (max {limit} bytes).")
