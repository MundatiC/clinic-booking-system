"""Booking rules: availability, book, cancel, reschedule (README section 1.6).

Correctness against double booking comes from the database's partial unique
indexes, not from checks here. These rules produce clear errors for inputs
that can never succeed. Each public method is one transaction.
"""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.db.models import (
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
    Doctor,
    User,
)
from app.repositories import appointments as appointments_repo
from app.repositories import doctors as doctors_repo
from app.repositories import patients as patients_repo
from app.services import slots
from app.services.notifications import Notifier
from app.services.slots import Slot, Window


class BookingService:
    def __init__(
        self, session: Session, settings: Settings, clock: Clock, notifier: Notifier
    ) -> None:
        self.session = session
        self.notify = notifier
        self.settings = settings
        self.clock = clock
        self.tz = settings.tz
        self.slot = timedelta(minutes=settings.slot_minutes)

    # ---- queries -------------------------------------------------------------------

    def availability(self, doctor_id: int, day: date) -> tuple[list[Window], list[Slot]]:
        """The day's working windows and its free slots: 2 queries, set difference."""
        self._active_doctor(doctor_id)
        windows = [
            (w.start_time, w.end_time)
            for w in doctors_repo.windows_for(self.session, doctor_id, day.weekday())
        ]
        now = self.clock.now()
        today = now.astimezone(self.tz).date()
        horizon = today + timedelta(days=self.settings.max_advance_days)
        if not windows or day < today or day > horizon:
            return windows, []
        candidates = slots.generate_slots(day, windows, self.tz, self.settings.slot_minutes)
        day_start, day_end = slots.local_day_bounds_utc(day, self.tz)
        taken = appointments_repo.booked_starts(self.session, doctor_id, day_start, day_end)
        earliest = now + timedelta(minutes=self.settings.min_lead_time_minutes)
        return windows, [(s, e) for s, e in candidates if s not in taken and s >= earliest]

    def get(self, user: User, appointment_id: uuid.UUID) -> Appointment:
        return _visible(appointments_repo.get(self.session, appointment_id), user, appointment_id)

    def doctor_day(self, doctor_id: int, day: date) -> list[Appointment]:
        """The doctor's booked appointments on a clinic-local date (staff schedule)."""
        self._active_doctor(doctor_id)
        start, end = slots.local_day_bounds_utc(day, self.tz)
        return appointments_repo.booked_between(self.session, doctor_id, start, end)

    # ---- commands ------------------------------------------------------------------

    def book(
        self, user: User, doctor_id: int, patient_id: uuid.UUID | None, start_at: datetime
    ) -> Appointment:
        if not user.is_staff:
            # Patients book for themselves; naming anyone else looks like "not found".
            if patient_id not in (None, user.patient_id):
                raise _patient_not_found(patient_id)
            patient_id = user.patient_id
        if patient_id is None:
            raise BusinessRuleError(
                "PATIENT_REQUIRED", "Staff bookings must say which patient they are for."
            )
        doctor = self._active_doctor(doctor_id)
        patient = patients_repo.get(self.session, patient_id)
        if patient is None:
            raise _patient_not_found(patient_id)
        self._validate_slot(doctor, start_at)

        appt = Appointment(
            doctor_id=doctor.id,
            patient_id=patient_id,
            start_at=start_at,
            end_at=start_at + self.slot,
            status=AppointmentStatus.BOOKED,
        )
        event = AppointmentEvent(type=AppointmentEventType.BOOKED, to_start_at=start_at)
        # No "is it free?" pre-check: the unique index answers that atomically, and its
        # violation is translated to the same friendly 409 SLOT_TAKEN.
        appointments_repo.add(self.session, appt, event)
        self.session.commit()
        self.notify.appointment("booked", appt, patient, doctor)
        return appt

    def cancel(self, user: User, appointment_id: uuid.UUID, reason: str) -> Appointment:
        appt = self._locked(user, appointment_id)
        if appt.status == AppointmentStatus.CANCELLED:
            raise ConflictError(
                "ALREADY_CANCELLED",
                "This appointment is already cancelled.",
                {"cancelled_at": _iso(appt.cancelled_at, self)},
            )
        self._not_started(appt)

        appt.status = AppointmentStatus.CANCELLED
        appt.cancel_reason = reason
        appt.cancelled_at = self.clock.now()
        event = AppointmentEvent(type=AppointmentEventType.CANCELLED, from_start_at=appt.start_at)
        appointments_repo.save(self.session, appt, event)
        self.session.commit()
        self._notify("cancelled", appt)
        return appt

    def reschedule(self, user: User, appointment_id: uuid.UUID, start_at: datetime) -> Appointment:
        appt = self._locked(user, appointment_id)
        if appt.status == AppointmentStatus.CANCELLED:
            raise ConflictError(
                "APPOINTMENT_CANCELLED", "A cancelled appointment cannot be rescheduled."
            )
        self._not_started(appt)
        if start_at == appt.start_at:
            raise BusinessRuleError(
                "NO_CHANGE",
                "The appointment is already at that time.",
                {"start_at": _iso(start_at, self)},
            )
        doctor = self._active_doctor(appt.doctor_id)
        self._validate_slot(doctor, start_at)

        old_start = appt.start_at
        appt.start_at = start_at
        appt.end_at = start_at + self.slot
        event = AppointmentEvent(
            type=AppointmentEventType.RESCHEDULED, from_start_at=old_start, to_start_at=start_at
        )
        # One UPDATE moves the row: the old slot is freed and the new one claimed
        # atomically. If the new slot is taken, the unique index rejects the UPDATE, the
        # transaction rolls back, and the original booking is left as it was.
        appointments_repo.save(self.session, appt, event)
        self.session.commit()
        self._notify("rescheduled", appt, previous=old_start)
        return appt

    # ---- rules ---------------------------------------------------------------------

    def _validate_slot(self, doctor: Doctor, start_at: datetime) -> None:
        """The rules every new slot must pass, shared by booking and rescheduling."""
        tz, minutes = self.tz, self.settings.slot_minutes
        if not slots.is_on_grid(start_at, tz, minutes):
            raise BusinessRuleError(
                "NOT_ON_SLOT_GRID",
                f"Appointments start on {minutes}-minute boundaries in {tz.key} time "
                f"(e.g. 09:00 or 09:30), with zero seconds.",
                {"start_at": _iso(start_at, self), "slot_minutes": minutes, "timezone": tz.key},
            )

        now = self.clock.now()
        if start_at <= now:
            raise BusinessRuleError(
                "SLOT_IN_PAST", "That time is in the past.", {"start_at": _iso(start_at, self)}
            )
        lead = self.settings.min_lead_time_minutes
        earliest = now + timedelta(minutes=lead)
        if start_at < earliest:
            raise BusinessRuleError(
                "TOO_SOON",
                f"Appointments must be booked at least {lead} minutes in advance.",
                {"min_lead_time_minutes": lead, "earliest_allowed": _iso(earliest, self)},
            )
        max_days = self.settings.max_advance_days
        last_day = now.astimezone(tz).date() + timedelta(days=max_days)
        if start_at.astimezone(tz).date() > last_day:
            raise BusinessRuleError(
                "TOO_FAR_IN_ADVANCE",
                f"Appointments can be booked at most {max_days} days ahead.",
                {"max_advance_days": max_days, "last_bookable_date": last_day.isoformat()},
            )

        local = start_at.astimezone(tz)
        windows = [
            (w.start_time, w.end_time)
            for w in doctors_repo.windows_for(self.session, doctor.id, local.weekday())
        ]
        if not slots.fits_in_windows(start_at, tz, minutes, windows):
            raise BusinessRuleError(
                "OUTSIDE_WORKING_HOURS",
                "The doctor is not working at that time."
                if windows
                else "The doctor does not work on that day.",
                {
                    "start_at": _iso(start_at, self),
                    "working_hours": [f"{s:%H:%M}-{e:%H:%M}" for s, e in windows],
                    "timezone": tz.key,
                },
            )

    def _active_doctor(self, doctor_id: int) -> Doctor:
        doctor = doctors_repo.get_active(self.session, doctor_id)
        if doctor is None:
            raise NotFoundError("DOCTOR_NOT_FOUND", "Doctor not found.", {"doctor_id": doctor_id})
        return doctor

    def _locked(self, user: User, appointment_id: uuid.UUID) -> Appointment:
        appt = appointments_repo.get_for_update(self.session, appointment_id)
        return _visible(appt, user, appointment_id)

    def _notify(self, kind: str, appt: Appointment, previous: datetime | None = None) -> None:
        self.notify.appointment(kind, appt, appt.patient, appt.doctor, previous)

    def _not_started(self, appt: Appointment) -> None:
        if appt.start_at <= self.clock.now():
            raise ConflictError(
                "APPOINTMENT_STARTED",
                "This appointment has already started or taken place.",
                {"start_at": _iso(appt.start_at, self)},
            )


def _visible(appt: Appointment | None, user: User, appointment_id: uuid.UUID) -> Appointment:
    """Staff see every appointment; patients only their own. Others' look like 404."""
    if appt is None or not (user.is_staff or appt.patient_id == user.patient_id):
        raise _appointment_not_found(appointment_id)
    return appt


def _patient_not_found(patient_id: uuid.UUID) -> NotFoundError:
    return NotFoundError("PATIENT_NOT_FOUND", "Patient not found.", {"patient_id": str(patient_id)})


def _appointment_not_found(appointment_id: uuid.UUID) -> NotFoundError:
    return NotFoundError(
        "APPOINTMENT_NOT_FOUND", "Appointment not found.", {"appointment_id": str(appointment_id)}
    )


def _iso(dt: datetime | None, svc: BookingService) -> str | None:
    return dt.astimezone(svc.tz).isoformat() if dt is not None else None
