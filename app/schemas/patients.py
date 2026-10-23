import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

from app.schemas.appointments import AppointmentOut
from app.schemas.common import RequestModel

_PHONE_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _normalise_phone(value: str) -> str:
    """Accept common formatting; store E.164. Kenyan local numbers (07.., 01..) get +254."""
    digits = _PHONE_SEPARATORS.sub("", value)
    if re.fullmatch(r"0[17]\d{8}", digits):
        digits = "+254" + digits[1:]
    if not _E164.match(digits):
        raise ValueError("phone must be E.164, e.g. +254712345678 (or Kenyan 0712345678)")
    return digits


Phone = Annotated[str, StringConstraints(max_length=32), AfterValidator(_normalise_phone)]
# Printable text only: names end up in emails, so no control characters (e.g. CR/LF).
Name = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]


class PatientCreate(RequestModel):
    full_name: Name = Field(examples=["Wanjiku Njoroge"])
    phone: Phone = Field(examples=["+254712345678"])
    email: Annotated[EmailStr, Field(max_length=254, examples=["wanjiku@example.com"])]


class PatientOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str
    email: str
    created_at: datetime


class PatientAppointmentsOut(BaseModel):
    patient_id: uuid.UUID
    total: int = Field(description="Total upcoming appointments, ignoring pagination.")
    limit: int
    offset: int
    items: list[AppointmentOut]
