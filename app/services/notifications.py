"""Builds the emails and queues them to send after the response."""

from datetime import datetime

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.core.mailer import Mailer, send_safely
from app.db.models import Appointment, Doctor, Patient
from app.emails import render


class Notifier:
    def __init__(
        self, mailer: Mailer, settings: Settings, background: BackgroundTasks | None
    ) -> None:
        self.mailer = mailer
        self.s = settings
        self.background = background  # None: send immediately (scripts, tests)

    # ---- links (tokens travel in the URL fragment: never sent to servers or Referer)

    def _link(self, view: str, token: str | None = None) -> str:
        return f"{self.s.public_base_url}/#/{view}" + (f"?token={token}" if token else "")

    def _when(self, dt: datetime) -> str:
        return dt.astimezone(self.s.tz).strftime("%A %d %B %Y, %H:%M")

    def _send(self, template: str, to: str, **values: str) -> None:
        message = render(
            template, to=to, sender=self.s.mail_from, clinic=self.s.clinic_name, **values
        )
        if self.background is None:
            send_safely(self.mailer, message, template)
        else:
            self.background.add_task(send_safely, self.mailer, message, template)

    # ---- account

    def verify_email(self, to: str, name: str, token: str) -> None:
        self._send("verify_email", to, name=name, link=self._link("verify", token))

    def already_registered(self, to: str) -> None:
        self._send(
            "already_registered",
            to,
            signin_link=self._link("signin"),
            reset_link=self._link("forgot"),
        )

    def welcome(self, to: str, name: str) -> None:
        self._send("welcome", to, name=name, signin_link=self._link("signin"))

    def new_sign_in(self, to: str, name: str, at: datetime, user_agent: str) -> None:
        self._send(
            "new_sign_in",
            to,
            name=name,
            when=self._when(at),
            device=_describe_device(user_agent),
            reset_link=self._link("forgot"),
        )

    def reset_password(self, to: str, token: str) -> None:
        self._send("reset_password", to, link=self._link("reset", token))

    def password_changed(self, to: str, name: str, at: datetime) -> None:
        self._send(
            "password_changed", to, name=name, when=self._when(at), reset_link=self._link("forgot")
        )

    # ---- appointments

    def appointment(
        self,
        kind: str,
        appt: Appointment,
        patient: Patient,
        doctor: Doctor,
        previous: datetime | None = None,
    ) -> None:
        values = {
            "name": patient.full_name,
            "doctor": doctor.name,
            "specialty": doctor.specialty,
            "when": self._when(appt.start_at),
            "signin_link": self._link("appointments"),
        }
        if kind == "rescheduled" and previous is not None:
            values["previous"] = self._when(previous)
        if kind == "cancelled":
            values["reason"] = appt.cancel_reason or ""
        self._send(f"appointment_{kind}", patient.email, **values)


def _describe_device(user_agent: str) -> str:
    """Coarse and safe to show: browser family and OS, never the raw header."""
    ua = user_agent.lower()
    browser = next((name for key, name in _BROWSERS if key in ua), "An app or unknown browser")
    system = next((name for key, name in _SYSTEMS if key in ua), "an unknown system")
    return f"{browser} on {system}"


_BROWSERS = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("firefox/", "Firefox"),
    ("chrome/", "Chrome"),
    ("safari/", "Safari"),
    ("curl/", "curl"),
)
_SYSTEMS = (
    ("android", "Android"),
    ("iphone", "iPhone"),
    ("ipad", "iPad"),
    ("windows", "Windows"),
    ("mac os", "macOS"),
    ("linux", "Linux"),
)
