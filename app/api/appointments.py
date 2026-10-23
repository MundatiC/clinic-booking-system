import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import BookingServiceDep, SettingsDep
from app.core.ratelimit import limit_writes
from app.schemas.appointments import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentOut,
    AppointmentReschedule,
)
from app.schemas.common import error_responses

router = APIRouter(prefix="/appointments", tags=["appointments"])
writes = [Depends(limit_writes)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Book a slot",
    description=(
        "Validates: doctor/patient exist, start on the 30-minute grid (clinic time), not in "
        "the past, at least `MIN_LEAD_TIME_MINUTES` ahead, within `MAX_ADVANCE_DAYS`, inside "
        "the doctor's working hours, and not already taken."
    ),
    dependencies=writes,
    responses=error_responses(404, 409, 413, 422, 429),
)
def book(
    body: AppointmentCreate, service: BookingServiceDep, settings: SettingsDep
) -> AppointmentOut:
    appt = service.book(body.doctor_id, body.patient_id, body.start_at)
    return AppointmentOut.build(appt, settings.tz)


@router.get("/{appointment_id}", summary="Get an appointment", responses=error_responses(404, 422))
def get_appointment(
    appointment_id: uuid.UUID, service: BookingServiceDep, settings: SettingsDep
) -> AppointmentOut:
    return AppointmentOut.build(service.get(appointment_id), settings.tz)


@router.patch(
    "/{appointment_id}/cancel",
    summary="Cancel an appointment",
    description="Frees the slot. 409 if already cancelled or already started.",
    dependencies=writes,
    responses=error_responses(404, 409, 413, 422, 429),
)
def cancel(
    appointment_id: uuid.UUID,
    body: AppointmentCancel,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AppointmentOut:
    return AppointmentOut.build(service.cancel(appointment_id, body.reason), settings.tz)


@router.patch(
    "/{appointment_id}/reschedule",
    summary="Move an appointment to a new slot (same doctor)",
    description=(
        "The new slot is validated exactly like a new booking. The original slot is freed "
        "in the same transaction. If the new slot is taken (409), the original is unchanged."
    ),
    dependencies=writes,
    responses=error_responses(404, 409, 413, 422, 429),
)
def reschedule(
    appointment_id: uuid.UUID,
    body: AppointmentReschedule,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AppointmentOut:
    return AppointmentOut.build(service.reschedule(appointment_id, body.start_at), settings.tz)
