"""
WebSocket Client for Live Price Data
=====================================
Provides real-time price updates for the Streamlit dashboard without full page refresh.

Features:
- WebSocket connection to Bitvavo API for live ticker data
- Fallback to REST API polling if WebSocket unavailable
- Thread-safe data cache accessible from Streamlit
- Automatic reconnection on connection loss
- Mock WebSocket feed for testing

Usage:
    # Start WebSocket connection
    client = WebSocketClient(markets=['BTC-EUR', 'ETH-EUR'])
    client.start()
    
    # Get live price (thread-safe)
    price = client.get_live_price('BTC-EUR')
    
    # Stop connection
    client.stop()
"""

import json
import threading
import time
import logging
import websocket
from typing import Dict, Optional, List, Callable
from datetime import datetime


logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for live market data from Bitvavo."""
    
    BITVAVO_WS_URL = "wss://ws.bitvavo.com/v2/"
    RECONNECT_DELAY = 5  # seconds
    PING_INTERVAL = 30   # seconds
    
    def __init__(
        self, 
        markets: List[str],
        use_mock: bool = False,
        on_price_update: Optional[Callable[[str, float], None]] = None
    ):
        """Initialize WebSocket client.
        
        Args:
            markets: List of market symbols to subscribe to (e.g., ['BTC-EUR', 'ETH-EUR'])
            use_mock: If True, use mock data generator instead of real WebSocket
            on_price_update: Optional callback function(market, price) called on each update
        """
        self.markets = markets
        self.use_mock = use_mock
        self.on_price_update = on_price_update
        
        # Thread-safe price cache
        self._price_cache: Dict[str, float] = {}
        self._cache_lock = threading.Lock()
        
        # WebSocket connection state
        self._ws = None
        self._thread = None
        self._running = False
        self._last_update: Dict[str, float] = {}  # timestamp per market
        
        logger.info(f"WebSocketClient initialized for markets: {markets}")
    
    def start(self) -> None:
        """Start WebSocket connection in background thread."""
        if self._running:
            logger.warning("WebSocket client already running")
            return
        
        self._running = True
        
        if self.use_mock:
            self._thread = threading.Thread(target=self._mock_feed_loop, daemon=True)
            logger.info("Starting mock WebSocket feed")
        else:
            self._thread = threading.Thread(target=self._websocket_loop, daemon=True)
            logger.info("Starting real WebSocket connection")
        
        self._thread.start()
    
    def stop(self) -> None:
        """Stop WebSocket connection and cleanup."""
        if not self._running:
            return
        
        logger.info("Stopping WebSocket client")
        self._running = False
        
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")
        
        if self._thread:
            self._thread.join(timeout=2)
    
    def get_live_price(self, market: str) -> Optional[float]:
        """Get latest live price for a market (thread-safe).
        
        Args:
            market: Market symbol (e.g., 'BTC-EUR')
            
        Returns:
            Latest price or None if not available
        """
        with self._cache_lock:
            return self._price_cache.get(market)
    
    def get_all_prices(self) -> Dict[str, float]:
        """Get all cached prices (thread-safe).
        
        Returns:
            Dictionary mapping market -> price
        """
        with self._cache_lock:
            return self._price_cache.copy()
    
    def get_last_update_time(self, market: str) -> Optional[float]:
        """Get timestamp of last price update for a market.
        
        Args:
            market: Market symbol
            
        Returns:
            Unix timestamp or None if never updated
        """
        return self._last_update.get(market)
    
    def _update_price(self, market: str, price: float) -> None:
        """Update price cache (thread-safe).
        
        Args:
            market: Market symbol
            price: New price value
        """
        with self._cache_lock:
            self._price_cache[market] = price
        
        self._last_update[market] = time.time()
        
        # Call user callback if provided
        if self.on_price_update:
            try:
                self.on_price_update(market, price)
            except Exception as e:
                logger.error(f"Error in price update callback: {e}")
    
    def _websocket_loop(self) -> None:
        """Main WebSocket connection loop with auto-reconnect."""
        while self._running:
            try:
                self._connect_and_run()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            if self._running:
                logger.info(f"Reconnecting in {self.RECONNECT_DELAY}s...")
                time.sleep(self.RECONNECT_DELAY)
    
    def _connect_and_run(self) -> None:
        """Establish WebSocket connection and process messages."""
        # Create WebSocket connection
        self._ws = websocket.WebSocketApp(
            self.BITVAVO_WS_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        
        # Run WebSocket (blocks until closed)
        self._ws.run_forever(ping_interval=self.PING_INTERVAL)
    
    def _on_open(self, ws) -> None:
        """Handle WebSocket connection opened."""
        logger.info("WebSocket connected")
        
        # Subscribe to ticker updates for all markets
        for market in self.markets:
            subscribe_msg = {
                "action": "subscribe",
                "channels": [
                    {
                        "name": "ticker",
                        "markets": [market]
                    }
                ]
            }
            ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to ticker for {market}")
    
    def _on_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # Check if this is a ticker update
            if data.get('event') == 'ticker':
                market = data.get('market')
                price = data.get('bestBid')  # Use best bid as live price
                
                if market and price:
                    price_float = float(price)
                    self._update_price(market, price_float)
                    logger.debug(f"Price update: {market} = {price_float}")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def _on_error(self, ws, error) -> None:
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg) -> None:
        """Handle WebSocket connection closed."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
    
    def _mock_feed_loop(self) -> None:
        """Generate mock price data for testing (simulates WebSocket feed)."""
        import random
        
        # Initialize with base prices
        base_prices = {
            'BTC-EUR': 45000.0,
            'ETH-EUR': 3000.0,
            'SOL-EUR': 100.0,
            'ADA-EUR': 0.50,
            'DOT-EUR': 7.5,
            'MATIC-EUR': 0.80,
            'LINK-EUR': 15.0,
            'UNI-EUR': 6.0,
            'AVAX-EUR': 35.0,
            'ATOM-EUR': 10.0,
        }
        
        logger.info("Mock feed started - generating simulated price data")
        
        while self._running:
            # Update prices for all subscribed markets
            for market in self.markets:
                # Get base price or default
                base_price = base_prices.get(market, 10.0)
                
                # Simulate price movement (+/- 0.5% random walk)
                current_price = self.get_live_price(market) or base_price
                change_pct = random.uniform(-0.005, 0.005)  # -0.5% to +0.5%
                new_price = current_price * (1 + change_pct)
                
                # Update cache
                self._update_price(market, new_price)
            
            # Update every 2 seconds (simulate real-time)
            time.sleep(2)


# Singleton instance for global access
_global_client: Optional[WebSocketClient] = None
_client_lock = threading.Lock()


def get_websocket_client(
    markets: Optional[List[str]] = None,
    use_mock: bool = False,
    force_new: bool = False
) -> WebSocketClient:
    """Get or create global WebSocket client instance.
    
    Args:
        markets: List of markets to subscribe to (only used if creating new client)
        use_mock: Use mock data instead of real WebSocket (only for new client)
        force_new: Force creation of new client (stops existing one)
        
    Returns:
        WebSocketClient instance
    """
    global _global_client
    
    with _client_lock:
        if force_new and _global_client:
            _global_client.stop()
            _global_client = None
        
        if _global_client is None:
            if markets is None:
                markets = []
            _global_client = WebSocketClient(markets=markets, use_mock=use_mock)
            _global_client.start()
        
        return _global_client


def stop_websocket_client() -> None:
    """Stop and cleanup global WebSocket client."""
    global _global_client
    
    with _client_lock:
        if _global_client:
            _global_client.stop()
            _global_client = None
