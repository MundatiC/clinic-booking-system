"""SmtpMailer: the right connection mode per setting, credentials only when configured."""

from email.message import EmailMessage
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from app.core import mailer as mailer_module
from app.core.config import Settings
from app.core.mailer import MemoryMailer, SmtpMailer, send_safely


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls: list[str] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}:{password}")

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append("send")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer_module.smtplib, "SMTP_SSL", FakeSMTP)


def _send(**settings: Any) -> FakeSMTP:
    SmtpMailer(Settings(**settings)).send(EmailMessage())
    return FakeSMTP.instances[-1]


def test_plain_local_smtp_has_no_tls_or_login() -> None:
    smtp = _send(smtp_host="mail", smtp_port=1025)
    assert (smtp.host, smtp.port) == ("mail", 1025)
    assert smtp.calls == ["send", "quit"]


def test_starttls_with_credentials() -> None:
    smtp = _send(smtp_security="starttls", smtp_user="u", smtp_password=SecretStr("p"))
    assert smtp.calls == ["starttls", "login:u:p", "send", "quit"]


def test_resend_style_implicit_tls() -> None:
    smtp = _send(
        smtp_host="smtp.resend.com",
        smtp_port=465,
        smtp_security="ssl",
        smtp_user="resend",
        smtp_password=SecretStr("re_key"),
    )
    assert "context" in smtp.kwargs  # verified TLS context passed to SMTP_SSL
    assert smtp.calls == ["login:resend:re_key", "send", "quit"]


def test_send_safely_swallows_and_logs_failures() -> None:
    class Broken(MemoryMailer):
        def send(self, message: EmailMessage) -> None:
            raise ConnectionRefusedError("smtp down")

    send_safely(Broken(), EmailMessage(), "welcome")  # must not raise
