import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PatientServiceDep, SettingsDep
from app.core.ratelimit import limit_writes
from app.schemas.appointments import AppointmentOut
from app.schemas.common import error_responses
from app.schemas.patients import PatientAppointmentsOut, PatientCreate, PatientOut

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a patient",
    description="Email is case-insensitive and unique (409 `PATIENT_EXISTS`).",
    dependencies=[Depends(limit_writes)],
    responses=error_responses(409, 413, 422, 429),
)
def register(body: PatientCreate, service: PatientServiceDep, settings: SettingsDep) -> PatientOut:
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
    description="Booked appointments starting now or later, soonest first, paginated.",
    responses=error_responses(404, 422),
)
def upcoming(
    patient_id: uuid.UUID,
    service: PatientServiceDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PatientAppointmentsOut:
    items, total = service.upcoming(patient_id, limit, offset)
    return PatientAppointmentsOut(
        patient_id=patient_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[AppointmentOut.build(a, settings.tz) for a in items],
    )
