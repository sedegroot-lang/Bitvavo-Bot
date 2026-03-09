"""Price service for Bitvavo API with caching."""
import logging
from typing import Dict, Optional, List
import os
import sys

from .cache_service import CacheService

logger = logging.getLogger(__name__)

# Add project root to path for bitvavo import
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class PriceService:
    """Service for fetching and caching crypto prices."""
    
    TTL_PRICE = 10  # Cache prices for 10 seconds
    TTL_BATCH = 15  # Cache batch prices for 15 seconds
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
        self._client = None
    
    def _get_client(self):
        """Lazy-load Bitvavo client."""
        if self._client is None:
            try:
                from python_bitvavo_api.bitvavo import Bitvavo
                
                api_key = os.getenv('BITVAVO_API_KEY', '')
                api_secret = os.getenv('BITVAVO_API_SECRET', '')
                
                self._client = Bitvavo({
                    'APIKEY': api_key,
                    'APISECRET': api_secret,
                })
            except Exception as e:
                logger.error(f"Failed to initialize Bitvavo client: {e}")
                self._client = None
        return self._client
    
    def get_price(self, market: str) -> Optional[float]:
        """Get single market price with caching."""
        cache_key = f'price:{market}'
        
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            client = self._get_client()
            if client is None:
                return None
            
            ticker = client.tickerPrice({'market': market})
            if ticker and 'price' in ticker:
                price = float(ticker['price'])
                self.cache.set(cache_key, price, self.TTL_PRICE)
                return price
        except Exception as e:
            logger.error(f"Error fetching price for {market}: {e}")
        
        return None
    
    def get_prices_batch(self, markets: List[str]) -> Dict[str, float]:
        """Get prices for multiple markets efficiently."""
        if not markets:
            return {}
        
        # Check cache for batch
        cache_key = 'prices:batch'
        cached_batch = self.cache.get(cache_key)
        
        if cached_batch:
            # Return only requested markets from cached batch
            return {m: cached_batch.get(m) for m in markets if m in cached_batch}
        
        # Fetch all ticker prices
        try:
            client = self._get_client()
            if client is None:
                return {}
            
            all_tickers = client.tickerPrice({})
            prices = {}
            
            if isinstance(all_tickers, list):
                for ticker in all_tickers:
                    market = ticker.get('market', '')
                    if 'price' in ticker:
                        prices[market] = float(ticker['price'])
            
            # Cache the batch
            if prices:
                self.cache.set(cache_key, prices, self.TTL_BATCH)
            
            # Return only requested markets
            return {m: prices.get(m) for m in markets if m in prices}
            
        except Exception as e:
            logger.error(f"Error fetching batch prices: {e}")
            return {}
    
    def prefetch_all_prices(self) -> Dict[str, float]:
        """Prefetch all EUR market prices."""
        cache_key = 'prices:batch'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        try:
            client = self._get_client()
            if client is None:
                return {}
            
            all_tickers = client.tickerPrice({})
            prices = {}
            
            if isinstance(all_tickers, list):
                for ticker in all_tickers:
                    market = ticker.get('market', '')
                    if market.endswith('-EUR') and 'price' in ticker:
                        prices[market] = float(ticker['price'])
            
            if prices:
                self.cache.set(cache_key, prices, self.TTL_BATCH)
            
            return prices
            
        except Exception as e:
            logger.error(f"Error prefetching prices: {e}")
            return {}
    
    def invalidate_prices(self) -> None:
        """Invalidate all price caches."""
        self.cache.delete('prices:batch')
