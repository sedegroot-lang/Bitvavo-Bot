"""
Thread-safe Market Reservation Manager

This module provides atomic operations for reserving markets during trade execution.
It prevents race conditions when multiple threads try to open trades on the same market.

Features:
- Atomic reserve/release operations
- Automatic expiration of stale reservations
- Detailed logging of reservation state
- Concurrency-safe design

Usage:
    from core.reservation_manager import ReservationManager

    manager = ReservationManager(default_timeout=60.0)

    # Try to reserve a market
    if manager.reserve('BTC-EUR', reason='Opening new trade'):
        try:
            execute_trade('BTC-EUR')
        finally:
            manager.release('BTC-EUR')
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Reservation:
    """Details of a market reservation."""

    market: str
    timestamp: float
    timeout: float
    reason: str
    thread_id: int

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check if this reservation has expired."""
        now = now or time.time()
        return (now - self.timestamp) > self.timeout

    @property
    def age(self) -> float:
        """Age of reservation in seconds."""
        return time.time() - self.timestamp

    @property
    def remaining(self) -> float:
        """Remaining time before expiration."""
        return max(0.0, self.timeout - self.age)


class ReservationManager:
    """
    Thread-safe manager for market reservations.

    Prevents race conditions when multiple threads attempt to trade
    the same market simultaneously.

    Args:
        default_timeout: Default reservation timeout in seconds
        cleanup_interval: How often to check for expired reservations
        log_level: Logging level for reservation events
    """

    _instance: Optional["ReservationManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for global access."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, default_timeout: float = 60.0, cleanup_interval: float = 30.0, log_level: str = "debug"):
        if hasattr(self, "_initialized"):
            return

        self._default_timeout = max(1.0, default_timeout)
        self._cleanup_interval = max(1.0, cleanup_interval)
        self._log_level = log_level.lower()

        self._reservations: Dict[str, Reservation] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()

        # Statistics
        self._total_reservations = 0
        self._successful_reservations = 0
        self._blocked_reservations = 0
        self._expired_reservations = 0
        self._explicit_releases = 0

        self._initialized = True

    def _log(self, message: str, level: Optional[str] = None) -> None:
        """Log a message at the configured level."""
        level = level or self._log_level
        log_func = getattr(logger, level, logger.debug)
        log_func(message)

    def _cleanup_expired(self) -> int:
        """Remove expired reservations. Must be called with lock held."""
        now = time.time()
        expired = [market for market, res in self._reservations.items() if res.is_expired(now)]
        for market in expired:
            res = self._reservations.pop(market, None)
            if res:
                self._expired_reservations += 1
                self._log(f"Reservation expired: {market} (age={res.age:.1f}s, reason={res.reason})", level="warning")
        return len(expired)

    def _maybe_cleanup(self) -> None:
        """Periodically cleanup expired reservations."""
        now = time.time()
        if (now - self._last_cleanup) < self._cleanup_interval:
            return
        self._cleanup_expired()
        self._last_cleanup = now

    def reserve(self, market: str, timeout: Optional[float] = None, reason: str = "") -> bool:
        """
        Attempt to reserve a market.

        Args:
            market: Market identifier (e.g., 'BTC-EUR')
            timeout: Reservation timeout in seconds (None = use default)
            reason: Reason for reservation (for logging)

        Returns:
            True if reservation was successful, False if market already reserved
        """
        timeout = timeout if timeout is not None else self._default_timeout
        thread_id = threading.current_thread().ident or 0
        now = time.time()

        with self._lock:
            self._total_reservations += 1
            self._maybe_cleanup()

            existing = self._reservations.get(market)

            # Check if there's an existing non-expired reservation
            if existing and not existing.is_expired(now):
                self._blocked_reservations += 1
                self._log(
                    f"Reservation blocked: {market} already reserved by thread {existing.thread_id} "
                    f"(age={existing.age:.1f}s, remaining={existing.remaining:.1f}s, reason={existing.reason})"
                )
                return False

            # Create new reservation
            self._reservations[market] = Reservation(
                market=market, timestamp=now, timeout=timeout, reason=reason, thread_id=thread_id
            )
            self._successful_reservations += 1
            self._log(f"Market reserved: {market} (timeout={timeout}s, reason={reason})")
            return True

    def release(self, market: str) -> bool:
        """
        Release a market reservation.

        Args:
            market: Market identifier

        Returns:
            True if reservation was released, False if not found
        """
        with self._lock:
            res = self._reservations.pop(market, None)
            if res:
                self._explicit_releases += 1
                self._log(f"Market released: {market} (held for {res.age:.1f}s)")
                return True
            return False

    def is_reserved(self, market: str) -> bool:
        """
        Check if a market is currently reserved.

        Args:
            market: Market identifier

        Returns:
            True if market has active (non-expired) reservation
        """
        with self._lock:
            self._maybe_cleanup()
            res = self._reservations.get(market)
            if res and not res.is_expired():
                return True
            return False

    def get_reservation(self, market: str) -> Optional[Reservation]:
        """
        Get details of a market's reservation.

        Returns:
            Reservation object or None if not reserved
        """
        with self._lock:
            res = self._reservations.get(market)
            if res and not res.is_expired():
                return res
            return None

    def list_reserved(self) -> List[str]:
        """
        Get list of all reserved markets.

        Returns:
            List of market identifiers with active reservations
        """
        with self._lock:
            self._cleanup_expired()
            return list(self._reservations.keys())

    def active_reservations(self) -> Dict[str, float]:
        """
        Get dict of active reservations with their timestamps.

        Returns:
            Dict mapping market to reservation timestamp
        """
        with self._lock:
            self._cleanup_expired()
            return {market: res.timestamp for market, res in self._reservations.items()}

    def count(self) -> int:
        """
        Get count of active reservations.

        Returns:
            Number of active reservations
        """
        with self._lock:
            self._cleanup_expired()
            return len(self._reservations)

    def clear_all(self) -> int:
        """
        Clear all reservations.

        Returns:
            Number of reservations cleared
        """
        with self._lock:
            count = len(self._reservations)
            self._reservations.clear()
            self._log(f"Cleared all {count} reservations", level="info")
            return count

    def force_release(self, market: str) -> bool:
        """
        Force release a reservation, even if held by another thread.
        Use with caution - primarily for cleanup/shutdown.

        Args:
            market: Market identifier

        Returns:
            True if reservation was released
        """
        with self._lock:
            res = self._reservations.pop(market, None)
            if res:
                self._log(f"Force released: {market} (was held by thread {res.thread_id})", level="warning")
                return True
            return False

    @property
    def stats(self) -> Dict[str, any]:
        """Get reservation statistics."""
        with self._lock:
            return {
                "active_reservations": len(self._reservations),
                "total_attempts": self._total_reservations,
                "successful": self._successful_reservations,
                "blocked": self._blocked_reservations,
                "expired": self._expired_reservations,
                "explicit_releases": self._explicit_releases,
                "success_rate": (
                    self._successful_reservations / self._total_reservations * 100
                    if self._total_reservations > 0
                    else 100.0
                ),
            }

    def __len__(self) -> int:
        """Number of active reservations."""
        with self._lock:
            return len(self._reservations)

    def __contains__(self, market: str) -> bool:
        """Check if market is reserved."""
        return self.is_reserved(market)


# Context manager for automatic reservation handling
class MarketReservation:
    """
    Context manager for market reservation.

    Usage:
        with MarketReservation('BTC-EUR', timeout=30.0) as reserved:
            if reserved:
                execute_trade('BTC-EUR')
    """

    def __init__(self, market: str, timeout: Optional[float] = None, reason: str = ""):
        self.market = market
        self.timeout = timeout
        self.reason = reason
        self._manager = ReservationManager()
        self._reserved = False

    def __enter__(self) -> bool:
        self._reserved = self._manager.reserve(self.market, timeout=self.timeout, reason=self.reason)
        return self._reserved

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._reserved:
            self._manager.release(self.market)
        return False  # Don't suppress exceptions
