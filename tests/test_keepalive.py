"""scripts/keepalive.py: retry, backoff and exit codes, with the HTTP call mocked."""

import pytest

from scripts import keepalive
from scripts.keepalive import Result


class FakeFetcher:
    def __init__(self, *results: Result) -> None:
        self.results = list(results)
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> Result:
        assert timeout >= 60  # must survive a cold start
        self.urls.append(url)
        return self.results.pop(0)


OK = Result(True, 200, 120)
DOWN = Result(False, None, 75000, "TimeoutError")
BAD = Result(False, 502, 300, "HTTP 502")


def _run(env: dict[str, str], fetcher: FakeFetcher, sleeps: list[float]) -> int:
    return keepalive.main(env, fetcher=fetcher, sleep=sleeps.append)


def test_no_app_url_is_a_harmless_noop(capsys: pytest.CaptureFixture[str]) -> None:
    fetcher = FakeFetcher()
    assert _run({}, fetcher, []) == 0
    assert fetcher.urls == []
    assert "APP_URL is not set" in capsys.readouterr().out


def test_success_first_try(capsys: pytest.CaptureFixture[str]) -> None:
    fetcher, sleeps = FakeFetcher(OK), []
    assert _run({"APP_URL": "https://x.example/"}, fetcher, sleeps) == 0
    assert fetcher.urls == ["https://x.example/health"]
    assert sleeps == []
    out = capsys.readouterr().out
    assert "status=200" in out and "latency_ms=120" in out


def test_retries_with_backoff_then_succeeds() -> None:
    fetcher, sleeps = FakeFetcher(DOWN, BAD, OK), []
    assert _run({"APP_URL": "https://x.example"}, fetcher, sleeps) == 0
    assert len(fetcher.urls) == 3
    assert sleeps == [5.0, 15.0]


def test_all_attempts_fail_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    fetcher, sleeps = FakeFetcher(DOWN, DOWN, BAD), []
    assert _run({"APP_URL": "https://x.example"}, fetcher, sleeps) == 1
    assert len(fetcher.urls) == 3
    assert "::error::" in capsys.readouterr().out


def test_every_third_run_also_checks_ready() -> None:
    fetcher = FakeFetcher(OK, OK)
    env = {"APP_URL": "https://x.example", "GITHUB_RUN_NUMBER": "9"}
    assert _run(env, fetcher, []) == 0
    assert fetcher.urls == ["https://x.example/health", "https://x.example/ready"]

    fetcher = FakeFetcher(OK)
    env["GITHUB_RUN_NUMBER"] = "10"
    assert _run(env, fetcher, []) == 0
    assert fetcher.urls == ["https://x.example/health"]


def test_ready_failure_fails_the_run() -> None:
    fetcher = FakeFetcher(OK, BAD, BAD, BAD)
    env = {"APP_URL": "https://x.example", "GITHUB_RUN_NUMBER": "3"}
    assert _run(env, fetcher, []) == 1


def test_fetch_rejects_non_http_schemes() -> None:
    with pytest.raises(ValueError, match="non-http"):
        keepalive.fetch("file:///etc/passwd", 1)


def test_fetch_reports_connection_errors() -> None:
    r = keepalive.fetch("http://127.0.0.1:9/health", 2)  # discard port: nothing listens
    assert not r.ok and r.status is None and r.error
