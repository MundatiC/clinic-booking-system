"""GET /doctors/{id}/availability."""

from datetime import time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.db.models import WorkingHours
from tests.utils import MON, NOW, SAT, TUE, WED, at, book, error_code, local, slot_starts

FULL_DAY_DR1 = [f"{h:02d}:{m:02d}" for h in (8, 9, 10, 11, 13, 14, 15, 16) for m in (0, 30)]


def test_response_shape(client: TestClient) -> None:
    r = client.get("/doctors/1/availability", params={"date": TUE})
    assert r.status_code == 200
    body = r.json()
    assert body["doctor_id"] == 1
    assert body["date"] == TUE
    assert body["timezone"] == "Africa/Nairobi"
    assert body["slot_minutes"] == 30
    assert body["slots"][0] == {
        "start": "2030-01-08T08:00:00+03:00",
        "end": "2030-01-08T08:30:00+03:00",
    }


def test_normal_day_respects_lunch_break(client: TestClient) -> None:
    starts = slot_starts(client, 1, TUE)
    assert starts == FULL_DAY_DR1
    assert len(starts) == 16
    assert "12:00" not in starts and "12:30" not in starts


def test_half_hour_windows(client: TestClient) -> None:
    starts = slot_starts(client, 5, TUE)  # 08:30-12:30, 13:30-16:30
    assert len(starts) == 8 + 6
    assert starts[0] == "08:30" and starts[7] == "12:00" and starts[-1] == "16:00"


def test_booked_slot_hidden_and_cancelled_reappears(client: TestClient) -> None:
    appt = book(client, local(TUE, "09:00")).json()
    assert "09:00" not in slot_starts(client, 1, TUE)
    r = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "No longer needed"})
    assert r.status_code == 200
    assert "09:00" in slot_starts(client, 1, TUE)


def test_other_doctors_bookings_do_not_affect(client: TestClient) -> None:
    book(client, local(TUE, "09:00"), doctor_id=2)
    assert slot_starts(client, 1, TUE) == FULL_DAY_DR1


def test_past_and_too_soon_hidden(client: TestClient, clock: FixedClock) -> None:
    clock.set(at(MON, "10:10"))  # earliest bookable: 11:10 -> first slot 11:30
    assert slot_starts(client, 1, MON) == ["11:30", "13:00", "13:30", "14:00", "14:30",
                                           "15:00", "15:30", "16:00", "16:30"]  # fmt: skip


def test_past_date_is_empty(client: TestClient) -> None:
    r = client.get("/doctors/1/availability", params={"date": "2030-01-04"})
    assert r.status_code == 200
    assert r.json()["slots"] == []


def test_day_off_is_empty(client: TestClient) -> None:
    assert slot_starts(client, 4, WED) == []  # cardiology: Tue/Thu only
    assert slot_starts(client, 1, SAT) == []
    assert slot_starts(client, 3, SAT) == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]


def test_beyond_advance_window_is_empty(client: TestClient) -> None:
    far = (NOW + timedelta(days=91)).date().isoformat()
    assert slot_starts(client, 1, far) == []


def test_window_not_ending_on_grid(client: TestClient, db: Session) -> None:
    db.add(WorkingHours(doctor_id=2, weekday=5, start_time=time(9, 10), end_time=time(10, 45)))
    db.commit()
    # 09:10 rounds up to 09:30; the last slot must end by 10:45.
    assert slot_starts(client, 2, SAT) == ["09:30", "10:00"]


def test_invalid_date_422(client: TestClient) -> None:
    for bad in ("2030-13-01", "08-01-2030", "tomorrow", "", "0", "1893456000", "2030-1-8"):
        r = client.get("/doctors/1/availability", params={"date": bad})
        assert r.status_code == 422, bad
        assert error_code(r) == "VALIDATION_ERROR"
    r = client.get("/doctors/1/availability")
    assert r.status_code == 422


def test_unknown_doctor_404(client: TestClient) -> None:
    r = client.get("/doctors/999/availability", params={"date": TUE})
    assert r.status_code == 404
    assert error_code(r) == "DOCTOR_NOT_FOUND"


def test_list_doctors(client: TestClient) -> None:
    r = client.get("/doctors")
    assert r.status_code == 200
    assert [d["id"] for d in r.json()] == [1, 2, 3, 4, 5]
