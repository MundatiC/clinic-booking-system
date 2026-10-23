"""Small in-process sliding-window rate limiter.

Used three ways: per IP on write endpoints, per IP on auth endpoints, and per
email for failed sign-ins (account lockout). State lives in this process:
fine for the single-instance deployment, but a multi-instance deployment needs
a shared store (e.g. Redis) or rate limiting at the edge. See README.
"""

import re
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.errors import RateLimitedError

_PERIODS = {"second": 1, "minute": 60, "hour": 3600}
_SPEC = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")


def parse_rate(spec: str) -> tuple[int, int]:
    """'30/minute' -> (30, 60)."""
    match = _SPEC.match(spec)
    if not match:
        raise ValueError(f"invalid rate limit {spec!r}; expected e.g. '30/minute'")
    return int(match.group(1)), _PERIODS[match.group(2)]


class RateLimiter:
    def __init__(
        self, limit: int, window_seconds: int, now: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._now = now
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def _retry_after(self, hits: deque[float], now: float) -> int:
        return max(1, int(hits[0] + self.window - now) + 1)

    def hit(self, key: str) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until a retry may succeed."""
        now = self._now()
        with self._lock:
            hits = self._live(key, now)
            if len(hits) >= self.limit:
                return self._retry_after(hits, now)
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: drop idle clients
                cutoff = now - self.window
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
            return None

    def blocked(self, key: str) -> int | None:
        """Like `hit`, but only checks: seconds to wait if the key is at its limit."""
        now = self._now()
        with self._lock:
            hits = self._live(key, now)
            return self._retry_after(hits, now) if len(hits) >= self.limit else None

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def too_many(retry_after: int, code: str = "RATE_LIMITED") -> RateLimitedError:
    return RateLimitedError(
        code,
        "Too many attempts. Please wait and try again."
        if code != "RATE_LIMITED"
        else "Too many requests. Please slow down.",
        {"retry_after_seconds": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def _per_ip(state_attr: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        limiter: RateLimiter | None = getattr(request.app.state, state_attr)
        if limiter is None:
            return
        client = request.client.host if request.client else "unknown"
        retry_after = limiter.hit(client)
        if retry_after is not None:
            raise too_many(retry_after)

    return dependency


limit_writes = _per_ip("write_limiter")  # every write endpoint
limit_auth = _per_ip("auth_limiter")  # sign-in, sign-up, password reset, verification
