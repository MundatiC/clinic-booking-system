import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, PatientServiceDep, SettingsDep, StaffUser
from app.core.ratelimit import limit_writes
from app.schemas.appointments import AppointmentOut
from app.schemas.common import error_responses
from app.schemas.patients import PatientAppointmentsOut, PatientCreate, PatientOut

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a walk-in patient (staff)",
    description=(
        "Staff only: records a patient without an online account. Email is case-insensitive "
        "and unique (409 `PATIENT_EXISTS`). Patients sign themselves up via `/auth/register`."
    ),
    dependencies=[Depends(limit_writes)],
    responses=error_responses(401, 403, 404, 409, 413, 422, 429),
)
def register(
    body: PatientCreate, _: StaffUser, service: PatientServiceDep, settings: SettingsDep
) -> PatientOut:
    p = service.register(body.full_name, body.phone, str(body.email))
    return PatientOut(
        id=p.id,
        full_name=p.full_name,
        phone=p.phone,
        email=p.email,
        created_at=p.created_at.astimezone(settings.tz),
    )


@router.get(
    "/{patient_id}/appointments",
    summary="A patient's upcoming appointments",
    description=(
        "Booked appointments starting now or later, soonest first, paginated. Patients may "
        "only list their own (anyone else's answers 404)."
    ),
    responses=error_responses(401, 404, 422),
)
def upcoming(
    patient_id: uuid.UUID,
    user: CurrentUser,
    service: PatientServiceDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PatientAppointmentsOut:
    items, total = service.upcoming(user, patient_id, limit, offset)
    return PatientAppointmentsOut(
        patient_id=patient_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[AppointmentOut.build(a, settings.tz) for a in items],
    )
