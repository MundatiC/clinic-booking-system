"""POST /appointments: every booking rule, and double booking (sequential)."""

from datetime import UTC, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.db.models import Appointment, AppointmentEvent, Doctor, WorkingHours
from tests.utils import MON, NOW, PATIENT, SAT, TUE, WED, at, book, error_code, local, new_patient


def test_book_success_returns_201_in_clinic_time(client: TestClient, db: Session) -> None:
    r = book(client, local(TUE, "09:00"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["start_at"] == "2030-01-08T09:00:00+03:00"
    assert body["end_at"] == "2030-01-08T09:30:00+03:00"
    assert body["status"] == "booked"
    assert body["doctor_id"] == 1 and body["patient_id"] == PATIENT

    # Stored as UTC: 09:00 Nairobi == 06:00Z.
    appt = db.scalar(select(Appointment))
    assert appt is not None
    assert appt.start_at == datetime(2030, 1, 8, 6, 0, tzinfo=UTC)
    assert appt.start_at.utcoffset() == timedelta(0)
    events = db.scalars(select(AppointmentEvent)).all()
    assert [e.type for e in events] == ["booked"]


def test_book_accepts_any_offset_for_same_instant(client: TestClient) -> None:
    r = book(client, "2030-01-08T06:00:00Z")  # == 09:00 Nairobi
    assert r.status_code == 201
    assert r.json()["start_at"] == "2030-01-08T09:00:00+03:00"


@pytest.mark.parametrize(
    ("start", "code"),
    [
        (local(TUE, "07:00"), "OUTSIDE_WORKING_HOURS"),  # before opening
        (local(TUE, "17:00"), "OUTSIDE_WORKING_HOURS"),  # starts at window end
        (local(TUE, "12:00"), "OUTSIDE_WORKING_HOURS"),  # lunch gap 12:00-13:00
        (local(TUE, "12:30"), "OUTSIDE_WORKING_HOURS"),  # lunch gap
        (local(SAT, "09:00"), "OUTSIDE_WORKING_HOURS"),  # doctor 1 is off on Saturday
        (local(TUE, "09:15"), "NOT_ON_SLOT_GRID"),
        ("2030-01-08T09:00:30+03:00", "NOT_ON_SLOT_GRID"),  # seconds
        ("2030-01-08T06:15:00Z", "NOT_ON_SLOT_GRID"),  # 09:15 local, given in UTC
        (local("2030-01-04", "09:00"), "SLOT_IN_PAST"),
    ],
)
def test_book_rule_violations_are_422(client: TestClient, start: str, code: str) -> None:
    r = book(client, start)
    assert r.status_code == 422, r.text
    assert error_code(r) == code


def test_outside_hours_error_lists_the_days_windows(client: TestClient) -> None:
    r = book(client, local(TUE, "12:00"))
    assert r.json()["error"]["details"]["working_hours"] == ["08:00-12:00", "13:00-17:00"]


def test_day_off_has_specific_message(client: TestClient) -> None:
    r = book(client, local(WED, "10:00"), doctor_id=4)  # cardiologist works Tue/Thu
    assert error_code(r) == "OUTSIDE_WORKING_HOURS"
    assert "does not work on that day" in r.json()["error"]["message"]


def test_last_slot_of_each_window_is_bookable(client: TestClient) -> None:
    assert book(client, local(TUE, "11:30")).status_code == 201  # ends 12:00
    assert book(client, local(TUE, "16:30")).status_code == 201  # ends 17:00


def test_slot_straddling_window_end_rejected(client: TestClient, db: Session) -> None:
    db.add(WorkingHours(doctor_id=2, weekday=5, start_time=time(9), end_time=time(10, 45)))
    db.commit()
    assert book(client, local(SAT, "10:00"), doctor_id=2).status_code == 201  # ends 10:30
    r = book(client, local(SAT, "10:30"), doctor_id=2)  # would end 11:00 > 10:45
    assert error_code(r) == "OUTSIDE_WORKING_HOURS"


def test_half_hour_window_starts_are_on_grid(client: TestClient) -> None:
    # Doctor 5 works 08:30-12:30 and 13:30-16:30.
    assert book(client, local(TUE, "08:30"), doctor_id=5).status_code == 201
    assert book(client, local(TUE, "12:00"), doctor_id=5).status_code == 201
    assert error_code(book(client, local(TUE, "12:30"), doctor_id=5)) == "OUTSIDE_WORKING_HOURS"
    assert error_code(book(client, local(TUE, "08:00"), doctor_id=5)) == "OUTSIDE_WORKING_HOURS"


def test_lead_time(client: TestClient, clock: FixedClock) -> None:
    clock.set(at(MON, "08:20"))
    r = book(client, local(MON, "09:00"))  # 40 minutes away
    assert r.status_code == 422
    assert error_code(r) == "TOO_SOON"
    assert r.json()["error"]["details"]["min_lead_time_minutes"] == 60
    assert book(client, local(MON, "09:30")).status_code == 201  # 70 minutes away


def test_lead_time_boundary_exactly_60_minutes_allowed(
    client: TestClient, clock: FixedClock
) -> None:
    clock.set(at(MON, "08:00"))
    assert book(client, local(MON, "09:00")).status_code == 201


def test_slot_starting_now_is_past(client: TestClient, clock: FixedClock) -> None:
    clock.set(at(MON, "09:00"))
    assert error_code(book(client, local(MON, "09:00"))) == "SLOT_IN_PAST"


def test_advance_window(client: TestClient) -> None:
    last_ok = (NOW + timedelta(days=88)).date().isoformat()  # Friday, 88 days ahead
    assert book(client, local(last_ok, "09:00")).status_code == 201
    too_far = (NOW + timedelta(days=91)).date().isoformat()  # Monday, 91 days ahead
    r = book(client, local(too_far, "09:00"))
    assert r.status_code == 422
    assert error_code(r) == "TOO_FAR_IN_ADVANCE"


def test_unknown_doctor_404(client: TestClient) -> None:
    r = book(client, local(TUE, "09:00"), doctor_id=999)
    assert r.status_code == 404
    assert error_code(r) == "DOCTOR_NOT_FOUND"


def test_inactive_doctor_404(client: TestClient, db: Session) -> None:
    doctor = db.get(Doctor, 1)
    assert doctor is not None
    doctor.is_active = False
    db.commit()
    assert error_code(book(client, local(TUE, "09:00"))) == "DOCTOR_NOT_FOUND"


def test_unknown_patient_404(client: TestClient) -> None:
    r = book(client, local(TUE, "09:00"), patient_id="00000000-0000-4000-8000-00000000dead")
    assert r.status_code == 404
    assert error_code(r) == "PATIENT_NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [
        {"doctor_id": 1, "patient_id": PATIENT, "start_at": "2030-01-08T09:00:00"},  # naive
        {"doctor_id": 1, "patient_id": PATIENT, "start_at": "next tuesday"},
        {"doctor_id": "1", "patient_id": PATIENT, "start_at": local(TUE, "09:00")},  # strict int
        {"doctor_id": 0, "patient_id": PATIENT, "start_at": local(TUE, "09:00")},
        {"doctor_id": 1, "patient_id": "not-a-uuid", "start_at": local(TUE, "09:00")},
        {"doctor_id": 1, "patient_id": PATIENT},
        {"doctor_id": 1, "patient_id": PATIENT, "start_at": local(TUE, "09:00"), "extra": 1},
    ],
)
def test_invalid_payloads_422(client: TestClient, payload: dict[str, object]) -> None:
    r = client.post("/appointments", json=payload)
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


def test_naive_datetime_error_points_at_field(client: TestClient) -> None:
    r = client.post(
        "/appointments",
        json={"doctor_id": 1, "patient_id": PATIENT, "start_at": "2030-01-08T09:00:00"},
    )
    errors = r.json()["error"]["details"]["errors"]
    assert errors[0]["loc"] == ["body", "start_at"]
    assert errors[0]["type"] == "timezone_aware"
    assert "input" not in errors[0]  # never echo submitted values


def test_double_booking_same_slot_409(client: TestClient) -> None:
    assert book(client, local(TUE, "09:00")).status_code == 201
    other = new_patient(client)
    r = book(client, local(TUE, "09:00"), patient_id=other)
    assert r.status_code == 409
    assert error_code(r) == "SLOT_TAKEN"


def test_same_slot_other_doctor_is_fine(client: TestClient) -> None:
    assert book(client, local(TUE, "09:00")).status_code == 201
    other = new_patient(client)
    assert book(client, local(TUE, "09:00"), doctor_id=2, patient_id=other).status_code == 201


def test_patient_cannot_be_in_two_places(client: TestClient) -> None:
    assert book(client, local(TUE, "09:00"), doctor_id=1).status_code == 201
    r = book(client, local(TUE, "09:00"), doctor_id=2)
    assert r.status_code == 409
    assert error_code(r) == "PATIENT_DOUBLE_BOOKED"
