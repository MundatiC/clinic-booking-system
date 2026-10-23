import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field

from app.db.models import Appointment
from app.schemas.common import INT32_MAX, RequestModel

_START_DOC = "Slot start, ISO-8601 **with offset** (naive datetimes are rejected)."


class AppointmentCreate(RequestModel):
    doctor_id: int = Field(gt=0, le=INT32_MAX, strict=True, examples=[1])
    patient_id: uuid.UUID | None = Field(
        default=None,
        description="Staff only. Patients book for themselves and may omit it.",
        examples=["00000000-0000-4000-8000-000000000001"],
    )
    start_at: AwareDatetime = Field(description=_START_DOC, examples=["2026-11-02T09:00:00+03:00"])


class AppointmentCancel(RequestModel):
    reason: str = Field(min_length=3, max_length=500, examples=["Feeling better, no longer needed"])


class AppointmentReschedule(RequestModel):
    start_at: AwareDatetime = Field(description=_START_DOC, examples=["2026-11-03T14:30:00+03:00"])


class AppointmentOut(BaseModel):
    id: uuid.UUID
    doctor_id: int
    patient_id: uuid.UUID
    start_at: datetime = Field(examples=["2026-11-02T09:00:00+03:00"])
    end_at: datetime = Field(examples=["2026-11-02T09:30:00+03:00"])
    status: str = Field(examples=["booked"])
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, appt: Appointment, tz: ZoneInfo) -> "AppointmentOut":
        """Render every timestamp in clinic-local time (with its offset)."""

        def local(dt: datetime | None) -> datetime | None:
            return dt.astimezone(tz) if dt is not None else None

        return cls(
            id=appt.id,
            doctor_id=appt.doctor_id,
            patient_id=appt.patient_id,
            start_at=appt.start_at.astimezone(tz),
            end_at=appt.end_at.astimezone(tz),
            status=appt.status,
            cancel_reason=appt.cancel_reason,
            cancelled_at=local(appt.cancelled_at),
            created_at=appt.created_at.astimezone(tz),
            updated_at=appt.updated_at.astimezone(tz),
        )
