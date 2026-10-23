"""Sign-up, verification, sign-in, lockout, password reset, sessions (OWASP ASVS V2/V3)."""

import hashlib
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.mailer import MemoryMailer
from app.core.ratelimit import RateLimiter
from app.db.models import AuthSession, User
from app.main import create_app
from tests.security.helpers import (
    STRONG,
    body_html,
    body_text,
    last_token,
    login,
    register,
    signup_and_verify,
    without_request_id,
)
from tests.utils import (
    NOW,
    PATIENT_EMAIL,
    PATIENT_PASSWORD,
    TUE,
    WED,
    book,
    error_code,
    local,
    open_client,
)

NEW = "amani@example.com"


# ---- sign-up and verification -----------------------------------------------------


def test_signup_verify_then_sign_in(anon: TestClient, mailer: MemoryMailer) -> None:
    r = register(anon, NEW)
    assert r.status_code == 202
    assert mailer.outbox[-1]["Subject"] == "Confirm your email to finish signing up"
    assert mailer.outbox[-1]["To"] == NEW

    blocked = login(anon, NEW)
    assert blocked.status_code == 403
    assert error_code(blocked) == "EMAIL_NOT_VERIFIED"

    assert anon.post("/auth/verify", json={"token": last_token(mailer)}).status_code == 200
    assert mailer.outbox[-1]["Subject"] == "Your account is ready"

    r = login(anon, NEW)
    assert r.status_code == 200
    me = anon.get("/auth/me").json()
    assert me["email"] == NEW and me["role"] == "patient" and me["patient"]["full_name"]


def test_signup_does_not_reveal_existing_accounts(
    anon: TestClient, mailer: MemoryMailer, db: Session
) -> None:
    new = register(anon, NEW)
    existing = register(anon, PATIENT_EMAIL.upper())  # case-insensitive match
    assert new.status_code == existing.status_code == 202
    assert new.json() == existing.json()
    assert mailer.outbox[-1]["Subject"] == "You already have an account"
    assert db.scalar(select(func.count()).select_from(User).where(User.email == PATIENT_EMAIL)) == 1


@pytest.mark.parametrize(
    "password",
    ["short", "password123", "aaaaaaaaaaaa", "amani-secret-2030", "1234567890"],
)
def test_weak_passwords_rejected(anon: TestClient, password: str) -> None:
    r = register(anon, NEW, password=password)
    assert r.status_code == 422
    assert error_code(r) == "WEAK_PASSWORD"


def test_password_over_max_rejected_before_hashing(anon: TestClient) -> None:
    r = register(anon, NEW, password="x" * 129)
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


def test_password_kept_exactly_as_typed(anon: TestClient, mailer: MemoryMailer) -> None:
    register(anon, NEW, password="  spaced passphrase  ")
    anon.post("/auth/verify", json={"token": last_token(mailer)})
    assert login(anon, NEW, "spaced passphrase").status_code == 401
    assert login(anon, NEW, "  spaced passphrase  ").status_code == 200


def test_mass_assignment_rejected(anon: TestClient) -> None:
    r = anon.post(
        "/auth/register",
        json={
            "full_name": "Eve",
            "phone": "+254722000111",
            "email": NEW,
            "password": STRONG,
            "role": "staff",
        },
    )
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


def test_verify_token_single_use_and_expiry(
    anon: TestClient, mailer: MemoryMailer, clock: FixedClock
) -> None:
    register(anon, NEW)
    token = last_token(mailer)
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert error_code(anon.post("/auth/verify", json={"token": tampered})) == "INVALID_TOKEN"
    assert anon.post("/auth/verify", json={"token": token}).status_code == 200
    assert error_code(anon.post("/auth/verify", json={"token": token})) == "INVALID_TOKEN"

    register(anon, "late@example.com")
    clock.advance(timedelta(hours=24, minutes=1))
    assert error_code(anon.post("/auth/verify", json={"token": last_token(mailer)})) == (
        "INVALID_TOKEN"
    )


def test_resend_verification_retires_old_link(anon: TestClient, mailer: MemoryMailer) -> None:
    register(anon, NEW)
    old = last_token(mailer)
    r = anon.post("/auth/resend-verification", json={"email": NEW})
    assert r.status_code == 202
    new = last_token(mailer)
    assert new != old
    assert error_code(anon.post("/auth/verify", json={"token": old})) == "INVALID_TOKEN"
    assert anon.post("/auth/verify", json={"token": new}).status_code == 200
    # Same answer for unknown emails, and nothing is sent.
    before = len(mailer.outbox)
    r2 = anon.post("/auth/resend-verification", json={"email": "nobody@example.com"})
    assert r2.status_code == 202 and r2.json() == r.json()
    assert len(mailer.outbox) == before


def test_signup_links_existing_walk_in_patient(
    client: TestClient, anon: TestClient, mailer: MemoryMailer
) -> None:
    walk_in = client.post(
        "/patients", json={"full_name": "Walk In", "phone": "+254733000000", "email": NEW}
    ).json()["id"]
    signup_and_verify(anon, mailer, NEW)
    login(anon, NEW)
    assert anon.get("/auth/me").json()["patient"]["id"] == walk_in


# ---- sign-in ---------------------------------------------------------------------


def test_unknown_email_and_wrong_password_look_identical(anon: TestClient) -> None:
    unknown = login(anon, "nobody@example.com", "whatever password here")
    wrong = login(anon, PATIENT_EMAIL, "whatever password here")
    assert unknown.status_code == wrong.status_code == 401
    assert without_request_id(unknown.json()) == without_request_id(wrong.json())


def test_lockout_after_repeated_failures(app: FastAPI, anon: TestClient) -> None:
    t = [0.0]
    app.state.login_failures = RateLimiter(5, 900, now=lambda: t[0])
    for _ in range(5):
        assert login(anon, PATIENT_EMAIL, "wrong guess number x").status_code == 401
    locked = login(anon, PATIENT_EMAIL, PATIENT_PASSWORD)  # even the right password
    assert locked.status_code == 429
    assert error_code(locked) == "ACCOUNT_LOCKED"
    assert int(locked.headers["Retry-After"]) > 0
    # Unknown emails lock the same way, so lockout reveals nothing.
    for _ in range(5):
        login(anon, "ghost@example.com", "wrong guess number x")
    assert error_code(login(anon, "ghost@example.com", "x" * 12)) == "ACCOUNT_LOCKED"

    t[0] = 901.0
    assert login(anon, PATIENT_EMAIL, PATIENT_PASSWORD).status_code == 200


def test_auth_endpoints_are_rate_limited_per_ip(session_factory: object) -> None:
    settings = Settings(rate_limit_enabled=True, rate_limit_auth="3/minute")
    app = create_app(settings, FixedClock(NOW), MemoryMailer())
    with open_client(app) as c:
        codes = [login(c, "a@example.com", "x" * 12).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_session_cookie_flags(anon: TestClient) -> None:
    r = login(anon, PATIENT_EMAIL, PATIENT_PASSWORD)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-session=")
    lowered = cookie.lower()
    for flag in ("httponly", "secure", "samesite=strict", "path=/"):
        assert flag in lowered
    assert "domain=" not in lowered
    assert "token" not in r.json() and "access_token" not in r.json()  # never in the body


def test_sign_in_notification_email(anon: TestClient, mailer: MemoryMailer) -> None:
    anon.headers["User-Agent"] = "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile"
    login(anon, PATIENT_EMAIL, PATIENT_PASSWORD)
    sent = mailer.outbox[-1]
    assert sent["Subject"] == "New sign-in to your account"
    assert "Chrome on Android" in body_text(sent)
    assert "Mozilla" not in body_text(sent)  # coarse device only, not the raw header


def test_session_token_is_stored_hashed(anon: TestClient, db: Session) -> None:
    login(anon, PATIENT_EMAIL, PATIENT_PASSWORD)
    token = anon.cookies.get("__Host-session")
    assert token
    stored = db.scalars(select(AuthSession.token_hash)).all()
    assert hashlib.sha256(token.encode()).digest() in stored
    assert token.encode() not in stored


def test_passwords_hashed_with_argon2id(db: Session) -> None:
    hashes = db.scalars(select(User.password_hash)).all()
    assert hashes and all(h.startswith("$argon2id$") for h in hashes)


def test_bearer_token_flow(anon: TestClient) -> None:
    r = anon.post("/auth/token", json={"email": PATIENT_EMAIL, "password": PATIENT_PASSWORD})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert "set-cookie" not in r.headers
    with TestClient(anon.app, base_url="https://testserver") as api:  # no Origin, no cookie
        assert api.get("/auth/me").status_code == 401
        api.headers["Authorization"] = f"Bearer {token}"
        assert api.get("/auth/me").status_code == 200


def test_logout_revokes_the_session(patient_client: TestClient) -> None:
    token = patient_client.cookies.get("__Host-session")
    assert patient_client.post("/auth/logout").status_code == 204
    with TestClient(patient_client.app, base_url="https://testserver") as other:
        other.headers["Authorization"] = f"Bearer {token}"
        assert other.get("/auth/me").status_code == 401  # dead server-side, not just cleared


def test_garbage_tokens_rejected(anon: TestClient) -> None:
    for value in ("", "Bearer", "Bearer ", "Bearer x", "Basic Zm9vOmJhcg==", "Bearer " + "A" * 500):
        r = anon.get("/auth/me", headers={"Authorization": value})
        assert r.status_code == 401, value


# ---- session lifetime ------------------------------------------------------------


@pytest.fixture
def strict_app(app: FastAPI, clock: FixedClock) -> FastAPI:
    """Real session lifetimes (the shared fixtures use very long ones)."""
    settings = Settings(session_idle_minutes=30, session_max_hours=12)
    return create_app(settings, clock, MemoryMailer())


def test_idle_timeout(strict_app: FastAPI, clock: FixedClock) -> None:
    with open_client(strict_app, PATIENT_EMAIL, PATIENT_PASSWORD) as c:
        clock.advance(timedelta(minutes=29))
        assert c.get("/auth/me").status_code == 200  # activity extends the idle window
        clock.advance(timedelta(minutes=29))
        assert c.get("/auth/me").status_code == 200
        clock.advance(timedelta(minutes=31))
        assert c.get("/auth/me").status_code == 401


def test_absolute_timeout(strict_app: FastAPI, clock: FixedClock) -> None:
    with open_client(strict_app, PATIENT_EMAIL, PATIENT_PASSWORD) as c:
        for _ in range(12 * 3):  # stay active every 20 minutes for 12 hours
            clock.advance(timedelta(minutes=20))
            c.get("/auth/me")
        assert c.get("/auth/me").status_code == 401


# ---- password reset --------------------------------------------------------------


def test_forgot_password_does_not_reveal_accounts(anon: TestClient, mailer: MemoryMailer) -> None:
    unknown = anon.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert not mailer.outbox
    known = anon.post("/auth/forgot-password", json={"email": PATIENT_EMAIL})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert mailer.outbox[-1]["Subject"] == "Reset your password"


def test_reset_password_flow_revokes_sessions(
    patient_client: TestClient, anon: TestClient, mailer: MemoryMailer
) -> None:
    anon.post("/auth/forgot-password", json={"email": PATIENT_EMAIL})
    token = last_token(mailer)
    r = anon.post("/auth/reset-password", json={"token": token, "password": STRONG})
    assert r.status_code == 200
    assert mailer.outbox[-1]["Subject"] == "Your password was changed"
    assert patient_client.get("/auth/me").status_code == 401  # signed out everywhere
    assert login(anon, PATIENT_EMAIL, PATIENT_PASSWORD).status_code == 401
    assert login(anon, PATIENT_EMAIL, STRONG).status_code == 200
    again = anon.post("/auth/reset-password", json={"token": token, "password": STRONG + "x"})
    assert error_code(again) == "INVALID_TOKEN"


def test_reset_token_rules(anon: TestClient, mailer: MemoryMailer, clock: FixedClock) -> None:
    anon.post("/auth/forgot-password", json={"email": PATIENT_EMAIL})
    first = last_token(mailer)
    anon.post("/auth/forgot-password", json={"email": PATIENT_EMAIL})
    second = last_token(mailer)
    body = {"password": STRONG}
    assert error_code(anon.post("/auth/reset-password", json={"token": first, **body})) == (
        "INVALID_TOKEN"
    )  # superseded by the newer link
    weak = anon.post("/auth/reset-password", json={"token": second, "password": "password123"})
    assert error_code(weak) == "WEAK_PASSWORD"
    clock.advance(timedelta(minutes=31))
    assert error_code(anon.post("/auth/reset-password", json={"token": second, **body})) == (
        "INVALID_TOKEN"
    )


def test_verify_token_cannot_reset_password(anon: TestClient, mailer: MemoryMailer) -> None:
    register(anon, NEW)
    verify_token = last_token(mailer)
    r = anon.post("/auth/reset-password", json={"token": verify_token, "password": STRONG})
    assert error_code(r) == "INVALID_TOKEN"


def test_reset_verifies_an_unverified_squatted_email(
    anon: TestClient, mailer: MemoryMailer
) -> None:
    # An attacker signs up with someone else's email and never verifies it...
    register(anon, NEW, password="attacker chose this one")
    # ...the real owner resets the password from their inbox and takes the account.
    anon.post("/auth/forgot-password", json={"email": NEW})
    anon.post("/auth/reset-password", json={"token": last_token(mailer), "password": STRONG})
    assert login(anon, NEW, "attacker chose this one").status_code == 401
    assert login(anon, NEW, STRONG).status_code == 200


# ---- email content safety --------------------------------------------------------


def test_email_templates_escape_user_text(anon: TestClient, mailer: MemoryMailer) -> None:
    register(anon, NEW, name='<script>alert("x")</script> Amani')
    html = body_html(mailer.outbox[-1])
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; Amani" in html
    assert "<img" not in html  # no remote images or tracking pixels


def test_links_carry_tokens_in_the_fragment(anon: TestClient, mailer: MemoryMailer) -> None:
    register(anon, NEW)
    text = body_text(mailer.outbox[-1])
    assert "https://testserver/#/verify?token=" in text  # fragment: never sent to servers


def test_appointment_emails(client: TestClient, mailer: MemoryMailer) -> None:
    appt = book(client, local(TUE, "09:00")).json()
    assert mailer.outbox[-1]["Subject"] == "Appointment booked for Tuesday 08 January 2030, 09:00"
    client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_at": local(WED, "10:00")})
    moved = mailer.outbox[-1]
    assert moved["Subject"] == "Appointment moved to Wednesday 09 January 2030, 10:00"
    assert "Tuesday 08 January 2030, 09:00" in body_text(moved)
    client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Feeling better"})
    assert mailer.outbox[-1]["Subject"].startswith("Appointment cancelled")
    assert "Feeling better" in body_text(mailer.outbox[-1])
    assert all(m["To"] == PATIENT_EMAIL for m in mailer.outbox[-3:])
