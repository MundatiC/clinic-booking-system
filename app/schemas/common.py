"""Shared schema pieces: strict request base model and the error envelope for OpenAPI."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, strings trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorBody(BaseModel):
    code: str = Field(examples=["SLOT_TAKEN"])
    message: str = Field(examples=["That slot has just been booked. Please pick another."])
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, examples=["9f1c2b6a4e0d4b7f8a3c1d2e5f6a7b8c"])


class ErrorResponse(BaseModel):
    error: ErrorBody


_DESCRIPTIONS = {
    401: "Not signed in, session expired, or wrong credentials (`NOT_AUTHENTICATED`, ...).",
    403: "Refused (`CSRF_FAILED`, `EMAIL_NOT_VERIFIED`).",
    404: "Unknown or inactive resource (`DOCTOR_NOT_FOUND`, `PATIENT_NOT_FOUND`, ...).",
    409: "Conflicts with current state (`SLOT_TAKEN`, `ALREADY_CANCELLED`, ...).",
    413: "Request body too large (`PAYLOAD_TOO_LARGE`).",
    422: "Invalid input or a booking rule failed (`VALIDATION_ERROR`, `TOO_SOON`, ...).",
    429: "Rate limited (`RATE_LIMITED`); see `Retry-After`.",
    503: "Not ready (`NOT_READY`).",
}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries documenting the error envelope."""
    return {s: {"model": ErrorResponse, "description": _DESCRIPTIONS[s]} for s in statuses}
