"""Domain errors and the single error envelope used for every error response.

{"error": {"code": "SLOT_TAKEN", "message": "...", "details": {...}, "request_id": "..."}}
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var


class AppError(Exception):
    """Base for errors the API reports deliberately. Subclasses fix the HTTP status."""

    status_code = 400

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    """The request was valid, but the current state of the world prevents it."""

    status_code = 409


class BusinessRuleError(AppError):
    """Well-formed input that the booking rules do not accept."""

    status_code = 422


class RateLimitedError(AppError):
    status_code = 429


class ServiceUnavailableError(AppError):
    status_code = 503


_HTTP_CODES = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


def _json(
    status: int, code: str, message: str, details: dict[str, Any] | None = None, **kw: Any
) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, details), **kw)


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # narrowing; registered for AppError only
        raise exc
    return _json(exc.status_code, exc.code, exc.message, exc.details, headers=exc.headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Echo location and reason only. The submitted value ("input") may be PII.
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return _json(422, "VALIDATION_ERROR", "Request validation failed.", {"errors": errors})


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
    return _json(exc.status_code, code, message, headers=getattr(exc, "headers", None))


def internal_error_response() -> JSONResponse:
    """Generic 500. Rendered by RequestContextMiddleware (see there for why)."""
    return _json(500, "INTERNAL_ERROR", "Something went wrong. Please try again later.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
