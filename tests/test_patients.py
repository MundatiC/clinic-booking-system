"""POST /patients and GET /patients/{id}/appointments."""

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from tests.utils import MON, PATIENT, TUE, WED, at, book, error_code, local, new_patient


def _register(client: TestClient, **overrides: str) -> object:
    body = {"full_name": "Achieng Otieno", "phone": "+254712345678", "email": "a@example.com"}
    body.update(overrides)
    return client.post("/patients", json=body)


def test_register_normalises_email_and_phone(client: TestClient) -> None:
    r = _register(client, email="  Achieng.O@Example.COM ", phone="0712 345-678")
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    body = r.json()  # type: ignore[attr-defined]
    assert body["email"] == "achieng.o@example.com"
    assert body["phone"] == "+254712345678"
    assert body["created_at"].endswith("+03:00")  # clinic time, like every other timestamp


def test_duplicate_email_case_insensitive_409(client: TestClient) -> None:
    assert _register(client, email="dup@example.com").status_code == 201  # type: ignore[attr-defined]
    r = _register(client, email="DUP@example.com")
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert error_code(r) == "PATIENT_EXISTS"


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"phone": "12345"},
        {"phone": "+0123456789"},
        {"full_name": "A"},
        {"full_name": "x" * 121},
    ],
)
def test_register_validation(client: TestClient, overrides: dict[str, str]) -> None:
    r = _register(client, **overrides)
    assert r.status_code == 422  # type: ignore[attr-defined]
    assert error_code(r) == "VALIDATION_ERROR"


def test_upcoming_sorted_excludes_cancelled_and_past(client: TestClient, clock: FixedClock) -> None:
    ids = {}
    for day, hhmm, doctor in [(WED, "10:00", 1), (MON, "09:00", 1), (TUE, "14:00", 2),
                              (TUE, "09:00", 1)]:  # fmt: skip
        r = book(client, local(day, hhmm), doctor_id=doctor)
        assert r.status_code == 201, r.text
        ids[(day, hhmm)] = r.json()["id"]
    client.patch(f"/appointments/{ids[(TUE, '14:00')]}/cancel", json={"reason": "clash"})
    other = new_patient(client)
    book(client, local(TUE, "10:00"), patient_id=other)  # someone else's

    clock.set(at(MON, "12:00"))  # Monday 09:00 is now in the past
    r = client.get(f"/patients/{PATIENT}/appointments")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [a["start_at"] for a in body["items"]] == [
        "2030-01-08T09:00:00+03:00",
        "2030-01-09T10:00:00+03:00",
    ]


def test_upcoming_pagination(client: TestClient) -> None:
    for hhmm in ("08:00", "08:30", "09:00", "09:30", "10:00"):
        assert book(client, local(TUE, hhmm)).status_code == 201
    r = client.get(f"/patients/{PATIENT}/appointments", params={"limit": 2, "offset": 2})
    body = r.json()
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 2
    assert [a["start_at"][11:16] for a in body["items"]] == ["09:00", "09:30"]
    r = client.get(f"/patients/{PATIENT}/appointments", params={"offset": 10})
    assert r.json()["items"] == [] and r.json()["total"] == 5


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_upcoming_bad_pagination_422(client: TestClient, params: dict[str, int]) -> None:
    r = client.get(f"/patients/{PATIENT}/appointments", params=params)
    assert r.status_code == 422


def test_upcoming_unknown_patient_404(client: TestClient) -> None:
    r = client.get("/patients/00000000-0000-4000-8000-00000000dead/appointments")
    assert r.status_code == 404
    assert error_code(r) == "PATIENT_NOT_FOUND"
