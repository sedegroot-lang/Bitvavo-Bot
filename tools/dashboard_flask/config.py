"""Configuration classes for Flask dashboard."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BaseConfig:
    """Base configuration."""
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'quantum-bot-secret-key-2024')
    JSON_SORT_KEYS = False
    
    # Paths
    PROJECT_ROOT = PROJECT_ROOT
    TRADE_LOG_PATH = PROJECT_ROOT / 'data' / 'trade_log.json'
    CONFIG_PATH = PROJECT_ROOT / 'config' / 'bot_config.json'
    HEARTBEAT_PATH = PROJECT_ROOT / 'data' / 'heartbeat.json'
    AI_SUGGESTIONS_PATH = PROJECT_ROOT / 'ai' / 'ai_suggestions.json'
    STRATEGY_PARAMS_PATH = PROJECT_ROOT / 'config' / 'strategy_params.json'
    DEPOSITS_PATH = PROJECT_ROOT / 'data' / 'deposits.json'
    
    # Cache TTLs (seconds)
    CACHE_CONFIG_TTL = 5
    CACHE_TRADES_TTL = 15
    CACHE_HEARTBEAT_TTL = 5
    CACHE_PRICES_TTL = 10
    CACHE_PORTFOLIO_TTL = 3


class DevelopmentConfig(BaseConfig):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(BaseConfig):
    """Production configuration."""
    DEBUG = False
    TESTING = False


class TestingConfig(BaseConfig):
    """Testing configuration."""
    DEBUG = True
    TESTING = True


config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}
