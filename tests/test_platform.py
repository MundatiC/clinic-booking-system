"""Cross-cutting behaviour: error envelope, request ids, headers, limits, probes, config."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.clock import FixedClock
from app.core.config import Settings, get_settings
from app.core.ratelimit import RateLimiter, parse_rate
from app.db.session import get_session
from app.main import create_app
from tests.utils import NOW, TUE, book, error_code, local


def _assert_envelope(body: dict[str, object]) -> None:
    assert set(body) == {"error"}
    err = body["error"]
    assert isinstance(err, dict)
    assert set(err) == {"code", "message", "details", "request_id"}
    assert isinstance(err["request_id"], str) and err["request_id"]


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("get", "/nope", 404, "NOT_FOUND"),
        ("delete", "/appointments", 405, "METHOD_NOT_ALLOWED"),
        ("get", "/doctors/abc/availability?date=2030-01-08", 422, "VALIDATION_ERROR"),
    ],
)
def test_framework_errors_use_envelope(
    client: TestClient, method: str, path: str, status: int, code: str
) -> None:
    r = client.request(method, path)
    assert r.status_code == status
    _assert_envelope(r.json())
    assert error_code(r) == code


def test_malformed_json_uses_envelope(client: TestClient) -> None:
    r = client.post(
        "/appointments", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    _assert_envelope(r.json())


def test_domain_error_envelope_and_request_id(client: TestClient) -> None:
    r = book(client, local(TUE, "09:15"))
    _assert_envelope(r.json())
    assert r.headers["X-Request-ID"] == r.json()["error"]["request_id"]


def test_incoming_request_id_is_echoed_if_safe(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    r = client.get("/health", headers={"X-Request-ID": "bad id\twith junk"})
    assert r.headers["X-Request-ID"] != "bad id\twith junk"


def test_security_headers(client: TestClient) -> None:
    r = client.get("/doctors")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in r.headers  # production only
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "Content-Security-Policy" not in docs.headers  # Swagger UI needs its CDN


def test_body_size_limit(client: TestClient) -> None:
    huge = {"reason": "x" * 20_000}
    r = client.patch("/appointments/00000000-0000-4000-8000-000000000000/cancel", json=huge)
    assert r.status_code == 413
    _assert_envelope(r.json())
    assert error_code(r) == "PAYLOAD_TOO_LARGE"


def test_unhandled_error_is_generic_500(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    _assert_envelope(r.json())
    assert error_code(r) == "INTERNAL_ERROR"
    assert "secret" not in r.text


def test_rate_limit_on_writes(session_factory: object) -> None:
    settings = Settings(rate_limit_enabled=True, rate_limit_writes="2/minute")
    with TestClient(create_app(settings, FixedClock(NOW))) as c:
        codes = [book(c, local(TUE, "09:15")).status_code for _ in range(3)]
        assert codes == [422, 422, 429]
        r = book(c, local(TUE, "09:15"))
        assert error_code(r) == "RATE_LIMITED"
        assert int(r.headers["Retry-After"]) >= 1
        # Reads and probes are not limited.
        assert c.get("/health").status_code == 200
        assert c.get("/doctors").status_code == 200


def test_rate_limiter_window_slides() -> None:
    t = [0.0]
    limiter = RateLimiter(2, 60, now=lambda: t[0])
    assert limiter.hit("ip") is None
    assert limiter.hit("ip") is None
    assert limiter.hit("ip") == 61
    assert limiter.hit("other") is None
    t[0] = 60.5
    assert limiter.hit("ip") is None


def test_parse_rate() -> None:
    assert parse_rate("30/minute") == (30, 60)
    assert parse_rate(" 5 / second ") == (5, 1)
    with pytest.raises(ValueError, match="invalid rate limit"):
        parse_rate("lots")


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_ready_503_when_db_down(app: FastAPI) -> None:
    class BrokenSession:
        def execute(self, *_: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def broken() -> Iterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken
    with TestClient(app) as c:
        r = c.get("/ready")
    assert r.status_code == 503
    assert error_code(r) == "NOT_READY"


def test_openapi_documents_error_envelope(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    post = spec["paths"]["/appointments"]["post"]
    assert {"201", "404", "409", "422", "429"} <= set(post["responses"])
    ref = post["responses"]["409"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorResponse")
    assert "/doctors/{doctor_id}/availability" in spec["paths"]


def test_settings_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins="*")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(rate_limit_writes="many")
    s = Settings(database_url="postgres://u:p@h:5432/d", cors_origins="https://a.io, https://b.io")  # type: ignore[arg-type]
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert s.cors_origins == ["https://a.io", "https://b.io"]
    assert get_settings().environment == "test"
