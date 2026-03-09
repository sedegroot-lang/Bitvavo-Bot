"""
Unit tests for core.reservation_manager module

Tests the ReservationManager for:
- Basic reserve/release operations
- Expiration of stale reservations
- Thread safety
- Statistics tracking
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.reservation_manager import ReservationManager, MarketReservation, Reservation


class TestReservation:
    """Tests for Reservation dataclass."""
    
    def test_reservation_creation(self):
        res = Reservation(
            market="BTC-EUR",
            timestamp=time.time(),
            timeout=60.0,
            reason="test",
            thread_id=1
        )
        assert res.market == "BTC-EUR"
        assert not res.is_expired()
    
    def test_reservation_expiration(self):
        res = Reservation(
            market="BTC-EUR",
            timestamp=time.time() - 100,
            timeout=60.0,
            reason="test",
            thread_id=1
        )
        assert res.is_expired()
    
    def test_reservation_remaining_time(self):
        res = Reservation(
            market="BTC-EUR",
            timestamp=time.time(),
            timeout=60.0,
            reason="test",
            thread_id=1
        )
        assert 59 < res.remaining < 61


class TestReservationManager:
    """Tests for ReservationManager."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        ReservationManager._instance = None
    
    def test_singleton(self):
        manager1 = ReservationManager()
        manager2 = ReservationManager()
        assert manager1 is manager2
    
    def test_reserve_success(self):
        manager = ReservationManager()
        assert manager.reserve("BTC-EUR", reason="test")
        assert manager.is_reserved("BTC-EUR")
        manager.release("BTC-EUR")
    
    def test_reserve_already_reserved(self):
        manager = ReservationManager()
        assert manager.reserve("BTC-EUR")
        assert not manager.reserve("BTC-EUR")  # Should fail
        manager.clear_all()
    
    def test_release(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        assert manager.release("BTC-EUR")
        assert not manager.is_reserved("BTC-EUR")
    
    def test_release_nonexistent(self):
        manager = ReservationManager()
        assert not manager.release("NONEXISTENT")
    
    def test_is_reserved(self):
        manager = ReservationManager()
        assert not manager.is_reserved("BTC-EUR")
        manager.reserve("BTC-EUR")
        assert manager.is_reserved("BTC-EUR")
        manager.clear_all()
    
    def test_reservation_expiration(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR", timeout=0.1)
        assert manager.is_reserved("BTC-EUR")
        time.sleep(0.15)
        assert not manager.is_reserved("BTC-EUR")
    
    def test_list_reserved(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        manager.reserve("ETH-EUR")
        
        reserved = manager.list_reserved()
        assert "BTC-EUR" in reserved
        assert "ETH-EUR" in reserved
        
        manager.clear_all()
    
    def test_clear_all(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        manager.reserve("ETH-EUR")
        
        count = manager.clear_all()
        assert count == 2
        assert len(manager) == 0
    
    def test_get_reservation(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR", reason="test reason")
        
        res = manager.get_reservation("BTC-EUR")
        assert res is not None
        assert res.market == "BTC-EUR"
        assert res.reason == "test reason"
        
        manager.clear_all()
    
    def test_stats(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        manager.reserve("BTC-EUR")  # Blocked
        manager.release("BTC-EUR")
        
        stats = manager.stats
        assert stats['successful'] >= 1
        assert stats['blocked'] >= 1
        assert stats['explicit_releases'] >= 1
    
    def test_contains(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        assert "BTC-EUR" in manager
        assert "ETH-EUR" not in manager
        manager.clear_all()
    
    def test_len(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        manager.reserve("ETH-EUR")
        assert len(manager) == 2
        manager.clear_all()
    
    def test_thread_safety(self):
        """Test concurrent reservations from multiple threads."""
        manager = ReservationManager()
        manager.clear_all()
        
        successful = []
        lock = threading.Lock()
        
        def worker(market):
            if manager.reserve(market, timeout=1.0):
                with lock:
                    successful.append(market)
                time.sleep(0.1)
                manager.release(market)
        
        # Multiple threads trying to reserve same market
        threads = [
            threading.Thread(target=worker, args=("BTC-EUR",))
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Only one should succeed at a time
        # (others may succeed after release, but no race conditions)
        manager.clear_all()
    
    def test_force_release(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        assert manager.force_release("BTC-EUR")
        assert not manager.is_reserved("BTC-EUR")


class TestMarketReservationContextManager:
    """Tests for MarketReservation context manager."""
    
    def setup_method(self):
        ReservationManager._instance = None
    
    def test_basic_context_manager(self):
        with MarketReservation("BTC-EUR") as reserved:
            assert reserved
            assert ReservationManager().is_reserved("BTC-EUR")
        
        assert not ReservationManager().is_reserved("BTC-EUR")
    
    def test_failed_reservation(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        
        with MarketReservation("BTC-EUR") as reserved:
            assert not reserved  # Should fail
        
        manager.clear_all()
    
    def test_exception_handling(self):
        """Reservation should be released even if exception occurs."""
        try:
            with MarketReservation("BTC-EUR") as reserved:
                assert reserved
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        assert not ReservationManager().is_reserved("BTC-EUR")


class TestNewMethods:
    """Tests for newly added methods (active_reservations, count)."""
    
    def setup_method(self):
        ReservationManager._instance = None
    
    def test_active_reservations_empty(self):
        manager = ReservationManager()
        result = manager.active_reservations()
        assert result == {}
    
    def test_active_reservations_with_items(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        manager.reserve("ETH-EUR")
        
        result = manager.active_reservations()
        assert "BTC-EUR" in result
        assert "ETH-EUR" in result
        assert len(result) == 2
        assert all(isinstance(ts, float) for ts in result.values())
        
        manager.clear_all()
    
    def test_count_empty(self):
        manager = ReservationManager()
        assert manager.count() == 0
    
    def test_count_with_items(self):
        manager = ReservationManager()
        manager.reserve("BTC-EUR")
        assert manager.count() == 1
        
        manager.reserve("ETH-EUR")
        assert manager.count() == 2
        
        manager.release("BTC-EUR")
        assert manager.count() == 1
        
        manager.clear_all()
        assert manager.count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
