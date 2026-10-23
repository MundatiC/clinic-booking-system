import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from app.core.security import PASSWORD_MAX
from app.schemas.common import RequestModel
from app.schemas.patients import Name, Phone

Email = Annotated[EmailStr, Field(max_length=254, examples=["wanjiku@example.com"])]
# Not trimmed or policy-checked here: the policy runs in the service, and a password
# is used exactly as typed. The cap stops oversized inputs reaching the hasher.
Password = Annotated[
    str, Field(min_length=1, max_length=PASSWORD_MAX, examples=["a long passphrase"])
]
Token = Annotated[str, Field(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]


class PasswordModel(RequestModel):
    # Strip only applies to other strings: passwords keep their spaces.
    model_config = RequestModel.model_config | {"str_strip_whitespace": False}


class RegisterIn(PasswordModel):
    full_name: Name = Field(examples=["Wanjiku Njoroge"])
    phone: Phone = Field(examples=["+254712345678"])
    email: Email
    password: Password


class LoginIn(PasswordModel):
    email: Email
    password: Password


class EmailIn(RequestModel):
    email: Email


class TokenIn(RequestModel):
    token: Token


class ResetIn(PasswordModel):
    token: Token
    password: Password


class MessageOut(BaseModel):
    message: str


class MePatient(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Literal["patient", "staff"]
    patient: MePatient | None


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (a scheme name, not a secret)
    expires_in: int = Field(description="Seconds until the session expires at the latest.")
