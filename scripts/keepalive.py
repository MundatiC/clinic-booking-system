"""Keep the free Render instance warm by pinging it from outside (GitHub Actions cron).

Standard library only. Behaviour:
- APP_URL unset      -> notice, exit 0 (harmless before the first deploy)
- GET {APP_URL}/health with a long timeout (cold starts can take ~a minute),
  up to 3 attempts with backoff; one log line per attempt
- every Nth run (KEEPALIVE_READY_EVERY, default 3; uses GITHUB_RUN_NUMBER) also
  GET /ready to keep a DB connection warm
- exit 1 if a check fails on every attempt, so the failure shows in Actions
"""

import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

TIMEOUT_SECONDS = 75.0
BACKOFF_SECONDS = (5.0, 15.0)  # waits between attempts 1->2 and 2->3
USER_AGENT = "clinic-booking-keepalive/1.0"


@dataclass
class Result:
    ok: bool
    status: int | None
    latency_ms: int
    error: str | None = None


Fetch = Callable[[str, float], Result]


def fetch(url: str, timeout: float) -> Result:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    started = time.monotonic()
    try:
        # Scheme validated above. nosec B310
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310  # nosec B310
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        return Result(False, exc.code, _ms(started), f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Result(False, None, _ms(started), type(exc).__name__)
    return Result(200 <= status < 300, status, _ms(started))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def check(
    base_url: str,
    path: str,
    *,
    fetcher: Fetch = fetch,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> bool:
    url = base_url.rstrip("/") + path
    for attempt in range(1, attempts + 1):
        r = fetcher(url, TIMEOUT_SECONDS)
        print(
            f"keepalive path={path} attempt={attempt}/{attempts} ok={r.ok} "
            f"status={r.status} latency_ms={r.latency_ms}"
            + (f" error={r.error}" if r.error else ""),
            flush=True,
        )
        if r.ok:
            return True
        if attempt < attempts:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
    return False


def should_check_ready(env: dict[str, str]) -> bool:
    every = int(env.get("KEEPALIVE_READY_EVERY", "3") or 0)
    run = env.get("GITHUB_RUN_NUMBER", "")
    return every > 0 and run.isdigit() and int(run) % every == 0


def main(
    env: dict[str, str] | None = None,
    fetcher: Fetch = fetch,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    env = dict(os.environ) if env is None else env
    base_url = env.get("APP_URL", "").strip()
    if not base_url:
        print("::notice::APP_URL is not set; nothing to ping (set the repo variable after deploy).")
        return 0

    paths = ["/health"] + (["/ready"] if should_check_ready(env) else [])
    ok = all(check(base_url, p, fetcher=fetcher, sleep=sleep) for p in paths)
    if not ok:
        print("::error::keep-alive ping failed on every attempt")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
