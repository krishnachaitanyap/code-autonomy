"""
Resiliency primitives for LLM API calls.

CircuitBreaker: prevents hammering a down API by failing fast after repeated failures.
TokenBucketRateLimiter: proactive rate limiting to avoid 429s.

Both are thread-safe and zero-dependency (stdlib only).
"""

import enum
import threading
import time
from dataclasses import dataclass, field


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and calls are rejected."""

    def __init__(self, failures: int, opens_at: float):
        remaining = max(0.0, opens_at - time.monotonic())
        super().__init__(
            f"Circuit breaker is OPEN after {failures} failures. "
            f"Retry in {remaining:.1f}s."
        )
        self.failures = failures
        self.opens_at = opens_at


@dataclass
class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    CLOSED  -> normal operation; failures are counted.
    OPEN    -> all calls rejected immediately (fail-fast).
    HALF_OPEN -> one probe call allowed; success closes, failure re-opens.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0

    # Internal state — not part of __init__ signature for callers
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _failure_count: int = field(default=0, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def ensure_closed(self) -> None:
        """Raise CircuitOpenError if OPEN; allow probe if HALF_OPEN."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self.recovery_timeout:
                    raise CircuitOpenError(
                        self._failure_count,
                        self._opened_at + self.recovery_timeout,
                    )
                # Transition to HALF_OPEN — allow one probe
                self._state = CircuitState.HALF_OPEN
            # CLOSED or HALF_OPEN: allow the call

    def record_success(self) -> None:
        """Reset failure count and close the circuit."""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Increment failure count; open circuit at threshold."""
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Manual reset to closed state."""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = 0.0


@dataclass
class TokenBucketRateLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Starts full (max_tokens). Tokens are consumed by acquire() and refilled
    at refill_rate tokens/second.
    """

    max_tokens: float = 10.0
    refill_rate: float = 1.0  # tokens per second

    _tokens: float = field(default=-1.0, init=False, repr=False)  # -1 = lazy init
    _last_refill: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _refill(self) -> None:
        """Add tokens based on elapsed time. Must be called under lock."""
        now = time.monotonic()
        if self._tokens < 0:
            # Lazy init: start full
            self._tokens = self.max_tokens
            self._last_refill = now
            return
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now

    def acquire(self, timeout: float | None = None) -> None:
        """
        Block until a token is available, then consume it.

        Args:
            timeout: Max seconds to wait. None = wait forever.

        Raises:
            TimeoutError: If timeout expires before a token is available.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # No token available — sleep briefly and retry
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Rate limiter: no token available within {timeout}s"
                )
            time.sleep(0.1)

    @property
    def available_tokens(self) -> float:
        """Current token count (for monitoring)."""
        with self._lock:
            self._refill()
            return self._tokens if self._tokens >= 0 else self.max_tokens
