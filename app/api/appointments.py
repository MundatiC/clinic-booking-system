import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import BookingServiceDep, CurrentUser, SettingsDep
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
        "the doctor's working hours, and not already taken. Patients book for themselves "
        "(`patient_id` may be omitted); staff must give `patient_id`."
    ),
    dependencies=writes,
    responses=error_responses(401, 403, 404, 409, 413, 422, 429),
)
def book(
    body: AppointmentCreate, user: CurrentUser, service: BookingServiceDep, settings: SettingsDep
) -> AppointmentOut:
    appt = service.book(user, body.doctor_id, body.patient_id, body.start_at)
    return AppointmentOut.build(appt, settings.tz)


@router.get(
    "/{appointment_id}", summary="Get an appointment", responses=error_responses(401, 404, 422)
)
def get_appointment(
    appointment_id: uuid.UUID, user: CurrentUser, service: BookingServiceDep, settings: SettingsDep
) -> AppointmentOut:
    return AppointmentOut.build(service.get(user, appointment_id), settings.tz)


@router.patch(
    "/{appointment_id}/cancel",
    summary="Cancel an appointment",
    description="Frees the slot. 409 if already cancelled or already started.",
    dependencies=writes,
    responses=error_responses(401, 403, 404, 409, 413, 422, 429),
)
def cancel(
    appointment_id: uuid.UUID,
    body: AppointmentCancel,
    user: CurrentUser,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AppointmentOut:
    return AppointmentOut.build(service.cancel(user, appointment_id, body.reason), settings.tz)


@router.patch(
    "/{appointment_id}/reschedule",
    summary="Move an appointment to a new slot (same doctor)",
    description=(
        "The new slot is validated exactly like a new booking. The original slot is freed "
        "in the same transaction. If the new slot is taken (409), the original is unchanged."
    ),
    dependencies=writes,
    responses=error_responses(401, 403, 404, 409, 413, 422, 429),
)
def reschedule(
    appointment_id: uuid.UUID,
    body: AppointmentReschedule,
    user: CurrentUser,
    service: BookingServiceDep,
    settings: SettingsDep,
) -> AppointmentOut:
    return AppointmentOut.build(
        service.reschedule(user, appointment_id, body.start_at), settings.tz
    )
