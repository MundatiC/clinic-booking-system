"""The database itself enforces the booking invariants (README 1.4)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import verify_password
from app.db.models import (
    UQ_DOCTOR_SLOT,
    UQ_PATIENT_SLOT,
    Appointment,
    Doctor,
    Patient,
    User,
    WorkingHours,
)
from scripts.seed import DEMO_PATIENT, DEMO_PATIENT_ID, seed

START = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)  # Monday 09:00 Nairobi


def _appt(doctor_id: int = 1, patient_id: uuid.UUID = DEMO_PATIENT_ID, **kw: object) -> Appointment:
    start = kw.pop("start_at", START)
    assert isinstance(start, datetime)
    return Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        **kw,
    )


def _other_patient(db: Session) -> uuid.UUID:
    p = Patient(full_name="Other", phone="+254711111111", email="other@example.com")
    db.add(p)
    db.commit()
    return p.id


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def test_same_doctor_same_slot_rejected(db: Session) -> None:
    db.add(_appt())
    db.commit()
    db.add(_appt(patient_id=_other_patient(db)))
    with pytest.raises(IntegrityError) as exc:
        db.commit()
    assert _constraint_name(exc.value) == UQ_DOCTOR_SLOT


def test_same_patient_same_time_two_doctors_rejected(db: Session) -> None:
    db.add(_appt(doctor_id=1))
    db.commit()
    db.add(_appt(doctor_id=2))
    with pytest.raises(IntegrityError) as exc:
        db.commit()
    assert _constraint_name(exc.value) == UQ_PATIENT_SLOT


def test_cancelled_row_frees_the_slot(db: Session) -> None:
    first = _appt()
    db.add(first)
    db.commit()
    first.status = "cancelled"
    first.cancelled_at = datetime.now(UTC)
    first.cancel_reason = "test"
    db.commit()
    db.add(_appt(patient_id=_other_patient(db)))
    db.commit()  # no IntegrityError
    assert db.scalar(select(func.count()).select_from(Appointment)) == 2


def test_cancelled_requires_cancelled_at(db: Session) -> None:
    db.add(_appt(status="cancelled"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_seed_is_idempotent(db: Session) -> None:
    seed(db)
    seed(db)
    assert db.scalar(select(func.count()).select_from(Doctor)) == 5
    assert db.scalar(select(func.count()).select_from(WorkingHours)) == 41
    assert db.scalar(select(func.count()).select_from(Patient)) == 1


def test_seed_gives_the_demo_patient_a_login_when_configured(db: Session) -> None:
    password = "demo patient for local testing"
    settings = get_settings().model_copy(update={"demo_patient_password": SecretStr(password)})
    seed(db, settings)
    seed(db, settings)  # still idempotent
    user = db.scalar(select(User).where(User.email == DEMO_PATIENT["email"]))
    assert user is not None
    assert user.patient_id == DEMO_PATIENT_ID
    assert user.email_verified_at is not None
    assert verify_password(password, user.password_hash)
