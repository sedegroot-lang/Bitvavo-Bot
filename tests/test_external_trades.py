"""
Tests for external_trades module
"""

import json
import pytest
from pathlib import Path
import tempfile
import shutil
import time

from modules.external_trades import (
    ExternalTradesManager,
    claim_market,
    release_market,
    is_market_claimed,
    get_claim_info,
)


@pytest.fixture
def temp_data_file():
    """Create temporary data file."""
    temp_dir = Path(tempfile.mkdtemp())
    data_file = temp_dir / 'active_external_trades.json'
    yield data_file
    shutil.rmtree(temp_dir)


@pytest.fixture
def manager(temp_data_file):
    """Create manager instance."""
    return ExternalTradesManager(temp_data_file)


def test_claim_market_success(manager):
    """Test successful market claim."""
    result = manager.claim_market('BTC-EUR', 'grid', {'note': 'test'})
    
    assert result is True
    assert manager.is_market_claimed('BTC-EUR') is True


def test_claim_market_already_claimed(manager):
    """Test claiming already claimed market fails."""
    manager.claim_market('BTC-EUR', 'grid')
    result = manager.claim_market('BTC-EUR', 'manual')
    
    assert result is False


def test_release_market_success(manager):
    """Test successful market release."""
    manager.claim_market('ETH-EUR', 'grid')
    result = manager.release_market('ETH-EUR')
    
    assert result is True
    assert manager.is_market_claimed('ETH-EUR') is False


def test_release_unclaimed_market(manager):
    """Test releasing unclaimed market returns False."""
    result = manager.release_market('XRP-EUR')
    
    assert result is False


def test_is_market_claimed(manager):
    """Test market claimed check."""
    assert manager.is_market_claimed('ADA-EUR') is False
    
    manager.claim_market('ADA-EUR', 'manual')
    assert manager.is_market_claimed('ADA-EUR') is True


def test_get_claim_info(manager):
    """Test getting claim information."""
    metadata = {'grid_size': 10, 'step_pct': 1.5}
    manager.claim_market('DOT-EUR', 'grid', metadata)
    
    info = manager.get_claim_info('DOT-EUR')
    
    assert info is not None
    assert info['source'] == 'grid'
    assert info['metadata'] == metadata
    assert 'claimed_at' in info


def test_get_claim_info_unclaimed(manager):
    """Test getting info for unclaimed market."""
    info = manager.get_claim_info('LINK-EUR')
    
    assert info is None


def test_get_all_claims(manager):
    """Test getting all claims."""
    manager.claim_market('BTC-EUR', 'grid')
    manager.claim_market('ETH-EUR', 'manual')
    manager.claim_market('ADA-EUR', 'grid')
    
    claims = manager.get_all_claims()
    
    assert len(claims) == 3
    assert 'BTC-EUR' in claims
    assert 'ETH-EUR' in claims
    assert 'ADA-EUR' in claims


def test_get_claims_by_source(manager):
    """Test filtering claims by source."""
    manager.claim_market('BTC-EUR', 'grid')
    manager.claim_market('ETH-EUR', 'manual')
    manager.claim_market('ADA-EUR', 'grid')
    
    grid_claims = manager.get_claims_by_source('grid')
    
    assert len(grid_claims) == 2
    assert 'BTC-EUR' in grid_claims
    assert 'ADA-EUR' in grid_claims
    assert 'ETH-EUR' not in grid_claims


def test_persistence(temp_data_file):
    """Test claims persist across manager instances."""
    manager1 = ExternalTradesManager(temp_data_file)
    manager1.claim_market('SOL-EUR', 'grid', {'test': 'data'})
    
    # Create new instance
    manager2 = ExternalTradesManager(temp_data_file)
    
    assert manager2.is_market_claimed('SOL-EUR') is True
    info = manager2.get_claim_info('SOL-EUR')
    assert info['source'] == 'grid'
    assert info['metadata']['test'] == 'data'


def test_cleanup_stale_claims(manager):
    """Test removing stale claims."""
    # Claim with modified timestamp
    manager.claim_market('BTC-EUR', 'grid')
    manager.claim_market('ETH-EUR', 'grid')
    
    # Manually modify one claim to be old
    data = manager._load()
    old_timestamp = '2020-01-01T00:00:00+00:00'
    data['claims']['BTC-EUR']['claimed_at'] = old_timestamp
    manager._save(data)
    
    # Cleanup with 1 hour max age
    removed = manager.cleanup_stale_claims(max_age_seconds=3600)
    
    assert removed == 1
    assert manager.is_market_claimed('BTC-EUR') is False
    assert manager.is_market_claimed('ETH-EUR') is True


def test_thread_safety(manager):
    """Test thread-safe operations."""
    import threading
    
    results = []
    
    def claim_worker():
        result = manager.claim_market('MATIC-EUR', 'grid')
        results.append(result)
    
    # Try to claim same market from multiple threads
    threads = [threading.Thread(target=claim_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Only one should succeed
    assert sum(results) == 1
    assert manager.is_market_claimed('MATIC-EUR') is True


def test_convenience_functions(temp_data_file):
    """Test global convenience functions."""
    from modules import external_trades
    external_trades._manager = ExternalTradesManager(temp_data_file)
    
    # Test claim
    assert claim_market('ATOM-EUR', 'manual', {'note': 'test'}) is True
    assert is_market_claimed('ATOM-EUR') is True
    
    # Test get info
    info = get_claim_info('ATOM-EUR')
    assert info is not None
    assert info['source'] == 'manual'
    
    # Test release
    assert release_market('ATOM-EUR') is True
    assert is_market_claimed('ATOM-EUR') is False


def test_file_creation(temp_data_file):
    """Test automatic file creation."""
    # File doesn't exist yet
    assert not temp_data_file.exists()
    
    # Creating manager should create file
    manager = ExternalTradesManager(temp_data_file)
    assert temp_data_file.exists()
    
    # File should have valid JSON
    with open(temp_data_file, 'r') as f:
        data = json.load(f)
    assert 'claims' in data
    assert isinstance(data['claims'], dict)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
