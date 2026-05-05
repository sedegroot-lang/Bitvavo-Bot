"""
API Rate Limiter Service with Adaptive Throttling
==================================================
Professional rate limiting for Bitvavo API with:
- Token bucket algorithm for smooth rate limiting
- Adaptive backoff on 429 errors
- Circuit breaker pattern for API protection
- Request prioritization (orders > data)
- Metrics tracking and alerting

Author: AI Trading Bot
Version: 1.0.0
"""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Request priority levels for queue management."""

    CRITICAL = 0  # Emergency sells, stop-loss
    HIGH = 1  # Regular orders, position management
    NORMAL = 2  # Price checks, balance queries
    LOW = 3  # Historical data, analytics
    BACKGROUND = 4  # Non-essential, can be delayed


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class RateLimitMetrics:
    """Metrics for rate limiting monitoring."""

    total_requests: int = 0
    successful_requests: int = 0
    rate_limited_requests: int = 0
    circuit_breaker_blocks: int = 0
    avg_response_time_ms: float = 0.0
    last_429_error: Optional[float] = None
    consecutive_429s: int = 0
    backoff_multiplier: float = 1.0
    tokens_available: float = 0.0
    requests_per_minute: float = 0.0
    _response_times: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_request(self, success: bool, response_time_ms: float):
        """Record a request for metrics."""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
            self.consecutive_429s = 0
        else:
            self.rate_limited_requests += 1
            self.consecutive_429s += 1
            self.last_429_error = time.time()

        self._response_times.append(response_time_ms)
        if self._response_times:
            self.avg_response_time_ms = sum(self._response_times) / len(self._response_times)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "rate_limited_requests": self.rate_limited_requests,
            "circuit_breaker_blocks": self.circuit_breaker_blocks,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "last_429_error": self.last_429_error,
            "consecutive_429s": self.consecutive_429s,
            "backoff_multiplier": round(self.backoff_multiplier, 2),
            "tokens_available": round(self.tokens_available, 2),
            "success_rate": round(self.successful_requests / max(1, self.total_requests) * 100, 2),
        }


class TokenBucket:
    """Token bucket algorithm for smooth rate limiting."""

    def __init__(self, capacity: float, refill_rate: float):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def consume(self, tokens: float = 1.0, wait: bool = True, timeout: float = 30.0) -> bool:
        """
        Try to consume tokens from bucket.

        Args:
            tokens: Number of tokens to consume
            wait: Whether to wait for tokens if not available
            timeout: Maximum time to wait for tokens

        Returns:
            True if tokens consumed, False otherwise
        """
        with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            if not wait:
                return False

            # Calculate wait time
            tokens_needed = tokens - self.tokens
            wait_time = tokens_needed / self.refill_rate

            if wait_time > timeout:
                return False

        # Wait outside lock
        time.sleep(min(wait_time, timeout))

        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def available(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self.tokens


class CircuitBreaker:
    """Circuit breaker to protect API from cascading failures."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, half_open_max_calls: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0
        self._lock = threading.Lock()

    def can_proceed(self) -> bool:
        """Check if request can proceed through circuit breaker."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("[CIRCUIT_BREAKER] Transitioning to HALF_OPEN state")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False

            return False

    def record_success(self):
        """Record a successful request."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                # Success in half-open -> close circuit
                self.state = CircuitState.CLOSED
                logger.info("[CIRCUIT_BREAKER] Circuit CLOSED after successful recovery")

            self.failure_count = 0

    def record_failure(self):
        """Record a failed request (429 or error)."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # Failure in half-open -> open circuit again
                self.state = CircuitState.OPEN
                logger.warning("[CIRCUIT_BREAKER] Circuit OPENED again after failure in half-open")
                return

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"[CIRCUIT_BREAKER] Circuit OPENED after {self.failure_count} failures")


class APIRateLimiter:
    """
    Advanced API Rate Limiter with adaptive throttling.

    Features:
    - Token bucket rate limiting
    - Adaptive backoff on errors
    - Circuit breaker protection
    - Request prioritization
    - Metrics tracking
    """

    # Bitvavo API limits (approximate)
    DEFAULT_CALLS_PER_SECOND = 10
    DEFAULT_BURST_CAPACITY = 20

    def __init__(
        self,
        calls_per_second: float = None,
        burst_capacity: float = None,
        enable_adaptive: bool = True,
        metrics_path: str = None,
    ):
        """
        Initialize rate limiter.

        Args:
            calls_per_second: Target requests per second
            burst_capacity: Maximum burst capacity
            enable_adaptive: Enable adaptive backoff
            metrics_path: Path to save metrics
        """
        self.calls_per_second = calls_per_second or self.DEFAULT_CALLS_PER_SECOND
        self.burst_capacity = burst_capacity or self.DEFAULT_BURST_CAPACITY
        self.enable_adaptive = enable_adaptive
        self.metrics_path = Path(metrics_path) if metrics_path else None

        # Token bucket for rate limiting
        self.bucket = TokenBucket(capacity=self.burst_capacity, refill_rate=self.calls_per_second)

        # Circuit breaker for protection
        self.circuit = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, half_open_max_calls=3)

        # Metrics
        self.metrics = RateLimitMetrics()

        # Adaptive backoff state
        self._backoff_until = 0.0
        self._current_backoff = 1.0
        self._max_backoff = 60.0
        self._backoff_lock = threading.Lock()

        # Request tracking
        self._request_times = deque(maxlen=60)  # Track last minute
        self._lock = threading.Lock()

        logger.info(f"[RATE_LIMITER] Initialized: {calls_per_second}/s, burst={burst_capacity}")

    def acquire(
        self, priority: RequestPriority = RequestPriority.NORMAL, cost: float = 1.0, timeout: float = 30.0
    ) -> bool:
        """
        Acquire permission to make an API request.

        Args:
            priority: Request priority level
            cost: Token cost for this request
            timeout: Maximum time to wait

        Returns:
            True if request can proceed, False otherwise
        """
        start_time = time.time()

        # Check circuit breaker first
        if not self.circuit.can_proceed():
            self.metrics.circuit_breaker_blocks += 1
            logger.warning("[RATE_LIMITER] Request blocked by circuit breaker")
            return False

        # Check adaptive backoff
        with self._backoff_lock:
            if time.time() < self._backoff_until:
                wait_time = self._backoff_until - time.time()
                if wait_time > timeout:
                    logger.debug(f"[RATE_LIMITER] Backoff active, {wait_time:.1f}s remaining")
                    return False
                logger.debug(f"[RATE_LIMITER] Waiting {wait_time:.1f}s for backoff")
                time.sleep(wait_time)

        # Adjust cost based on priority (critical requests get through faster)
        adjusted_cost = cost
        if priority == RequestPriority.CRITICAL:
            adjusted_cost = cost * 0.5  # Half cost for critical
        elif priority == RequestPriority.LOW:
            adjusted_cost = cost * 1.5  # Higher cost for low priority
        elif priority == RequestPriority.BACKGROUND:
            adjusted_cost = cost * 2.0  # Double cost for background

        # Try to consume tokens
        remaining_timeout = max(0, timeout - (time.time() - start_time))
        wait = priority in [RequestPriority.CRITICAL, RequestPriority.HIGH]

        if not self.bucket.consume(adjusted_cost, wait=wait, timeout=remaining_timeout):
            logger.debug("[RATE_LIMITER] Token bucket exhausted")
            return False

        # Track request for metrics
        with self._lock:
            self._request_times.append(time.time())
            self.metrics.tokens_available = self.bucket.available()

            # Calculate requests per minute
            now = time.time()
            recent = [t for t in self._request_times if now - t < 60]
            self.metrics.requests_per_minute = len(recent)

        return True

    def record_response(self, success: bool, response_time_ms: float = 0.0, status_code: int = 200):
        """
        Record an API response for adaptive rate limiting.

        Args:
            success: Whether request was successful
            response_time_ms: Response time in milliseconds
            status_code: HTTP status code
        """
        is_rate_limited = status_code == 429

        self.metrics.record_request(not is_rate_limited, response_time_ms)

        if is_rate_limited:
            self.circuit.record_failure()
            self._apply_backoff()
        elif success:
            self.circuit.record_success()
            self._reduce_backoff()

        self.metrics.backoff_multiplier = self._current_backoff

        # Save metrics periodically
        if self.metrics_path and self.metrics.total_requests % 100 == 0:
            self._save_metrics()

    def _apply_backoff(self):
        """Apply exponential backoff after rate limit hit."""
        if not self.enable_adaptive:
            return

        with self._backoff_lock:
            self._current_backoff = min(self._current_backoff * 2, self._max_backoff)
            self._backoff_until = time.time() + self._current_backoff
            logger.warning(f"[RATE_LIMITER] Backoff applied: {self._current_backoff:.1f}s")

    def _reduce_backoff(self):
        """Gradually reduce backoff after successful requests."""
        with self._backoff_lock:
            if self._current_backoff > 1.0:
                self._current_backoff = max(1.0, self._current_backoff * 0.9)

    def _save_metrics(self):
        """Save metrics to file."""
        try:
            if self.metrics_path:
                self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.metrics_path, "w") as f:
                    json.dump(self.metrics.to_dict(), f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save metrics: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status."""
        return {
            "circuit_state": self.circuit.state.value,
            "tokens_available": round(self.bucket.available(), 2),
            "backoff_active": time.time() < self._backoff_until,
            "backoff_remaining": max(0, self._backoff_until - time.time()),
            "metrics": self.metrics.to_dict(),
        }

    def reset(self):
        """Reset rate limiter state."""
        with self._lock:
            self.bucket.tokens = self.bucket.capacity
            self._current_backoff = 1.0
            self._backoff_until = 0.0
            self.circuit.state = CircuitState.CLOSED
            self.circuit.failure_count = 0
            logger.info("[RATE_LIMITER] State reset")


# Decorator for rate-limited API calls
def rate_limited(
    limiter: APIRateLimiter, priority: RequestPriority = RequestPriority.NORMAL, cost: float = 1.0, max_retries: int = 3
):
    """
    Decorator to add rate limiting to API calls.

    Args:
        limiter: APIRateLimiter instance
        priority: Request priority
        cost: Token cost
        max_retries: Maximum retry attempts
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                # Acquire rate limit permission
                if not limiter.acquire(priority=priority, cost=cost):
                    if attempt < max_retries - 1:
                        time.sleep(1.0)
                        continue
                    raise Exception("Rate limit exceeded, unable to acquire permission")

                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    response_time = (time.time() - start_time) * 1000

                    # Check for rate limit error in response
                    if isinstance(result, dict):
                        error_code = result.get("errorCode", 0)
                        if error_code == 429:
                            limiter.record_response(False, response_time, 429)
                            if attempt < max_retries - 1:
                                time.sleep(2**attempt)
                                continue
                            return result

                    limiter.record_response(True, response_time, 200)
                    return result

                except Exception as e:
                    response_time = (time.time() - start_time) * 1000
                    error_msg = str(e).lower()

                    if "429" in error_msg or "rate limit" in error_msg:
                        limiter.record_response(False, response_time, 429)
                    else:
                        limiter.record_response(False, response_time, 500)

                    if attempt < max_retries - 1:
                        time.sleep(2**attempt)
                        continue
                    raise

            return None

        return wrapper

    return decorator


# Global instance
_global_limiter: Optional[APIRateLimiter] = None
_limiter_lock = threading.Lock()


def get_rate_limiter(
    calls_per_second: float = None, burst_capacity: float = None, metrics_path: str = None
) -> APIRateLimiter:
    """
    Get or create global rate limiter instance.

    Args:
        calls_per_second: Target rate
        burst_capacity: Burst capacity
        metrics_path: Path for metrics file

    Returns:
        APIRateLimiter instance
    """
    global _global_limiter

    with _limiter_lock:
        if _global_limiter is None:
            _global_limiter = APIRateLimiter(
                calls_per_second=calls_per_second or 10,
                burst_capacity=burst_capacity or 20,
                metrics_path=metrics_path or "data/api_rate_metrics.json",
            )
        return _global_limiter


# Convenience wrapper for API calls
def safe_api_call(func: Callable, *args, priority: RequestPriority = RequestPriority.NORMAL, **kwargs) -> Any:
    """
    Make a rate-limited API call.

    Args:
        func: API function to call
        *args: Positional arguments
        priority: Request priority
        **kwargs: Keyword arguments

    Returns:
        API response or None on failure
    """
    limiter = get_rate_limiter()

    if not limiter.acquire(priority=priority):
        logger.warning(f"[RATE_LIMITER] Unable to acquire permission for {func.__name__}")
        return None

    start_time = time.time()
    try:
        result = func(*args, **kwargs)
        response_time = (time.time() - start_time) * 1000

        # Check for error in response
        if isinstance(result, dict):
            error_code = result.get("errorCode", 0)
            if error_code == 429:
                limiter.record_response(False, response_time, 429)
                return result

        limiter.record_response(True, response_time, 200)
        return result

    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        limiter.record_response(False, response_time, 500)
        logger.error(f"[RATE_LIMITER] API call failed: {e}")
        raise


if __name__ == "__main__":
    # Test the rate limiter
    limiter = get_rate_limiter()

    print("Testing rate limiter...")

    for i in range(25):
        acquired = limiter.acquire(priority=RequestPriority.NORMAL)
        print(f"Request {i + 1}: {'✓' if acquired else '✗'} | Tokens: {limiter.bucket.available():.2f}")

        if acquired:
            limiter.record_response(True, 50.0)

        time.sleep(0.05)

    print("\nStatus:", json.dumps(limiter.get_status(), indent=2))
