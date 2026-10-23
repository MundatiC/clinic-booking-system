import re
from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import BeforeValidator

from app.api.deps import BookingServiceDep, SessionDep, SettingsDep, StaffUser
from app.repositories import doctors as doctors_repo
from app.schemas.appointments import AppointmentOut
from app.schemas.common import INT32_MAX, error_responses
from app.schemas.doctors import AvailabilityOut, DoctorOut, ScheduleItem, SlotOut

router = APIRouter(prefix="/doctors", tags=["doctors"])
DoctorId = Annotated[int, Path(gt=0, le=INT32_MAX)]
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_only(value: object) -> object:
    # Pydantic would also read "0" or "1700000000" as Unix timestamps (found by Schemathesis).
    if isinstance(value, str) and not _ISO_DATE.fullmatch(value):
        raise ValueError("date must be YYYY-MM-DD")
    return value


LocalDate = Annotated[
    Date,
    BeforeValidator(_iso_only),
    Query(description="Clinic-local date, YYYY-MM-DD", examples=["2026-11-02"]),
]


@router.get("", summary="List active doctors")
def list_doctors(session: SessionDep) -> list[DoctorOut]:
    return [
        DoctorOut(id=d.id, name=d.name, specialty=d.specialty)
        for d in doctors_repo.list_active(session)
    ]


@router.get(
    "/{doctor_id}/availability",
    summary="Free 30-minute slots for a doctor on a date",
    description=(
        "`date` is a clinic-local date (YYYY-MM-DD). Hides slots that are booked, in the "
        "past, or inside the minimum lead time. A past date, a day off, or a date beyond "
        "the booking horizon returns an empty `slots` list."
    ),
    responses=error_responses(404, 422),
)
def availability(
    doctor_id: DoctorId,
    date: LocalDate,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AvailabilityOut:
    tz = settings.tz
    windows, free = service.availability(doctor_id, date)
    return AvailabilityOut(
        doctor_id=doctor_id,
        date=date,
        timezone=tz.key,
        slot_minutes=settings.slot_minutes,
        working_hours=[f"{start:%H:%M}-{end:%H:%M}" for start, end in windows],
        slots=[SlotOut(start=s.astimezone(tz), end=e.astimezone(tz)) for s, e in free],
    )


@router.get(
    "/{doctor_id}/appointments",
    summary="The doctor's booked appointments on a date (staff)",
    responses=error_responses(401, 404, 422),
)
def schedule(
    doctor_id: DoctorId,
    date: LocalDate,
    _: StaffUser,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> list[ScheduleItem]:
    return [
        ScheduleItem(
            **AppointmentOut.build(a, settings.tz).model_dump(),
            patient_name=a.patient.full_name,
            patient_phone=a.patient.phone,
        )
        for a in service.doctor_day(doctor_id, date)
    ]
