from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.appointments import AppointmentOut


class DoctorOut(BaseModel):
    id: int = Field(examples=[1])
    name: str = Field(examples=["Dr. Amina Odhiambo"])
    specialty: str = Field(examples=["General Practice"])


class SlotOut(BaseModel):
    start: datetime = Field(examples=["2026-11-02T09:00:00+03:00"])
    end: datetime = Field(examples=["2026-11-02T09:30:00+03:00"])


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    timezone: str = Field(examples=["Africa/Nairobi"])
    slot_minutes: int = Field(examples=[30])
    working_hours: list[str] = Field(
        description="The doctor's working windows that day, clinic time; empty on a day off.",
        examples=[["08:00-12:00", "13:00-17:00"]],
    )
    slots: list[SlotOut]


class ScheduleItem(AppointmentOut):
    patient_name: str
    patient_phone: str = Field(examples=["+254712345678"])
