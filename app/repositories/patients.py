import uuid

from sqlalchemy.orm import Session

from app.db.models import Patient
from app.repositories.integrity import flush_or_translate


def get(session: Session, patient_id: uuid.UUID) -> Patient | None:
    return session.get(Patient, patient_id)


def add(session: Session, patient: Patient) -> Patient:
    session.add(patient)
    flush_or_translate(session)
    return patient
