"""Small in-process sliding-window rate limiter for write endpoints.

Per client IP, shared across all write endpoints. State lives in this process:
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

    def hit(self, key: str) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until a retry may succeed."""
        now = self._now()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.window - now) + 1)
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: drop idle clients
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
            return None


def limit_writes(request: Request) -> None:
    """FastAPI dependency applied to every write endpoint."""
    limiter: RateLimiter | None = request.app.state.write_limiter
    if limiter is None:
        return
    client = request.client.host if request.client else "unknown"
    retry_after = limiter.hit(client)
    if retry_after is not None:
        raise RateLimitedError(
            "RATE_LIMITED",
            "Too many requests. Please slow down.",
            {"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
