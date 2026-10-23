from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Doctor, WorkingHours


def get_active(session: Session, doctor_id: int) -> Doctor | None:
    return session.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active))


def list_active(session: Session) -> list[Doctor]:
    return list(session.scalars(select(Doctor).where(Doctor.is_active).order_by(Doctor.id)))


def windows_for(session: Session, doctor_id: int, weekday: int) -> list[WorkingHours]:
    stmt = (
        select(WorkingHours)
        .where(WorkingHours.doctor_id == doctor_id, WorkingHours.weekday == weekday)
        .order_by(WorkingHours.start_time)
    )
    return list(session.scalars(stmt))
