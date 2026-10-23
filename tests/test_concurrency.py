"""Real concurrency against Postgres: threads, separate connections, a barrier to line them up.

These go through the service layer (one session per thread, as each request would
have) so the database is what arbitrates. No mocking of locks or constraints.
"""

import threading
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import FixedClock
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.mailer import MemoryMailer
from app.db.models import Appointment, Patient, User, UserRole
from app.services.booking import BookingService
from app.services.notifications import Notifier
from tests.utils import NOW, TUE, at

SLOT = at(TUE, "09:00")
STAFF = User(role=UserRole.STAFF)  # transient: services only read role/patient_id


def _service(session: Session) -> BookingService:
    settings = get_settings()
    return BookingService(
        session, settings, FixedClock(NOW), Notifier(MemoryMailer(), settings, None)
    )


def _patients(factory: sessionmaker[Session], n: int) -> list[uuid.UUID]:
    with factory() as s:
        ps = [
            Patient(full_name=f"P{i}", phone="+254700000001", email=f"c{i}@x.io") for i in range(n)
        ]
        s.add_all(ps)
        s.commit()
        return [p.id for p in ps]


def _race(
    factory: sessionmaker[Session], jobs: list[Callable[[BookingService], object]]
) -> list[str]:
    """Run jobs simultaneously, each in its own session; return 'ok' or the error code."""
    barrier = threading.Barrier(len(jobs))
    results: list[str] = [""] * len(jobs)

    def run(i: int) -> None:
        with factory() as session:
            svc = _service(session)
            barrier.wait()
            try:
                jobs[i](svc)
                results[i] = "ok"
            except AppError as exc:
                results[i] = exc.code

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _booked_at(factory: sessionmaker[Session], start: datetime) -> list[Appointment]:
    with factory() as s:
        stmt = select(Appointment).where(
            Appointment.start_at == start, Appointment.status == "booked"
        )
        return list(s.scalars(stmt))


def test_concurrent_bookings_exactly_one_wins(session_factory: sessionmaker[Session]) -> None:
    patients = _patients(session_factory, 10)
    results = _race(
        session_factory,
        [lambda svc, p=p: svc.book(STAFF, 1, p, SLOT) for p in patients],  # type: ignore[misc]
    )
    assert Counter(results) == {"ok": 1, "SLOT_TAKEN": 9}
    assert len(_booked_at(session_factory, SLOT)) == 1


def test_concurrent_reschedule_vs_booking_one_wins(session_factory: sessionmaker[Session]) -> None:
    mover, booker = _patients(session_factory, 2)
    target = at(TUE, "10:00")
    with session_factory() as s:
        appt = _service(s).book(STAFF, 1, mover, SLOT)
        appt_id = appt.id

    for _ in range(5):  # repeat to vary the interleaving
        results = _race(
            session_factory,
            [
                lambda svc: svc.reschedule(STAFF, appt_id, target),
                lambda svc: svc.book(STAFF, 1, booker, target),
            ],
        )
        assert sorted(results) == ["SLOT_TAKEN", "ok"]
        winners = _booked_at(session_factory, target)
        assert len(winners) == 1
        with session_factory() as s:
            moved = s.get(Appointment, appt_id)
            assert moved is not None and moved.status == "booked"
            if results[0] == "ok":  # reschedule won
                assert moved.start_at == target
            else:  # booking won: the original is untouched
                assert moved.start_at == SLOT
        # reset for the next round
        with session_factory() as s:
            for a in s.scalars(select(Appointment)):
                if a.id != appt_id:
                    s.delete(a)
            a0 = s.get(Appointment, appt_id)
            assert a0 is not None
            a0.start_at, a0.end_at = SLOT, at(TUE, "09:30")
            s.commit()


def test_concurrent_cancels_one_succeeds(session_factory: sessionmaker[Session]) -> None:
    (p,) = _patients(session_factory, 1)
    with session_factory() as s:
        appt_id = _service(s).book(STAFF, 1, p, SLOT).id
    results = _race(
        session_factory,
        [
            lambda svc: svc.cancel(STAFF, appt_id, "reason one"),
            lambda svc: svc.cancel(STAFF, appt_id, "two"),
        ],
    )
    assert sorted(results) == ["ALREADY_CANCELLED", "ok"]
    with session_factory() as s:
        n = s.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.status == "cancelled")
        )
        assert n == 1
