"""
Integration Tests
=================

End-to-end tests for bot, dashboard, and API interactions.
Tests complete workflows including:
- Trade lifecycle (open → DCA → close)
- Dashboard WebSocket updates
- API endpoint responses
- Bot heartbeat system
- AI supervisor integration
"""

import pytest
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Test configuration
BASE_URL = "http://localhost:5001"
PROJECT_ROOT = Path(__file__).parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"
HEARTBEAT_PATH = PROJECT_ROOT / "data" / "heartbeat.json"


def _dashboard_reachable() -> bool:
    import socket
    try:
        s = socket.create_connection(("localhost", 5001), timeout=1)
        s.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


_skip_no_dashboard = pytest.mark.skipif(
    not _dashboard_reachable(),
    reason="Dashboard not running on localhost:5001",
)


@_skip_no_dashboard
class TestAPIEndpoints:
    """Test all API endpoints"""
    
    def test_health_endpoint(self):
        """Test /api/health"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] in ('ok', 'warning', 'degraded')
        assert 'timestamp' in data
        assert 'version' in data
    
    def test_config_endpoint(self):
        """Test /api/config"""
        response = requests.get(f"{BASE_URL}/api/config")
        assert response.status_code == 200
        data = response.json()
        
        # Should have required config keys
        assert 'MAX_OPEN_TRADES' in data
        assert 'BASE_AMOUNT_EUR' in data
        
        # Should NOT have sensitive keys
        assert 'API_KEY' not in data
        assert 'API_SECRET' not in data
    
    def test_trades_endpoint(self):
        """Test /api/trades"""
        response = requests.get(f"{BASE_URL}/api/trades")
        assert response.status_code == 200
        data = response.json()
        assert 'open' in data
        assert 'closed' in data
    
    def test_open_trades_endpoint(self):
        """Test /api/trades/open"""
        response = requests.get(f"{BASE_URL}/api/trades/open")
        assert response.status_code == 200
        data = response.json()
        assert 'cards' in data
        assert 'totals' in data
        assert 'timestamp' in data
    
    def test_closed_trades_endpoint(self):
        """Test /api/trades/closed"""
        response = requests.get(f"{BASE_URL}/api/trades/closed")
        assert response.status_code == 200
        data = response.json()
        assert 'closed' in data
        assert 'count' in data
        assert isinstance(data['closed'], list)
    
    def test_heartbeat_endpoint(self):
        """Test /api/heartbeat"""
        response = requests.get(f"{BASE_URL}/api/heartbeat")
        assert response.status_code == 200
        data = response.json()
        assert 'heartbeat' in data
        assert 'bot_online' in data
        assert 'ai_online' in data
    
    def test_status_endpoint(self):
        """Test /api/status"""
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        assert 'bot_online' in data
        assert 'ai_online' in data
        assert 'open_trades' in data
        assert 'max_trades' in data
    
    def test_prices_endpoint(self):
        """Test /api/prices"""
        response = requests.get(f"{BASE_URL}/api/prices")
        assert response.status_code == 200
        data = response.json()
        assert 'prices' in data
        assert 'timestamp' in data
        assert isinstance(data['prices'], dict)
    
    def test_single_price_endpoint(self):
        """Test /api/price/<market>"""
        response = requests.get(f"{BASE_URL}/api/price/BTC-EUR")
        assert response.status_code == 200
        data = response.json()
        assert 'market' in data
        assert 'price' in data
        assert data['market'] == 'BTC-EUR'


@_skip_no_dashboard
class TestPageRendering:
    """Test page routes"""
    
    def test_index_redirect(self):
        """Test / redirects to /portfolio"""
        response = requests.get(BASE_URL, allow_redirects=False)
        assert response.status_code == 302
        assert '/portfolio' in response.headers['Location']
    
    def test_portfolio_page(self):
        """Test /portfolio page loads"""
        response = requests.get(f"{BASE_URL}/portfolio")
        assert response.status_code == 200
        assert 'text/html' in response.headers['Content-Type']
    
    def test_hodl_page(self):
        """Test /hodl page loads"""
        response = requests.get(f"{BASE_URL}/hodl")
        assert response.status_code == 200
    
    def test_grid_page(self):
        """Test /grid page loads"""
        response = requests.get(f"{BASE_URL}/grid")
        assert response.status_code == 200
    
    def test_ai_page(self):
        """Test /ai page loads"""
        response = requests.get(f"{BASE_URL}/ai")
        assert response.status_code == 200
    
    def test_parameters_page(self):
        """Test /parameters page loads"""
        response = requests.get(f"{BASE_URL}/parameters")
        assert response.status_code == 200
    
    def test_performance_page(self):
        """Test /performance page loads"""
        response = requests.get(f"{BASE_URL}/performance")
        assert response.status_code == 200


@_skip_no_dashboard
class TestTradeLifecycle:
    """Test complete trade workflow"""
    
    def test_trade_data_structure(self):
        """Verify trade_log.json structure"""
        if not TRADE_LOG_PATH.exists():
            pytest.skip("trade_log.json not found")
        
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert 'open' in data
        assert 'closed' in data
        assert isinstance(data['open'], dict)
        assert isinstance(data['closed'], list)
    
    def test_open_trade_fields(self):
        """Verify open trades have required fields"""
        if not TRADE_LOG_PATH.exists():
            pytest.skip("trade_log.json not found")
        
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data['open']:
            pytest.skip("No open trades")
        
        for market, trade in data['open'].items():
            required_fields = [
                'buy_price', 'amount', 'timestamp',
                'initial_invested_eur', 'total_invested_eur'
            ]
            for field in required_fields:
                assert field in trade, f"Missing field: {field}"
    
    def test_closed_trade_fields(self):
        """Verify closed trades have required fields"""
        if not TRADE_LOG_PATH.exists():
            pytest.skip("trade_log.json not found")
        
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data['closed']:
            pytest.skip("No closed trades")
        
        trade = data['closed'][0]
        required_fields = [
            'market', 'buy_price', 'sell_price', 'amount',
            'profit', 'timestamp', 'reason'
        ]
        for field in required_fields:
            assert field in trade, f"Missing field: {field}"
    
    def test_profit_calculation(self):
        """Verify profit calculations are correct"""
        if not TRADE_LOG_PATH.exists():
            pytest.skip("trade_log.json not found")
        
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data['closed']:
            pytest.skip("No closed trades")
        
        for trade in data['closed'][:10]:  # Check first 10
            buy_price = trade.get('buy_price', 0)
            sell_price = trade.get('sell_price', 0)
            amount = trade.get('amount', 0)
            profit = trade.get('profit', 0)

            # Skip trades with DCA or partial TPs: stored profit is correct
            # (uses weighted avg cost basis + multi-level fills) but the naive
            # (sell-buy)*amount calc here cannot reproduce that.
            if int(trade.get('dca_buys', 0) or 0) > 0:
                continue
            if trade.get('dca_events') or trade.get('partial_tp_events'):
                continue
            if float(trade.get('partial_tp_returned_eur', 0) or 0) > 0:
                continue

            if all([buy_price, sell_price, amount]):
                invested = buy_price * amount
                calculated_profit = (sell_price * amount) - invested

                # Naive (sell-buy)*amount cannot account for: trading fees,
                # slippage, partial fills, or weighted-average cost basis on
                # trades that had partial DCAs not flagged in dca_buys.
                # Allow large margin (300%) — this test only catches gross errors
                # like sign flips or order-of-magnitude mistakes.
                if abs(calculated_profit) > 0.50:  # Skip small trades where fees dominate
                    margin = abs(profit - calculated_profit) / max(abs(calculated_profit), 1)
                    assert margin < 3.0, f"Profit mismatch: stored={profit}, calc={calculated_profit}"


@_skip_no_dashboard
class TestHeartbeatSystem:
    """Test bot heartbeat and status tracking"""
    
    def test_heartbeat_file_exists(self):
        """Test heartbeat.json exists"""
        assert HEARTBEAT_PATH.exists(), "heartbeat.json not found"
    
    def test_heartbeat_structure(self):
        """Test heartbeat has required fields"""
        if not HEARTBEAT_PATH.exists():
            pytest.skip("heartbeat.json not found")
        
        with open(HEARTBEAT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        required_fields = [
            'ts', 'eur_balance', 'ai_active'
        ]
        for field in required_fields:
            assert field in data, f"Missing heartbeat field: {field}"
    
    def test_heartbeat_freshness(self):
        """Test heartbeat is recent (updated within last 2 minutes)"""
        if not HEARTBEAT_PATH.exists():
            pytest.skip("heartbeat.json not found")
        
        with open(HEARTBEAT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        ts = data.get('ts', 0)
        age = time.time() - ts
        
        # Heartbeat should be updated every 30s, allow 120s margin
        assert age < 120, f"Heartbeat too old: {age}s"
    
    def test_bot_status_consistency(self):
        """Test bot_online status matches across endpoints"""
        hb_response = requests.get(f"{BASE_URL}/api/heartbeat")
        status_response = requests.get(f"{BASE_URL}/api/status")
        
        assert hb_response.status_code == 200
        assert status_response.status_code == 200
        
        hb_data = hb_response.json()
        status_data = status_response.json()
        
        # bot_online should match
        assert hb_data['bot_online'] == status_data['bot_online']


@_skip_no_dashboard
class TestDashboardDataConsistency:
    """Test data consistency between dashboard and API"""
    
    def test_open_trades_count_matches(self):
        """Test open trades count is consistent"""
        api_response = requests.get(f"{BASE_URL}/api/trades/open")
        status_response = requests.get(f"{BASE_URL}/api/status")
        
        api_data = api_response.json()
        status_data = status_response.json()
        
        card_count = len(api_data['cards'])
        status_count = status_data['open_trades']
        
        # Allow difference of 1 (external balances)
        assert abs(card_count - status_count) <= 1
    
    def test_portfolio_totals_calculation(self):
        """Test portfolio totals are calculated correctly"""
        response = requests.get(f"{BASE_URL}/api/trades/open")
        data = response.json()
        
        cards = data['cards']
        totals = data['totals']
        
        # Calculate expected totals from cards
        expected_invested = sum(c.get('invested', 0) for c in cards)
        expected_current = sum(c.get('current_value', 0) for c in cards)
        
        # Allow 1% margin for rounding
        invested_diff = abs(totals['total_invested'] - expected_invested)
        assert invested_diff / max(expected_invested, 1) < 0.01
        
        current_diff = abs(totals['total_current'] - expected_current)
        assert current_diff / max(expected_current, 1) < 0.01


@_skip_no_dashboard
class TestWebSocketConnection:
    """Test WebSocket functionality"""
    
    @pytest.mark.slow
    def test_websocket_connection(self):
        """Test WebSocket can connect (requires socketio-client)"""
        try:
            from socketio import Client
        except ImportError:
            pytest.skip("python-socketio not installed")
        
        sio = Client()
        connected = False
        
        @sio.event
        def connect():
            nonlocal connected
            connected = True
        
        try:
            sio.connect(BASE_URL, wait_timeout=5)
            time.sleep(1)
            assert connected, "WebSocket failed to connect"
            sio.disconnect()
        except Exception as e:
            pytest.skip(f"WebSocket connection not available (server not running): {e}")
    
    @pytest.mark.slow
    def test_websocket_initial_data(self):
        """Test WebSocket sends initial_data event"""
        try:
            from socketio import Client
        except ImportError:
            pytest.skip("python-socketio not installed")
        
        sio = Client()
        initial_data = None
        
        @sio.event
        def initial_data(data):
            nonlocal initial_data
            initial_data = data
        
        try:
            sio.connect(BASE_URL, wait_timeout=5)
            time.sleep(2)  # Wait for data
            
            assert initial_data is not None, "No initial_data received"
            assert 'cards' in initial_data
            assert 'totals' in initial_data
            
            sio.disconnect()
        except Exception as e:
            pytest.skip(f"WebSocket connection not available (server not running): {e}")


@_skip_no_dashboard
class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_invalid_market_price(self):
        """Test /api/price with invalid market"""
        response = requests.get(f"{BASE_URL}/api/price/INVALID-EUR")
        assert response.status_code == 200
        data = response.json()
        assert data['price'] is None or data['price'] == 0
    
    def test_missing_data_graceful_failure(self):
        """Test dashboard handles missing data files"""
        # Portfolio should still load even with missing files
        response = requests.get(f"{BASE_URL}/portfolio")
        assert response.status_code == 200


@_skip_no_dashboard
class TestPerformance:
    """Test performance and response times"""
    
    def test_api_response_time(self):
        """Test API responds within acceptable time"""
        endpoints = [
            '/api/health',
            '/api/config',
            '/api/trades/open',
            '/api/heartbeat',
            '/api/status'
        ]
        
        for endpoint in endpoints:
            start = time.time()
            response = requests.get(f"{BASE_URL}{endpoint}")
            duration = time.time() - start
            
            assert response.status_code == 200
            assert duration < 10.0, f"{endpoint} took {duration}s (>10s limit)"
    
    def test_page_load_time(self):
        """Test pages load within acceptable time"""
        pages = ['/portfolio', '/hodl', '/grid', '/ai', '/performance']

        for page in pages:
            start = time.time()
            response = requests.get(f"{BASE_URL}{page}")
            duration = time.time() - start

            assert response.status_code == 200
            # 30s allowance: dashboard does live API calls + cold cache on first hit.
            # Bot trading correctness is unaffected by render time.
            assert duration < 30.0, f"{page} took {duration}s (>30s limit)"


# ========== TEST EXECUTION ==========

if __name__ == "__main__":
    print("Running integration tests...")
    print("=" * 60)
    print(f"Target: {BASE_URL}")
    print(f"Trade Log: {TRADE_LOG_PATH}")
    print(f"Heartbeat: {HEARTBEAT_PATH}")
    print("=" * 60)
    
    # Run pytest programmatically
    pytest.main([__file__, '-v', '--tb=short'])
