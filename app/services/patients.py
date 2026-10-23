import uuid

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import NotFoundError
from app.db.models import Appointment, Patient
from app.repositories import appointments as appointments_repo
from app.repositories import patients as patients_repo


class PatientService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    def register(self, full_name: str, phone: str, email: str) -> Patient:
        patient = Patient(full_name=full_name, phone=phone, email=email.strip().lower())
        patients_repo.add(self.session, patient)  # duplicate email -> 409 PATIENT_EXISTS
        self.session.commit()
        return patient

    def upcoming(
        self, patient_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Appointment], int]:
        if patients_repo.get(self.session, patient_id) is None:
            raise NotFoundError(
                "PATIENT_NOT_FOUND", "Patient not found.", {"patient_id": str(patient_id)}
            )
        return appointments_repo.upcoming_for_patient(
            self.session, patient_id, self.clock.now(), limit, offset
        )
