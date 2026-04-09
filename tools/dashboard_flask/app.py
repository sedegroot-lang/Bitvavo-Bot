"""
Flask Dashboard for Bitvavo Trading Bot
========================================

Production-ready Flask dashboard with native WebSocket support for live data.
Replaces Streamlit dashboard with true real-time updates.

Features:
- Flask-SocketIO for live price updates (no page refresh)
- REST API for all trading data
- Modern dark theme matching original Streamlit design
- All 9 tabs from original dashboard
- WebSocket price streaming from Bitvavo API

Run with: python tools/dashboard_flask/app.py
Access at: http://localhost:5001
"""

import sys
import os
import json
import time
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional, Dict, Any, List

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from flask import Flask, render_template, jsonify, request, redirect, url_for, send_from_directory, Response
from flask_socketio import SocketIO, emit

# Project modules
from modules.json_compat import write_json_compat
from modules.trade_store import load_snapshot as load_trade_snapshot, save_snapshot as save_trade_snapshot
from modules.cost_basis import derive_cost_basis
from modules import storage
from modules.signals import SignalContext, evaluate_signal_pack
import modules.dashboard_render as dashboard_render

# Crypto logo mapper for dynamic cryptocurrency icons
from tools.dashboard_flask.crypto_logo_mapper import (
    get_crypto_logo_url,
    get_crypto_name as get_crypto_name_mapped,
    extract_symbol_from_market,
)

# WebSocket client for Bitvavo
try:
    from modules.websocket_client import get_websocket_client
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    get_websocket_client = None

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO to DEBUG for WebSocket debugging
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('flask_dashboard')

# =====================================================
# FLASK APP INITIALIZATION
# =====================================================

app = Flask(__name__)
# Load SECRET_KEY from environment or use fallback
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'bitvavo-bot-dashboard-secret-key')
app.config['JSON_SORT_KEYS'] = False

# Register blueprints for modular architecture
try:
    from .blueprints import register_blueprints
    register_blueprints(app)
    logger.info("Blueprints registered: /api/v1/* endpoints available")
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path
    dashboard_path = Path(__file__).parent
    if str(dashboard_path) not in sys.path:
        sys.path.insert(0, str(dashboard_path))
    from blueprints import register_blueprints
    register_blueprints(app)
    logger.info("Blueprints registered (fallback): /api/v1/* endpoints available")

# Static file caching - 1 hour for CSS/JS (cache-busted via ?v= query param)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

# Initialize Flask-SocketIO with threading mode for live updates
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

@app.context_processor
def inject_status():
    """Automatically inject bot/AI status into all templates."""
    try:
        heartbeat = load_heartbeat()
        config = load_config()
        return {
            'bot_running': is_bot_online(heartbeat, config),
            'ai_running': heartbeat.get('ai_active', False)
        }
    except Exception:
        return {'bot_running': False, 'ai_running': False}

# =====================================================
# JINJA2 ERROR HANDLING FRAMEWORK
# =====================================================

def safe_get(obj, key, default='N/A'):
    """Safe dictionary/object access with fallback."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def safe_float(value, decimals=2, default=0.0):
    """Safely convert to float with formatting."""
    try:
        if value is None or value == '':
            return default
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    """Safely convert to integer."""
    try:
        if value is None or value == '':
            return default
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_percent(value, decimals=2, default=0.0):
    """Safely format percentage."""
    try:
        if value is None or value == '':
            return f"{default}%"
        return f"{round(float(value), decimals)}%"
    except (ValueError, TypeError):
        return f"{default}%"

# Register Jinja2 filters
app.jinja_env.filters['safe_get'] = safe_get
app.jinja_env.filters['safe_float'] = safe_float
app.jinja_env.filters['safe_int'] = safe_int
app.jinja_env.filters['safe_percent'] = safe_percent

# Set undefined behavior to log warning instead of crash
from jinja2 import DebugUndefined
app.jinja_env.undefined = DebugUndefined

# Context processor to inject time functions into templates
@app.context_processor
def inject_time_functions():
    """Make time functions available in Jinja2 templates."""
    return {
        'now': lambda: time.time(),
        'time': time
    }

# =====================================================
# PATHS AND CONSTANTS
# =====================================================

TRADE_LOG_PATH = PROJECT_ROOT / 'data' / 'trade_log.json'
CONFIG_PATH = PROJECT_ROOT / 'config' / 'bot_config.json'
CONFIG_OVERRIDES_PATH = PROJECT_ROOT / 'config' / 'bot_config_overrides.json'
CONFIG_LOCAL_PATH = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BotConfig' / 'bot_config_local.json'
HEARTBEAT_PATH = PROJECT_ROOT / 'data' / 'heartbeat.json'
METRICS_PATH = PROJECT_ROOT / 'metrics' / 'latest_metrics.json'
AI_SUGGESTIONS_FILE = PROJECT_ROOT / 'data' / 'ai_suggestions.json'
AI_HEARTBEAT_FILE = PROJECT_ROOT / 'data' / 'ai_heartbeat.json'
TRAILING_BOT_PID_FILE = PROJECT_ROOT / 'trailing_bot.pid'
AI_PID_FILE = PROJECT_ROOT / 'ai_supervisor.pid'
CRYPTO_NAMES_FILE = PROJECT_ROOT / 'data' / 'crypto_names.json'
DEPOSITS_FILE = PROJECT_ROOT / 'config' / 'deposits.json'
ICONS_DIR = PROJECT_ROOT / 'data' / 'icons'

# Cache storage
_CACHE = {
    'config': {'data': None, 'ts': 0, 'ttl': 5},
    'trades': {'data': None, 'ts': 0, 'ttl': 15},
    'heartbeat': {'data': None, 'ts': 0, 'ttl': 5},
    'metrics': {'data': None, 'ts': 0, 'ttl': 30},
    'prices': {'data': {}, 'ts': 0, 'ttl': 10},
    'portfolio_cards': {'data': None, 'ts': 0, 'ttl': 30},  # Cache built cards
    'portfolio_totals': {'data': None, 'ts': 0, 'ttl': 30},  # Cache totals
    'balances': {'data': None, 'ts': 0, 'ttl': 15},  # Cache API balances for 15 seconds
    'pending_orders': {'data': None, 'ts': 0, 'ttl': 5},  # Cache pending orders for 5 seconds
}

# Threading locks for cache updates (prevents parallel API calls)
_CACHE_LOCKS = {
    'balances': threading.Lock(),
    'pending_orders': threading.Lock(),
    'prices': threading.Lock(),
}

# Load crypto names
_CRYPTO_NAMES: Dict[str, str] = {}
try:
    if CRYPTO_NAMES_FILE.exists():
        with CRYPTO_NAMES_FILE.open('r', encoding='utf-8') as f:
            _CRYPTO_NAMES = json.load(f) or {}
except Exception:
    pass

# Load deposits tracking
def load_deposits() -> Dict:
    """Load deposit history to calculate real profit."""
    try:
        if DEPOSITS_FILE.exists():
            with DEPOSITS_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load deposits: {e}")
    return {'total_deposited_eur': 0, 'deposits': []}


def _sum_deposit_entries(data: Dict) -> float:
    """Safely sum deposit entries to avoid stale precomputed totals."""
    try:
        entries = data.get('deposits', []) or []
        return round(sum(float(item.get('amount') or 0) for item in entries), 2)
    except Exception:
        return 0.0

def sync_deposits_from_bitvavo() -> Dict:
    """Sync deposit history from Bitvavo API and return updated data."""
    try:
        import sys
        import os
        # Add project root to path
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
        from trailing_bot import bitvavo
        
        # Fetch deposit history from Bitvavo
        deposit_history = bitvavo.depositHistory({})
        
        if not deposit_history:
            logger.warning("No deposit history returned from Bitvavo")
            return load_deposits()
        
        # Process deposits (EUR only)
        deposits = []
        total = 0.0
        
        for item in deposit_history:
            if item.get('symbol') == 'EUR' and item.get('status') == 'completed':
                amount = float(item.get('amount', 0))
                timestamp = int(item.get('timestamp', 0))
                
                deposits.append({
                    'amount': amount,
                    'timestamp': timestamp,
                    'date': datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d') if timestamp else '',
                    'txId': item.get('txId', ''),
                    'note': 'Deposit'
                })
                total += amount
        
        # Sort by timestamp descending
        deposits.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Save to file
        data = {
            'total_deposited_eur': round(total, 2),
            'deposits': deposits,
            'last_synced': datetime.now(timezone.utc).isoformat(),
            'sync_source': 'bitvavo_api'
        }
        
        if DEPOSITS_FILE.exists():
            backup_path = DEPOSITS_FILE.with_suffix('.json.backup')
            # Use replace() instead of rename() — rename() fails on Windows when target exists
            DEPOSITS_FILE.replace(backup_path)
        
        with DEPOSITS_FILE.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Synced {len(deposits)} deposits from Bitvavo, total: €{total:.2f}")
        return data
        
    except Exception as e:
        logger.error(f"Failed to sync deposits from Bitvavo: {e}")
        return load_deposits()

def get_total_deposited(force_sync: bool = False) -> float:
    """Get total EUR deposited to Bitvavo account."""
    # Check if sync needed (force or older than 24h)
    data = load_deposits()
    last_synced = data.get('last_synced', '')
    
    if force_sync or not last_synced:
        data = sync_deposits_from_bitvavo()
    else:
        try:
            sync_time = datetime.fromisoformat(last_synced.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - sync_time).total_seconds() / 3600
            if age_hours > 24:
                logger.info(f"Deposit data is {age_hours:.1f}h old, syncing...")
                data = sync_deposits_from_bitvavo()
        except Exception:
            pass
    
    entry_sum = _sum_deposit_entries(data)
    stored_total = float(data.get('total_deposited_eur', 0) or 0)

    if entry_sum > 0:
        if abs(entry_sum - stored_total) > 0.01:
            logger.warning(
                "Deposit total mismatch: entries sum to %.2f but stored total is %.2f. Using entry sum.",
                entry_sum,
                stored_total,
            )
        return entry_sum

    return stored_total

# =====================================================
# DATA LOADING FUNCTIONS
# =====================================================

def get_cached(key: str) -> Any:
    """Get cached data if still valid."""
    cache = _CACHE.get(key)
    if cache and time.time() - cache['ts'] < cache['ttl']:
        return cache['data']
    return None

def set_cached(key: str, data: Any) -> None:
    """Store data in cache."""
    if key in _CACHE:
        _CACHE[key]['data'] = data
        _CACHE[key]['ts'] = time.time()

def load_config(force: bool = False) -> Dict:
    """Load bot configuration with 3-layer merge (same as modules/config.py).

    Layer 1: config/bot_config.json (base, OneDrive-synced)
    Layer 2: config/bot_config_overrides.json (OneDrive-synced)
    Layer 3: %LOCALAPPDATA%/BotConfig/bot_config_local.json (wins over all)
    """
    if not force:
        cached = get_cached('config')
        if cached:
            return cached

    cfg: Dict = {}
    # Layer 1 — base config
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open('r', encoding='utf-8') as f:
                cfg = json.load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")

    # Layer 2 — overrides
    try:
        if CONFIG_OVERRIDES_PATH.exists():
            with CONFIG_OVERRIDES_PATH.open('r', encoding='utf-8-sig') as f:
                overrides = json.load(f)
            if isinstance(overrides, dict):
                for k, v in overrides.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k] = {**cfg[k], **v}
                    else:
                        cfg[k] = v
    except Exception as e:
        logger.warning(f"Failed to load config overrides: {e}")

    # Layer 3 — local overrides (outside OneDrive, wins over everything)
    try:
        if CONFIG_LOCAL_PATH.exists():
            with CONFIG_LOCAL_PATH.open('r', encoding='utf-8-sig') as f:
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

    if cfg:
        set_cached('config', cfg)
    return cfg

_last_good_trades: Dict = {}  # fallback when file read fails

def load_trades(force: bool = False) -> Dict:
    """Load trade log data with fallback to last known good snapshot.

    When the trade_log has 0 open trades (e.g. OneDrive sync revert) but we
    have a _last_good_trades snapshot with real trades, return the last-known-
    good data.  This prevents all positions from briefly showing as 'external'.
    """
    global _last_good_trades
    if not force:
        cached = get_cached('trades')
        if cached:
            return cached
    
    try:
        if TRADE_LOG_PATH.exists():
            data = load_trade_snapshot(str(TRADE_LOG_PATH))
            if data and data.get('open'):
                _last_good_trades = data
                set_cached('trades', data)
                return data
            # Empty open trades but we have a last-known-good: OneDrive likely reverted
            if _last_good_trades and _last_good_trades.get('open'):
                logger.warning("trade_log has 0 open trades but last_good has %d — using fallback (OneDrive revert?)",
                               len(_last_good_trades.get('open', {})))
                set_cached('trades', _last_good_trades)
                return _last_good_trades
            set_cached('trades', data)
            return data
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
    # Fallback: return last known good data to prevent trades showing as external
    if _last_good_trades:
        logger.warning("Using last known good trade data as fallback")
        return _last_good_trades
    return {'open': {}, 'closed': []}

def load_heartbeat(force: bool = False) -> Dict:
    """Load bot heartbeat data."""
    if not force:
        cached = get_cached('heartbeat')
        if cached:
            return cached
    
    config = load_config()
    hb_path = Path(config.get('HEARTBEAT_FILE', 'data/heartbeat.json'))
    if not hb_path.is_absolute():
        hb_path = PROJECT_ROOT / hb_path
    
    try:
        if hb_path.exists():
            with hb_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                set_cached('heartbeat', data)
                return data
    except Exception as e:
        logger.error(f"Failed to load heartbeat: {e}")
    return {}

def load_metrics(force: bool = False) -> Dict:
    """Load latest metrics."""
    if not force:
        cached = get_cached('metrics')
        if cached:
            return cached
    
    try:
        if METRICS_PATH.exists():
            with METRICS_PATH.open('r', encoding='utf-8') as f:
                data = json.load(f)
                set_cached('metrics', data)
                return data
    except Exception as e:
        logger.error(f"Failed to load metrics: {e}")
    return {}

def get_crypto_name(symbol: str) -> str:
    """Get full name for crypto symbol."""
    return _CRYPTO_NAMES.get(symbol.upper(), symbol)

def is_bot_online(heartbeat: Dict, config: Dict) -> bool:
    """Check if bot is online based on heartbeat."""
    try:
        # Check PID file first
        if TRAILING_BOT_PID_FILE.exists():
            try:
                pid = int(TRAILING_BOT_PID_FILE.read_text().strip())
                # Check if process is running (Windows)
                import psutil
                if psutil.pid_exists(pid):
                    return True
            except Exception:
                pass
        
        # Fall back to heartbeat timestamp with LONGER threshold
        hb_ts = heartbeat.get('ts')
        if not hb_ts:
            # If no heartbeat file but PID exists, assume online
            if TRAILING_BOT_PID_FILE.exists():
                return True
            return False
        
        # More generous threshold - bot can skip heartbeat updates during processing
        threshold = max(180, int(config.get('SLEEP_SECONDS', 60)) * 4)
        return (time.time() - float(hb_ts)) <= threshold
    except Exception:
        return False

def is_ai_online(max_age: int = 600) -> bool:
    """Check if AI supervisor is online."""
    try:
        # Check AI supervisor PID file
        ai_pid_file = PROJECT_ROOT / 'logs' / 'ai_supervisor.py.pid'
        if ai_pid_file.exists():
            try:
                pid = int(ai_pid_file.read_text().strip())
                import psutil
                if psutil.pid_exists(pid):
                    return True
            except Exception:
                pass
        
        # Check AI heartbeat file with more generous threshold
        if AI_HEARTBEAT_FILE.exists():
            with AI_HEARTBEAT_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
            ts = data.get('ts')
            if ts:
                # AI supervisor runs less frequently, use longer threshold
                return (time.time() - float(ts)) <= 900  # 15 minutes
    except Exception:
        pass
    return False

def get_status_info() -> Dict:
    """Get bot and AI status for template rendering."""
    heartbeat = load_heartbeat()
    config = load_config()
    return {
        'bot_running': is_bot_online(heartbeat, config),
        'ai_running': heartbeat.get('ai_active', False)
    }

# =====================================================
# BITVAVO API INTEGRATION
# =====================================================

_bitvavo_client = None

def get_bitvavo():
    """Get Bitvavo API client using environment variables (secure)."""
    global _bitvavo_client
    if _bitvavo_client is None:
        try:
            from python_bitvavo_api.bitvavo import Bitvavo
            # Use environment variables first, fallback to config file
            api_key = os.getenv('BITVAVO_API_KEY') or load_config().get('API_KEY', '')
            api_secret = os.getenv('BITVAVO_API_SECRET') or load_config().get('API_SECRET', '')
            
            if not api_key or not api_secret:
                logger.warning("Bitvavo API credentials not found in environment or config")
                return None
            
            _bitvavo_client = Bitvavo({
                'APIKEY': api_key,
                'APISECRET': api_secret,
            })
            logger.info("Bitvavo API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Bitvavo: {e}")
            return None
    return _bitvavo_client

def get_live_price(market: str) -> Optional[float]:
    """Get live price for a market."""
    # Check cache first
    prices = _CACHE['prices']['data']
    if market in prices:
        cached_ts, cached_price = prices[market]
        if time.time() - cached_ts < 10:
            return cached_price
    
    try:
        bv = get_bitvavo()
        if bv:
            resp = bv.tickerPrice({'market': market})
            if isinstance(resp, dict) and resp.get('price'):
                price = float(resp['price'])
                _CACHE['prices']['data'][market] = (time.time(), price)
                return price
    except Exception as e:
        logger.debug(f"Price fetch failed for {market}: {e}")
    
    return None

def prefetch_all_prices() -> Dict[str, float]:
    """Fetch all market prices at once."""
    prices = {}
    try:
        bv = get_bitvavo()
        if bv:
            resp = bv.tickerPrice({})
            if isinstance(resp, list):
                now = time.time()
                for item in resp:
                    if isinstance(item, dict):
                        market = item.get('market')
                        price = item.get('price')
                        if market and price:
                            prices[market] = float(price)
                            _CACHE['prices']['data'][market] = (now, float(price))
    except Exception as e:
        logger.error(f"Failed to prefetch prices: {e}")
    return prices

def get_cached_balances() -> List[Dict]:
    """Get Bitvavo balances with caching to reduce API calls."""
    cache = _CACHE['balances']
    now = time.time()
    
    # Return cached if still valid (quick check without lock)
    if cache['data'] is not None and (now - cache['ts']) < cache['ttl']:
        return cache['data']
    
    # Use lock to prevent parallel API calls
    with _CACHE_LOCKS['balances']:
        # Double-check after acquiring lock (another thread may have updated)
        now = time.time()
        if cache['data'] is not None and (now - cache['ts']) < cache['ttl']:
            return cache['data']
        
        # Fetch fresh from API
        try:
            bv = get_bitvavo()
            if bv:
                api_balances = bv.balance({})
                if isinstance(api_balances, list):
                    cache['data'] = api_balances
                    cache['ts'] = now
                    logger.debug(f"Cached {len(api_balances)} balances for {cache['ttl']}s")
                    return api_balances
        except Exception as e:
            logger.error(f"Failed to fetch balances: {e}")
    
    # Return stale cache if API fails
    return cache['data'] or []

# =====================================================
# TRADE CALCULATIONS
# =====================================================

def get_trade_readiness_status(config: Dict, heartbeat: Dict, trades: Dict) -> Dict:
    """Determine trade readiness with DETAILED scan statistics showing why no trades.
    Returns: {status, color, icon, label, message, details, scan_stats}
    """
    # Filter out dust trades
    dust_threshold = float(config.get('DUST_TRADE_THRESHOLD_EUR', 1.0))
    open_trades_dict = trades.get('open', {})
    filtered_open = {m: t for m, t in open_trades_dict.items() 
                     if isinstance(t, dict) and 
                     float(t.get('invested_eur', 0) or 0) >= dust_threshold}
    open_count = len(filtered_open)
    max_trades = int(config.get('MAX_OPEN_TRADES', 5) or 5)
    eur_balance = float(heartbeat.get('eur_balance', 0) or 0)
    base_amount = float(config.get('BASE_AMOUNT_EUR', 12) or 12)
    min_balance = float(config.get('MIN_BALANCE_RESERVE', 10) or 10)
    
    blocks = []
    warnings = []
    scan_details = []
    
    # Get scan statistics from heartbeat
    scan_stats = heartbeat.get('last_scan_stats', {})
    total_markets = scan_stats.get('total_markets', 0)
    evaluated = scan_stats.get('evaluated', 0)
    passed_min_score = scan_stats.get('passed_min_score', 0)
    min_score_threshold = scan_stats.get('min_score_threshold', 0)
    
    # Market scan filter criteria
    min_score = float(config.get('MIN_SCORE_TO_BUY', 2) or 2)
    rsi_min = float(config.get('RSI_MIN_BUY', 35) or 35)
    rsi_max = float(config.get('RSI_MAX_BUY', 65) or 65)
    min_volume = float(config.get('MIN_AVG_VOLUME_1M', 5.0) or 5.0)
    max_spread = float(config.get('MAX_SPREAD_PCT', 0.005) or 0.005)
    
    # SCAN STATISTICS - Why no trades?
    if total_markets > 0:
        scan_details.append(f"🔍 **MARKET SCAN:** {total_markets} markets beschikbaar")
        scan_details.append(f"   ├─ Geëvalueerd: {evaluated} markets")
        
        if evaluated > 0:
            fail_rate = ((evaluated - passed_min_score) / evaluated * 100) if evaluated > 0 else 0
            scan_details.append(f"   ├─ ❌ Gefaald: {evaluated - passed_min_score} markets ({fail_rate:.0f}%)")
            scan_details.append(f"   └─ ✅ Passed: {passed_min_score} markets met score ≥ {min_score}")
            
            # Why markets fail
            if passed_min_score == 0:
                scan_details.append("")
                scan_details.append("❌ **GEEN MARKETS VOLDOEN** aan entry criteria:")
                scan_details.append(f"   • MIN_SCORE_TO_BUY: {min_score} → Alle markets scoren lager")
                scan_details.append(f"   • RSI filter: {rsi_min}-{rsi_max} → Markets buiten range")
                scan_details.append(f"   • Volume filter: ≥{min_volume}K EUR → Te laag volume")
                scan_details.append(f"   • Spread filter: ≤{max_spread*100:.2f}% → Te hoge spreads")
                scan_details.append("")
                scan_details.append("💡 **OPLOSSING:** Verlaag MIN_SCORE_TO_BUY naar 3-4")
            elif passed_min_score < 3:
                scan_details.append("")
                scan_details.append(f"⚠️ Slechts {passed_min_score} market(s) voldoet - zeer selectief!")
                scan_details.append(f"💡 Verlaag MIN_SCORE naar 3-4 voor meer opportunities")
    
    # FILTER DETAILS
    scan_details.append("")
    scan_details.append("📋 **ACTIEVE FILTERS:**")
    scan_details.append(f"   📊 MIN_SCORE_TO_BUY: {min_score}")
    scan_details.append(f"   📈 RSI range: {rsi_min}-{rsi_max}")
    scan_details.append(f"   💹 MIN_AVG_VOLUME_1M: {min_volume}K EUR")
    scan_details.append(f"   💱 MAX_SPREAD_PCT: {max_spread*100:.3f}%")
    
    # CAPACITY CHECK
    scan_details.append("")
    scan_details.append("💰 **TRADING CAPACITY:**")
    
    # Show pending reservations
    pending_res = int(heartbeat.get('pending_reservations', 0) or 0)
    if pending_res > 0:
        scan_details.append(f"   🔒 Reserveringen: {pending_res} market(s) worden verwerkt")
    
    # Check max trades
    if open_count >= max_trades:
        blocks.append(f"❌ Max trades bereikt: {open_count}/{max_trades}")
        scan_details.append(f"   ❌ Open trades: {open_count}/{max_trades} (VOL)")
    else:
        slots_free = max_trades - open_count
        scan_details.append(f"   ✅ Open trades: {open_count}/{max_trades} ({slots_free} slots vrij)")
        if open_count >= max_trades - 1:
            warnings.append(f"⚠️ Bijna vol: {open_count}/{max_trades}")
    
    # Check balance
    available_for_trades = eur_balance - min_balance
    if available_for_trades < base_amount:
        blocks.append(f"❌ Onvoldoende saldo: €{eur_balance:.2f}")
        scan_details.append(f"   ❌ Saldo: €{eur_balance:.2f} (nodig: €{base_amount + min_balance:.2f})")
    else:
        possible_trades = int(available_for_trades / base_amount)
        scan_details.append(f"   ✅ Saldo: €{eur_balance:.2f} (~{possible_trades} trades mogelijk)")
        if available_for_trades < base_amount * 2:
            warnings.append(f"⚠️ Laag saldo: €{eur_balance:.2f}")
    
    # RSI range check
    rsi_range = rsi_max - rsi_min
    if rsi_min >= rsi_max:
        blocks.append(f"❌ RSI range ongeldig: {rsi_min}-{rsi_max}")
    elif rsi_range < 20:
        warnings.append(f"⚠️ RSI window smal: {rsi_range} punten")
        scan_details.append(f"   ⚠️ RSI window: {rsi_range} punten (normaal: 40+)")
    
    # MIN_SCORE check
    if min_score > 8:
        blocks.append(f"❌ MIN_SCORE te hoog: {min_score}")
    elif min_score >= 5:
        scan_details.append(f"   ⚠️ Aggressive filter: MIN_SCORE {min_score}")
    
    # Determine final status
    if blocks:
        return {
            'status': 'red',
            'color': '#ef4444',
            'icon': '🔴',
            'label': 'GEBLOKKEERD',
            'message': blocks[0],
            'details': scan_details,
        }
    elif passed_min_score == 0 and total_markets > 0:
        # No blocks but NO markets qualify - critical issue!
        return {
            'status': 'red',
            'color': '#ef4444',
            'icon': '🔴',
            'label': 'GEEN MARKETS',
            'message': f'0/{evaluated} markets voldoen aan MIN_SCORE {min_score}',
            'details': scan_details,
        }
    elif warnings:
        # Show the warning + scan reason in the message
        warn_msg = warnings[0] if warnings else ''
        if passed_min_score == 0 and total_markets > 0:
            combined_msg = f'{warn_msg} · geen market scoort ≥{min_score}'
        else:
            combined_msg = f'{warn_msg} · {passed_min_score} market(s) beschikbaar'
        return {
            'status': 'yellow', 
            'color': '#f59e0b',
            'icon': '🟡',
            'label': 'BEPERKT',
            'message': combined_msg,
            'details': scan_details,
        }
    else:
        remaining_slots = max_trades - open_count
        possible_trades = int(available_for_trades / base_amount)
        return {
            'status': 'green',
            'color': '#10b981',
            'icon': '🟢',
            'label': 'GEREED',
            'message': f'{remaining_slots} slots vrij, {possible_trades} trades mogelijk',
            'details': [f'{remaining_slots} open trade slots beschikbaar', f'€{available_for_trades:.2f} beschikbaar voor trades'],
        }

def calculate_trade_financials(trade: Dict, live_price: Optional[float]) -> Dict:
    """Calculate P/L and other financials for a trade."""
    buy_price = float(trade.get('buy_price', 0) or 0)
    
    # CRITICAL: Use remaining_amount if available (after partial TP), else amount
    # After partial TP sells, remaining_amount is stored in last partial_tp_events entry
    partial_tp_events = trade.get('partial_tp_events', [])
    if partial_tp_events and len(partial_tp_events) > 0:
        # Use remaining_amount from most recent partial TP event
        last_event = partial_tp_events[-1]
        amount = float(last_event.get('remaining_amount', 0) or 0)
    else:
        # No partial TPs, use original amount
        amount = float(trade.get('amount', 0) or 0)
    
    # CRITICAL: Guard against stale invested_eur.
    # The sync engine now always derives cost basis from Bitvavo order history
    # (see FIX_LOG.md #001), so invested_eur should be authoritative.
    # Fallback to buy_price × amount only when invested_eur is missing.
    invested_eur = float(trade.get('invested_eur') or 0)
    partial_tp_returned = float(trade.get('partial_tp_returned_eur') or 0)
    computed_total = buy_price * amount if buy_price > 0 and amount > 0 else 0
    computed_active = max(computed_total - partial_tp_returned, 0) if computed_total > 0 else 0

    if invested_eur > 0:
        invested = invested_eur
    elif computed_active > 0:
        invested = computed_active
    else:
        total_invested = float(trade.get('total_invested_eur') or 0)
        initial_invested = float(trade.get('initial_invested_eur') or 0)
        invested = total_invested or initial_invested or (buy_price * amount)
    
    if live_price and live_price > 0:
        current_value = live_price * amount  # Uses remaining_amount if partial TP
        pnl = current_value - invested
        pnl_pct = ((current_value / invested) - 1) * 100 if invested > 0 else 0
    else:
        current_value = invested
        pnl = 0
        pnl_pct = 0
    
    return {
        'invested': invested,
        'current_value': current_value,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'buy_price': buy_price,
        'amount': amount,
        'live_price': live_price,
    }

def build_trade_cards(trades: Dict, config: Dict) -> List[Dict]:
    """Build trade card data for all open trades and external balances."""
    open_trades = trades.get('open', {}) or {}
    cards = []
    dca_max_levels = int(config.get('DCA_MAX_BUYS', 4) or 0)
    
    # Prefetch all prices
    all_prices = prefetch_all_prices()
    
    # Track which markets are already in trade_log
    tracked_markets = set(open_trades.keys())
    
    # First: Add cards for trades from trade_log.json
    for market, trade in open_trades.items():
        try:
            live_price = get_live_price(market)
            financials = calculate_trade_financials(trade, live_price)
            
            symbol = market.replace('-EUR', '')
            crypto_name = get_crypto_name_mapped(market)  # Use dynamic name from mapper
            logo_url = get_crypto_logo_url(market, size="large")  # Get CoinGecko logo URL
            
            # Determine status
            trailing_info = trade.get('trailing_info', {})
            tp_config = trade.get('tp_config', {})
            
            # COMPATIBILITY: Support both flat fields and trailing_info object format
            # Old format: trade['trailing_activated'], trade['activation_price']
            # New format: trade['trailing_info']['activated'], trade['trailing_info']['activation_price']
            trailing_activated = trailing_info.get('activated', False) or trade.get('trailing_activated', False)
            trailing_stop_val = trailing_info.get('trailing_stop') or trailing_info.get('stop_price') or trade.get('trailing_stop')
            activation_price_val = trailing_info.get('activation_price') or trade.get('activation_price')
            highest_price_val = trailing_info.get('highest_price') or trade.get('highest_price') or trade.get('highest_since_activation')
            
            # DCA level: use max of dca_buys counter and dca_events length
            # (dca_events may be incomplete if events were lost by earlier sync bugs)
            # Cap to dca_max_levels so corrupted legacy trades (dca_buys=50, max=9)
            # never show nonsense like "50/9".
            dca_events = trade.get('dca_events', [])
            dca_events_len = len(dca_events) if isinstance(dca_events, list) else 0
            dca_buys_counter = int(trade.get('dca_buys', 0) or 0)
            dca_level = min(max(dca_events_len, dca_buys_counter), dca_max_levels) if dca_max_levels else max(dca_events_len, dca_buys_counter)
            
            status = 'active'
            status_label = 'Actief'
            status_class = 'badge-neutral'
            
            # Only show "Trailing actief" when price is at or above buy price
            # (trailing_activated flag stays True forever once set, but the trail
            #  stop is only meaningful when the position is actually in profit)
            _in_profit = live_price and financials['buy_price'] and live_price >= financials['buy_price']
            if trailing_activated and _in_profit:
                status = 'trailing'
                status_label = 'Trailing actief'
                status_class = 'badge-success'
            elif tp_config.get('active'):
                status = 'tp-active'
                status_label = 'Take-Profit actief'
                status_class = 'badge-info'
            elif dca_level > 0:
                status = 'dca'
                status_label = f'DCA niveau {dca_level}'
                status_class = 'badge-warning'
            
            # Trailing stop info - already extracted above
            trailing_stop = trailing_stop_val
            activation_price = activation_price_val
            
            # Calculate activation_price from trade or config if not stored in trailing_info
            if not activation_price and financials['buy_price']:
                # First check if trade has its own trailing_activation_pct
                trailing_activation_pct = trade.get('trailing_activation_pct')
                if trailing_activation_pct is None:
                    trailing_activation_pct = float(config.get('TRAILING_ACTIVATION_PCT', 0.02))
                activation_price = financials['buy_price'] * (1 + float(trailing_activation_pct))
            
            # Calculate trailing stop price for dashboard display
            # Uses highest_since_activation and DEFAULT_TRAILING from config
            if trailing_activated and not trailing_stop and highest_price_val and financials['buy_price']:
                try:
                    _hw = float(highest_price_val)
                    _bp = float(financials['buy_price'])
                    _default_trail = float(config.get('DEFAULT_TRAILING', 0.04))
                    # Stepped trailing: tighter stop at higher profits
                    # Config format: [[profit_pct, trailing_pct], ...] or [{"profit_pct": .., "trailing_pct": ..}, ...]
                    _stepped_raw = config.get('STEPPED_TRAILING_LEVELS', [])
                    _stepped = []
                    for _s in (_stepped_raw or []):
                        if isinstance(_s, (list, tuple)) and len(_s) >= 2:
                            _stepped.append({'profit_pct': float(_s[0]), 'trailing_pct': float(_s[1])})
                        elif isinstance(_s, dict):
                            _stepped.append(_s)
                    if _hw > _bp:
                        _profit_pct = (_hw - _bp) / _bp
                        _trail_pct = _default_trail
                        for _lvl in reversed(_stepped):
                            if _profit_pct >= float(_lvl['profit_pct']):
                                _trail_pct = min(_trail_pct, float(_lvl['trailing_pct']))
                                break
                        trailing_stop = _hw * (1 - _trail_pct)
                except Exception as _ts_err:
                    logger.debug(f"Trailing stop calc for {market}: {_ts_err}")
            
            # Calculate trailing progress percentage
            trailing_progress = 0
            if activation_price and financials['buy_price'] and live_price and activation_price > financials['buy_price']:
                trailing_progress = ((live_price - financials['buy_price']) / (activation_price - financials['buy_price'])) * 100
                trailing_progress = max(0, min(100, trailing_progress))
            
            # Calculate DCA activation price and buy amount
            dca_next_price = trade.get('dca_next_price')
            dca_step_pct = float(config.get('DCA_STEP_PCT', 0.06))  # Default 6% drop
            dca_buy_eur = float(config.get('DCA_ORDER_EUR', 5.0))  # Default €5 DCA buy
            
            # If no dca_next_price, calculate from buy_price
            if not dca_next_price and financials['buy_price']:
                dca_next_price = financials['buy_price'] * (1 - dca_step_pct)
            
            # Calculate pyramid-up activation price (price where pyramid DCA would trigger)
            pyramid_up_enabled = bool(config.get('DCA_PYRAMID_UP', False))
            pyramid_min_profit = float(config.get('DCA_PYRAMID_MIN_PROFIT_PCT', 0.03))
            pyramid_price = None
            if pyramid_up_enabled and financials['buy_price']:
                pyramid_price = financials['buy_price'] * (1 + pyramid_min_profit)
            
            # Determine DCA mode for display
            dca_hybrid = bool(config.get('DCA_HYBRID', False))
            dca_mode = 'hybrid' if dca_hybrid else ('pyramid' if pyramid_up_enabled else 'average_down')
            
            # NOTE: dca_level can show high values for old trades due to order history detection
            # TODO: Improve bot's DCA logging to track only actual DCA safety buys, not all buy orders
            # For now, display the raw value - if incorrect, it's a bot logging issue to fix
            
            # Pure price drop % (no fees) and distance to DCA activation
            _bp = financials['buy_price'] or 0
            _lp = live_price or _bp
            price_drop_pct = ((_bp - _lp) / _bp * 100) if _bp > 0 else 0
            _dca_trigger_pct = float(trade.get('dca_drop_pct', config.get('DCA_DROP_PCT', 0.02)) or 0.02) * 100
            dca_distance_pct = max(0, _dca_trigger_pct - price_drop_pct)

            card = {
                'market': market,
                'symbol': symbol,
                'crypto_name': crypto_name,
                'logo_url': logo_url,  # Dynamic CoinGecko logo URL
                'buy_price': financials['buy_price'],
                'amount': financials['amount'],
                'live_price': live_price,
                'invested': financials['invested'],
                'current_value': financials['current_value'],
                'pnl': financials['pnl'],
                'pnl_pct': financials['pnl_pct'],
                'price_drop_pct': round(price_drop_pct, 2),
                'dca_distance_pct': round(dca_distance_pct, 2),
                'dca_trigger_pct': round(_dca_trigger_pct, 2),
                'status': status,
                'status_label': status_label,
                'status_class': status_class,
                'dca_level': dca_level,  # Raw value from trade_log
                'dca_max_levels': dca_max_levels,
                'dca_progress_pct': (dca_level / dca_max_levels * 100) if dca_max_levels else 0,
                'dca_remaining': max(dca_max_levels - dca_level, 0) if dca_max_levels else 0,
                'dca_next_price': dca_next_price,  # Price level for next DCA trigger
                'dca_buy_amount': dca_buy_eur,  # EUR amount per DCA buy
                'dca_mode': dca_mode,  # 'hybrid', 'pyramid', or 'average_down'
                'pyramid_price': pyramid_price,  # Price level for pyramid-up trigger
                'trailing_progress': trailing_progress,  # Add trailing progress to card
                'trailing_stop': trailing_stop,
                'activation_price': activation_price,
                'trailing_activated': trailing_activated,
                'highest_price': highest_price_val,
                'bought_at': trade.get('timestamp') or trade.get('opened_ts'),
            }
            cards.append(card)
        except Exception as e:
            logger.error(f"Error building card for {market}: {e}")
    
    # Second: Add cards for balances NOT in trade_log (external positions)
    # These are positions the user holds but aren't tracked as trades
    # Skip BTC and ETH (they're HODL positions, shown on HODL page)
    HODL_SYMBOLS = ['BTC', 'ETH']
    
    # Get CACHED balances from Bitvavo API (reduces API calls)
    raw_balances = get_cached_balances()
    
    if not raw_balances:
        # Fallback to cached file if API cache is empty
        balances_path = PROJECT_ROOT / 'data' / 'sync_raw_balances.json'
        if balances_path.exists():
            try:
                with open(balances_path, 'r') as f:
                    raw_balances = json.load(f)
                logger.debug(f"Using cached balances from sync_raw_balances.json")
            except Exception as file_err:
                logger.error(f"Failed to load cached balances: {file_err}")
    
    if raw_balances:
        external_count = 0
        for balance in raw_balances:
            symbol = balance.get('symbol', '')
            available = float(balance.get('available', 0) or 0)
            
            # Skip EUR, HODL assets (BTC/ETH), and already tracked markets
            if symbol == 'EUR' or symbol in HODL_SYMBOLS:
                continue
                
            market = f"{symbol}-EUR"
            if market in tracked_markets:
                logger.debug(f"Skipping {market} - already in trade_log")
                continue
            
            if available <= 0:
                continue
            
            # Get live price
            live_price = all_prices.get(market)
            if not live_price:
                logger.warning(f"No live price for {market}, skipping")
                continue
            
            current_value = available * live_price
            if current_value < 0.10:  # Skip dust
                logger.debug(f"Skipping {market} - dust (value={current_value:.2f})")
                continue
            
            # For external positions (not tracked by bot), show current value only
            # No P/L calculation since we don't know the original purchase price
            invested = current_value  # Show current value as "invested"
            buy_price = live_price  # Current price as reference
            pnl = 0.0  # No P/L for external positions
            pnl_pct = 0.0
            
            logger.debug(f"External position {market}: {available:.8f} @ €{live_price:.6f} = €{current_value:.2f}")
            
            # Create external position card with current value
            card = {
                'market': market,
                'symbol': symbol,
                'crypto_name': get_crypto_name_mapped(market),
                'logo_url': get_crypto_logo_url(market, size="large"),
                'buy_price': buy_price,  # Current price as reference
                'amount': available,
                'live_price': live_price,
                'invested': invested,  # Current value (no historical tracking)
                'current_value': current_value,
                'pnl': pnl,  # Zero for external positions
                'pnl_pct': pnl_pct,  # Zero for external positions
                'status': 'external',
                'status_label': 'Externe Positie',
                'status_class': 'badge-info',
                'dca_level': 0,
                'trailing_stop': None,
                'activation_price': None,
                'trailing_activated': False,
                'trailing_progress': 0,
                'highest_price': None,
                'bought_at': None,
            }
            cards.append(card)
            external_count += 1
            logger.info(f"Added external balance card for {market}: amount={available:.8f}, value=€{current_value:.2f}")
        
        logger.info(f"Added {external_count} external balance cards")
    else:
        logger.warning("No live balances fetched from Bitvavo API")
    
    # Sort by P/L descending
    cards.sort(key=lambda x: x.get('pnl', 0), reverse=True)
    return cards


def _calculate_period_pnl() -> Dict:
    """Calculate daily, weekly, and monthly realized P&L from closed trades."""
    now = time.time()
    day_ago = now - 86400
    week_ago = now - 7 * 86400
    month_ago = now - 30 * 86400

    daily_pnl = 0.0
    daily_invested = 0.0
    weekly_pnl = 0.0
    weekly_invested = 0.0
    monthly_pnl = 0.0
    monthly_invested = 0.0

    try:
        trades = load_trades()
        closed = trades.get('closed', []) or []

        # Also load archive for older trades
        archive_path = PROJECT_ROOT / 'data' / 'trade_archive.json'
        if archive_path.exists():
            try:
                with archive_path.open('r', encoding='utf-8') as f:
                    archive_data = json.load(f)
                if isinstance(archive_data, list):
                    closed = closed + archive_data
                elif isinstance(archive_data, dict):
                    closed = closed + (archive_data.get('closed', []) or [])
            except Exception:
                pass

        for trade in closed:
            ts = float(trade.get('timestamp', 0) or 0)
            if ts <= 0:
                continue
            profit = float(trade.get('profit', 0) or 0)
            invested = float(trade.get('initial_invested_eur', 0) or trade.get('invested_eur', 0) or 0)

            if ts >= month_ago:
                monthly_pnl += profit
                monthly_invested += invested
            if ts >= week_ago:
                weekly_pnl += profit
                weekly_invested += invested
            if ts >= day_ago:
                daily_pnl += profit
                daily_invested += invested

    except Exception as e:
        logger.debug(f"Period P&L calc error: {e}")

    def pct(pnl, invested):
        return (pnl / invested * 100) if invested > 0 else 0.0

    return {
        'daily_pnl': round(daily_pnl, 2),
        'daily_pnl_pct': round(pct(daily_pnl, daily_invested), 2),
        'weekly_pnl': round(weekly_pnl, 2),
        'weekly_pnl_pct': round(pct(weekly_pnl, weekly_invested), 2),
        'monthly_pnl': round(monthly_pnl, 2),
        'monthly_pnl_pct': round(pct(monthly_pnl, monthly_invested), 2),
    }


def calculate_portfolio_totals(cards: List[Dict], heartbeat: Dict = None) -> Dict:
    """Calculate portfolio totals from trade cards, including deposit-adjusted profit."""
    total_invested = sum(c.get('invested', 0) for c in cards)
    total_current = sum(c.get('current_value', 0) for c in cards)
    total_pnl = sum(c.get('pnl', 0) for c in cards)
    total_pnl_pct = ((total_current / total_invested) - 1) * 100 if total_invested > 0 else 0
    
    # Get ALL balances from Bitvavo and compute real total (like Bitvavo does)
    eur_balance = 0
    total_account_value = total_current  # fallback: just trade cards
    try:
        balances = get_cached_balances()
        if balances:
            # Compute total portfolio value from ALL Bitvavo balances × live prices
            live_total = 0.0
            for bal in balances:
                symbol = bal.get('symbol', '')
                available = float(bal.get('available', 0) or 0)
                in_order = float(bal.get('inOrder', 0) or 0)
                total_amount = available + in_order
                if total_amount <= 0:
                    continue
                if symbol == 'EUR':
                    eur_balance = total_amount
                    live_total += total_amount
                else:
                    market = f"{symbol}-EUR"
                    price = get_live_price(market)
                    if price:
                        live_total += total_amount * price
            if live_total > 0:
                total_account_value = live_total
            else:
                total_account_value = total_current + eur_balance
        else:
            total_account_value = total_current + eur_balance
    except Exception as e:
        logger.warning(f"Failed to compute live portfolio total: {e}")
        total_account_value = total_current + eur_balance
    
    # Fallback to heartbeat EUR if we got nothing from API
    if eur_balance == 0 and heartbeat:
        eur_balance = float(heartbeat.get('eur_balance', 0) or 0)
        if total_account_value == total_current:
            total_account_value = total_current + eur_balance
    
    # Get deposit data for real profit calculation
    total_deposited = get_total_deposited()
    
    # Real profit = (current portfolio value + EUR balance) - total deposited
    real_profit = total_account_value - total_deposited
    real_profit_pct = ((total_account_value / total_deposited) - 1) * 100 if total_deposited > 0 else 0
    
    # Calculate period P&L from closed trades
    period_pnl = _calculate_period_pnl()
    
    return {
        'total_invested': total_invested,
        'total_current': total_current,
        'total_pnl': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'trade_count': len(cards),
        'winning_trades': len([c for c in cards if c.get('pnl', 0) > 0]),
        'losing_trades': len([c for c in cards if c.get('pnl', 0) < 0]),
        # Deposit tracking
        'eur_balance': eur_balance,
        'total_account_value': total_account_value,
        'account_value': total_account_value,  # Alias for template compatibility
        'total_deposited': total_deposited,
        'real_profit': real_profit,
        'real_profit_pct': real_profit_pct,
        # Period P&L
        **period_pnl,
    }

# =====================================================
# WEBSOCKET LIVE DATA STREAMING
# =====================================================

_ws_clients = set()
_ws_thread = None
_ws_running = False

def start_price_stream():
    """Start background thread for price streaming."""
    global _ws_thread, _ws_running
    
    if _ws_thread and _ws_thread.is_alive():
        return
    
    _ws_running = True
    _ws_thread = threading.Thread(target=_price_stream_loop, daemon=True)
    _ws_thread.start()
    logger.info("Price stream started")

def stop_price_stream():
    """Stop price streaming."""
    global _ws_running
    _ws_running = False
    logger.info("Price stream stopped")

def _price_stream_loop():
    """Background loop for streaming prices to WebSocket clients."""
    global _ws_running
    logger.info("Price stream loop started")
    
    while _ws_running:
        try:
            if _ws_clients:
                logger.debug(f"Price stream: {len(_ws_clients)} clients connected")
                trades = load_trades()
                open_trades = trades.get('open', {}) or {}
                markets = list(open_trades.keys())
                
                if markets:
                    # OPTIMIZATION: Fetch ALL prices in ONE API call instead of per-market
                    all_prices = prefetch_all_prices()
                    prices = {m: all_prices[m] for m in markets if m in all_prices}
                    
                    if prices:
                        logger.debug(f"Price stream: Emitting {len(prices)} prices to {len(_ws_clients)} clients")
                        socketio.emit('price_update', {
                            'prices': prices,
                            'timestamp': time.time(),
                        })
                else:
                    logger.debug("Price stream: No open trades to update")
            else:
                logger.debug("Price stream: No clients connected")
            
            time.sleep(2)  # Update every 2 seconds
        except Exception as e:
            logger.error(f"Price stream error: {e}")
            time.sleep(5)
    
    logger.info("Price stream loop ended")

@socketio.on('connect')
def handle_connect():
    """Handle WebSocket client connection."""
    _ws_clients.add(request.sid)
    logger.info(f"Client connected: {request.sid}")
    start_price_stream()
    
    # Send initial data
    trades = load_trades()
    heartbeat = load_heartbeat()
    config = load_config()
    cards = build_trade_cards(trades, config)
    totals = calculate_portfolio_totals(cards, heartbeat)
    totals['max_open_trades'] = config.get('MAX_OPEN_TRADES', 5)
    
    # Check bot/AI status from heartbeat
    bot_running = True  # Dashboard running means bot is running
    ai_running = False
    if heartbeat:
        # AI supervisor updates heartbeat with ai_active field
        ai_running = heartbeat.get('ai_active', False)
        # Check if heartbeat is recent (within last 60 seconds)
        last_update = heartbeat.get('timestamp', 0)
        if time.time() - last_update > 60:
            bot_running = False
    
    emit('initial_data', {
        'cards': cards,
        'totals': totals,
        'timestamp': time.time(),
    })
    
    # Send status update
    emit('status_update', {
        'bot_running': bot_running,
        'ai_running': ai_running,
        'open_trades': len(trades.get('open', {})),
        'timestamp': time.time(),
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket client disconnection."""
    _ws_clients.discard(request.sid)
    logger.info(f"Client disconnected: {request.sid}")
    
    if not _ws_clients:
        stop_price_stream()

@socketio.on('request_refresh')
def handle_refresh_request():
    """Handle manual refresh request from client."""
    trades = load_trades(force=True)
    config = load_config(force=True)
    heartbeat = load_heartbeat(force=True)
    cards = build_trade_cards(trades, config)
    totals = calculate_portfolio_totals(cards, heartbeat)
    totals['max_open_trades'] = config.get('MAX_OPEN_TRADES', 5)
    
    emit('data_refresh', {
        'cards': cards,
        'totals': totals,
        'timestamp': time.time(),
    })

# =====================================================
# FLASK ROUTES - API ENDPOINTS
# =====================================================

@app.route('/api/health')
def api_health():
    """Comprehensive health check with bot heartbeat, process status, and error metrics."""
    import psutil
    import os

    now = time.time()
    health = {
        'status': 'ok',
        'timestamp': now,
        'version': '2.0',
    }

    # --- Bot heartbeat: check bot_log.txt last modified ---
    try:
        log_path = os.path.join(ROOT_DIR, 'logs', 'bot_log.txt')
        if os.path.exists(log_path):
            log_mtime = os.path.getmtime(log_path)
            heartbeat_age = now - log_mtime
            health['heartbeat_age_seconds'] = round(heartbeat_age, 1)
            health['heartbeat_ok'] = heartbeat_age < 120  # Bot should log every ~25s
            if heartbeat_age >= 120:
                health['status'] = 'degraded'
        else:
            health['heartbeat_ok'] = False
            health['status'] = 'degraded'
    except Exception:
        health['heartbeat_ok'] = False

    # --- Process status: count Python processes ---
    try:
        python_procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'create_time']):
            if proc.info['name'] and 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                mem_info = proc.info.get('memory_info')
                mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                uptime = now - (proc.info.get('create_time') or now)
                python_procs.append({
                    'pid': proc.info['pid'],
                    'cmd': cmdline[:100],
                    'memory_mb': round(mem_mb, 1),
                    'uptime_seconds': round(uptime, 0),
                })
        health['python_processes'] = len(python_procs)
        health['processes'] = python_procs[:10]
        total_mem = sum(p['memory_mb'] for p in python_procs)
        health['total_memory_mb'] = round(total_mem, 1)
        if total_mem > 500:
            health['status'] = 'warning'
            health['memory_warning'] = f'Total Python memory {total_mem:.0f}MB > 500MB'
    except Exception as e:
        health['process_error'] = str(e)[:100]

    # --- Open trades count ---
    try:
        trades = load_trades()
        open_count = len(trades.get('open', {}))
        closed_count = len(trades.get('closed', []))
        health['open_trades'] = open_count
        health['closed_trades'] = closed_count
    except Exception:
        pass

    # --- Error rate: count recent ERRORs in log ---
    try:
        log_path = os.path.join(ROOT_DIR, 'logs', 'bot_log.txt')
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-500:]
            error_count = sum(1 for l in lines if 'ERROR' in l or 'CRITICAL' in l)
            health['recent_errors'] = error_count
            if error_count > 20:
                health['status'] = 'degraded'
    except Exception:
        pass

    # --- Disk space ---
    try:
        usage = psutil.disk_usage(ROOT_DIR)
        health['disk_free_gb'] = round(usage.free / (1024**3), 1)
        if usage.percent > 90:
            health['status'] = 'warning'
    except Exception:
        pass

    return jsonify(health)

@app.route('/api/config')
def api_config():
    """Get bot configuration (non-sensitive fields)."""
    config = load_config()
    # Filter sensitive fields
    safe_config = {k: v for k, v in config.items() 
                   if 'SECRET' not in k.upper() and 'KEY' not in k.upper() 
                   and 'PASSWORD' not in k.upper()}
    return jsonify(safe_config)

@app.route('/api/trades')
def api_trades():
    """Get all trades."""
    trades = load_trades()
    return jsonify(trades)

@app.route('/api/trades/open')
def api_open_trades():
    """Get open trades with live data."""
    trades = load_trades()
    config = load_config()
    heartbeat = load_heartbeat()
    cards = build_trade_cards(trades, config)
    totals = calculate_portfolio_totals(cards, heartbeat)
    totals['max_open_trades'] = config.get('MAX_OPEN_TRADES', 5)
    
    return jsonify({
        'cards': cards,
        'totals': totals,
        'timestamp': time.time(),
    })

@app.route('/api/trades/closed')
def api_closed_trades():
    """Get closed trades."""
    trades = load_trades()
    return jsonify({
        'closed': trades.get('closed', []),
        'count': len(trades.get('closed', [])),
    })


@app.route('/api/orders/pending')
def api_pending_orders():
    """Get pending BUY orders not yet in open trades.
    
    These orders count towards MAX_OPEN_TRADES to prevent over-allocation.
    Returns order details including age and estimated value.
    Uses caching to reduce API calls.
    """
    cache = _CACHE['pending_orders']
    now = time.time()
    
    # Return cached if still valid
    if cache['data'] is not None and (now - cache['ts']) < cache['ttl']:
        return jsonify(cache['data'])
    
    try:
        from modules.trading import bitvavo
        
        orders = bitvavo.ordersOpen({}) or []
        trades = load_trades()
        config = load_config()
        open_trades = trades.get('open', {})
        timeout_seconds = int(config.get('LIMIT_ORDER_TIMEOUT_SECONDS', 3600) or 3600)
        max_trades = int(config.get('MAX_OPEN_TRADES', 5) or 5)
        now_ms = now * 1000  # milliseconds
        
        # Get grid order IDs AND grid markets to exclude from pending count
        grid_order_ids = set()
        grid_markets = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            if gm:
                grid_order_ids = gm.get_grid_order_ids()
                grid_markets = gm.get_grid_markets()
        except Exception:
            pass
        
        pending = []
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                # Skip grid bot orders (by ID or by market)
                if o.get('orderId') in grid_order_ids:
                    continue
                order_market = o.get('market') or o.get('symbol') or ''
                if order_market in grid_markets:
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in open_trades:
                    continue
                status = str(o.get('status', '')).lower().replace('_', '').replace('-', '').strip()
                if status not in {'new', 'open', 'partiallyfilled', 'partially filled', 'awaitingtrigger'}:
                    continue
                    
                created_ms = o.get('created', 0)
                age_sec = (now_ms - created_ms) / 1000 if created_ms else 0
                amount = float(o.get('amount', 0) or 0)
                price = float(o.get('price', 0) or 0)
                value_eur = amount * price
                symbol = market.replace('-EUR', '')
                
                # Determine if order is expiring soon (>80% of timeout)
                is_expiring = age_sec > (timeout_seconds * 0.8) if timeout_seconds > 0 else False
                
                pending.append({
                    'market': market,
                    'symbol': symbol,
                    'orderId': o.get('orderId'),
                    'amount': amount,
                    'price': price,
                    'value_eur': round(value_eur, 2),
                    'status': o.get('status'),
                    'created': created_ms,
                    'age_seconds': round(age_sec, 0),
                    'age_formatted': f"{int(age_sec // 3600)}h {int((age_sec % 3600) // 60)}m" if age_sec >= 3600 else f"{int(age_sec // 60)}m {int(age_sec % 60)}s",
                    'is_expiring': is_expiring,
                    'timeout_seconds': timeout_seconds,
                    'remaining_seconds': max(0, timeout_seconds - age_sec) if timeout_seconds > 0 else None,
                })
            except Exception:
                continue
        
        # Sort by age descending (oldest first)
        pending.sort(key=lambda x: x['age_seconds'], reverse=True)
        
        open_count = len([m for m in open_trades.values() if isinstance(m, dict)])
        total_slots_used = open_count + len(pending)
        
        result = {
            'pending': pending,
            'count': len(pending),
            'open_trades': open_count,
            'total_slots': total_slots_used,
            'max_trades': max_trades,
            'slots_remaining': max(0, max_trades - total_slots_used),
            'timeout_seconds': timeout_seconds,
            'timestamp': now,
        }
        
        # Cache the result
        cache['data'] = result
        cache['ts'] = now
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching pending orders: {e}")
        return jsonify({
            'pending': [],
            'count': 0,
            'error': str(e),
            'timestamp': now,
        })

@app.route('/api/heartbeat')
def api_heartbeat():
    """Get bot heartbeat status."""
    heartbeat = load_heartbeat()
    config = load_config()
    
    return jsonify({
        'heartbeat': heartbeat,
        'bot_online': is_bot_online(heartbeat, config),
        'ai_online': heartbeat.get('ai_active', False),  # Use heartbeat field
        'timestamp': time.time(),
    })

@app.route('/api/metrics')
def api_metrics():
    """Get latest metrics."""
    metrics = load_metrics()
    return jsonify(metrics)

@app.route('/api/prices')
def api_prices():
    """Get all current prices."""
    prices = prefetch_all_prices()
    return jsonify({
        'prices': prices,
        'timestamp': time.time(),
    })

@app.route('/api/price/<market>')
def api_price(market: str):
    """Get price for specific market."""
    price = get_live_price(market)
    return jsonify({
        'market': market,
        'price': price,
        'timestamp': time.time(),
    })

@app.route('/api/candles/<market>')
def api_candles(market: str):
    """Get historical candle data for chart timeframes.
    
    Query params:
    - interval: '1m', '5m', '15m', '1h', '4h', '1d' (default: '1h')
    - limit: number of candles to fetch (default: 100)
    
    Returns:
    {
        'candles': [[timestamp, open, high, low, close, volume], ...],
        'market': str,
        'interval': str,
        'count': int
    }
    """
    try:
        # Get query parameters
        interval = request.args.get('interval', '1h')
        limit = int(request.args.get('limit', 100))
        
        # Validate interval
        valid_intervals = ['1m', '5m', '15m', '1h', '4h', '1d']
        if interval not in valid_intervals:
            return jsonify({'error': f'Invalid interval. Must be one of: {valid_intervals}'}), 400
        
        # Validate limit (max 1440 for API safety)
        if limit < 1 or limit > 1440:
            return jsonify({'error': 'Limit must be between 1 and 1440'}), 400
        
        # Import get_candles from trailing_bot
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from trailing_bot import get_candles
        
        # Fetch candles from Bitvavo API
        candles = get_candles(market, interval=interval, limit=limit)
        
        if not candles:
            return jsonify({'error': f'No candle data available for {market}'}), 404
        
        return jsonify({
            'candles': candles,
            'market': market,
            'interval': interval,
            'count': len(candles),
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Error in /api/candles/{market}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    """Get overall system status."""
    heartbeat = load_heartbeat()
    config = load_config()
    trades = load_trades()
    
    open_count = len(trades.get('open', {}))
    max_trades = config.get('MAX_OPEN_TRADES', 5)
    eur_balance = heartbeat.get('eur_balance', 0)
    
    # Use heartbeat ai_active field (updated every 30s by bot)
    # instead of checking AI heartbeat file directly
    ai_active = heartbeat.get('ai_active', False)
    
    return jsonify({
        'bot_online': is_bot_online(heartbeat, config),
        'ai_online': ai_active,  # Use heartbeat value instead of is_ai_online()
        'open_trades': open_count,
        'max_trades': max_trades,
        'eur_balance': eur_balance,
        'last_heartbeat': heartbeat.get('ts'),
        'timestamp': time.time(),
    })

@app.route('/api/balance-history')
def api_balance_history():
    """Serve real balance history from balance_history.jsonl for the portfolio chart."""
    period = request.args.get('period', '7d').lower()
    now = time.time()

    period_seconds = {
        '1d': 86400,
        '7d': 7 * 86400,
        '30d': 30 * 86400,
        '1y': 365 * 86400,
        'all': None,
    }.get(period, 7 * 86400)

    balance_file = PROJECT_ROOT / 'data' / 'balance_history.jsonl'
    if not balance_file.exists():
        return jsonify({'labels': [], 'values': [], 'current': 0, 'change_pct': 0, 'min': 0, 'max': 0})

    try:
        raw = []
        with open(balance_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts = float(rec.get('ts', 0))
                    val = float(rec.get('total_eur', 0))
                    if period_seconds is None or (now - ts) <= period_seconds:
                        raw.append((ts, val))
                except (ValueError, KeyError):
                    continue

        if not raw:
            return jsonify({'labels': [], 'values': [], 'current': 0, 'change_pct': 0, 'min': 0, 'max': 0})

        raw.sort(key=lambda x: x[0])

        # Downsample to max 300 points
        target_points = 300
        if len(raw) > target_points:
            step = len(raw) / target_points
            raw = [raw[int(i * step)] for i in range(target_points)]
            raw.append((raw[-1][0], raw[-1][1]))  # ensure last point

        from datetime import datetime
        # Choose label format based on period
        if period == '1d':
            fmt = lambda ts: datetime.fromtimestamp(ts).strftime('%H:%M')
        elif period in ('7d', '30d'):
            fmt = lambda ts: datetime.fromtimestamp(ts).strftime('%d/%m %H:%M')
        else:
            fmt = lambda ts: datetime.fromtimestamp(ts).strftime('%d/%m/%y')

        labels = [fmt(ts) for ts, _ in raw]
        values = [round(v, 2) for _, v in raw]

        current_val = values[-1] if values else 0
        first_val = values[0] if values else 0
        change_pct = round((current_val - first_val) / first_val * 100, 2) if first_val else 0
        min_val = round(min(values), 2) if values else 0
        max_val = round(max(values), 2) if values else 0

        return jsonify({
            'labels': labels,
            'values': values,
            'current': current_val,
            'change_pct': change_pct,
            'min': min_val,
            'max': max_val,
        })
    except Exception as e:
        logger.error(f"[API] balance-history error: {e}")
        return jsonify({'error': str(e)}), 500

# =====================================================
# FLASK ROUTES - PAGE VIEWS
# =====================================================

@app.route('/')
def index():
    """Main dashboard page - redirect to portfolio."""
    return redirect(url_for('portfolio'))

@app.route('/portfolio')
def portfolio():
    """Portfolio Command page."""
    # Always load trades - needed for closed trades table and trade readiness
    trades = load_trades()
    config = load_config()
    heartbeat = load_heartbeat()
    
    # Use cached cards and totals for faster page loads
    cached_cards = get_cached('portfolio_cards')
    cached_totals = get_cached('portfolio_totals')
    
    if cached_cards is not None and cached_totals is not None:
        cards = cached_cards
        totals = cached_totals
    else:
        cards = build_trade_cards(trades, config)
        totals = calculate_portfolio_totals(cards, heartbeat)
        totals['max_open_trades'] = config.get('MAX_OPEN_TRADES', 5)
        
        # Cache the computed data
        set_cached('portfolio_cards', cards)
        set_cached('portfolio_totals', totals)
    
    # Generate portfolio combined chart data based on actual trade data
    from datetime import datetime, timedelta
    
    # Get current portfolio value
    current_active = totals.get('total_current', 0)
    current_invested = totals.get('total_invested', 0)
    
    # Generate realistic 14-day view (not 30 to avoid chart stretching)
    labels = []
    active_values = []
    hodl_values = []
    total_values = []
    
    current_date = datetime.now()
    
    # If portfolio is empty, show placeholder data so charts aren't blank
    if current_active == 0 and current_invested == 0:
        logger.info("[PORTFOLIO] Portfolio empty - using placeholder chart data")
        for i in range(14, -1, -1):
            date = current_date - timedelta(days=i)
            labels.append(date.strftime('%d/%m'))
            active_values.append(0)
            hodl_values.append(0)
            total_values.append(0)
    else:
        # Use actual invested value as baseline for realistic chart
        # Growth/decline based on current P/L percentage
        pnl_pct = totals.get('total_pnl_pct', 0) / 100  # Convert to decimal
        daily_change = pnl_pct / 14 if pnl_pct != 0 else 0.001  # Spread growth over 14 days
        
        # Generate 14 data points (manageable chart size)
        for i in range(14, -1, -1):
            date = current_date - timedelta(days=i)
            labels.append(date.strftime('%d/%m'))
            
            # Calculate value at that point in time (reverse from current)
            days_from_now = i
            growth_factor = 1 - (daily_change * days_from_now)
            
            active_val = max(0, current_active * growth_factor)
            hodl_val = max(0, current_invested * 0.1)  # Small HODL portion
            
            active_values.append(round(active_val, 2))
            hodl_values.append(round(hodl_val, 2))
            total_values.append(round(active_val + hodl_val, 2))
    
    portfolio_combined_data = {
        'labels': labels,
        'active_values': active_values,
        'hodl_values': hodl_values,
        'total_values': total_values
    }
    
    # DEBUG: Log chart data for troubleshooting
    logger.info(f"[PORTFOLIO] Combined chart data points: {len(labels)} labels, active_values={sum(active_values):.2f}")
    logger.debug(f"[PORTFOLIO] Chart data - Labels: {labels[:3]}..., Active: {active_values[:3]}..., Total: {total_values[:3]}...")
    
    # Generate allocation pie chart data
    allocation_data = {}
    allocation_labels = []
    allocation_values = []
    
    # Group by asset
    asset_totals = {}
    for card in cards:
        symbol = card.get('symbol', 'UNKNOWN')
        current_value = card.get('current_value', 0)
        
        if symbol in asset_totals:
            asset_totals[symbol] += current_value
        else:
            asset_totals[symbol] = current_value
    
    # Sort by value descending
    for symbol, value in sorted(asset_totals.items(), key=lambda x: x[1], reverse=True):
        allocation_labels.append(symbol)
        allocation_values.append(round(value, 2))
    
    portfolio_allocation = {
        'labels': allocation_labels,
        'values': allocation_values
    }
    
    # DEBUG: Log allocation data
    logger.info(f"[PORTFOLIO] Allocation chart: {len(allocation_labels)} assets, total value={sum(allocation_values):.2f}")
    logger.debug(f"[PORTFOLIO] Allocation - Labels: {allocation_labels}, Values: {allocation_values}")
    
    # Get last N closed trades for the closed trades table (configurable)
    trades_count = request.args.get('trades_count', 10, type=int)
    trades_count = max(1, min(trades_count, 500))  # clamp 1-500
    closed_trades_raw = trades.get('closed', [])
    # Sort by timestamp descending and take last N
    closed_trades_sorted = sorted(closed_trades_raw, key=lambda x: x.get('timestamp', 0), reverse=True)[:trades_count]
    
    # Format closed trades for display
    closed_trades = []
    for trade in closed_trades_sorted:
        # Get trade details
        amount = float(trade.get('amount', 0) or 0)
        buy_price = float(trade.get('buy_price', 0) or 0)
        sell_price = float(trade.get('sell_price', 0) or 0)
        
        # Calculate invested: Use stored value OR calculate from buy_price * amount
        # Prefer invested_eur (current exposure after TPs) for display
        invested = float(trade.get('invested_eur') or trade.get('total_invested_eur') or trade.get('initial_invested_eur') or 0)
        if invested == 0 and buy_price > 0 and amount > 0:
            invested = buy_price * amount
        
        # Skip dust trades (very small amounts)
        if invested < 0.01:
            continue
        
        sold_for = amount * sell_price if sell_price > 0 else 0
        profit = float(trade.get('profit', 0) or 0)
        
        # Recalculate profit if missing (for sync_removed trades)
        if profit == 0 and sell_price > 0 and invested > 0:
            profit = sold_for - invested
        
        # Format timestamp
        ts = trade.get('timestamp', 0)
        try:
            from datetime import datetime
            closed_date = datetime.fromtimestamp(ts).strftime('%d-%m %H:%M') if ts else 'Onbekend'
        except:
            closed_date = 'Onbekend'
        
        # Get trailing info if available
        trailing_data = trade.get('trailing_info', {})
        trailing_stop = trailing_data.get('trailing_stop') if trailing_data else None
        highest_price = trade.get('highest_price')
        
        closed_trades.append({
            'market': trade.get('market', 'N/A'),
            'reason': trade.get('reason', 'unknown'),
            'invested': invested,
            'sold_for': sold_for,
            'profit': profit,
            'profit_pct': ((sold_for / invested) - 1) * 100 if invested > 0 and sold_for > 0 else 0,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'amount': amount,
            'closed_date': closed_date,
            'trailing_stop': trailing_stop,
            'highest_price': highest_price,
        })
    
    # Trade readiness status indicator (Streamlit-style)
    try:
        trade_readiness = get_trade_readiness_status(config, heartbeat, trades)
        logger.info(f"[PORTFOLIO] Trade readiness: {trade_readiness.get('label', 'N/A')} - {trade_readiness.get('message', 'N/A')}")
        logger.debug(f"[PORTFOLIO] Trade readiness details: {trade_readiness.get('details', [])}")
    except Exception as e:
        logger.error(f"[PORTFOLIO] Trade readiness FAILED: {e}", exc_info=True)
        # Provide fallback status instead of None
        trade_readiness = {
            'status': 'unknown',
            'color': '#64748b',
            'icon': '⚪',
            'label': 'STATUS ONBEKEND',
            'message': 'Data tijdelijk niet beschikbaar',
            'details': ['Bot status wordt geladen...', 'Probeer de pagina te vernieuwen']
        }
    
    # DEBUG: Log data being passed to template
    logger.info(f"[PORTFOLIO] Closed trades count: {len(closed_trades)}")
    logger.info(f"[PORTFOLIO] Cards count: {len(cards)}")
    
    return render_template('portfolio.html',
        cards=cards,
        totals=totals,
        config=config,
        heartbeat=heartbeat,
        bot_running=is_bot_online(heartbeat, config),
        ai_running=heartbeat.get('ai_active', False),  # FIX: Use heartbeat field (updated by bot every 30s)
        portfolio_combined_data=portfolio_combined_data,
        portfolio_allocation=portfolio_allocation,
        closed_trades=closed_trades,
        trades_count=trades_count,
        trade_readiness=trade_readiness,
        active_tab='portfolio',
    )

@app.route('/hodl')
def hodl():
    """HODL Planner page."""
    trades = load_trades()
    config = load_config()
    
    # Prefetch ALL prices at once to avoid multiple API calls
    all_prices = prefetch_all_prices()
    
    # Load real balances from sync_raw_balances.json
    balances_path = PROJECT_ROOT / 'data' / 'sync_raw_balances.json'
    balances = {}
    if balances_path.exists():
        try:
            with open(balances_path, 'r') as f:
                raw_balances = json.load(f)
                for b in raw_balances:
                    symbol = b.get('symbol', '')
                    available = float(b.get('available', 0) or 0)
                    if available > 0 and symbol != 'EUR':
                        balances[symbol] = available
        except Exception as e:
            logger.error(f"Error loading balances: {e}")
    
    # Build HODL positions from BTC and ETH only (true HODL assets)
    hodl_positions = []
    HODL_SYMBOLS = ['BTC', 'ETH']  # Only these are HODL positions
    
    # Create positions ONLY for BTC and ETH
    for symbol in HODL_SYMBOLS:
        amount = balances.get(symbol, 0)
        if amount <= 0:
            continue
            
        market = f"{symbol}-EUR"
        live_price = all_prices.get(market)  # Use prefetched prices
        
        # Skip if we can't get a price
        if not live_price:
            continue
            
        current_value = amount * live_price
        if current_value < 0.10:  # Skip dust (< €0.10)
            continue
        
        position = {
            'symbol': symbol,
            'market': market,
            'amount': amount,
            'entry_price': live_price,  # Use current price as baseline
            'avg_buy': live_price,
            'current_price': live_price,
            'live_price': live_price,
            'entry_date': '2024-01-01',
            'invested': current_value,  # Baseline as current value
            'current_value': current_value,
            'pnl': 0.0,  # No P/L since we don't have historical entry
            'pnl_pct': 0.0,
            'strategy': 'Long-term HODL',
            'active': True,
            'logo_url': get_crypto_logo_url(market, size='large'),
            'crypto_name': get_crypto_name_mapped(market),
            'targets': []
        }
        hodl_positions.append(position)
    
    # Sort by current value descending
    hodl_positions.sort(key=lambda x: x.get('current_value', 0), reverse=True)
    
    # Calculate totals (prices already set from prefetch)
    total_value = 0.0
    total_invested = 0.0
    total_pnl = 0.0
    
    for position in hodl_positions:
        market = position['market']
        live_price = all_prices.get(market) or position['entry_price']  # Use prefetched prices
        
        # Calculate current value
        current_value = position['amount'] * live_price
        invested = position['invested']
        pnl = current_value - invested
        pnl_pct = ((live_price / position['entry_price']) - 1) * 100 if position['entry_price'] > 0 else 0
        
        # Add calculated fields to position
        position['live_price'] = live_price
        position['current_price'] = live_price  # Template expects current_price
        position['current_value'] = current_value
        position['pnl'] = pnl
        position['pnl_pct'] = pnl_pct
        position['logo_url'] = get_crypto_logo_url(market, size='large')
        position['crypto_name'] = get_crypto_name_mapped(market)
        
        # Aggregate totals
        total_value += current_value
        total_invested += invested
        total_pnl += pnl
    
    hodl_value = total_value
    hodl_pnl = total_pnl
    hodl_count = len(hodl_positions)
    hodl_pnl_pct = ((total_value / total_invested) - 1) * 100 if total_invested > 0 else 0
    
    # Allocation data for pie chart
    allocation = [
        {
            'symbol': pos['symbol'],
            'percentage': (pos['current_value'] / total_value * 100) if total_value > 0 else 0,
            'value': pos['current_value']
        }
        for pos in hodl_positions
    ]
    
    # Get available markets from config whitelist
    available_markets = config.get('WHITELIST_MARKETS', [])
    
    return render_template('hodl.html', 
        hodl_value=hodl_value,
        hodl_pnl=hodl_pnl,
        hodl_pnl_pct=hodl_pnl_pct,
        hodl_count=hodl_count,
        hodl_positions=hodl_positions,
        allocation=allocation,
        total_invested=total_invested,
        available_markets=available_markets,
        active_tab='hodl'
    )

@app.route('/hedge')
def hedge():
    """Hedge Lab page."""
    config = load_config()
    
    # Calculate hedge data
    protected_value = 0.0
    total_risk = 0.0
    hedges = []
    active_hedges = []  # For template compatibility
    risk_percentage = 0.0
    risk_level = 'low'  # low, medium, high
    max_drawdown = 0.0
    var_1d = 0.0  # Value at Risk 1 day
    hedge_count = 0
    sharpe_ratio = 0.0  # Risk-adjusted return metric
    
    # TODO: Load from actual hedge data when implemented
    
    return render_template('hedge.html', 
        config=config,
        protected_value=protected_value,
        total_risk=total_risk,
        hedges=hedges,
        active_hedges=active_hedges,
        risk_percentage=risk_percentage,
        risk_level=risk_level,
        max_drawdown=max_drawdown,
        var_1d=var_1d,
        hedge_count=hedge_count,
        sharpe_ratio=sharpe_ratio,
        active_tab='hedge',
    )

@app.route('/grid')
def grid():
    """Grid Bot page."""
    config = load_config()
    
    # Get available markets - start with common EUR markets as default
    available_markets = [
        'BTC-EUR', 'ETH-EUR', 'XRP-EUR', 'ADA-EUR', 'SOL-EUR',
        'DOT-EUR', 'DOGE-EUR', 'MATIC-EUR', 'LINK-EUR', 'UNI-EUR',
        'AVAX-EUR', 'ATOM-EUR', 'ALGO-EUR', 'FTM-EUR', 'NEAR-EUR',
        'SHIB-EUR', 'APT-EUR', 'FET-EUR', 'DYDX-EUR', 'ENA-EUR',
        'COTI-EUR', 'MOODENG-EUR', 'LTC-EUR', 'BCH-EUR', 'EOS-EUR',
    ]
    
    # Try to load all EUR markets from Bitvavo API
    try:
        import python_bitvavo_api.bitvavo as Bitvavo
        bitvavo = Bitvavo.Bitvavo({})
        markets_data = bitvavo.markets({})
        # Filter EUR markets only and sort
        api_markets = sorted([m['market'] for m in markets_data if m['market'].endswith('-EUR')])
        if len(api_markets) > len(available_markets):
            available_markets = api_markets  # Use API markets if more comprehensive
            logger.info(f"Loaded {len(available_markets)} EUR markets from Bitvavo API")
    except Exception as e:
        logger.warning(f"Failed to load markets from Bitvavo API: {e}, using fallback list")
    
    # Load grid data from GridManager
    total_grid_profit = 0.0
    total_grid_fees = 0.0
    active_grids = []
    grid_count = 0
    grid_history = []
    filled_orders = 0
    avg_grid_levels = 0
    
    try:
        from modules.grid_trading import GridManager
        grid_manager = GridManager()
        
        # Convert GridState objects to template-friendly dicts
        for market, state in grid_manager.grids.items():
            # Count filled orders
            filled_count = sum(1 for level in state.levels if level.status == 'filled')
            filled_orders += filled_count
            
            # Calculate average grid levels
            avg_grid_levels = (avg_grid_levels * len(active_grids) + len(state.levels)) / (len(active_grids) + 1) if active_grids else len(state.levels)
            
            # Build grid card data with comprehensive level info
            levels_list = []
            placed_count = 0
            total_buy_value = 0.0
            total_sell_value = 0.0
            for level in state.levels:
                val_eur = round(level.amount * level.price, 2)
                levels_list.append({
                    'price': level.price,
                    'type': level.side,
                    'status': level.status,
                    'amount': level.amount,
                    'value_eur': val_eur,
                    'order_id': level.order_id,
                })
                if level.status == 'placed':
                    placed_count += 1
                    if level.side == 'buy':
                        total_buy_value += val_eur
                    else:
                        total_sell_value += val_eur
            
            roi_pct = (state.total_profit / state.config.total_investment * 100) if state.config.total_investment > 0 else 0
            net_profit = state.total_profit - state.total_fees
            spacing_eur = (state.config.upper_price - state.config.lower_price) / max(1, state.config.num_grids - 1)
            spacing_pct = (spacing_eur / state.config.lower_price * 100) if state.config.lower_price > 0 else 0
            
            grid_data = {
                'id': market,
                'market': market,
                'mode': state.config.grid_mode,
                'active': state.status == 'running',
                'upper_price': state.config.upper_price,
                'lower_price': state.config.lower_price,
                'current_price': state.current_price,
                'investment': state.config.total_investment,
                'grid_count': state.config.num_grids,
                'trades_executed': state.total_trades,
                'profit': state.total_profit,
                'fees': state.total_fees,
                'net_profit': round(net_profit, 4),
                'roi_pct': round(roi_pct, 2),
                'placed_orders': placed_count,
                'filled_orders_count': filled_count,
                'total_buy_value': round(total_buy_value, 2),
                'total_sell_value': round(total_sell_value, 2),
                'spacing_eur': round(spacing_eur, 2),
                'spacing_pct': round(spacing_pct, 2),
                'stop_loss_pct': state.config.stop_loss_pct,
                'take_profit_pct': state.config.take_profit_pct,
                'levels': levels_list,
            }
            
            total_grid_profit += state.total_profit
            total_grid_fees += state.total_fees
            
            if state.status in ['running', 'paused']:
                active_grids.append(grid_data)
                grid_count += 1
            else:
                grid_history.append({
                    'market': market,
                    'mode': state.config.grid_mode,
                    'duration': 'N/A',  # Would need start/end timestamps
                    'trades': state.total_trades,
                    'profit': state.total_profit,
                    'roi': (state.total_profit / state.config.total_investment * 100) if state.config.total_investment > 0 else 0,
                    'status': state.status
                })
        
        logger.info(f"Loaded {len(active_grids)} active grids, gross profit: €{total_grid_profit:.2f}, fees: €{total_grid_fees:.2f}")
    except Exception as e:
        logger.warning(f"Failed to load GridManager data: {e}")
    
    # Load ETH-EUR strategy if exists (fail-safe)
    import json
    eth_strategy = None
    eth_config_path = PROJECT_ROOT / 'config' / 'grid_strategy_eth.json'
    logger.info(f"Looking for ETH strategy at: {eth_config_path}")
    if eth_config_path.exists():
        try:
            with open(eth_config_path, 'r', encoding='utf-8') as f:
                eth_strategy = json.load(f)
            logger.info(
                f"Loaded ETH-EUR grid strategy: {eth_strategy.get('market')}, "
                f"Investment: €{eth_strategy.get('investment', {}).get('total_eur')}"
            )
        except Exception as e:
            logger.error(f"Failed to parse ETH strategy file: {e}", exc_info=True)
    else:
        logger.warning(f"ETH strategy file not found at {eth_config_path}")
    
    # DEBUG: Verify available_markets is populated
    logger.info(f"Grid route: available_markets has {len(available_markets)} markets")
    
    total_grid_net_profit = total_grid_profit - total_grid_fees
    logger.info(f"[GRID PROFIT DEBUG] gross={total_grid_profit!r} fees={total_grid_fees!r} net={total_grid_net_profit!r} active_grids_count={len(active_grids)}")
    return render_template('grid.html',
        config=config,
        total_grid_profit=total_grid_profit,
        total_grid_fees=total_grid_fees,
        total_grid_net_profit=total_grid_net_profit,
        active_grids=active_grids,
        grid_count=grid_count,
        grid_history=grid_history,
        filled_orders=filled_orders,
        avg_grid_levels=int(avg_grid_levels),
        available_markets=available_markets,
        eth_strategy=eth_strategy,
        active_tab='grid',
    )

@app.route('/ai')
def ai_copilot():
    """AI Copilot page."""
    config = load_config()
    heartbeat = load_heartbeat()
    
    # Load AI suggestions
    suggestions = []
    market_analysis = []
    model_accuracy = 0.0
    ai_stats = {}
    ai_active = heartbeat.get('ai_active', False)  # Use heartbeat field
    ai_suggestions = []  # For template compatibility
    last_ai_update = 'Never'
    
    try:
        if AI_SUGGESTIONS_FILE.exists():
            with AI_SUGGESTIONS_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
                suggestions = data.get('suggestions', [])
                ai_suggestions = suggestions  # Use same data
                market_analysis = data.get('market_analysis', [])
                
                # Get timestamp if available
                ts = data.get('timestamp')
                if ts:
                    from datetime import datetime
                    dt = datetime.fromtimestamp(ts)
                    last_ai_update = dt.strftime('%H:%M:%S')
    except Exception:
        pass
    
    # Load AI model metrics
    model_metrics = {
        'accuracy': 0.0,
        'precision': 0.0,
        'recall': 0.0,
        'f1_score': 0.0
    }
    try:
        ai_metrics_path = PROJECT_ROOT / 'ai' / 'ai_model_metrics.json'
        if ai_metrics_path.exists():
            with ai_metrics_path.open('r', encoding='utf-8') as f:
                ai_stats = json.load(f)
                model_accuracy = ai_stats.get('accuracy', 0.0) * 100  # Convert to percentage
                # Populate model_metrics dict
                model_metrics['accuracy'] = ai_stats.get('accuracy', 0.0) * 100
                model_metrics['precision'] = ai_stats.get('precision', 0.0) * 100
                model_metrics['recall'] = ai_stats.get('recall', 0.0) * 100
                model_metrics['f1_score'] = ai_stats.get('f1_score', 0.0) * 100
    except Exception:
        pass
    
    # AI configuration (mock data - would load from ai_config.json)
    ai_config = {
        'mode': 'advisory',
        'min_confidence': 75,
        'max_trades_per_day': 10,
        'risk_level': 'moderate',
        'use_technical_analysis': True,
        'use_sentiment_analysis': False
    }
    
    return render_template('ai.html',
        config=config,
        suggestions=suggestions,
        ai_suggestions=ai_suggestions,
        market_analysis=market_analysis,
        model_accuracy=model_accuracy,
        model_metrics=model_metrics,
        ai_stats=ai_stats,
        ai_config=ai_config,
        ai_online=heartbeat.get('ai_active', False),  # Use heartbeat field
        ai_active=ai_active,
        last_ai_update=last_ai_update,
        active_tab='ai',
    )

@app.route('/parameters')
def parameters():
    """Strategy & Parameters page."""
    config = load_config()
    heartbeat = load_heartbeat()
    
    # Create comprehensive params object from config - LIVE SYNC
    params = {
        # Entry parameters
        'entry_strategy': config.get('ENTRY_STRATEGY', 'dca'),
        'min_entry_amount': config.get('BASE_AMOUNT_EUR', 45.0),
        'max_entry_amount': config.get('MAX_TOTAL_EXPOSURE_EUR', 350),
        'entry_threshold': config.get('ENTRY_THRESHOLD', 0.5),
        
        # Exit parameters
        'take_profit': config.get('TRAILING_ACTIVATION_PCT', 0.035) * 100,
        'take_profit_pct': config.get('TRAILING_ACTIVATION_PCT', 0.035) * 100,
        'stop_loss': config.get('STOP_LOSS_HARD_PCT', 0.12) * 100,
        'stop_loss_pct': config.get('STOP_LOSS_HARD_PCT', 0.12) * 100,
        'trailing_stop': config.get('DEFAULT_TRAILING', 0.012) * 100,
        'trailing_stop_pct': config.get('DEFAULT_TRAILING', 0.012) * 100,
        'max_hold_time': config.get('MAX_HOLD_TIME', 168),
        
        # Risk management
        'max_portfolio_risk': config.get('MAX_PORTFOLIO_RISK', 25),
        'max_simultaneous_trades': config.get('MAX_OPEN_TRADES', 3),
        'max_trade_size_pct': config.get('MAX_TRADE_SIZE_PCT', 20),
        'min_balance_reserve': config.get('MIN_BALANCE_EUR', 15),
        'risk_per_trade': config.get('RISK_PER_TRADE', 2.0),
        'max_position_size': config.get('MAX_POSITION_SIZE', 500),
        
        # DCA settings
        'dca_enabled': config.get('DCA_ENABLED', True),
        'enable_dca': config.get('DCA_ENABLED', True),
        'dca_max_buys': config.get('DCA_MAX_BUYS', 5),
        'max_dca_levels': config.get('DCA_MAX_BUYS', 5),
        'dca_drop_pct': config.get('DCA_DROP_PCT', 0.055) * 100,
        'dca_trigger_pct': config.get('DCA_DROP_PCT', 0.055) * 100,
        'dca_multiplier': config.get('DCA_SIZE_MULTIPLIER', 1.5),
        
        # Technical indicators - FIXED KEYS
        'rsi_period': config.get('SIGNALS_TA_RSI_PERIOD', 14),
        'rsi_oversold': config.get('RSI_MIN_BUY', 30),
        'rsi_overbought': config.get('RSI_MAX_BUY', 70),
        'macd_fast': config.get('MACD_FAST', 12),
        
        # Timing & Execution
        'scan_interval': config.get('SLEEP_SECONDS', 60),
        'order_timeout': config.get('ORDER_TIMEOUT', 30),
        'use_market_orders': config.get('USE_MARKET_ORDERS', False),
        'allow_weekend_trading': config.get('ALLOW_WEEKEND_TRADING', True),
        
        # Additional params for template
        'min_score_entry': config.get('MIN_SCORE_TO_BUY', 7.5),
        'max_open_trades': config.get('MAX_OPEN_TRADES', 3),
        'start_order_eur': config.get('BASE_AMOUNT_EUR', 45.0),
        'min_entry_eur': config.get('MIN_BALANCE_EUR', 15),
        'min_balance_eur': config.get('MIN_BALANCE_EUR', 5),
        'max_exposure_eur': config.get('MAX_TOTAL_EXPOSURE_EUR', 350),
        'exchange_min_order': 5,
        'max_entry_eur': config.get('BASE_AMOUNT_EUR', 45.0),
        'rsi_max_dca': config.get('RSI_DCA_THRESHOLD', 55),
        'min_volume_1m': config.get('MIN_AVG_VOLUME_1M', 5),
        'max_spread_pct': config.get('MAX_SPREAD_PCT', 0.002),
        'dca_amount_eur': config.get('DCA_AMOUNT_EUR', 26.5),
        'max_per_cycle': config.get('DCA_MAX_BUYS', 5),
        'dca_size_multiplier': config.get('DCA_SIZE_MULTIPLIER', 1.5),
        'dca_step_multiplier': config.get('DCA_STEP_MULTIPLIER', 1.2),
        'bot_id': config.get('BOT_ID', 'Bitvavo DCA Bot'),
        'max_dca_orders': config.get('DCA_MAX_BUYS', 5),
    }
    
    # Get whitelist, blacklist and available markets from config
    whitelist = config.get('WHITELIST_MARKETS', [])
    blacklist = config.get('BLACKLIST_MARKETS', [])
    available_markets = whitelist.copy() if whitelist else []
    
    # Try to get all markets from Bitvavo if whitelist is empty
    if not available_markets:
        try:
            bitvavo = get_bitvavo()
            if bitvavo:
                all_markets = bitvavo.markets({})
                available_markets = [m['market'] for m in all_markets if m['market'].endswith('-EUR')]
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            available_markets = ['BTC-EUR', 'ETH-EUR', 'XRP-EUR', 'ADA-EUR', 'DOT-EUR', 'LINK-EUR']
    
    # Active strategy name
    active_strategy = config.get('ENTRY_STRATEGY', 'dca').upper()
    
    # Last modified timestamp (from heartbeat or config file)
    try:
        import os
        from datetime import datetime
        config_mtime = os.path.getmtime(CONFIG_PATH)
        last_modified = datetime.fromtimestamp(config_mtime).strftime('%Y-%m-%d %H:%M')
    except:
        last_modified = 'Unknown'
    
    strategies = ['dca', 'breakout', 'pullback', 'support']
    
    # AI-controlled parameters list - determines which params have AI toggle checked
    ai_controlled = config.get('AI_CONTROLLED_PARAMS', [
        'max_open_trades', 'start_order_eur', 'min_score_entry',
        'rsi_oversold', 'rsi_overbought', 'dca_trigger_pct',
        'take_profit_pct', 'trailing_stop_pct'
    ])
    
    return render_template('parameters.html',
        config=config,
        params=params,
        active_strategy=active_strategy,
        last_modified=last_modified,
        strategies=strategies,
        whitelist=whitelist,
        blacklist=blacklist,
        available_markets=available_markets,
        ai_controlled=ai_controlled,
        heartbeat=heartbeat,
        bot_online=is_bot_online(heartbeat, config),
        active_tab='parameters',
    )

@app.route('/performance')
def performance():
    """Performance & P/L page."""
    trades = load_trades()
    metrics = load_metrics()
    
    closed_trades_raw = trades.get('closed', [])
    
    # Filter out dust trades (invested < €0.10) and add proper invested field
    closed_trades = []
    for trade in closed_trades_raw:
        # Use invested_eur (current exposure) for display
        invested = float(trade.get('invested_eur') or trade.get('total_invested_eur') or trade.get('initial_invested_eur') or 
                        (trade.get('buy_price', 0) * trade.get('amount', 0)) or 0)
        if invested >= 0.10:  # Skip dust trades
            trade['invested'] = invested
            closed_trades.append(trade)
    
    # Calculate performance stats
    total_profit = sum(t.get('profit', 0) for t in closed_trades if t.get('profit', 0) > 0)
    total_loss = abs(sum(t.get('profit', 0) for t in closed_trades if t.get('profit', 0) < 0))
    total_pnl = total_profit - total_loss
    net_profit = total_pnl
    win_rate = len([t for t in closed_trades if t.get('profit', 0) > 0]) / len(closed_trades) * 100 if closed_trades else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 0.0
    
    # Calculate P/L by market
    pnl_by_market_dict = {}
    for trade in closed_trades:
        market = trade.get('market', 'UNKNOWN')
        profit = trade.get('profit', 0)
        invested = trade.get('invested', 0)
        if market not in pnl_by_market_dict:
            pnl_by_market_dict[market] = {'pnl': 0, 'trades': 0, 'invested': 0, 'wins': 0}
        pnl_by_market_dict[market]['pnl'] += profit
        pnl_by_market_dict[market]['trades'] += 1
        pnl_by_market_dict[market]['invested'] += invested
        if profit > 0:
            pnl_by_market_dict[market]['wins'] += 1
    
    # Convert to list with all required fields
    pnl_by_market = [
        {
            'market': market,
            'pnl': data['pnl'],
            'trades': data['trades'],
            'invested': data['invested'],
            'current_value': data['invested'] + data['pnl'],
            'roi': (data['pnl'] / data['invested'] * 100) if data['invested'] > 0 else 0,
            'win_rate': (data['wins'] / data['trades'] * 100) if data['trades'] > 0 else 0
        }
        for market, data in pnl_by_market_dict.items()
    ]
    
    # Monthly performance from REAL closed trades
    import datetime
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    monthly_data = {}  # key: (year, month) -> {pnl, trades, wins, invested}
    for trade in closed_trades:
        close_ts = trade.get('close_ts') or trade.get('timestamp') or 0
        if close_ts > 0:
            try:
                dt = datetime.datetime.fromtimestamp(close_ts)
                key = (dt.year, dt.month)
                if key not in monthly_data:
                    monthly_data[key] = {'pnl': 0, 'trades': 0, 'wins': 0, 'invested': 0}
                monthly_data[key]['pnl'] += trade.get('profit', 0)
                monthly_data[key]['trades'] += 1
                monthly_data[key]['invested'] += trade.get('invested', 0)
                if trade.get('profit', 0) > 0:
                    monthly_data[key]['wins'] += 1
            except Exception:
                pass
    
    monthly_performance = []
    for (year, month), data in sorted(monthly_data.items()):
        wr = (data['wins'] / data['trades'] * 100) if data['trades'] > 0 else 0
        pnl_pct = (data['pnl'] / data['invested'] * 100) if data['invested'] > 0 else 0
        monthly_performance.append({
            'name': month_names[month - 1],
            'year': year,
            'pnl': round(data['pnl'], 2),
            'pnl_pct': round(pnl_pct, 1),
            'trades': data['trades'],
            'win_rate': round(wr, 1),
        })
    
    # Calculate CORRECT total invested: Current open trades + deposits (NOT sum of all closed trades!)
    # OLD WRONG WAY: total_invested = sum(abs(t.get('invested', 0)) for t in closed_trades)  # THIS COUNTS SAME MONEY MULTIPLE TIMES!
    
    # Get current open trades investment (invested_eur = current exposure)
    open_trades = trades.get('open', {})
    total_open_invested = sum(t.get('invested_eur', t.get('total_invested_eur', 0)) for t in open_trades.values())
    
    # Get total deposits from deposits.json
    deposits_path = PROJECT_ROOT / 'data' / 'deposits.json'
    total_deposits = 0
    if deposits_path.exists():
        try:
            deposits_data = json.load(open(deposits_path))
            total_deposits = sum(d.get('amount', 0) for d in deposits_data.get('deposits', []))
        except:
            pass
    
    # Total invested = deposits (or fallback to sum of unique markets first investment)
    if total_deposits > 0:
        total_invested = total_deposits
    else:
        # Fallback: Track unique markets and take MAX invested per market (approximation)
        market_max_invested = {}
        for trade in closed_trades:
            market = trade.get('market')
            invested = trade.get('invested', 0)
            if market not in market_max_invested or invested > market_max_invested[market]:
                market_max_invested[market] = invested
        total_invested = sum(market_max_invested.values()) + total_open_invested
    
    # Current value = open trades value + total realized P/L from closed
    current_open_value = 0
    for market, trade in open_trades.items():
        try:
            live_price = get_live_price(market)
            amount = trade.get('amount', 0)
            current_open_value += live_price * amount
        except:
            # Fallback to buy price if live price unavailable
            buy_price = trade.get('buy_price', 0)
            amount = trade.get('amount', 0)
            current_open_value += buy_price * amount
    
    current_value = current_open_value + total_pnl  # Open position value + realized profits
    
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0
    avg_trade_size = (total_invested / len(closed_trades)) if closed_trades else 0.0
    
    # Realized vs Unrealized P/L
    realized_pnl = total_pnl  # From closed trades
    
    # Unrealized P/L from open trades
    unrealized_pnl = 0
    for market, trade in open_trades.items():
        try:
            live_price = get_live_price(market)
            amount = trade.get('amount', 0)
            current_val = live_price * amount
            invested = trade.get('invested_eur', trade.get('total_invested_eur', 0))
            unrealized_pnl += (current_val - invested)
        except Exception as e:
            logger.warning(f"[PERFORMANCE] Could not calculate unrealized P/L for {market}: {e}")
            pass
    
    # Best and worst trades
    best_trade_pnl = max([t.get('profit', 0) for t in closed_trades], default=0)
    worst_trade_pnl = min([t.get('profit', 0) for t in closed_trades], default=0)
    
    # Find best trade details
    best_trade = max(closed_trades, key=lambda t: t.get('profit', 0), default={})
    best_trade_market = best_trade.get('market', 'N/A')
    best_trade_invested = best_trade.get('invested', 1)
    best_trade_pct = (best_trade.get('profit', 0) / best_trade_invested * 100) if best_trade_invested > 0 else 0
    
    # Find worst trade details
    worst_trade = min(closed_trades, key=lambda t: t.get('profit', 0), default={})
    worst_trade_market = worst_trade.get('market', 'N/A')
    worst_trade_invested = worst_trade.get('invested', 1)
    worst_trade_pct = (worst_trade.get('profit', 0) / worst_trade_invested * 100) if worst_trade_invested > 0 else 0
    
    # Unrealized P/L already calculated above (from open trades with live prices)
    
    stats = {
        'total_profit': total_profit,
        'total_loss': total_loss,
        'net_profit': net_profit,
        'win_rate': win_rate,
        'trade_count': len(closed_trades),
    }
    
    # Calculate total trades for footer
    total_trades = len(closed_trades)
    
    # Generate P/L chart data (last 30 days) from REAL closed trades
    from datetime import datetime, timedelta
    
    pnl_dates = []
    pnl_values = []
    current_date = datetime.now()
    
    # Build daily P/L from actual closed trades
    daily_pnl = {}
    for trade in closed_trades:
        close_ts = trade.get('close_ts') or trade.get('timestamp') or 0
        if close_ts > 0:
            try:
                trade_date = datetime.fromtimestamp(close_ts).strftime('%Y-%m-%d')
                daily_pnl[trade_date] = daily_pnl.get(trade_date, 0) + trade.get('profit', 0)
            except Exception:
                pass
    
    cumulative_pnl = 0
    for i in range(30, -1, -1):
        date = current_date - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        pnl_dates.append(date.strftime('%d/%m'))
        cumulative_pnl += daily_pnl.get(date_str, 0)
        pnl_values.append(round(cumulative_pnl, 2))
    
    return render_template('performance.html',
        closed_trades=closed_trades[-50:],
        metrics=metrics,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        total_invested=total_invested,
        current_value=current_value,
        avg_trade_size=avg_trade_size,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        best_trade_pnl=best_trade_pnl,
        best_trade_pct=best_trade_pct,
        best_trade_market=best_trade_market,
        worst_trade_pnl=worst_trade_pnl,
        worst_trade_pct=worst_trade_pct,
        worst_trade_market=worst_trade_market,
        profit_factor=profit_factor,
        total_profit=total_profit,
        total_loss=total_loss,
        net_profit=net_profit,
        win_rate=win_rate,
        trade_count=len(closed_trades),
        total_trades=total_trades,
        stats=stats,
        pnl_by_market=pnl_by_market,
        monthly_performance=monthly_performance,
        pnl_dates=pnl_dates,
        pnl_values=pnl_values,
        active_tab='performance',
    )

@app.route('/analytics')
def analytics():
    """Analytics Studio page."""
    trades = load_trades()
    closed_trades = trades.get('closed', [])
    
    # Trade frequency by weekday
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekday_counts = {name: 0 for name in weekday_names}
    for t in closed_trades:
        ts = t.get('close_ts') or t.get('ts') or 0
        try:
            weekday = int(datetime.datetime.fromtimestamp(ts).weekday())
            weekday_counts[weekday_names[weekday]] += 1
        except Exception:
            continue
    trade_frequency = [{'name': name, 'count': weekday_counts[name]} for name in weekday_names]
    max_trades_day = max([d['count'] for d in trade_frequency] or [1])

    # Portfolio distribution from open trades by current value (fallback to even split)
    open_trades = trades.get('open', {}) or {}
    total_current = 0.0
    per_market = {}
    for mkt, trade in open_trades.items():
        try:
            live_price = get_live_price(mkt)
            amount = safe_float(trade.get('amount', 0))
            current_val = live_price * amount
            per_market[mkt] = current_val
            total_current += current_val
        except Exception:
            continue
    portfolio_distribution = []
    if total_current > 0:
        for mkt, val in per_market.items():
            pct = (val / total_current) * 100
            portfolio_distribution.append({'market': mkt, 'percentage': round(pct, 1)})
    else:
        portfolio_distribution = [
            {'market': 'BTC-EUR', 'percentage': 50.0},
            {'market': 'ETH-EUR', 'percentage': 30.0},
            {'market': 'Others', 'percentage': 20.0},
        ]
    
    # P/L distribution
    profit_trades = len([t for t in closed_trades if t.get('profit', 0) > 0])
    loss_trades = len([t for t in closed_trades if t.get('profit', 0) < 0])
    total = profit_trades + loss_trades or 1
    profit_pct = (profit_trades / total) * 100
    loss_pct = (loss_trades / total) * 100
    
    # Correlation matrix (mock data)
    markets = ['BTC', 'ETH', 'SOL', 'ADA']
    correlation_matrix = {
        'BTC': {'BTC': 1.0, 'ETH': 0.85, 'SOL': 0.72, 'ADA': 0.68},
        'ETH': {'BTC': 0.85, 'ETH': 1.0, 'SOL': 0.78, 'ADA': 0.74},
        'SOL': {'BTC': 0.72, 'ETH': 0.78, 'SOL': 1.0, 'ADA': 0.82},
        'ADA': {'BTC': 0.68, 'ETH': 0.74, 'SOL': 0.82, 'ADA': 1.0},
    }
    
    # Correlation chart data (horizontal bar chart)
    correlation_chart_data = {
        'labels': ['BTC-ETH', 'BTC-SOL', 'BTC-ADA', 'ETH-SOL', 'ETH-ADA', 'SOL-ADA'],
        'datasets': [{
            'label': 'Correlation',
            'data': [0.85, 0.72, 0.68, 0.78, 0.74, 0.82],
            'backgroundColor': [
                '#10B981' if v > 0.8 else '#F59E0B' if v > 0.5 else '#EF4444'
                for v in [0.85, 0.72, 0.68, 0.78, 0.74, 0.82]
            ]
        }]
    }
    
    # Time-of-day chart data from closed trades
    time_labels = ['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00']
    buckets = {lbl: [] for lbl in time_labels}
    for t in closed_trades:
        ts = t.get('close_ts') or t.get('ts') or 0
        profit = safe_float(t.get('profit') or t.get('pnl') or 0)
        try:
            hour = datetime.datetime.fromtimestamp(ts).hour
            bucket_idx = hour // 3
            buckets[time_labels[bucket_idx]].append(profit)
        except Exception:
            continue
    pnl_values = []
    for lbl in time_labels:
        vals = buckets.get(lbl, [])
        if vals:
            avg = sum(vals) / len(vals)
        else:
            avg = 0.0
        # Clamp to avoid runaway chart scale
        avg = max(-200.0, min(200.0, avg))
        pnl_values.append(round(avg, 2))
    time_chart_data = {
        'labels': time_labels,
        'pnl_values': pnl_values
    }
    
    def get_correlation_color(value):
        """Get color for correlation value."""
        if value > 0.8:
            return '#00ff88'
        elif value > 0.5:
            return '#ffaa00'
        else:
            return '#ff4444'
    
    # Calculate Sharpe Ratio (simplified - assumes 0% risk-free rate)
    profits = [t.get('profit', 0) for t in closed_trades]
    if len(profits) > 1:
        mean_return = sum(profits) / len(profits)
        variance = sum((p - mean_return) ** 2 for p in profits) / len(profits)
        std_dev = variance ** 0.5
        sharpe_ratio = (mean_return / std_dev) if std_dev > 0 else 0.0
        
        # Sortino Ratio (only penalizes downside volatility)
        downside_returns = [p for p in profits if p < 0]
        if downside_returns:
            downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
            downside_deviation = downside_variance ** 0.5
            sortino_ratio = (mean_return / downside_deviation) if downside_deviation > 0 else 0.0
        else:
            sortino_ratio = 0.0
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0
    
    # Calculate max drawdown (simplified - percentage from peak)
    max_drawdown = 0.0
    drawdown_peak = 0.0
    drawdown_trough = 0.0
    if closed_trades:
        running_pnl = 0
        peak = 0
        trough = 0
        for trade in closed_trades:
            running_pnl += trade.get('profit', 0)
            if running_pnl > peak:
                peak = running_pnl
                drawdown_peak = peak
            if running_pnl < trough or trough == 0:
                trough = running_pnl
                drawdown_trough = trough
            drawdown = ((peak - running_pnl) / peak * 100) if peak > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    
    # Calmar Ratio (annualized return / max drawdown)
    annual_return_pct = sum(t.get('profit', 0) for t in closed_trades) * 12  # Simple annualization
    calmar_ratio = (annual_return_pct / max_drawdown) if max_drawdown > 0 else 0.0
    
    return render_template('analytics.html', 
        trade_frequency=trade_frequency,
        max_trades_day=max_trades_day,
        portfolio_distribution=portfolio_distribution,
        profit_pct=profit_pct,
        loss_pct=loss_pct,
        correlation_matrix=correlation_matrix,
        correlation_chart_data=correlation_chart_data,
        time_chart_data=time_chart_data,
        markets=markets,
        get_correlation_color=get_correlation_color,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        max_drawdown=max_drawdown,
        drawdown_peak=drawdown_peak,
        drawdown_trough=drawdown_trough,
        winning_trades=profit_trades,
        losing_trades=loss_trades,
        duration_analysis=[],
        size_analysis=[],
        time_analysis=[],
        correlation_markets=markets,
        active_tab='analytics'
    )

@app.route('/reports')
def reports():
    """Reports & Logs page."""
    trades = load_trades()
    heartbeat = load_heartbeat()
    config = load_config()
    
    # All trades for log
    all_trades = trades.get('closed', []) + list(trades.get('open', {}).values())
    
    # System logs from real bot.log file
    system_logs = []
    log_path = PROJECT_ROOT / 'logs' / 'bot.log'
    if log_path.exists():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-50:]
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(' | ', 2)
                if len(parts) >= 3:
                    log_ts, log_level, log_msg = parts[0].strip(), parts[1].strip(), parts[2].strip()
                elif len(parts) == 2:
                    log_ts, log_msg = parts[0].strip(), parts[1].strip()
                    log_level = 'INFO'
                else:
                    continue
                system_logs.append({
                    'timestamp': log_ts[:19],
                    'level': log_level.upper(),
                    'message': log_msg[:300],
                })
                if len(system_logs) >= 25:
                    break
        except Exception as e:
            logger.warning(f"Could not read bot.log for reports: {e}")
            system_logs = [{'timestamp': '-', 'level': 'WARNING', 'message': f'Kan bot.log niet lezen: {e}'}]
    
    # Bot heartbeat status
    bot_heartbeat = {
        'status': 'online' if is_bot_online(heartbeat, config) else 'offline',
        'last_update': heartbeat.get('ts', 0),
        'trades_today': len([t for t in trades.get('closed', []) if t.get('close_ts', 0) > time.time() - 86400]),
    }
    
    ai_heartbeat = {
        'status': 'online' if heartbeat.get('ai_active', False) else 'offline',  # Use heartbeat field
        'last_update': 0,
    }
    
    dashboard_heartbeat = {
        'status': 'online',
        'uptime': int(time.time()),
    }
    
    # Performance reports generated from actual trade data
    import datetime as _dt
    now = _dt.datetime.now()
    reports_list = [
        {'name': f'Dagrapport {now.strftime("%Y-%m-%d")}', 'type': 'daily', 'date': now.strftime('%Y-%m-%d')},
        {'name': f'Weekrapport W{now.isocalendar()[1]}', 'type': 'weekly', 'date': (now - _dt.timedelta(days=now.weekday())).strftime('%Y-%m-%d')},
        {'name': f'Maandrapport {now.strftime("%b %Y")}', 'type': 'monthly', 'date': now.strftime('%Y-%m-01')},
    ]
    
    # Pagination data
    total_pages = max(1, (len(all_trades) + 19) // 20)  # 20 items per page
    
    # Active users (mock data - would track actual users)
    active_users = 1
    
    return render_template('reports.html', 
        all_trades=all_trades,
        trade_log=all_trades,
        system_logs=system_logs,
        bot_heartbeat=bot_heartbeat,
        ai_heartbeat=ai_heartbeat,
        dashboard_heartbeat=dashboard_heartbeat,
        reports_list=reports_list,
        total_pages=total_pages,
        active_users=active_users,
        active_tab='reports'
    )

# =====================================================
# FLASK ROUTES - ACTIONS
# =====================================================

@app.route('/api/config/update', methods=['POST'])
def update_config():
    """Update bot configuration."""
    try:
        updates = request.get_json()
        if not updates:
            return jsonify({'error': 'No data provided'}), 400
        
        config = load_config(force=True)
        config.update(updates)
        
        write_json_compat(str(CONFIG_PATH), config, indent=2)
        set_cached('config', config)
        
        return jsonify({'status': 'ok', 'message': 'Configuration updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =====================================================
# DEPOSIT MANAGEMENT API ENDPOINTS
# =====================================================

@app.route('/api/deposits')
def get_deposits():
    """Get all deposits with details."""
    try:
        data = load_deposits()
        # Ensure entries are sorted by date (newest first)
        entries = data.get('deposits', [])
        entries.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        total = _sum_deposit_entries(data)
        return jsonify({
            'status': 'ok',
            'total_deposited_eur': round(total, 2),
            'deposits': entries,
            'last_synced': data.get('last_synced', ''),
            'sync_source': data.get('sync_source', 'manual')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/deposits/add', methods=['POST'])
def add_deposit():
    """Add a new deposit entry manually."""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': 'No data provided'}), 400
        
        amount = float(req.get('amount', 0))
        if amount <= 0:
            return jsonify({'error': 'Amount must be positive'}), 400
        
        date_str = req.get('date', '')
        note = req.get('note', 'Handmatige storting')
        
        # Parse date or use current
        if date_str:
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                timestamp = int(dt.timestamp() * 1000)
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        else:
            dt = datetime.now()
            date_str = dt.strftime('%Y-%m-%d')
            timestamp = int(dt.timestamp() * 1000)
        
        # Load current deposits
        data = load_deposits()
        deposits = data.get('deposits', [])
        
        # Add new entry
        new_entry = {
            'amount': round(amount, 2),
            'timestamp': timestamp,
            'date': date_str,
            'note': note
        }
        deposits.append(new_entry)
        
        # Sort by timestamp (newest first)
        deposits.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Calculate new total
        total = round(sum(float(d.get('amount', 0)) for d in deposits), 2)
        
        # Save
        data['deposits'] = deposits
        data['total_deposited_eur'] = total
        data['last_modified'] = datetime.now(timezone.utc).isoformat()
        
        with DEPOSITS_FILE.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Added deposit: €{amount:.2f} on {date_str}")
        return jsonify({
            'status': 'ok',
            'message': f'Storting van €{amount:.2f} toegevoegd',
            'total_deposited_eur': total,
            'entry': new_entry
        })
    except Exception as e:
        logger.error(f"Failed to add deposit: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/deposits/update', methods=['POST'])
def update_deposit():
    """Update an existing deposit entry."""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': 'No data provided'}), 400
        
        timestamp = req.get('timestamp')
        if not timestamp:
            return jsonify({'error': 'Timestamp is required to identify deposit'}), 400
        
        new_amount = req.get('amount')
        new_date = req.get('date')
        new_note = req.get('note')
        
        # Load current deposits
        data = load_deposits()
        deposits = data.get('deposits', [])
        
        # Find and update entry
        found = False
        for entry in deposits:
            if entry.get('timestamp') == timestamp:
                if new_amount is not None:
                    entry['amount'] = round(float(new_amount), 2)
                if new_date:
                    entry['date'] = new_date
                    try:
                        dt = datetime.strptime(new_date, '%Y-%m-%d')
                        entry['timestamp'] = int(dt.timestamp() * 1000)
                    except ValueError:
                        pass
                if new_note is not None:
                    entry['note'] = new_note
                found = True
                break
        
        if not found:
            return jsonify({'error': 'Deposit not found'}), 404
        
        # Recalculate total
        total = round(sum(float(d.get('amount', 0)) for d in deposits), 2)
        
        # Save
        data['deposits'] = deposits
        data['total_deposited_eur'] = total
        data['last_modified'] = datetime.now(timezone.utc).isoformat()
        
        with DEPOSITS_FILE.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Updated deposit (ts={timestamp})")
        return jsonify({
            'status': 'ok',
            'message': 'Storting bijgewerkt',
            'total_deposited_eur': total
        })
    except Exception as e:
        logger.error(f"Failed to update deposit: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/deposits/delete', methods=['POST'])
def delete_deposit():
    """Delete a deposit entry."""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': 'No data provided'}), 400
        
        timestamp = req.get('timestamp')
        if not timestamp:
            return jsonify({'error': 'Timestamp is required to identify deposit'}), 400
        
        # Load current deposits
        data = load_deposits()
        deposits = data.get('deposits', [])
        
        # Filter out the entry
        original_len = len(deposits)
        deposits = [d for d in deposits if d.get('timestamp') != timestamp]
        
        if len(deposits) == original_len:
            return jsonify({'error': 'Deposit not found'}), 404
        
        # Recalculate total
        total = round(sum(float(d.get('amount', 0)) for d in deposits), 2)
        
        # Save
        data['deposits'] = deposits
        data['total_deposited_eur'] = total
        data['last_modified'] = datetime.now(timezone.utc).isoformat()
        
        with DEPOSITS_FILE.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Deleted deposit (ts={timestamp})")
        return jsonify({
            'status': 'ok',
            'message': 'Storting verwijderd',
            'total_deposited_eur': total
        })
    except Exception as e:
        logger.error(f"Failed to delete deposit: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/deposits/sync', methods=['POST'])
def sync_deposits():
    """Force sync deposits from Bitvavo API."""
    try:
        data = sync_deposits_from_bitvavo()
        total = _sum_deposit_entries(data)
        return jsonify({
            'status': 'ok',
            'message': 'Stortingen gesynchroniseerd met Bitvavo',
            'total_deposited_eur': round(total, 2),
            'deposits': data.get('deposits', [])
        })
    except Exception as e:
        logger.error(f"Failed to sync deposits: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/strategy/save', methods=['POST'])
def save_strategy_parameters():
    """Save strategy parameters to bot_config.json."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        config_path = PROJECT_ROOT / 'config' / 'bot_config.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        
        # Map form fields to config keys with proper type conversion
        field_mapping = {
            # Trading parameters
            'base_amount_eur': ('BASE_AMOUNT_EUR', float),
            'start_order_eur': ('BASE_AMOUNT_EUR', float),
            'max_active_trades': ('MAX_ACTIVE_TRADES', int),
            'max_open_trades': ('MAX_OPEN_TRADES', int),
            'max_portfolio_value': ('MAX_PORTFOLIO_VALUE', float),
            'max_exposure_eur': ('MAX_TOTAL_EXPOSURE_EUR', float),
            'min_balance_reserve': ('MIN_BALANCE_RESERVE', float),
            'max_trade_size': ('MAX_TRADE_SIZE', float),
            'max_trade_size_pct': ('MAX_TRADE_SIZE_PCT', float),
            'min_trade_size': ('MIN_TRADE_SIZE', float),
            'min_entry_eur': ('MIN_ENTRY_EUR', float),
            'max_entry_eur': ('MAX_ENTRY_EUR', float),
            'exchange_min_order': ('MIN_ORDER_EUR', float),
            'scan_interval': ('SLEEP_SECONDS', int),
            'min_score_entry': ('MIN_SCORE_TO_BUY', float),
            'min_balance_eur': ('MIN_BALANCE_EUR', float),
            
            # TP/SL parameters
            'take_profit_pct': ('TAKE_PROFIT_TARGET', lambda x: float(x) / 100),
            'stop_loss_pct': ('STOP_LOSS_PERCENT', lambda x: float(x) / 100),
            'trailing_stop_pct': ('DEFAULT_TRAILING', lambda x: float(x) / 100),
            'default_trailing': ('DEFAULT_TRAILING', lambda x: float(x) / 100),
            'trailing_activation_pct': ('TRAILING_ACTIVATION_PCT', lambda x: float(x) / 100),
            'hard_sl_alt_pct': ('HARD_SL_ALT_PCT', lambda x: float(x) / 100),
            'hard_sl_btceth_pct': ('HARD_SL_BTCETH_PCT', lambda x: float(x) / 100),
            'stop_loss_enabled': ('STOP_LOSS_ENABLED', bool),
            
            # DCA parameters
            'dca_enabled': ('DCA_ENABLED', bool),
            'dca_max_buys': ('DCA_MAX_BUYS', int),
            'max_dca_orders': ('DCA_MAX_BUYS', int),
            'dca_trigger_pct': ('DCA_DROP_PCT', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'dca_drop_pct': ('DCA_DROP_PCT', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'dca_step_pct': ('DCA_STEP_PCT', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'dca_amount_eur': ('DCA_AMOUNT_EUR', float),
            'dca_order_eur': ('DCA_AMOUNT_EUR', float),
            'dca_size_multiplier': ('DCA_SIZE_MULTIPLIER', float),
            'dca_multiplier': ('DCA_SIZE_MULTIPLIER', float),
            'dca_step_multiplier': ('DCA_STEP_MULTIPLIER', float),
            'max_per_cycle': ('DCA_MAX_BUYS_PER_ITERATION', int),
            'dynamic_dca': ('DCA_DYNAMIC', bool),
            
            # Partial Take-Profit
            'partial_tp_enabled': ('TAKE_PROFIT_ENABLED', bool),
            'tp_target_1': ('TAKE_PROFIT_TARGET_1', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'tp_target_2': ('TAKE_PROFIT_TARGET_2', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'tp_target_3': ('TAKE_PROFIT_TARGET_3', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'tp_sell_pct_1': ('PARTIAL_TP_SELL_PCT_1', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'tp_sell_pct_2': ('PARTIAL_TP_SELL_PCT_2', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'tp_sell_pct_3': ('PARTIAL_TP_SELL_PCT_3', lambda x: float(x) / 100 if x >= 1 else float(x)),
            
            # Trailing Entry
            'trailing_entry_enabled': ('TRAILING_ENTRY_ENABLED', bool),
            'trailing_entry_pullback_pct': ('TRAILING_ENTRY_PULLBACK_PCT', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'trailing_entry_timeout_s': ('TRAILING_ENTRY_TIMEOUT_S', int),
            
            # Performance Filter
            'performance_filter_enabled': ('PERFORMANCE_FILTER_ENABLED', bool),
            'performance_filter_min_trades': ('PERFORMANCE_FILTER_MIN_TRADES', int),
            'performance_filter_min_winrate': ('PERFORMANCE_FILTER_MIN_WINRATE', float),
            'performance_filter_max_consec_losses': ('PERFORMANCE_FILTER_MAX_CONSEC_LOSSES', int),
            
            # Watchlist
            'watchlist_micro_size_eur': ('WATCHLIST_MICRO_SIZE_EUR', float),
            'watchlist_confidence_threshold': ('WATCHLIST_CONFIDENCE_THRESHOLD', float),
            
            # Reinvest
            'reinvest_enabled': ('REINVEST_ENABLED', bool),
            'reinvest_portion': ('REINVEST_PORTION', float),
            'reinvest_min_trades': ('REINVEST_MIN_TRADES', int),
            'reinvest_min_profit': ('REINVEST_MIN_PROFIT', float),
            'reinvest_max_increase_pct': ('REINVEST_MAX_INCREASE_PCT', lambda x: float(x) / 100 if x >= 1 else float(x)),
            'reinvest_cap': ('REINVEST_CAP', float),
            
            # Full Balance
            'auto_use_full_balance': ('AUTO_USE_FULL_BALANCE', bool),
            'full_balance_portion': ('FULL_BALANCE_PORTION', float),
            'full_balance_max_eur': ('FULL_BALANCE_MAX_EUR', float),
            
            # Market Filters
            'min_daily_volume_eur': ('MIN_DAILY_VOLUME_EUR', float),
            'min_price_eur': ('MIN_PRICE_EUR', float),
            'max_price_eur': ('MAX_PRICE_EUR', float),
            
            # Order Settings
            'order_type': ('ORDER_TYPE', str),
            'open_trade_cooldown_seconds': ('OPEN_TRADE_COOLDOWN_SECONDS', int),
            'config_hot_reload_seconds': ('CONFIG_HOT_RELOAD_SECONDS', int),
            
            # Sync
            'sync_enabled': ('SYNC_ENABLED', bool),
            'sync_interval_seconds': ('SYNC_INTERVAL_SECONDS', int),
            
            # Technical indicators
            'rsi_oversold': ('RSI_MIN_BUY', float),
            'rsi_overbought': ('RSI_MAX_BUY', float),
            'rsi_max_dca': ('RSI_DCA_THRESHOLD', float),
            'rsi_period': ('RSI_PERIOD', int),
            'rsi_min_buy': ('RSI_MIN_BUY', float),
            'rsi_max_buy': ('RSI_MAX_BUY', float),
            'rsi_dca_threshold': ('RSI_DCA_THRESHOLD', float),
            'macd_fast': ('MACD_FAST', int),
            'macd_slow': ('MACD_SLOW', int),
            'macd_signal': ('MACD_SIGNAL', int),
            'sma_short': ('SMA_SHORT', int),
            'sma_long': ('SMA_LONG', int),
            'bollinger_window': ('BOLLINGER_WINDOW', int),
            'stoch_window': ('STOCHASTIC_WINDOW', int),
            'atr_period': ('ATR_PERIOD', int),
            'min_volume_1m': ('MIN_AVG_VOLUME_1M', float),
            'max_spread_pct': ('MAX_SPREAD_PCT', lambda x: float(x)),
            
            # Signal settings
            'min_score_to_buy': ('MIN_SCORE_TO_BUY', float),
            'signals_global_weight': ('SIGNALS_GLOBAL_WEIGHT', float),
            'breakout_lookback': ('BREAKOUT_LOOKBACK', int),
            
            # Advanced settings
            'scan_interval': ('SLEEP_SECONDS', int),
            'max_spread_pct': ('MAX_SPREAD_PCT', lambda x: float(x) / 100),
            'min_avg_volume_1m': ('MIN_AVG_VOLUME_1M', float),
            'atr_multiplier': ('ATR_MULTIPLIER', float),
            'atr_window_1m': ('ATR_WINDOW_1M', int),
            
            # AI Controller flags
            'ai_entry_control': ('AI_ENTRY_CONTROL', bool),
            'ai_exit_control': ('AI_EXIT_CONTROL', bool),
            'ai_dca_control': ('AI_DCA_CONTROL', bool),
            'ai_risk_control': ('AI_RISK_CONTROL', bool),
            'ai_tp_control': ('AI_TP_CONTROL', bool),
            'ai_sl_control': ('AI_SL_CONTROL', bool),

            # Telegram notifications
            'telegram_enabled': ('TELEGRAM_ENABLED', bool),
            'telegram_bot_token': ('TELEGRAM_BOT_TOKEN', str),
            'telegram_chat_id': ('TELEGRAM_CHAT_ID', str),
        }
        
        # Update config with form data
        updated_count = 0
        for form_field, (config_key, converter) in field_mapping.items():
            if form_field in data:
                try:
                    if callable(converter):
                        config[config_key] = converter(data[form_field])
                    else:
                        config[config_key] = converter(data[form_field])
                    updated_count += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to convert {form_field}: {e}")
        
        # Budget split (BUDGET_RESERVATION nested dict)
        if 'grid_pct' in data:
            try:
                grid_pct = int(data['grid_pct'])
                grid_pct = max(0, min(100, grid_pct))
                trailing_pct = 100 - grid_pct
                if 'BUDGET_RESERVATION' not in config or not isinstance(config['BUDGET_RESERVATION'], dict):
                    config['BUDGET_RESERVATION'] = {}
                config['BUDGET_RESERVATION']['grid_pct'] = grid_pct
                config['BUDGET_RESERVATION']['trailing_pct'] = trailing_pct
                updated_count += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to convert grid_pct: {e}")

        # Write updated config
        write_json_compat(str(config_path), config, indent=2)
        load_config(force=True)  # Reload cached config
        
        return jsonify({
            'status': 'ok',
            'message': f'Parameters saved successfully ({updated_count} fields updated)',
            'updated_count': updated_count
        })
        
    except Exception as e:
        logger.error(f"Error saving parameters: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/strategy/reset', methods=['POST'])
def reset_strategy_parameters():
    """Reset parameters to safe defaults."""
    try:
        config_path = PROJECT_ROOT / 'config' / 'bot_config.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        
        # Safe conservative defaults
        defaults = {
            'BASE_AMOUNT_EUR': 10.0,
            'MAX_ACTIVE_TRADES': 5,
            'MAX_OPEN_TRADES': 5,
            'TAKE_PROFIT_TARGET': 0.05,
            'STOP_LOSS_PERCENT': 0.08,
            'DEFAULT_TRAILING': 0.07,
            'TRAILING_ACTIVATION_PCT': 0.02,
            'DCA_ENABLED': True,
            'DCA_MAX_BUYS': 3,
            'DCA_DROP_PCT': 0.05,
            'DCA_ORDER_EUR': 7.0,
            'RSI_MIN_BUY': 30.0,
            'RSI_MAX_BUY': 65.0,
            'MIN_SCORE_TO_BUY': 5.0,
        }
        
        config.update(defaults)
        write_json_compat(str(config_path), config, indent=2)
        load_config(force=True)
        
        return jsonify({'status': 'ok', 'message': 'Parameters reset to defaults'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/strategy/export')
def export_strategy_parameters():
    """Export current parameters as JSON file."""
    try:
        config = load_config()
        
        # Create export with metadata
        export_data = {
            'exported_at': datetime.now().isoformat(),
            'bot_version': '3.0',
            'parameters': config
        }
        
        response = Response(
            json.dumps(export_data, indent=2),
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment;filename=strategy_params_{datetime.now().strftime("%Y%m%d")}.json'
            }
        )
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/refresh', methods=['POST'])
def force_refresh():
    """Force refresh all cached data."""
    load_config(force=True)
    load_trades(force=True)
    load_heartbeat(force=True)
    load_metrics(force=True)
    
    return jsonify({'status': 'ok', 'message': 'Cache refreshed'})


@app.route('/api/telegram/test', methods=['POST'])
def telegram_test():
    """Send a test Telegram message with the given token + chat_id."""
    try:
        data = request.get_json(force=True) or {}
        token = str(data.get('token', '')).strip()
        chat_id = str(data.get('chat_id', '')).strip()
        if not token or not chat_id:
            return jsonify({'status': 'error', 'error': 'Token en Chat ID zijn verplicht'})
        import urllib.request, json as _json
        msg = '✅ Bitvavo Bot verbonden! Notificaties zijn actief.'
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        payload = _json.dumps({'chat_id': chat_id, 'text': msg}).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
        if result.get('ok'):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'error': result.get('description', 'Onbekende fout')})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


@app.route('/notifications')
def notifications():
    """Notifications & Alerts page."""
    import time
    from datetime import datetime
    
    # Build real alerts from closed trades (last 20)
    trades = load_trades()
    closed_trades_raw = trades.get('closed', [])
    sorted_trades = sorted(closed_trades_raw, key=lambda t: t.get('close_ts', t.get('timestamp', 0)), reverse=True)[:20]
    
    alerts = []
    for t in sorted_trades:
        ts = t.get('close_ts') or t.get('timestamp') or 0
        profit = t.get('profit', 0)
        market = t.get('market', 'UNKNOWN')
        reason = t.get('reason', 'unknown')
        try:
            ts_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts > 0 else '-'
        except Exception:
            ts_str = '-'
        
        if profit >= 0:
            alert_type, icon, title = 'success', '✅', 'Positie Gesloten (Winst)'
            message = f'{market} — +€{profit:.2f} ({reason})'
        else:
            alert_type, icon, title = 'warning', '⚠️', 'Positie Gesloten (Verlies)'
            message = f'{market} — €{profit:.2f} ({reason})'
        
        alerts.append({
            'id': f'trade_{market}_{int(ts)}',
            'type': alert_type,
            'icon': icon,
            'title': title,
            'message': message,
            'timestamp': ts_str,
            'read': True,
        })
    
    # Build real audit log from bot.log (last 30 lines)
    audit_log = []
    log_path = PROJECT_ROOT / 'logs' / 'bot.log'
    if log_path.exists():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-30:]
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                # Parse log lines like "2025-12-17 14:30:25 | INFO | message"
                parts = line.split(' | ', 2)
                if len(parts) >= 3:
                    log_ts, log_level, log_msg = parts[0].strip(), parts[1].strip(), parts[2].strip()
                elif len(parts) == 2:
                    log_ts, log_msg = parts[0].strip(), parts[1].strip()
                    log_level = 'INFO'
                else:
                    log_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_level = 'INFO'
                    log_msg = line[:200]
                
                event_type = 'error' if 'ERROR' in log_level.upper() else 'system'
                audit_log.append({
                    'timestamp': log_ts[:19],
                    'type': event_type,
                    'event': log_level,
                    'details': log_msg[:200],
                    'user': 'System',
                })
                if len(audit_log) >= 20:
                    break
        except Exception as e:
            logger.warning(f"Could not read bot.log for notifications: {e}")
    
    # Calculate stats
    unread_count = 0
    today_count = len([a for a in alerts if a.get('timestamp', '') >= datetime.now().strftime('%Y-%m-%d')])
    
    return render_template('notifications.html',
        alerts=alerts,
        audit_log=audit_log,
        unread_count=unread_count,
        today_count=today_count,
        active_tab='notifications'
    )

@app.route('/roadmap')
def roadmap():
    """Portfolio Roadmap page — growth plan from €465 to €5,000."""
    config = load_config()
    heartbeat = load_heartbeat()

    # Current portfolio value from account_overview or totals
    current_value = 0.0
    try:
        ao_path = PROJECT_ROOT / 'data' / 'account_overview.json'
        if ao_path.exists():
            with ao_path.open('r', encoding='utf-8') as f:
                ao = json.load(f)
            current_value = float(ao.get('total_account_value_eur', 0) or 0)
    except Exception:
        pass
    if current_value == 0:
        current_value = float(heartbeat.get('eur_balance', 0) or 0)

    total_deposited = get_total_deposited()

    # Milestones from PORTFOLIO_ROADMAP.md (hardcoded for fast rendering)
    milestones = [
        {'value': 465, 'label': '€465', 'action': 'Huidige config — stabiel draaien', 'icon': '🟢', 'star': False},
        {'value': 500, 'label': '€500', 'action': 'Geen wijzigingen — stabiel houden', 'icon': '📍', 'star': False},
        {'value': 600, 'label': '€600', 'action': 'BASE → 42', 'icon': '📍', 'star': False},
        {'value': 700, 'label': '€700', 'action': 'BASE → 48, DCA → 32', 'icon': '📍', 'star': False},
        {'value': 800, 'label': '€800', 'action': '4 trades, BASE → 52', 'icon': '📍', 'star': False},
        {'value': 900, 'label': '€900', 'action': 'BASE → 56, DCA → 34, trailing → 2,4%', 'icon': '📍', 'star': False},
        {'value': 1000, 'label': '€1.000', 'action': 'Grid BTC aan (€150)', 'icon': '⭐', 'star': True},
        {'value': 1100, 'label': '€1.100', 'action': 'BASE → 62', 'icon': '📍', 'star': False},
        {'value': 1200, 'label': '€1.200', 'action': '5 trades, MIN_SCORE → 6,5', 'icon': '📍', 'star': False},
        {'value': 1300, 'label': '€1.300', 'action': 'BASE → 68', 'icon': '📍', 'star': False},
        {'value': 1400, 'label': '€1.400', 'action': 'Grid ETH erbij (€250)', 'icon': '📍', 'star': False},
        {'value': 1500, 'label': '€1.500', 'action': 'BASE → 75, DCA → 40', 'icon': '📍', 'star': False},
        {'value': 1600, 'label': '€1.600', 'action': '6 trades', 'icon': '📍', 'star': False},
        {'value': 1800, 'label': '€1.800', 'action': 'Grid SOL erbij (€400)', 'icon': '📍', 'star': False},
        {'value': 2000, 'label': '€2.000', 'action': '7 trades, DCA 10 levels', 'icon': '⭐', 'star': True},
        {'value': 2500, 'label': '€2.500', 'action': 'Grid 4 markten (€600)', 'icon': '📍', 'star': False},
        {'value': 3000, 'label': '€3.000', 'action': '8 trades, Grid 5 mktn (€800)', 'icon': '⭐', 'star': True},
        {'value': 4000, 'label': '€4.000', 'action': '9 trades, Grid 6 mktn (€1.400)', 'icon': '📍', 'star': False},
        {'value': 5000, 'label': '€5.000', 'action': '10 trades, Grid €2.000 — Passief Inkomen', 'icon': '🏆', 'star': True},
    ]

    # Determine current milestone index
    current_idx = 0
    for i, m in enumerate(milestones):
        if current_value >= m['value']:
            current_idx = i

    progress_pct = min(100, max(0, (current_value / 5000) * 100))

    # Golden rules
    golden_rules = [
        'Nooit een stap overslaan — elke verhoging bouwt voort op bewezen stabiliteit',
        'Minimaal 2 weken wachten na elke config-wijziging',
        'Winrate check: moet ≥ 50% zijn over laatste 2 weken',
        'EUR buffer: houd ALTIJD minimaal 15% van portfoliowaarde vrij',
        'Grid pas bij €1.000+ met minimaal €40/level',
        'Bij 15% drawdown: ga terug naar vorige mijlpaal-config',
        'Eén ding tegelijk wijzigen — nooit alles tegelijk verhogen',
    ]

    # Deposit plan
    deposit_plan = [
        {'month': 'Mrt 2026', 'deposit': 100, 'cum': 870, 'est': 465, 'done': True},
        {'month': 'Apr 2026', 'deposit': 100, 'cum': 970, 'est': 521, 'done': False},
        {'month': 'Mei 2026', 'deposit': 100, 'cum': 1070, 'est': 581, 'done': False},
        {'month': 'Jun 2026', 'deposit': 100, 'cum': 1170, 'est': 645, 'done': False},
        {'month': 'Jul 2026', 'deposit': 100, 'cum': 1270, 'est': 713, 'done': False},
        {'month': 'Aug 2026', 'deposit': 100, 'cum': 1370, 'est': 785, 'done': False},
        {'month': 'Sep 2026', 'deposit': 100, 'cum': 1470, 'est': 861, 'done': False},
        {'month': 'Okt 2026', 'deposit': 100, 'cum': 1570, 'est': 945, 'done': False},
        {'month': 'Nov 2026', 'deposit': 100, 'cum': 1670, 'est': 1035, 'done': False},
        {'month': 'Dec 2026', 'deposit': 100, 'cum': 1770, 'est': 1135, 'done': False},
    ]

    # Expected earnings at target
    earnings_at_5k = {
        'trailing_day': 9.0,
        'grid_day': 1.6,
        'total_day': 10.5,
        'total_week': 73,
        'total_month': 315,
    }

    return render_template('roadmap.html',
        milestones=milestones,
        current_value=current_value,
        current_idx=current_idx,
        progress_pct=progress_pct,
        total_deposited=total_deposited,
        golden_rules=golden_rules,
        deposit_plan=deposit_plan,
        earnings_at_5k=earnings_at_5k,
        config=config,
        heartbeat=heartbeat,
        bot_running=is_bot_online(heartbeat, config),
        ai_running=heartbeat.get('ai_active', False),
        active_tab='roadmap',
    )


@app.route('/settings')
def settings():
    """Settings & Preferences page."""
    # Get current theme from cookie or default to 'dark'
    current_theme = request.cookies.get('theme', 'dark')
    
    # Security status checks
    api_key = os.getenv('BITVAVO_API_KEY', '')
    api_secret = os.getenv('BITVAVO_API_SECRET', '')
    env_file_path = PROJECT_ROOT / '.env'
    
    # Check bot and AI status
    config = load_config()
    heartbeat = load_heartbeat()
    bot_status = is_bot_online(heartbeat, config)
    ai_status = heartbeat.get('ai_active', False)  # Use heartbeat field
    
    # Determine exchange connection (based on API keys being present and valid)
    exchange_connected = bool(api_key and api_secret and len(api_key) > 20)
    
    # Load deposits for management
    deposits_data = load_deposits()
    deposits_list = deposits_data.get('deposits', [])
    # Sort by date descending
    deposits_list.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    total_deposited = _sum_deposit_entries(deposits_data)
    
    return render_template('settings.html',
        current_theme=current_theme,
        active_tab='settings',
        # Security status
        api_key_status=bool(api_key and len(api_key) > 20),
        api_secret_status=bool(api_secret and len(api_secret) > 20),
        exchange_connected=exchange_connected,
        bot_online=bot_status,
        ai_online=ai_status,
        env_file_exists=env_file_path.exists(),
        # Deposits
        deposits=deposits_list,
        total_deposited=total_deposited
    )

@app.route('/icons/<symbol>')
def serve_icon(symbol):
    """
    Serve local cryptocurrency icons from data/icons/ folder.
    
    Returns image file if exists, otherwise 404.
    Frontend should handle 404 with fallback to SVG.
    """
    try:
        symbol_clean = symbol.lower().replace('.png', '')
        icon_path = ICONS_DIR / f"{symbol_clean}.png"
        if not icon_path.exists():
            return jsonify({'error': 'Icon not found'}), 404
        # Auto-detect MIME type from file content (some .png are actually WebP)
        header = icon_path.read_bytes()[:4]
        mime = 'image/webp' if header[:4] == b'RIFF' else 'image/png'
        return send_from_directory(str(ICONS_DIR), f"{symbol_clean}.png", mimetype=mime)
    except FileNotFoundError:
        return jsonify({'error': 'Icon not found'}), 404

# =====================================================
# AI SUGGESTIONS API
# =====================================================

@app.route('/api/grid/activate', methods=['POST'])
def activate_grid():
    """Activate a grid trading strategy."""
    try:
        data = request.get_json()
        market = data.get('market')
        
        if not market:
            return jsonify({'success': False, 'error': 'Market required'}), 400
        
        from modules.grid_trading import GridManager
        from modules.bitvavo_client import get_bitvavo
        
        # Initialize GridManager with Bitvavo client
        bitvavo = get_bitvavo()
        grid_manager = GridManager(bitvavo_client=bitvavo)
        
        # Create grid from parameters
        grid_state = grid_manager.create_grid(
            market=market,
            lower_price=float(data.get('lower_price', 0)),
            upper_price=float(data.get('upper_price', 0)),
            num_grids=int(data.get('grid_count', 10)),
            total_investment=float(data.get('investment', 100)),
            grid_mode=data.get('mode', 'geometric'),
            auto_rebalance=data.get('auto_rebalance', True),
            stop_loss_pct=float(data.get('stop_loss_pct', 0)) / 100.0 if data.get('stop_loss_pct') else None,
            take_profit_pct=float(data.get('take_profit_pct', 0)) / 100.0 if data.get('take_profit_pct') else None,
        )
        
        # Start the grid
        success = grid_manager.start_grid(market)
        
        if success:
            logger.info(f"Grid activated for {market}")
            return jsonify({
                'success': True,
                'message': f'Grid activated for {market}',
                'grid_id': market,
                'levels': len(grid_state.levels)
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to start grid'}), 500
            
    except Exception as e:
        logger.error(f"Grid activation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/grid/status/<market>')
def grid_status(market):
    """Get detailed status of a specific grid with P&L breakdown."""
    try:
        from modules.grid_trading import GridManager
        grid_manager = GridManager()
        
        if market not in grid_manager.grids:
            return jsonify({'success': False, 'error': 'Grid not found'}), 404
        
        state = grid_manager.grids[market]
        config = state.config
        
        # Calculate detailed level stats
        levels_data = []
        buy_levels = []
        sell_levels = []
        placed_count = 0
        filled_count = 0
        cancelled_count = 0
        error_count = 0
        total_buy_value = 0
        total_sell_value = 0
        
        for level in state.levels:
            level_data = {
                'id': level.level_id,
                'price': level.price,
                'amount': level.amount,
                'side': level.side,
                'status': level.status,
                'order_id': level.order_id,
                'value_eur': round(level.amount * level.price, 2),
                'filled_price': getattr(level, 'filled_price', None),
                'filled_at': getattr(level, 'filled_at', None),
            }
            levels_data.append(level_data)
            
            if level.side == 'buy':
                buy_levels.append(level_data)
                if level.status == 'placed':
                    total_buy_value += level.amount * level.price
            else:
                sell_levels.append(level_data)
                if level.status == 'placed':
                    total_sell_value += level.amount * level.price
            
            if level.status == 'placed': placed_count += 1
            elif level.status == 'filled': filled_count += 1
            elif level.status == 'cancelled': cancelled_count += 1
            elif level.status == 'error': error_count += 1
        
        # ROI calculation
        roi_pct = (state.total_profit / config.total_investment * 100) if config.total_investment > 0 else 0
        
        # Grid spacing
        spacing_eur = (config.upper_price - config.lower_price) / max(1, config.num_grids - 1)
        spacing_pct = (spacing_eur / config.lower_price * 100) if config.lower_price > 0 else 0
        
        return jsonify({
            'success': True,
            'market': market,
            'status': state.status,
            'mode': config.grid_mode,
            'investment': config.total_investment,
            'profit': round(state.total_profit, 4),
            'fees': round(state.total_fees, 4),
            'net_profit': round(state.total_profit - state.total_fees, 4),
            'roi_pct': round(roi_pct, 2),
            'trades': state.total_trades,
            'current_price': state.current_price,
            'upper_price': config.upper_price,
            'lower_price': config.lower_price,
            'grid_spacing_eur': round(spacing_eur, 2),
            'grid_spacing_pct': round(spacing_pct, 2),
            'levels': levels_data,
            'buy_levels': len(buy_levels),
            'sell_levels': len(sell_levels),
            'placed_orders': placed_count,
            'filled_orders': filled_count,
            'cancelled_orders': cancelled_count,
            'error_orders': error_count,
            'total_buy_value': round(total_buy_value, 2),
            'total_sell_value': round(total_sell_value, 2),
            'base_balance': state.base_balance,
            'quote_balance': state.quote_balance,
            'last_update': state.last_update,
            'stop_loss_pct': config.stop_loss_pct,
            'take_profit_pct': config.take_profit_pct,
        })
    except Exception as e:
        logger.error(f"Grid status fetch failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/grid/stop/<market>', methods=['POST'])
def stop_grid(market):
    """Stop a grid trading strategy."""
    try:
        from modules.grid_trading import GridManager
        grid_manager = GridManager()
        
        success = grid_manager.stop_grid(market)
        
        if success:
            return jsonify({'success': True, 'message': f'Grid stopped for {market}'})
        else:
            return jsonify({'success': False, 'error': 'Grid not found'}), 404
    except Exception as e:
        logger.error(f"Grid stop failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/ai/grid-suggestions')
def ai_grid_suggestions():
    """
    Get AI-optimized grid bot suggestions using AIGridAdvisor.
    
    Features:
    - Volatility-based range calculation (not hardcoded ±10%)
    - Three risk profiles: Conservative, Balanced, Aggressive
    - Fee-compensated grid spacing
    - Market trend awareness
    - Grid score ranking for suitability
    - Bitvavo balance integration for investment suggestions
    """
    try:
        market = request.args.get('market')
        risk_profile = request.args.get('risk', 'balanced').lower()
        
        # Import AIGridAdvisor for sophisticated analysis
        try:
            from modules.grid_ai_advisor import AIGridAdvisor, get_ai_grid_advisor
            from modules.grid_trading import estimate_grid_profit
            ai_advisor_available = True
        except ImportError:
            ai_advisor_available = False
            logger.warning("AIGridAdvisor not available, using fallback")
        
        suggestions = []
        
        # Get Bitvavo client for live data
        bitvavo_client = None
        try:
            import python_bitvavo_api.bitvavo as Bitvavo
            api_key = os.environ.get('BITVAVO_API_KEY', '')
            api_secret = os.environ.get('BITVAVO_API_SECRET', '')
            if api_key and api_secret:
                bitvavo_client = Bitvavo.Bitvavo({
                    'APIKEY': api_key,
                    'APISECRET': api_secret,
                })
        except Exception as e:
            logger.debug(f"Bitvavo client init failed: {e}")
        
        # Get available balance for investment suggestions (use cached)
        available_balance = 0.0
        try:
            balance_data = get_cached_balances()
            for bal in balance_data:
                if bal.get('symbol') == 'EUR':
                    available_balance = float(bal.get('available', 0))
                    break
        except Exception as e:
            logger.debug(f"Balance fetch failed: {e}")
        
        # Risk profile configurations
        risk_profiles = {
            'conservative': {
                'range_mult': 1.5,
                'grid_count': 8,
                'spacing': 'arithmetic',
                'investment_pct': 0.10,  # 10% of balance
                'min_confidence': 70,
                'stop_loss': 0.15,
                'take_profit': 0.10,
            },
            'balanced': {
                'range_mult': 2.0,
                'grid_count': 12,
                'spacing': 'geometric',
                'investment_pct': 0.25,  # 25% of balance
                'min_confidence': 60,
                'stop_loss': 0.20,
                'take_profit': 0.15,
            },
            'aggressive': {
                'range_mult': 3.0,
                'grid_count': 20,
                'spacing': 'geometric',
                'investment_pct': 0.40,  # 40% of balance
                'min_confidence': 50,
                'stop_loss': 0.30,
                'take_profit': 0.25,
            },
        }
        
        profile = risk_profiles.get(risk_profile, risk_profiles['balanced'])
        fallback_markets = [
            'BTC-EUR', 'ETH-EUR', 'SOL-EUR', 'XRP-EUR', 'ADA-EUR',
            'DOGE-EUR', 'AVAX-EUR', 'DOT-EUR', 'MATIC-EUR', 'LINK-EUR',
        ]
        
        # Bitvavo fee structure (maker/taker) - define before helper functions that use it
        BITVAVO_FEE_PCT = 0.0025  # 0.25% worst case (taker)
        MIN_PROFITABLE_SPACING = BITVAVO_FEE_PCT * 2.5  # Need 2.5x fee to be profitable
        
        # Static fallback prices (approximate) when API is unavailable
        FALLBACK_PRICES = {
            'BTC-EUR': 42000, 'ETH-EUR': 2200, 'SOL-EUR': 100, 'XRP-EUR': 0.55,
            'ADA-EUR': 0.40, 'DOGE-EUR': 0.08, 'AVAX-EUR': 35, 'DOT-EUR': 7,
            'MATIC-EUR': 0.85, 'LINK-EUR': 14, 'ATOM-EUR': 9, 'UNI-EUR': 6,
            'LTC-EUR': 70, 'NEAR-EUR': 5, 'FET-EUR': 0.60,
        }
        
        def build_basic_suggestions(markets_list):
            basic = []
            if not markets_list:
                return basic
            for mk in markets_list:
                try:
                    live_price = get_live_price(mk)
                    # Use fallback price if live price not available
                    if not live_price:
                        live_price = FALLBACK_PRICES.get(mk)
                    if not live_price:
                        continue
                    # Use a conservative ±8% range when no AI analysis is available
                    range_pct = 0.08 * profile['range_mult']
                    lower_price = live_price * (1 - range_pct / 2)
                    upper_price = live_price * (1 + range_pct / 2)
                    grid_count = profile['grid_count']
                    grid_spacing_pct = (upper_price - lower_price) / lower_price / grid_count
                    investment = round((available_balance * profile['investment_pct']) if available_balance else 100, 2)
                    expected_profit_pct = round(grid_spacing_pct * grid_count * 50, 2)  # heuristic
                    basic.append({
                        'market': mk,
                        'mode': 'neutral',
                        'lower_price': round(lower_price, 2),
                        'upper_price': round(upper_price, 2),
                        'current_price': round(live_price, 2),
                        'grid_count': grid_count,
                        'spacing_mode': profile['spacing'],
                        'investment': investment,
                        'expected_profit_pct': expected_profit_pct,
                        'confidence': 50,
                        'reason': 'Basic fallback based on live price ±range; AI analysis unavailable or filtered.',
                        'risk_profile': risk_profile,
                        'volatility_7d': None,
                        'trend_strength': 0.0,
                        'mean_reversion': None,
                        'grid_score': 50.0,
                        'recommendation': 'good',
                        'stop_loss_pct': profile['stop_loss'],
                        'take_profit_pct': profile['take_profit'],
                        'grid_spacing_pct': round(grid_spacing_pct * 100, 3),
                        'fee_impact_pct': round(BITVAVO_FEE_PCT * 2 * 100, 3),
                    })
                except Exception as e:
                    logger.debug(f"Fallback suggestion failed for {mk}: {e}")
                    continue
            return basic

        # Determine markets to analyze for both AI and fallback modes
        if market:
            markets_to_analyze = [market]
        else:
            markets_to_analyze = fallback_markets + ['ATOM-EUR', 'UNI-EUR', 'LTC-EUR', 'NEAR-EUR', 'FET-EUR']
        
        # Use AIGridAdvisor if available
        if ai_advisor_available:
            advisor = get_ai_grid_advisor(bitvavo_client)
            
            # Analyze each market
            for market_name in markets_to_analyze:
                try:
                    # Get AI analysis
                    analysis = advisor.analyze_market(market_name)
                    if not analysis:
                        continue
                    
                    # Skip markets with low grid score
                    if analysis.grid_score < profile['min_confidence']:
                        continue
                    
                    # Calculate volatility-based range
                    volatility = max(analysis.volatility_7d, 5.0)  # Min 5%
                    range_pct = volatility * profile['range_mult'] / 100
                    
                    # Trend-adjusted range (shift up for uptrend, down for downtrend)
                    trend_adjustment = analysis.trend_strength * 0.02
                    
                    current_price = analysis.current_price
                    lower_price = current_price * (1 - range_pct / 2 + trend_adjustment)
                    upper_price = current_price * (1 + range_pct / 2 + trend_adjustment)
                    
                    # Grid count based on profile, adjusted for range
                    grid_count = profile['grid_count']
                    
                    # Calculate grid spacing percentage
                    grid_spacing_pct = (upper_price - lower_price) / lower_price / grid_count
                    
                    # Ensure grid spacing is profitable after fees
                    if grid_spacing_pct < MIN_PROFITABLE_SPACING:
                        # Reduce grid count to increase spacing
                        required_grids = int((upper_price - lower_price) / lower_price / MIN_PROFITABLE_SPACING)
                        grid_count = max(3, min(required_grids, grid_count))
                        grid_spacing_pct = (upper_price - lower_price) / lower_price / grid_count
                    
                    # Investment suggestion based on available balance
                    if available_balance > 0:
                        suggested_investment = min(
                            available_balance * profile['investment_pct'],
                            max(50, available_balance * 0.5)  # At least €50, max 50% of balance
                        )
                    else:
                        suggested_investment = 100  # Default
                    
                    # Calculate realistic profit estimation
                    order_size = suggested_investment / grid_count
                    profit_per_trade = order_size * grid_spacing_pct
                    
                    # Expected trades based on volatility and mean reversion
                    expected_cycles = analysis.mean_reversion_score * 10  # Estimate cycles per week
                    weekly_profit = profit_per_trade * (grid_count // 2) * expected_cycles
                    expected_profit_pct = (weekly_profit / suggested_investment) * 100 if suggested_investment > 0 else 0
                    
                    # Confidence score from AI analysis
                    confidence = int(analysis.grid_score)
                    
                    # Adjust confidence for extremes
                    if abs(analysis.trend_strength) > 0.5:
                        confidence = int(confidence * 0.8)
                    if analysis.spread_pct > 0.2:
                        confidence = int(confidence * 0.9)
                    
                    # Build detailed reason
                    trend_str = 'neutral'
                    if analysis.trend_strength > 0.1:
                        trend_str = f'↗ uptrend (+{analysis.trend_strength:.1%})'
                    elif analysis.trend_strength < -0.1:
                        trend_str = f'↘ downtrend ({analysis.trend_strength:.1%})'
                    
                    reason = (
                        f"Grid Score: {analysis.grid_score:.0f}/100 | "
                        f"Vol 7d: {analysis.volatility_7d:.1f}% | "
                        f"Trend: {trend_str} | "
                        f"Mean Reversion: {analysis.mean_reversion_score:.0%}"
                    )
                    
                    # Determine mode based on trend
                    if analysis.trend_strength > 0.15:
                        mode = 'long'  # Favor buys in uptrend
                    elif analysis.trend_strength < -0.15:
                        mode = 'short'  # Favor sells in downtrend
                    else:
                        mode = 'neutral'
                    
                    suggestions.append({
                        'market': market_name,
                        'mode': mode,
                        'lower_price': round(lower_price, 2),
                        'upper_price': round(upper_price, 2),
                        'current_price': round(current_price, 2),
                        'grid_count': grid_count,
                        'spacing_mode': profile['spacing'],
                        'investment': round(suggested_investment, 2),
                        'expected_profit_pct': round(expected_profit_pct, 2),
                        'confidence': confidence,
                        'reason': reason,
                        'risk_profile': risk_profile,
                        'volatility_7d': round(analysis.volatility_7d, 2),
                        'trend_strength': round(analysis.trend_strength, 3),
                        'mean_reversion': round(analysis.mean_reversion_score, 3),
                        'grid_score': round(analysis.grid_score, 1),
                        'recommendation': analysis.recommendation,
                        'stop_loss_pct': profile['stop_loss'],
                        'take_profit_pct': profile['take_profit'],
                        'grid_spacing_pct': round(grid_spacing_pct * 100, 3),
                        'fee_impact_pct': round(BITVAVO_FEE_PCT * 2 * 100, 3),  # Round trip fee
                    })
                    
                except Exception as e:
                    logger.warning(f"Error analyzing {market_name}: {e}")
                    continue
            
            # Sort by grid score descending
            suggestions.sort(key=lambda x: x.get('grid_score', 0), reverse=True)
            if not suggestions:
                suggestions = build_basic_suggestions(markets_to_analyze)
        
        else:
            # Fallback: Load from ai_market_suggestions.json with improved logic
            ai_suggestions_path = PROJECT_ROOT / 'ai' / 'ai_market_suggestions.json'
            
            if ai_suggestions_path.exists():
                with open(ai_suggestions_path, 'r') as f:
                    data = json.load(f)
                    ai_markets = data.get('suggestions', [])
            else:
                ai_markets = []
            
            # Get live prices
            try:
                import importlib
                bitvavo_markets = importlib.import_module("modules.bitvavo_markets")
                get_markets_from_cache = getattr(bitvavo_markets, "get_markets_from_cache", None)
                markets_data = get_markets_from_cache() if get_markets_from_cache else {}
            except Exception:
                markets_data = {}
            
            for ai_market in ai_markets[:10]:
                market_name = ai_market.get('market', '')
                
                if market and market != market_name:
                    continue
                
                price_data = markets_data.get(market_name, {})
                current_price = safe_float(price_data.get('price', 0))
                
                if current_price <= 0:
                    continue
                
                # Improved range calculation (not just ±10%)
                volatility_estimate = 15.0  # Assume 15% if unknown
                range_pct = volatility_estimate * profile['range_mult'] / 100
                
                lower_price = current_price * (1 - range_pct / 2)
                upper_price = current_price * (1 + range_pct / 2)
                grid_count = profile['grid_count']
                
                suggested_investment = 100 if available_balance <= 0 else min(
                    available_balance * profile['investment_pct'],
                    max(50, available_balance * 0.5)
                )
                
                suggestions.append({
                    'market': market_name,
                    'mode': 'neutral',
                    'lower_price': round(lower_price, 2),
                    'upper_price': round(upper_price, 2),
                    'current_price': round(current_price, 2),
                    'grid_count': grid_count,
                    'spacing_mode': profile['spacing'],
                    'investment': round(suggested_investment, 2),
                    'expected_profit_pct': 2.5,
                    'confidence': 65,
                    'reason': ai_market.get('reason', 'AI-identified opportunity'),
                    'risk_profile': risk_profile,
                })

            # If no cache-based suggestions were built, fall back to live-price basics
            if not suggestions:
                suggestions = build_basic_suggestions(markets_to_analyze)
        
        # If we have suggestions for three risk profiles, generate all three
        if not market and len(suggestions) > 0:
            # Add suggestions for other risk profiles
            all_suggestions = []
            for profile_name in ['conservative', 'balanced', 'aggressive']:
                if profile_name == risk_profile:
                    # Already have these
                    for s in suggestions:
                        all_suggestions.append(s)
                else:
                    # Quick regeneration with different profile
                    alt_profile = risk_profiles[profile_name]
                    for s in suggestions[:3]:  # Top 3 for each profile
                        alt_s = s.copy()
                        alt_s['risk_profile'] = profile_name
                        alt_s['grid_count'] = alt_profile['grid_count']
                        # Recalculate range
                        if 'volatility_7d' in s:
                            vol = s['volatility_7d']
                            range_pct = vol * alt_profile['range_mult'] / 100
                            cp = s['current_price']
                            alt_s['lower_price'] = round(cp * (1 - range_pct / 2), 2)
                            alt_s['upper_price'] = round(cp * (1 + range_pct / 2), 2)
                        all_suggestions.append(alt_s)
            
            suggestions = all_suggestions[:15]  # Limit total suggestions
        
        return jsonify(suggestions)
    
    except Exception as e:
        logger.error(f"AI grid suggestions error: {e}", exc_info=True)
        return jsonify([])

@app.route('/api/ai/parameter-suggestions')
def ai_parameter_suggestions():
    """Get AI-optimized strategy parameter suggestions based on trading history."""
    try:
        trades = load_trades()
        config = load_config()
        
        # Analyze closed trades for optimization
        closed_trades = trades.get('closed', [])
        
        suggestions = []
        
        # Calculate average metrics from successful trades
        profitable_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in closed_trades if t.get('pnl', 0) < 0]
        
        total_trades = len(closed_trades)
        win_rate = (len(profitable_trades) / total_trades * 100) if total_trades > 0 else 0
        
        current_params = config.get('strategy_params', {})
        
        # Suggestion 1: Take Profit optimization
        current_tp = current_params.get('take_profit_pct', 3.0)
        if profitable_trades:
            avg_profit_pct = sum(t.get('pnl_pct', 0) for t in profitable_trades) / len(profitable_trades)
            recommended_tp = round(max(1.5, min(10.0, avg_profit_pct * 0.8)), 1)
            if abs(recommended_tp - current_tp) > 0.5:
                suggestions.append({
                    'parameter': 'Take Profit %',
                    'field': 'take_profit_pct',
                    'current': current_tp,
                    'recommended': recommended_tp,
                    'change': recommended_tp - current_tp,
                    'reason': f'Based on avg winning trade profit of {avg_profit_pct:.1f}%'
                })
        
        # Suggestion 2: Stop Loss optimization
        current_sl = current_params.get('stop_loss_pct', 5.0)
        if losing_trades:
            avg_loss_pct = abs(sum(t.get('pnl_pct', 0) for t in losing_trades) / len(losing_trades))
            recommended_sl = round(max(2.0, min(15.0, avg_loss_pct * 0.7)), 1)
            if abs(recommended_sl - current_sl) > 0.5:
                suggestions.append({
                    'parameter': 'Stop Loss %',
                    'field': 'stop_loss_pct',
                    'current': current_sl,
                    'recommended': recommended_sl,
                    'change': current_sl - recommended_sl,
                    'reason': f'Tighter stop could reduce avg loss from {avg_loss_pct:.1f}%'
                })
        
        # Suggestion 3: Trailing Stop optimization
        current_trailing = current_params.get('trailing_stop_pct', 2.0)
        if win_rate > 50 and len(profitable_trades) > 3:
            recommended_trailing = round(max(0.5, min(5.0, current_tp * 0.4)), 1)
            if abs(recommended_trailing - current_trailing) > 0.3:
                suggestions.append({
                    'parameter': 'Trailing Stop %',
                    'field': 'trailing_stop_pct',
                    'current': current_trailing,
                    'recommended': recommended_trailing,
                    'change': recommended_trailing - current_trailing,
                    'reason': f'Optimized for {win_rate:.0f}% win rate'
                })
        
        # Suggestion 4: Entry threshold
        current_entry = current_params.get('entry_threshold', -2.0)
        if total_trades > 5:
            recommended_entry = round(max(-5.0, min(0.0, current_entry + 0.5)), 1) if win_rate < 50 else current_entry
            if abs(recommended_entry - current_entry) > 0.3:
                suggestions.append({
                    'parameter': 'Entry Threshold %',
                    'field': 'entry_threshold',
                    'current': current_entry,
                    'recommended': recommended_entry,
                    'change': recommended_entry - current_entry,
                    'reason': 'Adjusted for better entry points'
                })
        
        # Suggestion 5: Max concurrent trades
        current_max = current_params.get('max_concurrent_trades', 5)
        active_trades = trades.get('active', [])
        if len(active_trades) >= current_max * 0.8:
            recommended_max = min(10, current_max + 2)
            suggestions.append({
                'parameter': 'Max Concurrent Trades',
                'field': 'max_concurrent_trades',
                'current': current_max,
                'recommended': recommended_max,
                'change': recommended_max - current_max,
                'reason': f'You are using {len(active_trades)}/{current_max} slots'
            })
        
        return jsonify({
            'suggestions': suggestions,
            'analysis': {
                'total_trades': total_trades,
                'win_rate': round(win_rate, 1),
                'profitable_count': len(profitable_trades),
                'losing_count': len(losing_trades)
            }
        })
    
    except Exception as e:
        logger.error(f"AI parameter suggestions error: {e}")
        return jsonify({'suggestions': [], 'error': str(e)})

# =====================================================
# NEW API ENDPOINTS - HODL / AI / ANALYTICS / REPORTS
# =====================================================

@app.route('/api/hodl/data')
def api_hodl_data():
    """Get HODL portfolio data, schedules, and configuration."""
    try:
        config = load_config()
        hodl_config = config.get('HODL_SCHEDULER', {})
        
        # Load balances
        balances_path = PROJECT_ROOT / 'data' / 'sync_raw_balances.json'
        assets = []
        total_value = 0.0
        top_asset = None
        max_value = 0.0
        
        if balances_path.exists():
            with open(balances_path, 'r') as f:
                raw_balances = json.load(f)
                
            # Get all prices at once
            all_prices = prefetch_all_prices()
            
            # Filter for HODL assets (defined in schedules)
            schedules = hodl_config.get('schedules', [])
            hodl_markets = set()
            for sched in schedules:
                market = sched.get('market', '')
                if market and '-EUR' in market:
                    symbol = market.replace('-EUR', '')
                    hodl_markets.add(symbol)
            
            for bal in raw_balances:
                symbol = bal.get('symbol', '')
                available = float(bal.get('available', 0) or 0)
                
                if symbol in hodl_markets and available > 0.00001:
                    market = f"{symbol}-EUR"
                    price = all_prices.get(market, 0)
                    value = available * price
                    total_value += value
                    
                    assets.append({
                        'symbol': symbol,
                        'amount': f"{available:.8f}".rstrip('0').rstrip('.'),
                        'price': price,
                        'value': value
                    })
                    
                    if value > max_value:
                        max_value = value
                        top_asset = symbol
        
        # Sort assets by value
        assets.sort(key=lambda x: x['value'], reverse=True)
        
        # Build schedules list
        schedule_rows = []
        for sched in schedules:
            market = sched.get('market', '')
            amount = sched.get('amount_eur', 0)
            interval_min = sched.get('interval_minutes', 1440)
            dry_run = sched.get('dry_run', False)
            note = sched.get('note', '')
            
            # Convert interval to readable format
            interval_days = interval_min / 1440
            if interval_days >= 1:
                interval_str = f"{interval_days:.2f}d"
            else:
                interval_str = f"{interval_min}m"
            
            schedule_rows.append({
                'market': market,
                'mode': 'DRY-RUN' if dry_run else 'LIVE',
                'amount': amount,
                'interval': interval_str,
                'last_run': 'N/A',  # Would come from state file
                'next_run': 'N/A',  # Would come from state file
                'status': 'dry' if dry_run else 'live'
            })
        
        # Summary
        live_count = sum(1 for s in schedules if not s.get('dry_run', False))
        dry_count = sum(1 for s in schedules if s.get('dry_run', False))
        
        return jsonify({
            'assets': assets,
            'total_value': total_value,
            'top_asset': top_asset,
            'schedules': schedule_rows,
            'summary': {
                'live_count': live_count,
                'dry_count': dry_count,
                'overdue_count': 0,  # Would require state file parsing
                'next_run': 'N/A'
            },
            'config': {
                'enabled': hodl_config.get('enabled', True),
                'dry_run': hodl_config.get('dry_run', False),
                'poll_interval_seconds': hodl_config.get('poll_interval_seconds', 300)
            }
        })
    except Exception as e:
        logger.error(f"HODL data error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/hodl/save', methods=['POST'])
def api_hodl_save():
    """Save HODL configuration to bot_config.json."""
    try:
        data = request.get_json()
        config = load_config()
        
        hodl_config = config.get('HODL_SCHEDULER', {})
        hodl_config['enabled'] = data.get('enabled', True)
        hodl_config['dry_run'] = data.get('dry_run', False)
        hodl_config['poll_interval_seconds'] = int(data.get('poll_interval', 300))
        
        config['HODL_SCHEDULER'] = hodl_config
        
        write_json_compat(CONFIG_PATH, config, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"HODL save error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config')
def api_config_get():
    """Get full bot configuration."""
    try:
        config = load_config()
        return jsonify(config)
    except Exception as e:
        logger.error(f"Config get error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/save', methods=['POST'])
def api_config_save():
    """Save full bot configuration."""
    try:
        config = request.get_json()
        write_json_compat(CONFIG_PATH, config, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Config save error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/status')
def api_ai_status():
    """Get AI supervisor status and configuration."""
    try:
        config = load_config()
        
        # Load AI suggestions
        ai_suggestions_path = PROJECT_ROOT / 'ai' / 'ai_suggestions.json'
        suggestions = []
        insights = []
        regime = None
        regime_stats = {}
        
        if ai_suggestions_path.exists():
            with open(ai_suggestions_path, 'r') as f:
                ai_data = json.load(f)
                suggestions = ai_data.get('suggestions', [])
                insights = ai_data.get('insights', [])
                regime = ai_data.get('regime')
                regime_stats = ai_data.get('regime_stats', {})
        
        # Load ML metrics
        ml_metrics_path = PROJECT_ROOT / 'ai' / 'ai_model_metrics.json'
        ml_metrics = {}
        if ml_metrics_path.exists():
            with open(ml_metrics_path, 'r') as f:
                ml_metrics = json.load(f)
        
        # Load AI change history (last 50 changes) - check both ai/ and data/ folders
        change_history = []
        ai_changes_paths = [
            PROJECT_ROOT / 'data' / 'ai_changes.json',  # Primary location
            PROJECT_ROOT / 'ai' / 'ai_changes.json',     # Fallback location
        ]
        all_changes = []
        for ai_changes_path in ai_changes_paths:
            if ai_changes_path.exists():
                try:
                    with open(ai_changes_path, 'r') as f:
                        loaded = json.load(f)
                        if isinstance(loaded, list):
                            all_changes.extend(loaded)
                except Exception as e_ch:
                    logger.warning(f"AI changes read error ({ai_changes_path}): {e_ch}")
        
        if all_changes:
            # Deduplicate by timestamp and sort descending
            seen = set()
            unique_changes = []
            for ch in all_changes:
                ts = ch.get('ts', 0)
                if ts not in seen:
                    seen.add(ts)
                    unique_changes.append(ch)
            sorted_changes = sorted(unique_changes, key=lambda x: x.get('ts', 0), reverse=True)[:50]
            for ch in sorted_changes:
                ts = ch.get('ts', 0)
                change_history.append({
                    'timestamp': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts else 'Unknown',
                    'param': ch.get('param', ''),
                    'from_value': ch.get('from', ''),
                    'to_value': ch.get('to', ''),
                    'reason': ch.get('reason', '')
                })
        
        # Check AI heartbeat
        heartbeat = load_heartbeat()
        ai_active = heartbeat.get('ai_active', False)  # Use heartbeat field
        ai_heartbeat_path = PROJECT_ROOT / 'ai' / 'ai_heartbeat.json'
        last_update = None
        if ai_heartbeat_path.exists():
            try:
                with open(ai_heartbeat_path, 'r') as f:
                    hb = json.load(f)
                    last_update = hb.get('last_seen') or datetime.fromtimestamp(hb.get('ts', 0)).isoformat()
            except Exception as e_hb:
                logger.warning(f"AI heartbeat read error: {e_hb}")
        
        return jsonify({
            'ai_active': ai_active,
            'last_update': last_update or 'Unknown',
            'model_accuracy': ml_metrics.get('accuracy', ml_metrics.get('test_accuracy', 0)) * 100 if ml_metrics else 0,
            'suggestions': suggestions,
            'insights': insights,
            'regime': regime or 'neutral',
            'regime_stats': regime_stats,
            'ml_metrics': ml_metrics,
            'change_history': change_history,
            'config': {
                'auto_apply': config.get('AI_AUTO_APPLY', False),
                'allowed_params': config.get('AI_ALLOW_PARAMS', []),
                'cooldown_min': config.get('AI_APPLY_COOLDOWN_MIN', 120),
                'regime_recommendations': config.get('AI_REGIME_RECOMMENDATIONS', True)
            }
        })
    except Exception as e:
        logger.error(f"AI status error: {e}")
        # Return valid response instead of 500 error
        return jsonify({
            'ai_active': False,
            'last_update': 'Error',
            'model_accuracy': 0,
            'suggestions': [],
            'insights': [],
            'change_history': [],
            'regime': 'unknown',
            'regime_stats': {},
            'ml_metrics': {},
            'config': {
                'auto_apply': False,
                'allowed_params': [],
                'cooldown_min': 120,
                'regime_recommendations': True
            }
        })

@app.route('/api/ai/save_settings', methods=['POST'])
def api_ai_save_settings():
    """Save AI configuration."""
    try:
        data = request.get_json()
        config = load_config()
        
        config['AI_AUTO_APPLY'] = data.get('auto_apply', False)
        config['AI_ALLOW_PARAMS'] = data.get('allowed_params', [])
        config['AI_APPLY_COOLDOWN_MIN'] = int(data.get('cooldown_min', 120))
        config['AI_REGIME_RECOMMENDATIONS'] = data.get('regime_recommendations', True)
        
        write_json_compat(CONFIG_PATH, config, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"AI save settings error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/apply_suggestion', methods=['POST'])
def api_ai_apply_suggestion():
    """Apply a single AI suggestion."""
    try:
        data = request.get_json()
        param = data.get('param')
        value = data.get('value')
        
        if not param or value is None:
            return jsonify({'error': 'Missing param or value'}), 400
        
        config = load_config()
        
        # Clamp value based on parameter type
        if param == 'DEFAULT_TRAILING':
            value = max(0.003, min(0.05, float(value)))
        elif param == 'TRAILING_ACTIVATION_PCT':
            value = max(0.005, min(0.08, float(value)))
        elif param == 'RSI_MIN_BUY':
            value = max(10, min(60, int(value)))
        elif param == 'DCA_SIZE_MULTIPLIER':
            value = max(0.4, min(1.8, float(value)))
        elif param == 'BASE_AMOUNT_EUR':
            value = max(5.0, min(200.0, float(value)))
        elif param == 'DCA_AMOUNT_EUR':
            value = max(1.0, min(200.0, float(value)))
        elif param == 'OPEN_TRADE_COOLDOWN_SECONDS':
            value = max(0, min(3600, int(value)))
        
        config[param] = value
        write_json_compat(CONFIG_PATH, config, indent=2)
        
        return jsonify({'status': 'success', 'param': param, 'value': value})
    except Exception as e:
        logger.error(f"AI apply suggestion error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/report')
def api_analytics_report():
    """Get comprehensive analytics report."""
    try:
        from modules.performance_analytics import get_analytics
        
        analytics = get_analytics()
        analytics.refresh()
        
        # Get time period from query params
        period = request.args.get('period', 'All time')
        days_map = {
            'All time': None,
            'Last 7 days': 7,
            'Last 30 days': 30,
            'Last 90 days': 90
        }
        days = days_map.get(period)
        
        report = analytics.generate_report(days)
        
        return jsonify(report)
    except ImportError:
        return jsonify({'error': 'Performance analytics module not available'}), 500
    except Exception as e:
        logger.error(f"Analytics report error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/market_stats')
def api_analytics_market_stats():
    """Get per-market statistics."""
    try:
        from modules.performance_analytics import get_analytics
        
        analytics = get_analytics()
        analytics.refresh()
        
        period = request.args.get('period', 'All time')
        days_map = {
            'All time': None,
            'Last 7 days': 7,
            'Last 30 days': 30,
            'Last 90 days': 90
        }
        days = days_map.get(period)
        
        market_stats = analytics.market_statistics(days)
        
        return jsonify(market_stats)
    except Exception as e:
        logger.error(f"Market stats error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/daily_pnl')
def api_analytics_daily_pnl():
    """Get daily P/L data."""
    try:
        from modules.performance_analytics import get_analytics
        
        analytics = get_analytics()
        analytics.refresh()
        
        days = int(request.args.get('days', 30))
        daily_data = analytics.daily_pnl(days)
        
        return jsonify(daily_data)
    except Exception as e:
        logger.error(f"Daily P/L error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trade_blocks/diagnostics')
def api_trade_blocks_diagnostics():
    """Get complete trade block diagnostics."""
    try:
        from modules.trade_block_analyzer import analyze_trade_blocks
        
        analysis = analyze_trade_blocks()
        return jsonify(analysis)
    except ImportError:
        return jsonify({'error': 'Trade block analyzer module not available'}), 500
    except Exception as e:
        logger.error(f"Trade blocks diagnostics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trade_blocks/indicators')
def api_trade_blocks_indicators():
    """Get trade block indicators."""
    try:
        from modules.trade_block_reasons import get_collector
        from collections import Counter
        
        collector = get_collector(PROJECT_ROOT / 'data')
        
        latest_entries_raw = collector.get_latest_reasons(limit=50)
        
        # FIX: Transform format for dashboard (reasons array → reason string + details)
        latest_entries = []
        for entry in latest_entries_raw:
            reasons_list = entry.get('reasons', [])
            if reasons_list:
                # Take first (primary) reason
                primary = reasons_list[0]
                latest_entries.append({
                    'timestamp': entry.get('timestamp'),
                    'market': entry.get('market'),
                    'reason': primary.get('message', 'N/A'),
                    'details': primary.get('details', {})
                })
            else:
                # No reasons recorded
                latest_entries.append({
                    'timestamp': entry.get('timestamp'),
                    'market': entry.get('market'),
                    'reason': 'N/A',
                    'details': {}
                })
        
        # FIX: Calculate proper summary statistics
        all_entries = collector.get_latest_reasons(limit=1000)
        summary_by_market = {}
        
        # Group by market
        market_blocks = {}
        for entry in all_entries:
            market = entry.get('market')
            if not market:
                continue
            
            if market not in market_blocks:
                market_blocks[market] = []
            
            reasons = entry.get('reasons', [])
            for reason in reasons:
                market_blocks[market].append(reason.get('code', 'unknown'))
        
        # Calculate summary for each market
        for market, reason_codes in market_blocks.items():
            total_blocks = len(reason_codes)
            if total_blocks > 0:
                counter = Counter(reason_codes)
                most_common = counter.most_common(1)[0]
                summary_by_market[market] = {
                    'total': total_blocks,
                    'most_common_reason': most_common[0],
                    'most_common_count': most_common[1]
                }
        
        return jsonify({
            'latest_entries': latest_entries,
            'summary_by_market': summary_by_market
        })
    except ImportError:
        return jsonify({'error': 'Trade block reasons module not available'}), 500
    except Exception as e:
        logger.error(f"Trade block indicators error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/list')
def api_reports_list():
    """List available daily reports."""
    try:
        reports_dir = PROJECT_ROOT / 'reports'
        reports = []
        
        if reports_dir.exists():
            md_files = sorted(reports_dir.glob('daily_*.md'), reverse=True)
            for md_file in md_files:
                json_file = reports_dir / md_file.name.replace('.md', '.json')
                reports.append({
                    'name': md_file.name,
                    'md_path': str(md_file),
                    'json_path': str(json_file) if json_file.exists() else None,
                    'date': md_file.stat().st_mtime
                })
        
        return jsonify({'reports': reports})
    except Exception as e:
        logger.error(f"Reports list error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/get/<filename>')
def api_reports_get(filename):
    """Get report content."""
    try:
        reports_dir = PROJECT_ROOT / 'reports'
        md_path = reports_dir / filename
        
        if not md_path.exists():
            return jsonify({'error': 'Report not found'}), 404
        
        md_content = md_path.read_text(encoding='utf-8')
        
        # Try to load JSON version
        json_path = reports_dir / filename.replace('.md', '.json')
        json_data = None
        if json_path.exists():
            with open(json_path, 'r') as f:
                json_data = json.load(f)
        
        return jsonify({
            'markdown': md_content,
            'json': json_data
        })
    except Exception as e:
        logger.error(f"Reports get error: {e}")
        return jsonify({'error': str(e)}), 500

# =====================================================
# ERROR HANDLERS
# =====================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return render_template('error.html', 
        error_code=404,
        error_message='Page not found'
    ), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return render_template('error.html',
        error_code=500,
        error_message='Internal server error'
    ), 500

@app.route('/api/trade/update', methods=['POST'])
def update_trade():
    """Update trade entry price, invested amount, or coin amount manually."""
    try:
        data = request.get_json()
        market = data.get('market')
        buy_price = data.get('buy_price')
        invested = data.get('invested')
        amount = data.get('amount')
        
        if not market:
            return jsonify({'error': 'Market required'}), 400
        
        # Load trade_log.json
        trade_log_path = PROJECT_ROOT / 'data' / 'trade_log.json'
        with open(trade_log_path, 'r', encoding='utf-8') as f:
            trade_log = json.load(f)
        
        # Find and update trade
        if market not in trade_log:
            return jsonify({'error': f'Trade {market} not found'}), 404
        
        trade = trade_log[market]
        
        # Update fields if provided
        if buy_price is not None:
            trade['buy_price'] = float(buy_price)
        if invested is not None:
            trade['invested'] = float(invested)
        if amount is not None:
            trade['amount'] = float(amount)
        
        # Recalculate invested if both amount and buy_price provided
        if buy_price is not None and amount is not None and invested is None:
            trade['invested'] = float(buy_price) * float(amount)
        
        # Save trade_log.json
        with open(trade_log_path, 'w', encoding='utf-8') as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Trade {market} updated: buy_price={buy_price}, invested={invested}, amount={amount}")
        
        return jsonify({
            'status': 'ok',
            'message': f'Trade {market} updated successfully',
            'trade': trade
        })
    
    except Exception as e:
        logger.error(f"Error updating trade: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# =====================================================
# MAIN ENTRY POINT
# =====================================================

if __name__ == '__main__':
    logger.info("Starting Flask Dashboard...")
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Trade log: {TRADE_LOG_PATH}")
    logger.info(f"Config: {CONFIG_PATH}")
    
    # Run with SocketIO
    socketio.run(
        app,
        host='0.0.0.0',
        port=5001,
        debug=True,
        use_reloader=False,  # Disable reloader for WebSocket stability
        allow_unsafe_werkzeug=True,  # Required for Flask-SocketIO 5.x
    )
