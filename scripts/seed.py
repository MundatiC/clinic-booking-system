"""Idempotent seed: 5 doctors, their working hours, and one demo patient.

Safe to run on every deploy:
- doctors are upserted by their fixed id;
- each seeded doctor's working hours are replaced with the definition below
  (appointments are never touched);
- the demo patient is upserted by email.

Usage: python -m scripts.seed
"""

import logging
import uuid
from datetime import time

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Doctor, Patient, WorkingHours
from app.db.session import get_sessionmaker

log = logging.getLogger("seed")

MON, TUE, WED, THU, FRI, SAT = range(6)
WEEKDAYS = (MON, TUE, WED, THU, FRI)

Window = tuple[time, time]

# (id, name, specialty, {weekday: [windows]}); a weekday with no windows is a day off.
DOCTORS: list[tuple[int, str, str, dict[int, list[Window]]]] = [
    (
        1,
        "Dr. Amina Odhiambo",
        "General Practice",
        {d: [(time(8), time(12)), (time(13), time(17))] for d in WEEKDAYS},
    ),
    (
        2,
        "Dr. Brian Kamau",
        "Paediatrics",
        {d: [(time(9), time(13)), (time(14), time(17))] for d in WEEKDAYS},
    ),
    (
        3,
        "Dr. Grace Wanjiru",
        "Dermatology",
        {
            **{d: [(time(8), time(12)), (time(13), time(16))] for d in (MON, WED, FRI)},
            SAT: [(time(9), time(12))],
        },
    ),
    (
        4,
        "Dr. David Mutua",
        "Cardiology",
        {d: [(time(10), time(13)), (time(14), time(18))] for d in (TUE, THU)},
    ),
    (
        5,
        "Dr. Faith Achieng",
        "Obstetrics & Gynaecology",
        {d: [(time(8, 30), time(12, 30)), (time(13, 30), time(16, 30))] for d in WEEKDAYS},
    ),
]

DEMO_PATIENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEMO_PATIENT = {
    "id": DEMO_PATIENT_ID,
    "full_name": "Demo Patient",
    "phone": "+254700000000",
    "email": "demo.patient@example.com",
}


def seed(session: Session) -> None:
    for doctor_id, name, specialty, schedule in DOCTORS:
        session.execute(
            insert(Doctor)
            .values(id=doctor_id, name=name, specialty=specialty, is_active=True)
            .on_conflict_do_update(
                index_elements=[Doctor.id],
                set_={"name": name, "specialty": specialty, "is_active": True},
            )
        )
        session.execute(delete(WorkingHours).where(WorkingHours.doctor_id == doctor_id))
        session.add_all(
            WorkingHours(doctor_id=doctor_id, weekday=day, start_time=start, end_time=end)
            for day, windows in schedule.items()
            for start, end in windows
        )

    session.execute(
        insert(Patient).values(**DEMO_PATIENT).on_conflict_do_nothing(index_elements=["email"])
    )

    # Explicit ids were inserted, so move the sequence past them for future inserts.
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('doctors', 'id'), (SELECT MAX(id) FROM doctors))"
        )
    )
    session.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with get_sessionmaker()() as session:
        seed(session)
        count = session.scalar(select(func.count()).select_from(Doctor))
    log.info("seed complete: %s doctors", count)


if __name__ == "__main__":
    main()
