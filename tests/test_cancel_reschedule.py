"""PATCH /appointments/{id}/cancel and /reschedule, plus GET /appointments/{id}."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.db.models import AppointmentEvent
from tests.utils import TUE, WED, at, book, error_code, local, new_patient, slot_starts

UNKNOWN = "00000000-0000-4000-8000-00000000beef"


def _booked(client: TestClient, start: str = local(TUE, "09:00"), **kw: Any) -> str:
    r = book(client, start, **kw)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _cancel(client: TestClient, appt_id: str, reason: str = "Travelling that week") -> Any:
    return client.patch(f"/appointments/{appt_id}/cancel", json={"reason": reason})


def _reschedule(client: TestClient, appt_id: str, start: str) -> Any:
    return client.patch(f"/appointments/{appt_id}/reschedule", json={"start_at": start})


# ---- get ---------------------------------------------------------------------------


def test_get_appointment(client: TestClient) -> None:
    appt_id = _booked(client)
    r = client.get(f"/appointments/{appt_id}")
    assert r.status_code == 200
    assert r.json()["start_at"] == "2030-01-08T09:00:00+03:00"


def test_get_unknown_404_and_bad_uuid_422(client: TestClient) -> None:
    assert error_code(client.get(f"/appointments/{UNKNOWN}")) == "APPOINTMENT_NOT_FOUND"
    assert client.get("/appointments/123").status_code == 422


# ---- cancel ------------------------------------------------------------------------


def test_cancel_success_frees_slot_for_rebooking(client: TestClient) -> None:
    appt_id = _booked(client)
    r = _cancel(client, appt_id, "  Feeling better  ")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Feeling better"  # trimmed
    assert body["cancelled_at"] == "2030-01-07T06:00:00+03:00"

    assert "09:00" in slot_starts(client, 1, TUE)
    other = new_patient(client)
    assert book(client, local(TUE, "09:00"), patient_id=other).status_code == 201


def test_cancel_twice_409(client: TestClient) -> None:
    appt_id = _booked(client)
    assert _cancel(client, appt_id).status_code == 200
    r = _cancel(client, appt_id)
    assert r.status_code == 409
    assert error_code(r) == "ALREADY_CANCELLED"


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "  no  "}, {"reason": "x" * 501}])
def test_cancel_reason_validation(client: TestClient, body: dict[str, str]) -> None:
    appt_id = _booked(client)
    r = client.patch(f"/appointments/{appt_id}/cancel", json=body)
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


def test_cancel_unknown_404(client: TestClient) -> None:
    r = _cancel(client, UNKNOWN)
    assert r.status_code == 404
    assert error_code(r) == "APPOINTMENT_NOT_FOUND"


def test_cancel_after_start_409(client: TestClient, clock: FixedClock) -> None:
    appt_id = _booked(client)
    clock.set(at(TUE, "09:05"))
    r = _cancel(client, appt_id)
    assert r.status_code == 409
    assert error_code(r) == "APPOINTMENT_STARTED"


# ---- reschedule --------------------------------------------------------------------


def test_reschedule_moves_slot(client: TestClient, db: Session) -> None:
    appt_id = _booked(client)
    r = _reschedule(client, appt_id, local(WED, "14:30"))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == appt_id  # same appointment, moved
    assert r.json()["start_at"] == "2030-01-09T14:30:00+03:00"
    assert r.json()["end_at"] == "2030-01-09T15:00:00+03:00"

    assert "09:00" in slot_starts(client, 1, TUE)  # old slot freed
    assert "14:30" not in slot_starts(client, 1, WED)  # new slot taken

    events = db.scalars(select(AppointmentEvent).order_by(AppointmentEvent.id)).all()
    assert [e.type for e in events] == ["booked", "rescheduled"]
    assert events[1].from_start_at == at(TUE, "09:00")
    assert events[1].to_start_at == at(WED, "14:30")


def test_reschedule_cancelled_409(client: TestClient) -> None:
    appt_id = _booked(client)
    _cancel(client, appt_id)
    r = _reschedule(client, appt_id, local(WED, "10:00"))
    assert r.status_code == 409
    assert error_code(r) == "APPOINTMENT_CANCELLED"


def test_reschedule_into_taken_slot_409_leaves_original(client: TestClient) -> None:
    mine = _booked(client, local(TUE, "09:00"))
    other = new_patient(client)
    _booked(client, local(TUE, "10:00"), patient_id=other)

    r = _reschedule(client, mine, local(TUE, "10:00"))
    assert r.status_code == 409
    assert error_code(r) == "SLOT_TAKEN"

    original = client.get(f"/appointments/{mine}").json()
    assert original["status"] == "booked"
    assert original["start_at"] == "2030-01-08T09:00:00+03:00"
    assert "09:00" not in slot_starts(client, 1, TUE)  # still held


def test_reschedule_same_slot_422(client: TestClient) -> None:
    appt_id = _booked(client)
    r = _reschedule(client, appt_id, "2030-01-08T06:00:00Z")  # same instant, other offset
    assert r.status_code == 422
    assert error_code(r) == "NO_CHANGE"


@pytest.mark.parametrize(
    ("start", "code"),
    [
        (local(TUE, "09:15"), "NOT_ON_SLOT_GRID"),
        (local(TUE, "12:00"), "OUTSIDE_WORKING_HOURS"),
        (local("2030-01-04", "09:00"), "SLOT_IN_PAST"),
        (local("2030-01-07", "06:30"), "TOO_SOON"),  # 30 min after "now"
        (local("2030-04-08", "09:00"), "TOO_FAR_IN_ADVANCE"),  # 91 days ahead
    ],
)
def test_reschedule_validates_like_booking(client: TestClient, start: str, code: str) -> None:
    appt_id = _booked(client)
    r = _reschedule(client, appt_id, start)
    assert r.status_code == 422
    assert error_code(r) == code


def test_reschedule_too_soon(client: TestClient, clock: FixedClock) -> None:
    appt_id = _booked(client, local(TUE, "15:00"))
    clock.set(at(TUE, "08:30"))
    assert error_code(_reschedule(client, appt_id, local(TUE, "09:00"))) == "TOO_SOON"


def test_reschedule_naive_datetime_422(client: TestClient) -> None:
    appt_id = _booked(client)
    r = _reschedule(client, appt_id, "2030-01-09T10:00:00")
    assert error_code(r) == "VALIDATION_ERROR"


def test_reschedule_after_start_409(client: TestClient, clock: FixedClock) -> None:
    appt_id = _booked(client)
    clock.set(at(TUE, "09:10"))
    assert error_code(_reschedule(client, appt_id, local(WED, "10:00"))) == "APPOINTMENT_STARTED"


def test_reschedule_unknown_404(client: TestClient) -> None:
    assert error_code(_reschedule(client, UNKNOWN, local(WED, "10:00"))) == "APPOINTMENT_NOT_FOUND"
