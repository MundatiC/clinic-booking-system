"""initial schema

Revision ID: d3c7c1c12e26
Revises:
Create Date: 2026-10-23 11:33:03.727781

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3c7c1c12e26"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "doctors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
    )
    op.create_index("uq_patients_email", "patients", ["email"], unique=True)
    op.create_table(
        "appointments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name=op.f("ck_appointments_cancelled_at_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('booked', 'cancelled')", name=op.f("ck_appointments_status_values")
        ),
        sa.CheckConstraint("end_at > start_at", name=op.f("ck_appointments_time_order")),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=op.f("fk_appointments_doctor_id_doctors"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_appointments_patient_id_patients"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
    )
    op.create_index(
        "uq_appointments_doctor_slot",
        "appointments",
        ["doctor_id", "start_at"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.create_index(
        "uq_appointments_patient_slot",
        "appointments",
        ["patient_id", "start_at"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.create_table(
        "working_hours",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.CheckConstraint("end_time > start_time", name=op.f("ck_working_hours_window_order")),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_working_hours_weekday_range")),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=op.f("fk_working_hours_doctor_id_doctors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_working_hours")),
    )
    op.create_index(
        "ix_working_hours_doctor_weekday", "working_hours", ["doctor_id", "weekday"], unique=False
    )
    op.create_table(
        "appointment_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("from_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_events_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_events")),
    )
    op.create_index(
        op.f("ix_appointment_events_appointment_id"),
        "appointment_events",
        ["appointment_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_appointment_events_appointment_id"), table_name="appointment_events")
    op.drop_table("appointment_events")
    op.drop_index("ix_working_hours_doctor_weekday", table_name="working_hours")
    op.drop_table("working_hours")
    op.drop_index(
        "uq_appointments_patient_slot",
        table_name="appointments",
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.drop_index(
        "uq_appointments_doctor_slot",
        table_name="appointments",
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.drop_table("appointments")
    op.drop_index("uq_patients_email", table_name="patients")
    op.drop_table("patients")
    op.drop_table("doctors")
