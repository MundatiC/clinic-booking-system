"""End-to-end check of a deployed API (standard library only).

Runs the assignment's flows against a live URL: availability, book, double booking,
the validation rules, reschedule, cancel, upcoming list, auth and staff routes.
It books, moves and cancels its own appointment (and, with a staff login, one walk-in
patient), so it leaves no booked slot behind. Passwords are asked for, never echoed
or printed.

Usage: python scripts/live_check.py https://clinic-booking-api-ixbo.onrender.com
       (patient: demo.patient@example.com; staff checks run only if a staff email is given)
"""

import getpass
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

NAIROBI = timezone(timedelta(hours=3))  # Africa/Nairobi has no DST; no tzdata needed on Windows
USER_AGENT = "clinic-booking-live-check/1.0"
results: list[bool] = []


def call(
    base: str, method: str, path: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    url = base + path
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        # Scheme validated above. nosec B310
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310  # nosec B310
            raw = resp.read()
            return int(resp.status), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def code_of(body: object) -> str:
    return body.get("error", {}).get("code", "") if isinstance(body, dict) else ""


def check(name: str, ok: bool, got: object = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got})"), flush=True)


def expect(name: str, got: tuple[int, object], status: int, code: str = "") -> object:
    ok = got[0] == status and (not code or code_of(got[1]) == code)
    check(name, ok, f"{got[0]} {code_of(got[1])}")
    return got[1]


def find_free_day(base: str) -> tuple[int, str, list[dict[str, str]]]:
    # A day at least two days out, so the 1-hour lead time never interferes.
    start = datetime.now(NAIROBI).date() + timedelta(days=2)
    for offset in range(14):
        day = (start + timedelta(days=offset)).isoformat()
        for doctor in range(1, 6):
            _, body = call(base, "GET", f"/doctors/{doctor}/availability?date={day}")
            slots = body.get("slots", []) if isinstance(body, dict) else []
            if len(slots) >= 3:
                return doctor, day, slots
    raise SystemExit("no doctor has 3 free slots in the next two weeks")


def public_checks(base: str) -> None:
    status, body = call(base, "GET", "/health")
    check(
        "GET /health is ok", status == 200 and isinstance(body, dict) and body.get("status") == "ok"
    )
    expect("GET /ready (database reachable)", call(base, "GET", "/ready"), 200)
    status, body = call(base, "GET", "/doctors")
    check(
        "GET /doctors lists 5 doctors", status == 200 and isinstance(body, list) and len(body) == 5
    )
    expect(
        "unknown doctor -> 404",
        call(base, "GET", "/doctors/999/availability?date=2030-01-07"),
        404,
        "DOCTOR_NOT_FOUND",
    )
    expect(
        "bad date format -> 422",
        call(base, "GET", "/doctors/1/availability?date=07-01-2030"),
        422,
        "VALIDATION_ERROR",
    )
    status, body = call(base, "GET", "/doctors/1/availability?date=2020-01-06")
    check(
        "past date -> 200 with no slots",
        status == 200 and isinstance(body, dict) and body.get("slots") == [],
        status,
    )
    expect(
        "booking without signing in -> 401",
        call(
            base, "POST", "/appointments", {"doctor_id": 1, "start_at": "2030-01-07T09:00:00+03:00"}
        ),
        401,
        "NOT_AUTHENTICATED",
    )


def patient_checks(base: str, password: str) -> None:
    body = expect(
        "patient signs in (POST /auth/token)",
        call(
            base, "POST", "/auth/token", {"email": "demo.patient@example.com", "password": password}
        ),
        200,
    )
    if not isinstance(body, dict):
        return
    token = str(body["access_token"])
    expect("GET /auth/me", call(base, "GET", "/auth/me", token=token), 200)

    doctor, day, slots = find_free_day(base)
    first, second = slots[-1]["start"], slots[-2]["start"]
    print(f"      using doctor {doctor} on {day}: {first} then {second}")

    booked = expect(
        "book a free slot -> 201",
        call(base, "POST", "/appointments", {"doctor_id": doctor, "start_at": first}, token),
        201,
    )
    if not isinstance(booked, dict):
        return
    appt = booked["id"]
    _, avail = call(base, "GET", f"/doctors/{doctor}/availability?date={day}")
    starts = [s["start"] for s in avail["slots"]] if isinstance(avail, dict) else []
    check("booked slot disappears from availability", first not in starts)
    expect(
        "same slot again -> 409 SLOT_TAKEN",
        call(base, "POST", "/appointments", {"doctor_id": doctor, "start_at": first}, token),
        409,
        "SLOT_TAKEN",
    )

    local = datetime.fromisoformat(first)
    rules = [
        (
            "off the 30-minute grid -> 422",
            (local + timedelta(minutes=15)).isoformat(),
            "NOT_ON_SLOT_GRID",
        ),
        ("naive datetime -> 422", local.replace(tzinfo=None).isoformat(), "VALIDATION_ERROR"),
        ("in the past -> 422", "2020-01-06T09:00:00+03:00", "SLOT_IN_PAST"),
        ("within 1 hour of now -> 422", _next_grid_time().isoformat(), "TOO_SOON"),
        (
            "over 90 days ahead -> 422",
            (local + timedelta(days=120)).replace(hour=9, minute=0).isoformat(),
            "TOO_FAR_IN_ADVANCE",
        ),
        (
            "outside working hours -> 422",
            local.replace(hour=3, minute=0).isoformat(),
            "OUTSIDE_WORKING_HOURS",
        ),
    ]
    for name, start_at, code in rules:
        expect(
            name,
            call(base, "POST", "/appointments", {"doctor_id": doctor, "start_at": start_at}, token),
            422,
            code,
        )

    expect("GET /appointments/{id}", call(base, "GET", f"/appointments/{appt}", token=token), 200)
    me = call(base, "GET", "/auth/me", token=token)[1]
    patient_id = me["patient"]["id"] if isinstance(me, dict) and me.get("patient") else ""
    status, upcoming = call(base, "GET", f"/patients/{patient_id}/appointments", token=token)
    items = upcoming.get("items", []) if isinstance(upcoming, dict) else []
    check(
        "upcoming list includes it, sorted by start",
        status == 200
        and any(i["id"] == appt for i in items)
        and [i["start_at"] for i in items] == sorted(i["start_at"] for i in items),
        status,
    )

    expect(
        "reschedule to the same slot -> 422 NO_CHANGE",
        call(base, "PATCH", f"/appointments/{appt}/reschedule", {"start_at": first}, token),
        422,
        "NO_CHANGE",
    )
    expect(
        "reschedule to another free slot -> 200",
        call(base, "PATCH", f"/appointments/{appt}/reschedule", {"start_at": second}, token),
        200,
    )
    _, avail = call(base, "GET", f"/doctors/{doctor}/availability?date={day}")
    starts = [s["start"] for s in avail["slots"]] if isinstance(avail, dict) else []
    check("old slot is free again, new one taken", first in starts and second not in starts)

    expect(
        "cancel with a too-short reason -> 422",
        call(base, "PATCH", f"/appointments/{appt}/cancel", {"reason": "no"}, token),
        422,
    )
    expect(
        "cancel with a reason -> 200",
        call(
            base,
            "PATCH",
            f"/appointments/{appt}/cancel",
            {"reason": "live check, please ignore"},
            token,
        ),
        200,
    )
    expect(
        "cancel again -> 409 ALREADY_CANCELLED",
        call(base, "PATCH", f"/appointments/{appt}/cancel", {"reason": "again"}, token),
        409,
        "ALREADY_CANCELLED",
    )
    expect(
        "reschedule a cancelled visit -> 409",
        call(base, "PATCH", f"/appointments/{appt}/reschedule", {"start_at": first}, token),
        409,
        "APPOINTMENT_CANCELLED",
    )
    _, avail = call(base, "GET", f"/doctors/{doctor}/availability?date={day}")
    starts = [s["start"] for s in avail["slots"]] if isinstance(avail, dict) else []
    check("cancelled slot is bookable again", second in starts)

    stranger = uuid.uuid4()
    expect(
        "someone else's appointment -> 404",
        call(base, "GET", f"/appointments/{stranger}", token=token),
        404,
    )
    expect(
        "someone else's list -> 404",
        call(base, "GET", f"/patients/{stranger}/appointments", token=token),
        404,
    )
    expect(
        "staff-only schedule as a patient -> 404",
        call(base, "GET", f"/doctors/{doctor}/appointments?date={day}", token=token),
        404,
    )
    expect("sign out -> 204", call(base, "POST", "/auth/logout", token=token), 204)
    expect("token is dead after sign-out -> 401", call(base, "GET", "/auth/me", token=token), 401)


def staff_checks(base: str, email: str, password: str) -> None:
    body = expect(
        "staff signs in",
        call(base, "POST", "/auth/token", {"email": email, "password": password}),
        200,
    )
    if not isinstance(body, dict):
        return
    token = str(body["access_token"])
    doctor, day, slots = find_free_day(base)
    walk_in = {
        "full_name": "Live Check Walk-in",
        "phone": "0712345678",
        "email": f"live-check-{uuid.uuid4().hex[:8]}@example.com",
    }
    created = expect(
        "staff registers a walk-in patient -> 201",
        call(base, "POST", "/patients", walk_in, token),
        201,
    )
    if not isinstance(created, dict):
        return
    dup = expect(
        "same email again -> 409 with the existing id",
        call(base, "POST", "/patients", walk_in, token),
        409,
        "PATIENT_EXISTS",
    )
    check(
        "409 carries the patient_id",
        isinstance(dup, dict) and dup["error"]["details"].get("patient_id") == created["id"],
    )
    booked = expect(
        "staff books for the walk-in -> 201",
        call(
            base,
            "POST",
            "/appointments",
            {"doctor_id": doctor, "patient_id": created["id"], "start_at": slots[-1]["start"]},
            token,
        ),
        201,
    )
    status, schedule = call(base, "GET", f"/doctors/{doctor}/appointments?date={day}", token=token)
    check(
        "day schedule shows it with the patient's name",
        status == 200
        and isinstance(schedule, list)
        and any(
            isinstance(booked, dict)
            and a["id"] == booked["id"]
            and a["patient_name"] == walk_in["full_name"]
            for a in schedule
        ),
        status,
    )
    if isinstance(booked, dict):
        expect(
            "staff cancels it -> 200",
            call(
                base,
                "PATCH",
                f"/appointments/{booked['id']}/cancel",
                {"reason": "live check, please ignore"},
                token,
            ),
            200,
        )
    expect("staff signs out -> 204", call(base, "POST", "/auth/logout", token=token), 204)


def _next_grid_time() -> datetime:
    now = datetime.now(NAIROBI).replace(second=0, microsecond=0)
    return now + timedelta(minutes=30 - now.minute % 30)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    base = argv[1].rstrip("/")
    patient_password = getpass.getpass("Demo patient password: ")
    staff_email = input("Staff email (blank to skip staff checks): ").strip()
    staff_password = getpass.getpass("Staff password: ") if staff_email else ""

    print(f"Checking {base} on {datetime.now(NAIROBI):%Y-%m-%d %H:%M} Nairobi time")
    public_checks(base)
    patient_checks(base, patient_password)
    if staff_email:
        staff_checks(base, staff_email, staff_password)
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
