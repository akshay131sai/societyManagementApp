"""In-process rate limiting.

A sliding-window counter keyed by ``firebase_uid``, falling back to client IP
for unauthenticated routes. No Redis: with a single API process a shared store
buys nothing. The limiter sits behind :class:`RateLimiter` so a shared backend
can replace it when a second instance appears.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.errors import RateLimitedError


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int


class RateLimiter:
    """Sliding-window counter with periodic pruning.

    Memory is bounded by pruning idle keys: without it, a scan over many IPs
    would grow the dict without limit, which is itself a denial-of-service.
    """

    def __init__(self, *, window_seconds: int = 60, max_keys: int = 50_000) -> None:
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune = time.monotonic()

    def check(self, key: str, limit: int) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - self.window

        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(self.window - (now - bucket[0])))
            return RateLimitDecision(False, 0, retry_after)

        bucket.append(now)
        self._maybe_prune(now)
        return RateLimitDecision(True, max(0, limit - len(bucket)), 0)

    def enforce(self, key: str, limit: int) -> RateLimitDecision:
        decision = self.check(key, limit)
        if not decision.allowed:
            raise RateLimitedError(retry_after=decision.retry_after)
        return decision

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < 30 and len(self._hits) < self.max_keys:
            return
        self._last_prune = now
        cutoff = now - self.window
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
