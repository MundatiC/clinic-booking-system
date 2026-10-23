"""Shared test helpers. The fixed "now" is Monday 2030-01-07 06:00 in Nairobi."""

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import User, UserRole
from scripts.seed import DEMO_PATIENT, DEMO_PATIENT_ID

NAIROBI = ZoneInfo("Africa/Nairobi")
NOW = datetime(2030, 1, 7, 6, 0, tzinfo=NAIROBI)  # Monday
MON, TUE, WED = "2030-01-07", "2030-01-08", "2030-01-09"
SAT = "2030-01-12"
PATIENT = str(DEMO_PATIENT_ID)
PATIENT_EMAIL = str(DEMO_PATIENT["email"])
PATIENT_PASSWORD = "correct horse battery staple"
ORIGIN = "https://testserver"


def make_patient_user(
    db: Session,
    patient_id: uuid.UUID = DEMO_PATIENT_ID,
    email: str = PATIENT_EMAIL,
    password: str = PATIENT_PASSWORD,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.PATIENT,
        patient_id=patient_id,
        email_verified_at=datetime(2029, 1, 1, tzinfo=UTC),
    )
    db.add(user)
    db.commit()
    return user


def open_client(app: FastAPI, email: str | None = None, password: str | None = None) -> TestClient:
    """https base URL so the Secure cookie flows; optionally signed in via the cookie flow."""
    c = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    if email is not None:
        r = c.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
    return c


def local(day: str, hhmm: str) -> str:
    """ISO-8601 with Nairobi offset, e.g. local(TUE, "09:00") -> 2030-01-08T09:00:00+03:00."""
    return f"{day}T{hhmm}:00+03:00"


def at(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(local(day, hhmm))


def book(client: TestClient, start: str, doctor_id: int = 1, patient_id: str = PATIENT) -> Any:
    return client.post(
        "/appointments", json={"doctor_id": doctor_id, "patient_id": patient_id, "start_at": start}
    )


def new_patient(client: TestClient, email: str | None = None) -> str:
    email = email or f"p-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/patients", json={"full_name": "Test Patient", "phone": "+254711000000", "email": email}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def slot_starts(client: TestClient, doctor_id: int, day: str) -> list[str]:
    r = client.get(f"/doctors/{doctor_id}/availability", params={"date": day})
    assert r.status_code == 200, r.text
    return [s["start"][11:16] for s in r.json()["slots"]]
