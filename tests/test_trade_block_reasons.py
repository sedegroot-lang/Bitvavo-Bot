"""
Tests for trade_block_reasons module
"""

import json
import pytest
from pathlib import Path
import tempfile
import shutil

from modules.trade_block_reasons import (
    TradeBlockCollector,
    collect_and_record,
    REASON_LOW_SCORE,
    REASON_RSI_BLOCK,
    REASON_BALANCE_LOW,
    REASON_PERFORMANCE_FILTER,
    REASON_CIRCUIT_BREAKER,
    REASON_MAX_TRADES,
    REASON_EXTERNAL_TRADE,
)


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def collector(temp_data_dir):
    """Create collector instance."""
    return TradeBlockCollector(temp_data_dir)


def test_collect_low_score(collector):
    """Test low score detection."""
    context = {
        'signal_score': 5.0,
        'min_score_threshold': 7.0,
    }
    
    reasons = collector.collect_reasons('BTC-EUR', context)
    
    assert len(reasons) == 1
    assert reasons[0]['code'] == REASON_LOW_SCORE
    assert '5.00' in reasons[0]['details']
    assert '7.00' in reasons[0]['details']


def test_collect_rsi_block(collector):
    """Test RSI out of range detection."""
    context = {
        'signal_score': 10.0,
        'min_score_threshold': 7.0,
        'rsi': 60.0,
        'rsi_min': 42.0,
        'rsi_max': 55.0,
    }
    
    reasons = collector.collect_reasons('ETH-EUR', context)
    
    assert len(reasons) == 1
    assert reasons[0]['code'] == REASON_RSI_BLOCK
    assert 'RSI' in reasons[0]['message']


def test_collect_balance_low(collector):
    """Test insufficient balance detection."""
    context = {
        'signal_score': 10.0,
        'min_score_threshold': 7.0,
        'balance_eur': 5.0,
        'order_amount': 10.0,
    }
    
    reasons = collector.collect_reasons('ADA-EUR', context)
    
    assert len(reasons) == 1
    assert reasons[0]['code'] == REASON_BALANCE_LOW


def test_collect_multiple_reasons(collector):
    """Test multiple blocking reasons."""
    context = {
        'signal_score': 5.0,
        'min_score_threshold': 7.0,
        'rsi': 60.0,
        'rsi_min': 42.0,
        'rsi_max': 55.0,
        'balance_eur': 5.0,
        'order_amount': 10.0,
        'performance_filter_blocked': True,
        'circuit_breaker_active': True,
    }
    
    reasons = collector.collect_reasons('DOT-EUR', context)
    
    assert len(reasons) == 5
    codes = [r['code'] for r in reasons]
    assert REASON_LOW_SCORE in codes
    assert REASON_RSI_BLOCK in codes
    assert REASON_BALANCE_LOW in codes
    assert REASON_PERFORMANCE_FILTER in codes
    assert REASON_CIRCUIT_BREAKER in codes


def test_collect_no_reasons(collector):
    """Test when no blocking reasons exist."""
    context = {
        'signal_score': 10.0,
        'min_score_threshold': 7.0,
        'rsi': 50.0,
        'rsi_min': 42.0,
        'rsi_max': 55.0,
        'balance_eur': 100.0,
        'order_amount': 10.0,
        'has_operator_id': True,
        'performance_filter_blocked': False,
        'circuit_breaker_active': False,
        'max_trades_reached': False,
    }
    
    reasons = collector.collect_reasons('SOL-EUR', context)
    
    assert len(reasons) == 0


def test_record_block(collector):
    """Test recording blocking reasons."""
    market = 'MATIC-EUR'
    reasons = [
        {'code': REASON_LOW_SCORE, 'message': 'Score too low', 'details': 'Score 5.0 < 7.0'}
    ]
    
    collector.record_block(market, reasons)
    
    # Verify file was created
    assert collector.data_file.exists()
    
    # Verify content
    with open(collector.data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    assert len(data['entries']) == 1
    assert data['entries'][0]['market'] == market
    assert data['entries'][0]['reason_count'] == 1


def test_get_latest_reasons(collector):
    """Test retrieving latest reasons."""
    # Record multiple entries
    for i in range(10):
        market = f'COIN{i}-EUR'
        reasons = [
            {'code': REASON_LOW_SCORE, 'message': 'Test', 'details': f'Entry {i}'}
        ]
        collector.record_block(market, reasons)
    
    # Get latest 5
    latest = collector.get_latest_reasons(limit=5)
    
    assert len(latest) == 5
    assert latest[-1]['market'] == 'COIN9-EUR'


def test_get_latest_reasons_by_market(collector):
    """Test filtering by market."""
    # Record entries for different markets
    for i in range(5):
        collector.record_block('BTC-EUR', [{'code': REASON_LOW_SCORE, 'message': 'Test', 'details': f'BTC {i}'}])
        collector.record_block('ETH-EUR', [{'code': REASON_RSI_BLOCK, 'message': 'Test', 'details': f'ETH {i}'}])
    
    # Get BTC only
    btc_entries = collector.get_latest_reasons(market='BTC-EUR')
    
    assert len(btc_entries) == 5
    assert all(e['market'] == 'BTC-EUR' for e in btc_entries)


def test_get_summary_by_market(collector):
    """Test getting summary grouped by market."""
    # Record entries
    collector.record_block('BTC-EUR', [
        {'code': REASON_LOW_SCORE, 'message': 'Test', 'details': 'BTC blocked'}
    ])
    collector.record_block('ETH-EUR', [
        {'code': REASON_RSI_BLOCK, 'message': 'Test', 'details': 'ETH blocked'},
        {'code': REASON_BALANCE_LOW, 'message': 'Test', 'details': 'Balance low'},
    ])
    
    summary = collector.get_summary_by_market()
    
    assert 'BTC-EUR' in summary
    assert 'ETH-EUR' in summary
    assert summary['BTC-EUR']['reason_count'] == 1
    assert summary['ETH-EUR']['reason_count'] == 2


def test_max_entries_trimming(collector):
    """Test that old entries are trimmed."""
    collector.max_entries = 10
    
    # Record 15 entries
    for i in range(15):
        collector.record_block(f'COIN{i}-EUR', [
            {'code': REASON_LOW_SCORE, 'message': 'Test', 'details': f'Entry {i}'}
        ])
    
    # Verify only last 10 remain
    latest = collector.get_latest_reasons(limit=100)
    
    assert len(latest) == 10
    assert latest[0]['market'] == 'COIN5-EUR'
    assert latest[-1]['market'] == 'COIN14-EUR'


def test_collect_and_record_integration(temp_data_dir):
    """Test convenience function."""
    from modules import trade_block_reasons
    trade_block_reasons._collector = TradeBlockCollector(temp_data_dir)
    
    context = {
        'signal_score': 5.0,
        'min_score_threshold': 7.0,
        'performance_filter_blocked': True,
    }
    
    reasons = collect_and_record('XRP-EUR', context, metadata={'note': 'test'})
    
    assert len(reasons) == 2
    
    # Verify it was recorded
    collector = trade_block_reasons.get_collector()
    latest = collector.get_latest_reasons(market='XRP-EUR')
    
    assert len(latest) == 1
    assert latest[0]['metadata']['note'] == 'test'


def test_external_trade_reason(collector):
    """Test external trade blocking."""
    context = {
        'signal_score': 10.0,
        'min_score_threshold': 7.0,
        'is_external_trade': True,
    }
    
    reasons = collector.collect_reasons('LINK-EUR', context)
    
    assert len(reasons) == 1
    assert reasons[0]['code'] == REASON_EXTERNAL_TRADE
    assert 'grid' in reasons[0]['details'].lower() or 'manual' in reasons[0]['details'].lower()


def test_max_trades_reason(collector):
    """Test max trades blocking."""
    context = {
        'signal_score': 10.0,
        'min_score_threshold': 7.0,
        'max_trades_reached': True,
    }
    
    reasons = collector.collect_reasons('ATOM-EUR', context)
    
    assert len(reasons) == 1
    assert reasons[0]['code'] == REASON_MAX_TRADES


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
