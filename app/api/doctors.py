from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import BookingServiceDep, SessionDep, SettingsDep
from app.repositories import doctors as doctors_repo
from app.schemas.common import error_responses
from app.schemas.doctors import AvailabilityOut, DoctorOut, SlotOut

router = APIRouter(prefix="/doctors", tags=["doctors"])


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
    doctor_id: int,
    date: Annotated[Date, Query(description="Clinic-local date", examples=["2026-11-02"])],
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AvailabilityOut:
    tz = settings.tz
    free = service.availability(doctor_id, date)
    return AvailabilityOut(
        doctor_id=doctor_id,
        date=date,
        timezone=tz.key,
        slot_minutes=settings.slot_minutes,
        slots=[SlotOut(start=s.astimezone(tz), end=e.astimezone(tz)) for s, e in free],
    )
