"""Services package - Business logic layer."""
from .data_service import DataService
from .cache_service import CacheService
from .price_service import PriceService
from .portfolio_service import PortfolioService

# Singleton instances
_data_service = None
_cache_service = None
_price_service = None
_portfolio_service = None


def get_cache_service() -> CacheService:
    """Get or create cache service singleton."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def get_data_service() -> DataService:
    """Get or create data service singleton."""
    global _data_service
    if _data_service is None:
        _data_service = DataService(get_cache_service())
    return _data_service


def get_price_service() -> PriceService:
    """Get or create price service singleton."""
    global _price_service
    if _price_service is None:
        _price_service = PriceService(get_cache_service())
    return _price_service


def get_portfolio_service() -> PortfolioService:
    """Get or create portfolio service singleton."""
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = PortfolioService(
            get_data_service(),
            get_price_service()
        )
    return _portfolio_service


# Import new services
from .trade_service import TradeService, get_trade_service
from .ai_service import AIService, get_ai_service


__all__ = [
    'DataService',
    'CacheService', 
    'PriceService',
    'PortfolioService',
    'TradeService',
    'AIService',
    'get_data_service',
    'get_cache_service',
    'get_price_service',
    'get_portfolio_service',
    'get_trade_service',
    'get_ai_service',
]
