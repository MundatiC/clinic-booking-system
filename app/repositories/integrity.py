"""Translate database constraint violations into domain errors.

The partial unique indexes are the source of truth for "slot already taken";
this is where their violations become 409 responses.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models import UQ_DOCTOR_SLOT, UQ_PATIENT_EMAIL, UQ_PATIENT_SLOT, UQ_USER_EMAIL

_BY_CONSTRAINT = {
    UQ_DOCTOR_SLOT: ("SLOT_TAKEN", "That slot has just been booked. Please pick another."),
    UQ_PATIENT_SLOT: (
        "PATIENT_DOUBLE_BOOKED",
        "This patient already has an appointment at that time.",
    ),
    UQ_PATIENT_EMAIL: ("PATIENT_EXISTS", "A patient with this email already exists."),
    UQ_USER_EMAIL: ("EMAIL_TAKEN", "An account with this email already exists."),
}


def constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


def flush_or_translate(session: Session) -> None:
    """Flush pending changes; on a known unique violation roll back and raise 409."""
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        known = _BY_CONSTRAINT.get(constraint_name(exc) or "")
        if known is None:
            raise
        code, message = known
        raise ConflictError(code, message) from None
