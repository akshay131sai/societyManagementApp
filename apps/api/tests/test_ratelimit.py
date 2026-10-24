"""Rate limiter.

Tested directly rather than over HTTP: the rest of the suite runs with the
limiter disabled (see conftest), so this is the one place its behaviour is
pinned down.
"""

from __future__ import annotations

import pytest

from app.core.errors import RateLimitedError
from app.core.ratelimit import RateLimiter


def test_requests_under_the_limit_are_allowed() -> None:
    limiter = RateLimiter(window_seconds=60)
    for i in range(5):
        decision = limiter.check("user-a", limit=5)
        assert decision.allowed, f"request {i + 1} should be allowed"
        assert decision.remaining == 4 - i


def test_request_over_the_limit_is_refused() -> None:
    limiter = RateLimiter(window_seconds=60)
    for _ in range(3):
        assert limiter.check("user-a", limit=3).allowed

    decision = limiter.check("user-a", limit=3)
    assert not decision.allowed
    assert decision.remaining == 0
    assert decision.retry_after > 0


def test_keys_are_independent() -> None:
    """One noisy client must not consume another's budget."""
    limiter = RateLimiter(window_seconds=60)
    for _ in range(3):
        limiter.check("user-a", limit=3)

    assert not limiter.check("user-a", limit=3).allowed
    assert limiter.check("user-b", limit=3).allowed


def test_window_slides() -> None:
    limiter = RateLimiter(window_seconds=0)
    for _ in range(3):
        limiter.check("user-a", limit=3)
    # A zero-length window means every prior hit is already outside it.
    assert limiter.check("user-a", limit=3).allowed


def test_enforce_raises_with_a_retry_after() -> None:
    limiter = RateLimiter(window_seconds=60)
    limiter.enforce("user-a", limit=1)

    with pytest.raises(RateLimitedError) as exc:
        limiter.enforce("user-a", limit=1)
    assert exc.value.status_code == 429
    assert exc.value.retry_after > 0


def test_idle_keys_are_pruned() -> None:
    """Unbounded key growth would itself be a denial of service."""
    limiter = RateLimiter(window_seconds=0, max_keys=10)
    for i in range(50):
        limiter.check(f"ip-{i}", limit=100)

    limiter._maybe_prune(__import__("time").monotonic())
    assert len(limiter._hits) < 50


def test_reset_clears_all_state() -> None:
    limiter = RateLimiter(window_seconds=60)
    limiter.check("user-a", limit=1)
    limiter.reset()
    assert limiter.check("user-a", limit=1).allowed
