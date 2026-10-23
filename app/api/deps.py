"""FastAPI dependencies wiring settings, clock and session into services."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.db.session import get_session
from app.services.booking import BookingService
from app.services.patients import PatientService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def get_booking_service(
    session: SessionDep, settings: SettingsDep, clock: ClockDep
) -> BookingService:
    return BookingService(session, settings, clock)


def get_patient_service(session: SessionDep, clock: ClockDep) -> PatientService:
    return PatientService(session, clock)


BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]
