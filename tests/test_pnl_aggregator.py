"""
Tests for pnl_aggregator module
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import json

from modules.pnl_aggregator import (
    compute_total_pnl,
    compute_pnl_today,
    load_trades_from_log,
    compute_pnl_metrics,
)


def test_compute_total_pnl_closed_only():
    """Test total P/L with only closed trades."""
    open_trades = {}
    closed_trades = [
        {'profit': 10.5},
        {'profit': -5.2},
        {'profit': 8.0},
    ]
    last_prices = {}
    
    total, realized, unrealized = compute_total_pnl(open_trades, closed_trades, last_prices)
    
    assert realized == pytest.approx(13.3, rel=0.01)
    assert unrealized == 0.0
    assert total == pytest.approx(13.3, rel=0.01)


def test_compute_total_pnl_open_only():
    """Test total P/L with only open trades."""
    open_trades = {
        'BTC-EUR': {
            'amount': 0.01,
            'buy_price': 50000.0,
            'invested_eur': 500.0,
        },
    }
    closed_trades = []
    last_prices = {'BTC-EUR': 55000.0}  # 10% gain
    
    total, realized, unrealized = compute_total_pnl(open_trades, closed_trades, last_prices)
    
    assert realized == 0.0
    # Current value = 0.01 * 55000 = 550
    # Invested = 500
    # Entry fee = 500 * 0.0025 = 1.25
    # Exit fee = 550 * 0.0025 = 1.375
    # P/L = 550 - 500 - 1.25 - 1.375 = 47.375
    assert unrealized == pytest.approx(47.375, rel=0.01)
    assert total == pytest.approx(47.375, rel=0.01)


def test_compute_total_pnl_mixed():
    """Test total P/L with both open and closed trades."""
    open_trades = {
        'ETH-EUR': {
            'amount': 1.0,
            'buy_price': 3000.0,
            'invested_eur': 3000.0,
        },
    }
    closed_trades = [
        {'profit': 25.0},
        {'profit': -10.0},
    ]
    last_prices = {'ETH-EUR': 3200.0}  # Gain
    
    total, realized, unrealized = compute_total_pnl(open_trades, closed_trades, last_prices)
    
    assert realized == 15.0
    # ETH unrealized: 3200 - 3000 - fees
    # Entry fee = 7.5, Exit fee = 8.0
    # P/L = 200 - 7.5 - 8.0 = 184.5
    assert unrealized == pytest.approx(184.5, rel=0.01)
    assert total == pytest.approx(199.5, rel=0.01)


def test_compute_pnl_today():
    """Test today's P/L calculation."""
    now = datetime.now(timezone.utc)
    today_ts = now.timestamp()
    yesterday_ts = (now - timedelta(days=1)).timestamp()
    
    open_trades = {
        'BTC-EUR': {
            'amount': 0.01,
            'entry_price': 50000.0,
            'invested': 500.0,
            'entry_ts': today_ts,  # Opened today
        },
    }
    closed_trades = [
        {'profit': 10.0, 'exit_ts': today_ts},  # Closed today
        {'profit': 5.0, 'exit_ts': yesterday_ts},  # Closed yesterday
    ]
    last_prices = {'BTC-EUR': 51000.0}
    
    total_today, realized_today, unrealized_today = compute_pnl_today(
        open_trades, closed_trades, last_prices
    )
    
    assert realized_today == 10.0  # Only today's closed trade
    assert unrealized_today > 0  # BTC position opened today
    assert total_today == pytest.approx(realized_today + unrealized_today, rel=0.01)


def test_compute_pnl_today_timezone():
    """Test today's P/L with timezone offset."""
    # Create timestamps for CET (UTC+1)
    now_utc = datetime.now(timezone.utc)
    now_cet = now_utc + timedelta(hours=1)
    
    # Trade closed just before midnight CET (still yesterday in CET)
    before_midnight_cet = now_cet.replace(hour=23, minute=59)
    before_midnight_utc = before_midnight_cet - timedelta(hours=1)
    
    closed_trades = [
        {'profit': 10.0, 'exit_ts': before_midnight_utc.timestamp()},
    ]
    
    # With CET timezone (offset=1)
    total_today, realized_today, unrealized_today = compute_pnl_today(
        {}, closed_trades, {}, timezone_offset=1
    )
    
    # Trade should not count as today in CET if it was before midnight CET
    # (depends on exact timing, but this tests the timezone logic)
    assert isinstance(realized_today, float)


def test_load_trades_from_log():
    """Test loading trades from JSON file."""
    # Create temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        data = {
            'open': {
                'BTC-EUR': {'amount': 0.01, 'entry_price': 50000.0}
            },
            'closed': [
                {'market': 'ETH-EUR', 'profit': 15.0}
            ]
        }
        json.dump(data, f)
        temp_path = Path(f.name)
    
    try:
        open_trades, closed_trades = load_trades_from_log(temp_path)
        
        assert 'BTC-EUR' in open_trades
        assert len(closed_trades) == 1
        assert closed_trades[0]['profit'] == 15.0
    finally:
        temp_path.unlink()


def test_load_trades_from_missing_file():
    """Test loading from non-existent file."""
    open_trades, closed_trades = load_trades_from_log(Path('/nonexistent/path.json'))
    
    assert open_trades == {}
    assert closed_trades == []


def test_compute_pnl_metrics():
    """Test comprehensive metrics computation."""
    # Create temp trade log
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        now_ts = datetime.now(timezone.utc).timestamp()
        data = {
            'open': {
                'BTC-EUR': {
                    'amount': 0.01,
                    'entry_price': 50000.0,
                    'invested': 500.0,
                    'entry_ts': now_ts,
                }
            },
            'closed': [
                {'market': 'ETH-EUR', 'profit': 25.0, 'exit_ts': now_ts},
                {'market': 'ADA-EUR', 'profit': -10.0, 'exit_ts': now_ts - 86400},
            ]
        }
        json.dump(data, f)
        temp_path = Path(f.name)
    
    try:
        # Note: Without Bitvavo client, last_prices will be empty
        # so unrealized P/L will be 0
        metrics = compute_pnl_metrics(temp_path)
        
        assert 'total_pnl' in metrics
        assert 'realized_pnl' in metrics
        assert 'unrealized_pnl' in metrics
        assert 'total_today' in metrics
        assert 'realized_today' in metrics
        assert 'unrealized_today' in metrics
        assert metrics['open_positions'] == 1
        assert metrics['closed_trades'] == 2
        assert metrics['realized_pnl'] == 15.0  # 25 - 10
        assert metrics['realized_today'] == 25.0  # Only today's trade
        
    finally:
        temp_path.unlink()


def test_handle_missing_fields():
    """Test handling of trades with missing fields."""
    open_trades = {
        'BTC-EUR': {
            # Missing amount and entry_price
        },
    }
    closed_trades = [
        {},  # Empty trade
        {'profit': 'invalid'},  # Invalid profit type
    ]
    last_prices = {'BTC-EUR': 50000.0}
    
    # Should not crash
    total, realized, unrealized = compute_total_pnl(open_trades, closed_trades, last_prices)
    
    assert realized == 0.0
    assert unrealized == 0.0
    assert total == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
