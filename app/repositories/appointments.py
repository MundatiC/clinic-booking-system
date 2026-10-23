import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.models import Appointment, AppointmentEvent, AppointmentStatus
from app.repositories.integrity import flush_or_translate


def get(session: Session, appointment_id: uuid.UUID) -> Appointment | None:
    return session.get(Appointment, appointment_id)


def get_for_update(session: Session, appointment_id: uuid.UUID) -> Appointment | None:
    """Load and row-lock (SELECT ... FOR UPDATE) until the transaction ends."""
    stmt = (
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalar(stmt)


def booked_starts(
    session: Session, doctor_id: int, from_utc: datetime, to_utc: datetime
) -> set[datetime]:
    """Start times of the doctor's booked appointments in [from, to). One query."""
    stmt = select(Appointment.start_at).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.start_at >= from_utc,
        Appointment.start_at < to_utc,
    )
    return set(session.scalars(stmt))


def add(session: Session, appointment: Appointment, event: AppointmentEvent) -> Appointment:
    session.add(appointment)
    flush_or_translate(session)
    event.appointment_id = appointment.id
    session.add(event)
    flush_or_translate(session)
    return appointment


def save(session: Session, appointment: Appointment, event: AppointmentEvent) -> Appointment:
    """Flush changes to an existing (locked) appointment plus its audit event."""
    flush_or_translate(session)
    event.appointment_id = appointment.id
    session.add(event)
    flush_or_translate(session)
    return appointment


def _upcoming_filter(patient_id: uuid.UUID, now: datetime) -> list[ColumnElement[bool]]:
    return [
        Appointment.patient_id == patient_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.start_at >= now,
    ]


def upcoming_for_patient(
    session: Session, patient_id: uuid.UUID, now: datetime, limit: int, offset: int
) -> tuple[list[Appointment], int]:
    where = _upcoming_filter(patient_id, now)
    total = session.scalar(select(func.count()).select_from(Appointment).where(*where)) or 0
    stmt = (
        select(Appointment)
        .where(*where)
        .order_by(Appointment.start_at, Appointment.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt)), total
