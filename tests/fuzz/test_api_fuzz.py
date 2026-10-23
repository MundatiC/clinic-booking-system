"""Property-based fuzzing of every operation in the OpenAPI schema (Schemathesis).

Run with `make fuzz` (marker `fuzz`; excluded from the default test run because
it is slower). Generates valid and invalid inputs for every endpoint and checks:
no 5xx, documented status codes / content types / headers / response schemas,
invalid data rejected, and more (Schemathesis' default checks).
"""

import os

import pytest
import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from schemathesis import Case
from schemathesis.checks import positive_data_acceptance

from tests.conftest import STAFF_PASSWORD

pytestmark = pytest.mark.fuzz
MAX_EXAMPLES = int(os.environ.get("FUZZ_EXAMPLES", "30"))


@pytest.fixture
def api_schema(app: FastAPI) -> schemathesis.BaseSchema:
    return schemathesis.openapi.from_asgi("/openapi.json", app)


@pytest.fixture
def staff_token(app: FastAPI) -> str:
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/auth/token", json={"email": "staff@example.com", "password": STAFF_PASSWORD})
        return str(r.json()["access_token"])


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_api_conforms_and_never_errors(case: Case, staff_token: str) -> None:
    case.call_and_validate(
        headers={"Authorization": f"Bearer {staff_token}"},
        # Schema-valid input is legitimately refused by booking rules (past, off-grid,
        # outside hours, ...) with a documented 4xx, so "valid data accepted" can't hold.
        excluded_checks=[positive_data_acceptance],
    )
