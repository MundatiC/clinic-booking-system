"""CSRF, CORS, injection, and what responses reveal (OWASP A03/A05, ASVS V4/V5/V14)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Doctor
from tests.utils import PATIENT_EMAIL, PATIENT_PASSWORD, TUE, book, error_code, local

EVIL = "https://evil.example"


# ---- CSRF ------------------------------------------------------------------------


def test_cookie_write_from_foreign_origin_refused(patient_client: TestClient) -> None:
    r = patient_client.post(
        "/appointments",
        json={"doctor_id": 1, "start_at": local(TUE, "09:00")},
        headers={"Origin": EVIL},
    )
    assert r.status_code == 403
    assert error_code(r) == "CSRF_FAILED"


def test_cookie_write_without_origin_or_referer_refused(patient_client: TestClient) -> None:
    del patient_client.headers["Origin"]
    r = patient_client.post("/appointments", json={"doctor_id": 1, "start_at": local(TUE, "09:00")})
    assert error_code(r) == "CSRF_FAILED"
    ok = patient_client.post(
        "/appointments",
        json={"doctor_id": 1, "start_at": local(TUE, "09:00")},
        headers={"Referer": "https://testserver/#/book"},
    )
    assert ok.status_code == 201


def test_cookie_reads_need_no_origin(patient_client: TestClient) -> None:
    del patient_client.headers["Origin"]
    assert patient_client.get("/auth/me").status_code == 200


def test_bearer_writes_need_no_origin(patient_client: TestClient) -> None:
    r = patient_client.post(
        "/auth/token", json={"email": PATIENT_EMAIL, "password": PATIENT_PASSWORD}
    )
    token = r.json()["access_token"]
    with TestClient(patient_client.app, base_url="https://testserver") as api:
        api.headers["Authorization"] = f"Bearer {token}"
        r = api.post("/appointments", json={"doctor_id": 1, "start_at": local(TUE, "09:00")})
        assert r.status_code == 201


def test_login_csrf_refused(anon: TestClient) -> None:
    r = anon.post(
        "/auth/login",
        json={"email": PATIENT_EMAIL, "password": PATIENT_PASSWORD},
        headers={"Origin": EVIL},
    )
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_cors_does_not_trust_foreign_origins(anon: TestClient) -> None:
    pre = anon.options(
        "/appointments",
        headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in pre.headers
    r = anon.get("/doctors", headers={"Origin": EVIL})
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers


# ---- injection -------------------------------------------------------------------

SQLI = ["' OR '1'='1", "1; DROP TABLE doctors; --", "1 UNION SELECT password_hash FROM users"]


@pytest.mark.parametrize("payload", SQLI)
def test_sql_injection_in_params_is_just_invalid_input(
    anon: TestClient, db: Session, payload: str
) -> None:
    assert anon.get(f"/doctors/{payload}/availability", params={"date": TUE}).status_code == 422
    assert anon.get("/doctors/1/availability", params={"date": payload}).status_code == 422
    r = anon.post("/auth/login", json={"email": payload, "password": payload})
    assert r.status_code == 422
    assert db.scalar(select(func.count()).select_from(Doctor)) == 5


@pytest.mark.parametrize("payload", [*SQLI, "<img src=x onerror=alert(1)>", "{{7*7}} ${7*7}"])
def test_hostile_text_is_stored_and_returned_inert(client: TestClient, payload: str) -> None:
    appt = book(client, local(TUE, "09:00")).json()
    r = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": payload})
    assert r.status_code == 200
    assert r.json()["cancel_reason"] == payload  # verbatim: data, never code or SQL
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    "name", ["Eve\r\nBcc: victim@example.com", "Tab\there", "Null\x00byte", "Bell\x07"]
)
def test_control_characters_rejected_in_names(anon: TestClient, name: str) -> None:
    r = anon.post(
        "/auth/register",
        json={
            "full_name": name,
            "phone": "+254722000111",
            "email": "e@example.com",
            "password": "plum jacaranda morning walk",
        },
    )
    assert r.status_code == 422


def test_json_only(patient_client: TestClient) -> None:
    r = patient_client.post(
        "/auth/login",
        content=f"email={PATIENT_EMAIL}&password={PATIENT_PASSWORD}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 422  # HTML forms cannot drive the API


# ---- information exposure --------------------------------------------------------


def test_errors_never_echo_secrets(anon: TestClient) -> None:
    r = anon.post("/auth/login", json={"email": "x", "password": "my secret value"})
    assert "my secret value" not in r.text


def test_openapi_documents_auth_errors(anon: TestClient) -> None:
    spec = anon.get("/openapi.json").json()
    assert {"401", "403"} <= set(spec["paths"]["/appointments"]["post"]["responses"])


def test_openapi_offers_bearer_auth_on_protected_routes(anon: TestClient) -> None:
    spec = anon.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert spec["paths"]["/appointments"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in spec["paths"]["/doctors"]["get"]
