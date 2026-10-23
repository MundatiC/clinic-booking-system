"""Post-deploy smoke test (standard library only).

Waits until the public /health reports the expected commit (so we test the new
release, not the old one still serving during the deploy), then checks /ready
and that the seeded doctors are listed. Exits non-zero on failure.

Usage: python scripts/smoke.py --url https://... --expect-version <git sha> [--timeout 900]
"""

import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urlsplit

USER_AGENT = "clinic-booking-smoke/1.0"


def get_json(url: str, timeout: float = 60.0) -> tuple[int, object]:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    # Scheme validated above. nosec B310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        return int(resp.status), json.loads(resp.read().decode())


def wait_for_version(base: str, expected: str, timeout: float, interval: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = get_json(f"{base}/health")
            version = body.get("version", "") if isinstance(body, dict) else ""
            print(f"smoke /health status={status} version={version}", flush=True)
            if status == 200 and expected and str(version).startswith(expected[:12]):
                return True
            if status == 200 and not expected:
                return True
        except Exception as exc:
            print(f"smoke /health not yet: {type(exc).__name__}", flush=True)
        time.sleep(interval)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--expect-version", default="")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")

    if not wait_for_version(base, args.expect_version, args.timeout):
        print(f"::error::{base} did not report version {args.expect_version!r} in time")
        return 1
    status, _ = get_json(f"{base}/ready")
    if status != 200:
        print(f"::error::/ready returned {status}")
        return 1
    status, doctors = get_json(f"{base}/doctors")
    if status != 200 or not isinstance(doctors, list) or len(doctors) < 1:
        print(f"::error::/doctors unexpected: status={status}")
        return 1
    print(f"smoke OK: version live, /ready 200, {len(doctors)} doctors listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
