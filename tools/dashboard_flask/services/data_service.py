"""Data service for JSON file operations with caching."""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from .cache_service import CacheService

logger = logging.getLogger(__name__)


class DataService:
    """Service for loading and caching JSON data files."""
    
    # Cache TTLs in seconds
    TTL_CONFIG = 5
    TTL_TRADES = 15
    TTL_HEARTBEAT = 5
    TTL_DEPOSITS = 30
    TTL_AI_SUGGESTIONS = 10
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent
    
    def _load_json(self, path: Path, default: Any = None) -> Any:
        """Load JSON file with error handling."""
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return default if default is not None else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading {path}: {e}")
            return default if default is not None else {}
    
    def _save_json(self, path: Path, data: Any) -> bool:
        """Save data to JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            logger.error(f"Error saving {path}: {e}")
            return False
    
    # ========== Config ==========
    
    def load_config(self) -> Dict[str, Any]:
        """Load bot configuration with 3-layer merge.

        Layer 1: config/bot_config.json (base)
        Layer 2: config/bot_config_overrides.json (overrides)
        Layer 3: %LOCALAPPDATA%/BotConfig/bot_config_local.json (wins over all)
        """
        return self.cache.get_or_set(
            'config',
            self._load_merged_config,
            self.TTL_CONFIG
        )

    def _load_merged_config(self) -> Dict[str, Any]:
        root = self._project_root
        cfg: Dict[str, Any] = self._load_json(root / 'config' / 'bot_config.json', {})

        # Layer 2 — overrides
        try:
            ovr_path = root / 'config' / 'bot_config_overrides.json'
            if ovr_path.exists():
                with ovr_path.open('r', encoding='utf-8-sig') as f:
                    overrides = json.load(f)
                if isinstance(overrides, dict):
                    for k, v in overrides.items():
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            cfg[k] = {**cfg[k], **v}
                        else:
                            cfg[k] = v
        except Exception as e:
            logger.warning(f"Failed to load config overrides: {e}")

        # Layer 3 — local overrides (outside OneDrive)
        try:
            local_path = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BotConfig' / 'bot_config_local.json'
            if local_path.exists():
                with local_path.open('r', encoding='utf-8-sig') as f:
                    local = json.load(f)
                if isinstance(local, dict):
                    for k, v in local.items():
                        if k.startswith('_'):
                            continue
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            cfg[k] = {**cfg[k], **v}
                        else:
                            cfg[k] = v
        except Exception as e:
            logger.warning(f"Failed to load local config: {e}")

        return cfg
    
    def load_strategy_params(self) -> Dict[str, Any]:
        """Load strategy parameters with caching."""
        return self.cache.get_or_set(
            'strategy_params',
            lambda: self._load_json(
                self._project_root / 'config' / 'strategy_params.json',
                {}
            ),
            self.TTL_CONFIG
        )
    
    # ========== Trades ==========
    
    def load_trades(self) -> Dict[str, Any]:
        """Load trade log with caching."""
        return self.cache.get_or_set(
            'trades',
            lambda: self._load_json(
                self._project_root / 'data' / 'trade_log.json',
                {'open': {}, 'closed': []}
            ),
            self.TTL_TRADES
        )
    
    def get_open_trades(self) -> Dict[str, Any]:
        """Get open trades dictionary."""
        trades = self.load_trades()
        return trades.get('open', {})
    
    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get closed trades list."""
        trades = self.load_trades()
        return trades.get('closed', [])
    
    # ========== Heartbeat ==========
    
    def load_heartbeat(self) -> Dict[str, Any]:
        """Load heartbeat data with caching."""
        return self.cache.get_or_set(
            'heartbeat',
            lambda: self._load_json(
                self._project_root / 'data' / 'heartbeat.json',
                {
                    'bot_running': False,
                    'ai_running': False,
                    'eur_balance': 0,
                    'timestamp': None
                }
            ),
            self.TTL_HEARTBEAT
        )
    
    def load_account_overview(self) -> Dict[str, Any]:
        """Load account overview (includes eur_in_orders from open grid/limit orders)."""
        return self.cache.get_or_set(
            'account_overview',
            lambda: self._load_json(
                self._project_root / 'data' / 'account_overview.json',
                {}
            ),
            self.TTL_HEARTBEAT
        )

    def is_bot_online(self) -> bool:
        """Check if bot is online (heartbeat within 2 minutes)."""
        heartbeat = self.load_heartbeat()
        timestamp = heartbeat.get('timestamp')
        if not timestamp:
            return False
        
        try:
            if isinstance(timestamp, str):
                last_update = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                last_update = datetime.fromtimestamp(timestamp)
            
            age = (datetime.now() - last_update.replace(tzinfo=None)).total_seconds()
            return age < 120  # 2 minutes
        except Exception:
            return False
    
    # ========== Deposits ==========
    
    def load_deposits(self) -> List[Dict[str, Any]]:
        """Load deposits history."""
        return self.cache.get_or_set(
            'deposits',
            lambda: self._load_json(
                self._project_root / 'data' / 'deposits.json',
                []
            ),
            self.TTL_DEPOSITS
        )
    
    def get_total_deposited(self) -> float:
        """Calculate total deposited amount."""
        deposits = self.load_deposits()
        if isinstance(deposits, list):
            return sum(float(d.get('amount', 0)) for d in deposits)
        elif isinstance(deposits, dict):
            # Handle legacy format
            entries = deposits.get('entries', [])
            return sum(float(d.get('amount', 0)) for d in entries)
        return 0.0
    
    # ========== AI Suggestions ==========
    
    def load_ai_suggestions(self) -> Dict[str, Any]:
        """Load AI suggestions with caching."""
        return self.cache.get_or_set(
            'ai_suggestions',
            lambda: self._load_json(
                self._project_root / 'ai' / 'ai_suggestions.json',
                {'suggestions': []}
            ),
            self.TTL_AI_SUGGESTIONS
        )
    
    # ========== Cache Management ==========
    
    def invalidate_cache(self, key: Optional[str] = None) -> None:
        """Invalidate cache for specific key or all."""
        if key:
            self.cache.delete(key)
        else:
            self.cache.clear()
