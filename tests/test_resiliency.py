"""Tests for src/resiliency.py — CircuitBreaker and TokenBucketRateLimiter."""

import threading
import time
from unittest.mock import patch

import pytest

from src.resiliency import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    TokenBucketRateLimiter,
)


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreakerInit:
    def test_default_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_default_failure_count_is_zero(self):
        cb = CircuitBreaker()
        assert cb.failure_count == 0

    def test_custom_thresholds(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30.0


class TestCircuitBreakerStateTransitions:
    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 2

    def test_failures_at_threshold_open_circuit(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_success_resets_failures_and_closes(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerEnsureClosed:
    def test_closed_does_not_raise(self):
        cb = CircuitBreaker()
        cb.ensure_closed()  # Should not raise

    def test_open_raises_circuit_open_error(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.ensure_closed()
        assert exc_info.value.failures == 1

    def test_open_after_timeout_transitions_and_allows(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.ensure_closed()  # Should not raise — transitions to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_probe(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        _ = cb.state  # Trigger transition to HALF_OPEN
        cb.ensure_closed()  # Should not raise


class TestCircuitBreakerReset:
    def test_reset_from_open(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerThreadSafety:
    def test_concurrent_failures(self):
        cb = CircuitBreaker(failure_threshold=100)
        errors = []

        def fail_many():
            try:
                for _ in range(50):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fail_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb.failure_count == 200  # 4 threads * 50


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter
# ---------------------------------------------------------------------------

class TestTokenBucketInit:
    def test_starts_full_on_first_access(self):
        rl = TokenBucketRateLimiter(max_tokens=5)
        assert rl.available_tokens == 5.0

    def test_custom_params(self):
        rl = TokenBucketRateLimiter(max_tokens=20.0, refill_rate=2.0)
        assert rl.max_tokens == 20.0
        assert rl.refill_rate == 2.0


class TestTokenBucketAcquire:
    def test_acquire_consumes_token(self):
        rl = TokenBucketRateLimiter(max_tokens=3, refill_rate=0.0)
        rl.acquire()
        assert rl.available_tokens < 3.0

    def test_exhaust_all_tokens(self):
        rl = TokenBucketRateLimiter(max_tokens=3, refill_rate=0.0)
        rl.acquire()
        rl.acquire()
        rl.acquire()
        # Next acquire should block/timeout
        with pytest.raises(TimeoutError):
            rl.acquire(timeout=0.2)

    def test_refill_allows_new_acquire(self):
        rl = TokenBucketRateLimiter(max_tokens=1, refill_rate=20.0)
        rl.acquire()
        # At refill_rate=20/s, should get a token within 0.1s
        rl.acquire(timeout=0.5)  # Should not raise

    def test_never_exceeds_max_tokens(self):
        rl = TokenBucketRateLimiter(max_tokens=5, refill_rate=100.0)
        time.sleep(0.1)  # Let refill accumulate
        assert rl.available_tokens <= 5.0

    def test_timeout_raises(self):
        rl = TokenBucketRateLimiter(max_tokens=1, refill_rate=0.0)
        rl.acquire()
        with pytest.raises(TimeoutError):
            rl.acquire(timeout=0.15)


class TestTokenBucketThreadSafety:
    def test_concurrent_acquires(self):
        rl = TokenBucketRateLimiter(max_tokens=100, refill_rate=0.0)
        acquired = []
        lock = threading.Lock()

        def acquire_many():
            count = 0
            for _ in range(25):
                try:
                    rl.acquire(timeout=1.0)
                    count += 1
                except TimeoutError:
                    break
            with lock:
                acquired.append(count)

        threads = [threading.Thread(target=acquire_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(acquired)
        assert total == 100  # Exactly max_tokens consumed
