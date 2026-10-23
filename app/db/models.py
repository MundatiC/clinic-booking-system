"""ORM models. See README section 1.2 for the data model rationale."""

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Constraint names the repository layer maps to domain errors.
UQ_DOCTOR_SLOT = "uq_appointments_doctor_slot"
UQ_PATIENT_SLOT = "uq_appointments_patient_slot"
UQ_PATIENT_EMAIL = "uq_patients_email"


class AppointmentStatus(enum.StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class AppointmentEventType(enum.StrEnum):
    BOOKED = "booked"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class WorkingHours(Base):
    __tablename__ = "working_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="window_order"),
        Index("ix_working_hours_doctor_weekday", "doctor_id", "weekday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday ... 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time)  # clinic-local wall clock
    end_time: Mapped[time] = mapped_column(Time)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (Index(UQ_PATIENT_EMAIL, "email", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254))  # stored lower-cased
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("status IN ('booked', 'cancelled')", name="status_values"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="cancelled_at_matches_status",
        ),
        # Source of truth for "a slot can only be booked once" (README 1.4).
        Index(
            UQ_DOCTOR_SLOT,
            "doctor_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        # Also serves GET /patients/{id}/appointments (booked, ordered by start_at),
        # so no separate (patient_id, start_at) index is needed.
        Index(
            UQ_PATIENT_SLOT,
            "patient_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=AppointmentStatus.BOOKED.value)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()


class AppointmentEvent(Base):
    """Append-only audit trail; written in the same transaction as the change."""

    __tablename__ = "appointment_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    from_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


UQ_USER_EMAIL = "uq_users_email"


class UserRole(enum.StrEnum):
    PATIENT = "patient"
    STAFF = "staff"


class User(Base):
    """A login. Patients are linked to exactly one Patient record; staff to none."""

    __tablename__ = "users"
    __table_args__ = (
        Index(UQ_USER_EMAIL, "email", unique=True),
        CheckConstraint("role IN ('patient', 'staff')", name="role_values"),
        CheckConstraint("(role = 'patient') = (patient_id IS NOT NULL)", name="patient_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254))  # stored lower-cased
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), unique=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped[Patient | None] = relationship()

    @property
    def is_staff(self) -> bool:
        return self.role == UserRole.STAFF


class AuthSession(Base):
    """Server-side session. Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class EmailTokenPurpose(enum.StrEnum):
    VERIFY = "verify"
    RESET = "reset"


class EmailToken(Base):
    """Single-use token sent by email (verification, password reset). Stored hashed."""

    __tablename__ = "email_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('verify', 'reset')", name="purpose_values"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
