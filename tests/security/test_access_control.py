"""Broken access control (OWASP A01): authentication everywhere it is needed, and IDOR."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Patient
from tests.utils import PATIENT, TUE, book, error_code, local, make_patient_user, open_client

# Everything else must answer 401 without a session. Adding a route forces a decision here.
PUBLIC = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/doctors"),
    ("GET", "/doctors/{doctor_id}/availability"),
    ("POST", "/auth/register"),
    ("POST", "/auth/verify"),
    ("POST", "/auth/resend-verification"),
    ("POST", "/auth/login"),
    ("POST", "/auth/token"),
    ("POST", "/auth/forgot-password"),
    ("POST", "/auth/reset-password"),
}
SAMPLE = {"doctor_id": "1", "appointment_id": str(uuid.uuid4()), "patient_id": PATIENT}


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    # From the OpenAPI schema: it lists every operation however routers are nested.
    return sorted(
        (method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops
    )


def test_every_non_public_route_requires_sign_in(app: FastAPI, anon: TestClient) -> None:
    protected = [r for r in _routes(app) if r not in PUBLIC]
    assert len(protected) >= 8
    for method, path in protected:
        r = anon.request(method, path.format(**SAMPLE), params={"date": TUE}, json={})
        assert r.status_code == 401, (method, path, r.status_code)
        assert error_code(r) == "NOT_AUTHENTICATED"


def test_public_list_has_no_stale_entries(app: FastAPI) -> None:
    assert set(_routes(app)) >= PUBLIC


@pytest.fixture
def other(app: FastAPI, db: Session) -> TestClient:
    """A second, unrelated patient with a verified login."""
    p = Patient(full_name="Baraka Mwangi", phone="+254744000000", email="baraka@example.com")
    db.add(p)
    db.commit()
    make_patient_user(db, p.id, "baraka@example.com", "another long passphrase")
    return open_client(app, "baraka@example.com", "another long passphrase")


def test_patient_cannot_touch_someone_elses_appointment(
    patient_client: TestClient, other: TestClient
) -> None:
    mine = book(patient_client, local(TUE, "09:00"), patient_id=None).json()  # type: ignore[arg-type]
    url = f"/appointments/{mine['id']}"
    for r in (
        other.get(url),
        other.patch(f"{url}/cancel", json={"reason": "not mine"}),
        other.patch(f"{url}/reschedule", json={"start_at": local(TUE, "10:00")}),
    ):
        assert r.status_code == 404  # indistinguishable from a non-existent id
        assert error_code(r) == "APPOINTMENT_NOT_FOUND"
    still = patient_client.get(url).json()
    assert still["status"] == "booked" and still["start_at"].endswith("09:00:00+03:00")


def test_patient_cannot_list_someone_elses_appointments(
    patient_client: TestClient, other: TestClient
) -> None:
    r = other.get(f"/patients/{PATIENT}/appointments")
    assert r.status_code == 404
    assert patient_client.get(f"/patients/{PATIENT}/appointments").status_code == 200


def test_patient_cannot_book_for_someone_else(other: TestClient) -> None:
    r = book(other, local(TUE, "09:00"), patient_id=PATIENT)
    assert r.status_code == 404
    assert error_code(r) == "PATIENT_NOT_FOUND"


def test_patient_books_for_self_without_patient_id(patient_client: TestClient) -> None:
    r = patient_client.post("/appointments", json={"doctor_id": 1, "start_at": local(TUE, "09:00")})
    assert r.status_code == 201
    assert r.json()["patient_id"] == PATIENT


def test_staff_must_name_the_patient(client: TestClient) -> None:
    r = client.post("/appointments", json={"doctor_id": 1, "start_at": local(TUE, "09:00")})
    assert r.status_code == 422
    assert error_code(r) == "PATIENT_REQUIRED"


def test_staff_only_routes_hidden_from_patients(patient_client: TestClient) -> None:
    walk_in = {"full_name": "Walk In", "phone": "+254733000000", "email": "w@example.com"}
    assert patient_client.post("/patients", json=walk_in).status_code == 404
    assert patient_client.get("/doctors/1/appointments", params={"date": TUE}).status_code == 404


def test_staff_schedule(client: TestClient) -> None:
    book(client, local(TUE, "09:00"))
    r = client.get("/doctors/1/appointments", params={"date": TUE})
    assert r.status_code == 200
    (item,) = r.json()
    assert item["patient_name"] == "Demo Patient" and item["start_at"].endswith("09:00:00+03:00")
    assert item["patient_phone"] == "+254700000000"
