import re
from email.message import EmailMessage
from typing import Any

from fastapi.testclient import TestClient

from app.core.mailer import MemoryMailer

STRONG = "plum jacaranda morning walk"
_TOKEN = re.compile(r"token=([A-Za-z0-9_-]+)")


def body_text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return str(part.get_content())


def body_html(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("html",))
    assert part is not None
    return str(part.get_content())


def last_token(mailer: MemoryMailer) -> str:
    match = _TOKEN.search(body_text(mailer.outbox[-1]))
    assert match, body_text(mailer.outbox[-1])
    return match.group(1)


def register(
    anon: TestClient, email: str, password: str = STRONG, name: str = "Amani Otieno"
) -> Any:
    return anon.post(
        "/auth/register",
        json={"full_name": name, "phone": "+254722000111", "email": email, "password": password},
    )


def signup_and_verify(anon: TestClient, mailer: MemoryMailer, email: str) -> None:
    assert register(anon, email).status_code == 202
    assert anon.post("/auth/verify", json={"token": last_token(mailer)}).status_code == 200


def login(c: TestClient, email: str, password: str = STRONG) -> Any:
    return c.post("/auth/login", json={"email": email, "password": password})


def without_request_id(body: dict[str, Any]) -> dict[str, Any]:
    body = dict(body)
    if "error" in body:
        body["error"] = {k: v for k, v in body["error"].items() if k != "request_id"}
    return body
