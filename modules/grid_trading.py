"""
Grid Trading Module - Fully automated grid bot with REAL Bitvavo order execution.

Architecture:
- Places real limit orders on Bitvavo at grid price levels
- When a buy fills -> places a sell at the next higher level (and vice versa)
- Auto-selects markets based on volume + volatility
- Auto-creates and manages grids without user intervention
- Fee-aware: Bitvavo maker fee = 0.15%, grid spacing must exceed 0.30%
- Integrates with main bot's risk management and exposure limits

Usage from trailing_bot.py:
    grid_mgr = get_grid_manager(bitvavo, CONFIG)
    grid_mgr.auto_manage()  # Called every bot loop cycle
"""

import json
import os
import time
import math
import statistics
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_DOWN

# Project imports
try:
    from modules.json_compat import write_json_compat
    from modules.logging_utils import log
except ImportError:
    def write_json_compat(path, data, **kwargs):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, **kwargs)
    def log(msg, level='info'):
        print(f"[{level.upper()}] {msg}")

# Fee constants
MAKER_FEE_PCT = 0.0015   # 0.15% per side for limit orders
TAKER_FEE_PCT = 0.0025   # 0.25% per side for market orders
MIN_GRID_SPACING_PCT = 0.005  # 0.50% minimum spacing (to exceed 2x maker fee)


# ================= DATA CLASSES =================

@dataclass
class GridLevel:
    """Represents a single grid level with a real Bitvavo order."""
    level_id: int
    price: float
    side: str               # 'buy' or 'sell'
    amount: float           # base currency amount
    status: str = 'pending' # 'pending', 'placed', 'filled', 'cancelled', 'error'
    order_id: Optional[str] = None
    filled_at: Optional[float] = None
    filled_price: Optional[float] = None
    placed_at: Optional[float] = None
    error_msg: Optional[str] = None
    pair_level_id: Optional[int] = None  # matching level for buy/sell ping-pong


@dataclass
class GridConfig:
    """Configuration for a grid trading instance."""
    market: str
    lower_price: float
    upper_price: float
    num_grids: int = 10
    total_investment: float = 50.0
    grid_mode: str = 'arithmetic'   # 'arithmetic' or 'geometric'
    auto_rebalance: bool = True
    stop_loss_pct: float = 0.15     # 15% stop loss
    take_profit_pct: float = 0.20   # 20% take profit
    trailing_tp_enabled: bool = False   # Enable trailing take-profit
    trailing_tp_callback_pct: float = 0.03  # 3% callback from peak profit
    profit_compounding: bool = True     # Reinvest cycle profits into next orders
    volatility_adaptive: bool = True    # Auto-adjust grid density to volatility
    inventory_skew: bool = True         # Skew counter-order prices by inventory imbalance
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    auto_created: bool = False      # True if auto-selected by the bot


@dataclass
class GridState:
    """Current state of a grid trading instance."""
    config: GridConfig
    levels: List[GridLevel] = field(default_factory=list)
    current_price: float = 0.0
    total_profit: float = 0.0
    total_fees: float = 0.0
    total_trades: int = 0
    last_update: float = field(default_factory=time.time)
    status: str = 'initializing'  # 'initializing', 'placing_orders', 'running', 'paused', 'stopped', 'error'
    base_balance: float = 0.0
    quote_balance: float = 0.0
    rebalance_count: int = 0
    last_rebalance: Optional[float] = None
    last_order_check: float = 0.0
    error_count: int = 0
    trailing_tp_peak: float = 0.0        # Highest profit seen (for trailing TP)
    trailing_tp_active: bool = False     # Whether trailing TP has been activated


# ================= GRID MANAGER =================

class GridManager:
    """
    Fully automated grid trading manager with real Bitvavo order execution.

    Call auto_manage() from the main bot loop every cycle. It will:
    1. Auto-select suitable markets if no grids exist
    2. Place real limit orders on Bitvavo
    3. Monitor fills and create counter-orders (buy->sell, sell->buy)
    4. Rebalance grids when price exits range
    5. Respect exposure limits and fee requirements
    """

    GRID_STATE_FILE = 'data/grid_states.json'
    ORDER_CHECK_INTERVAL = 30  # seconds between order status checks

    def __init__(self, bitvavo_client=None, config: dict = None):
        self.bitvavo = bitvavo_client
        self.bot_config = config or {}
        self.grids: Dict[str, GridState] = {}
        self._api_module = None
        self._market_info_cache: Dict[str, dict] = {}
        self._load_states()

    def _get_grid_config(self) -> dict:
        """Get GRID_TRADING config section from bot config."""
        return self.bot_config.get('GRID_TRADING', {})

    def _get_api(self):
        """Lazy-load bot.api module for normalization functions."""
        if self._api_module is None:
            try:
                import bot.api as api_mod
                self._api_module = api_mod
            except ImportError:
                self._api_module = None
        return self._api_module

    def _safe_call(self, func, *args, **kwargs):
        """Call Bitvavo API with retry logic."""
        try:
            api = self._get_api()
            if api:
                return api.safe_call(func, *args, **kwargs)
            return func(*args, **kwargs)
        except Exception as e:
            log(f"[Grid] API call failed: {e}", level='error')
            return None

    def _get_market_info(self, market: str) -> dict:
        """Get market info (tickSize, minOrderAmount, etc.) with caching."""
        if market in self._market_info_cache:
            return self._market_info_cache[market]

        info = {}
        # Try bot.api first
        api = self._get_api()
        if api and hasattr(api, 'get_market_info'):
            try:
                info = api.get_market_info(market) or {}
            except Exception:
                pass

        # Fallback: fetch directly from our own bitvavo client
        if not info and self.bitvavo:
            try:
                resp = self._safe_call(self.bitvavo.markets, {'market': market})
                if isinstance(resp, list) and resp:
                    info = resp[0]
                elif isinstance(resp, dict) and not resp.get('errorCode'):
                    info = resp
            except Exception:
                pass

        if info:
            self._market_info_cache[market] = info
        return info

    def _normalize_amount(self, market: str, amount: float) -> float:
        """Normalize amount to valid precision for market."""
        # Try bot.api first (best source)
        api = self._get_api()
        if api and hasattr(api, 'normalize_amount'):
            try:
                result = api.normalize_amount(market, amount)
                if result and result > 0:
                    return result
            except Exception:
                pass

        # Fallback: use our own market info
        info = self._get_market_info(market)
        if info:
            min_amt = info.get('minOrderAmount')
            if min_amt:
                try:
                    d_amt = Decimal(str(amount))
                    d_step = Decimal(str(min_amt))
                    units = (d_amt / d_step).to_integral_value(rounding=ROUND_DOWN)
                    return float(units * d_step)
                except Exception:
                    pass

        return float(Decimal(str(amount)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))

    def _normalize_price(self, market: str, price: float) -> float:
        """Normalize price to valid tick size for market."""
        # Try bot.api first
        api = self._get_api()
        if api and hasattr(api, 'normalize_price'):
            try:
                result = api.normalize_price(market, price)
                if result and result > 0:
                    return result
            except Exception:
                pass

        # Fallback: use our own market info (tick size)
        info = self._get_market_info(market)
        if info:
            tick_size = info.get('tickSize')
            if tick_size:
                try:
                    d_px = Decimal(str(price))
                    d_tick = Decimal(str(tick_size))
                    units = (d_px / d_tick).to_integral_value(rounding=ROUND_DOWN)
                    result = float(units * d_tick)
                    log(f"[Grid] _normalize_price {market}: {price} -> {result} (tick={tick_size})", level='debug')
                    return result
                except Exception as e:
                    log(f"[Grid] Tick normalization failed {market}: {e}", level='warning')

        # Last resort: round to 2 decimals
        return float(Decimal(str(price)).quantize(Decimal('0.01'), rounding=ROUND_DOWN))

    def _get_min_order_size(self, market: str) -> float:
        """Get minimum order size for market."""
        api = self._get_api()
        if api and hasattr(api, 'get_min_order_size'):
            return api.get_min_order_size(market)
        return 0.0

    def _get_current_price(self, market: str) -> Optional[float]:
        """Get current market price."""
        api = self._get_api()
        if api and hasattr(api, 'get_current_price'):
            return api.get_current_price(market, force_refresh=True)
        if self.bitvavo:
            try:
                ticker = self._safe_call(self.bitvavo.tickerPrice, {'market': market})
                if ticker and 'price' in ticker:
                    return float(ticker['price'])
            except Exception:
                pass
        return None

    def _get_candles(self, market: str, interval: str = '1h', limit: int = 48) -> list:
        """Get OHLCV candles for volatility calculation."""
        api = self._get_api()
        if api and hasattr(api, 'get_candles'):
            return api.get_candles(market, interval, limit) or []
        if self.bitvavo:
            try:
                return self._safe_call(self.bitvavo.candles, market, interval, {'limit': limit}) or []
            except Exception:
                pass
        return []

    def _get_candles_safe(self, market: str, interval: str = '1m', limit: int = 100) -> list:
        """Get candles with error handling (returns [] on failure)."""
        try:
            return self._get_candles(market, interval, limit)
        except Exception:
            return []

    def _get_eur_balance(self) -> float:
        """Get available EUR balance via bot.api or direct bitvavo call."""
        # Try bot.api first (cached, preferred)
        api = self._get_api()
        if api and hasattr(api, 'get_eur_balance'):
            try:
                bal = api.get_eur_balance(force_refresh=False)
                if bal and bal > 0:
                    return bal
            except Exception:
                pass
        # Fallback: use bitvavo client directly
        if self.bitvavo:
            try:
                balances = self._safe_call(self.bitvavo.balance, {})
                if isinstance(balances, list):
                    for entry in balances:
                        if isinstance(entry, dict) and entry.get('symbol') == 'EUR':
                            return float(entry.get('available', 0.0))
            except Exception as e:
                log(f"[Grid] EUR balance fallback failed: {e}", level='warning')
        return 0.0

    def _get_total_eur_balance(self) -> float:
        """Get TOTAL EUR balance (available + inOrder) for dynamic budget calc."""
        api = self._get_api()
        if api and hasattr(api, 'get_eur_balance'):
            try:
                avail = api.get_eur_balance(force_refresh=True) or 0.0
                # Also get inOrder via balance API
                if self.bitvavo:
                    balances = self._safe_call(self.bitvavo.balance, {})
                    if isinstance(balances, list):
                        for entry in balances:
                            if isinstance(entry, dict) and entry.get('symbol') == 'EUR':
                                return float(entry.get('available', 0.0)) + float(entry.get('inOrder', 0.0))
                return avail
            except Exception:
                pass
        if self.bitvavo:
            try:
                balances = self._safe_call(self.bitvavo.balance, {})
                if isinstance(balances, list):
                    for entry in balances:
                        if isinstance(entry, dict) and entry.get('symbol') == 'EUR':
                            return float(entry.get('available', 0.0)) + float(entry.get('inOrder', 0.0))
            except Exception as e:
                log(f"[Grid] Total EUR balance failed: {e}", level='warning')
        return 0.0

    # ==================== STATE PERSISTENCE ====================

    def _load_states(self) -> None:
        """Load grid states from disk."""
        try:
            if os.path.exists(self.GRID_STATE_FILE):
                with open(self.GRID_STATE_FILE, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)

                for market, state_data in data.items():
                    config_data = state_data.get('config', {})
                    config = GridConfig(**{k: v for k, v in config_data.items()
                                          if k in GridConfig.__dataclass_fields__})

                    levels = []
                    for ld in state_data.get('levels', []):
                        levels.append(GridLevel(**{k: v for k, v in ld.items()
                                                   if k in GridLevel.__dataclass_fields__}))

                    self.grids[market] = GridState(
                        config=config,
                        levels=levels,
                        current_price=state_data.get('current_price', 0),
                        total_profit=state_data.get('total_profit', 0),
                        total_fees=state_data.get('total_fees', 0),
                        total_trades=state_data.get('total_trades', 0),
                        last_update=state_data.get('last_update', 0),
                        status=state_data.get('status', 'stopped'),
                        base_balance=state_data.get('base_balance', 0),
                        quote_balance=state_data.get('quote_balance', 0),
                        rebalance_count=state_data.get('rebalance_count', 0),
                        last_rebalance=state_data.get('last_rebalance'),
                        last_order_check=state_data.get('last_order_check', 0),
                        error_count=state_data.get('error_count', 0),
                        trailing_tp_peak=state_data.get('trailing_tp_peak', 0),
                        trailing_tp_active=state_data.get('trailing_tp_active', False),
                    )
                if self.grids:
                    log(f"[Grid] Loaded {len(self.grids)} grid states")

                    # Sync runtime config from bot_config to existing grids
                    # (in case settings were changed after grid creation)
                    gcfg = self._get_grid_config()
                    if gcfg.get('enabled'):
                        for market, state in self.grids.items():
                            cfg = state.config
                            cfg.trailing_tp_enabled = bool(gcfg.get('trailing_tp_enabled', cfg.trailing_tp_enabled))
                            cfg.trailing_tp_callback_pct = float(gcfg.get('trailing_tp_callback_pct', cfg.trailing_tp_callback_pct))
                            cfg.take_profit_pct = float(gcfg.get('take_profit_pct', cfg.take_profit_pct))
                            cfg.stop_loss_pct = float(gcfg.get('stop_loss_pct', cfg.stop_loss_pct))
                            cfg.profit_compounding = bool(gcfg.get('profit_compounding', cfg.profit_compounding))
                            cfg.volatility_adaptive = bool(gcfg.get('volatility_adaptive', cfg.volatility_adaptive))
                            cfg.inventory_skew = bool(gcfg.get('inventory_skew', cfg.inventory_skew))
                        self._save_states()
                        log(f"[Grid] Synced runtime config to {len(self.grids)} grids")
        except Exception as e:
            log(f"[Grid] Failed to load states: {e}", level='warning')

    def _save_states(self) -> None:
        """Save grid states to disk."""
        try:
            data = {}
            for market, state in self.grids.items():
                data[market] = {
                    'config': asdict(state.config),
                    'levels': [asdict(level) for level in state.levels],
                    'current_price': state.current_price,
                    'total_profit': state.total_profit,
                    'total_fees': state.total_fees,
                    'total_trades': state.total_trades,
                    'last_update': state.last_update,
                    'status': state.status,
                    'base_balance': state.base_balance,
                    'quote_balance': state.quote_balance,
                    'rebalance_count': state.rebalance_count,
                    'last_rebalance': state.last_rebalance,
                    'last_order_check': state.last_order_check,
                    'error_count': state.error_count,
                    'trailing_tp_peak': state.trailing_tp_peak,
                    'trailing_tp_active': state.trailing_tp_active,
                }

            os.makedirs(os.path.dirname(self.GRID_STATE_FILE) or '.', exist_ok=True)
            write_json_compat(self.GRID_STATE_FILE, data, indent=2)
        except Exception as e:
            log(f"[Grid] Failed to save states: {e}", level='error')

    # ==================== ORDER EXECUTION ====================

    def _place_limit_order(self, market: str, side: str, amount: float, price: float) -> Optional[dict]:
        """Place a real limit order on Bitvavo.

        Returns order response dict or None on failure.
        """
        if not self.bitvavo:
            log("[Grid] Cannot place order: no Bitvavo client", level='error')
            return None

        norm_amount = self._normalize_amount(market, amount)
        norm_price = self._normalize_price(market, price)

        if norm_amount <= 0:
            log(f"[Grid] Amount normalized to 0 for {market}, skipping", level='warning')
            return None

        min_size = self._get_min_order_size(market)
        if min_size > 0 and norm_amount < min_size:
            log(f"[Grid] Amount {norm_amount} < min {min_size} for {market}", level='warning')
            return None

        # Check minimum order value (Bitvavo requires >= 5 EUR)
        # Use round() to avoid floating-point artefacts like 4.9999999 showing as "5.00"
        order_value = norm_amount * norm_price
        if round(order_value, 2) < 5.0:
            log(f"[Grid] Order value {order_value:.4f} EUR < 5 EUR minimum for {market}", level='warning')
            return None

        params = {
            'amount': str(norm_amount),
            'price': str(norm_price),
        }

        # Add operator ID if available
        operator_id = self.bot_config.get('OPERATOR_ID')
        if operator_id:
            params['operatorId'] = str(operator_id)

        try:
            resp = self._safe_call(self.bitvavo.placeOrder, market, side, 'limit', params)

            if isinstance(resp, dict) and not resp.get('error') and not resp.get('errorCode'):
                order_id = resp.get('orderId', '')
                log(f"[Grid] {side.upper()} limit placed: {market} "
                    f"{norm_amount} @ {norm_price} (id={order_id})", level='info')
                return resp
            else:
                error_msg = str(resp.get('error', resp) if isinstance(resp, dict) else resp)
                log(f"[Grid] Order failed {market} {side}: {error_msg}", level='error')
                return None
        except Exception as e:
            log(f"[Grid] Exception placing order {market} {side}: {e}", level='error')
            return None

    def _cancel_order(self, market: str, order_id: str) -> bool:
        """Cancel a Bitvavo order."""
        if not self.bitvavo or not order_id:
            return False
        try:
            resp = self._safe_call(self.bitvavo.cancelOrder, market, order_id)
            if isinstance(resp, dict) and resp.get('orderId'):
                log(f"[Grid] Cancelled order {order_id} for {market}", level='info')
                return True
            return False
        except Exception as e:
            log(f"[Grid] Cancel order failed {market}/{order_id}: {e}", level='warning')
            return False

    def _check_order_status(self, market: str, order_id: str) -> Optional[dict]:
        """Check status of a Bitvavo order."""
        if not self.bitvavo or not order_id:
            return None
        try:
            resp = self._safe_call(self.bitvavo.getOrder, market, order_id)
            return resp if isinstance(resp, dict) else None
        except Exception as e:
            log(f"[Grid] Order status check failed {market}/{order_id}: {e}", level='debug')
            return None

    def _get_open_orders(self, market: str) -> list:
        """Get all open orders for a market."""
        if not self.bitvavo:
            return []
        try:
            resp = self._safe_call(self.bitvavo.ordersOpen, {'market': market})
            return resp if isinstance(resp, list) else []
        except Exception:
            return []

    # ==================== GRID CREATION ====================

    def create_grid(
        self,
        market: str,
        lower_price: float,
        upper_price: float,
        num_grids: int = 10,
        total_investment: float = 50.0,
        grid_mode: str = 'arithmetic',
        auto_rebalance: bool = True,
        stop_loss_pct: float = 0.15,
        take_profit_pct: float = 0.20,
        trailing_tp_enabled: bool = False,
        trailing_tp_callback_pct: float = 0.03,
        profit_compounding: bool = True,
        volatility_adaptive: bool = True,
        inventory_skew: bool = True,
        auto_created: bool = False,
    ) -> Optional[GridState]:
        """Create a new grid trading configuration with calculated levels."""
        if lower_price >= upper_price:
            log(f"[Grid] Invalid range: lower={lower_price} >= upper={upper_price}", level='error')
            return None

        if num_grids < 3:
            num_grids = 3

        # Verify grid spacing exceeds fees
        spacing_pct = (upper_price - lower_price) / lower_price / (num_grids - 1)
        if spacing_pct < MIN_GRID_SPACING_PCT:
            log(f"[Grid] Grid spacing {spacing_pct*100:.2f}% < min {MIN_GRID_SPACING_PCT*100:.2f}%, "
                f"reducing num_grids", level='warning')
            num_grids = max(3, int((upper_price - lower_price) / (lower_price * MIN_GRID_SPACING_PCT)) + 1)

        config = GridConfig(
            market=market,
            lower_price=lower_price,
            upper_price=upper_price,
            num_grids=num_grids,
            total_investment=total_investment,
            grid_mode=grid_mode,
            auto_rebalance=auto_rebalance,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_tp_enabled=trailing_tp_enabled,
            trailing_tp_callback_pct=trailing_tp_callback_pct,
            profit_compounding=profit_compounding,
            volatility_adaptive=volatility_adaptive,
            inventory_skew=inventory_skew,
            auto_created=auto_created,
        )

        # Get current price to determine buy/sell split
        current_price = self._get_current_price(market)
        if not current_price:
            log(f"[Grid] Cannot get price for {market}", level='error')
            return None

        levels = self._calculate_grid_levels(config, current_price)
        if not levels:
            log(f"[Grid] No valid levels calculated for {market}", level='error')
            return None

        state = GridState(
            config=config,
            levels=levels,
            current_price=current_price,
            status='initialized',
            quote_balance=total_investment,
        )

        self.grids[market] = state
        self._save_states()

        log(f"[Grid] Created grid for {market}: {len(levels)} levels, "
            f"{lower_price:.2f}-{upper_price:.2f}, investment={total_investment:.0f} EUR", level='info')

        return state

    def _calculate_grid_levels(self, config: GridConfig, current_price: float) -> List[GridLevel]:
        """Calculate grid price levels. Uses Avellaneda-Stoikov dynamic spacing when possible,
        falls back to arithmetic/geometric spacing."""
        levels = []
        n = config.num_grids

        # ── Try Avellaneda-Stoikov dynamic spacing ──
        if self.bot_config.get('AVELLANEDA_STOIKOV_GRID', True):
            try:
                from core.avellaneda_stoikov import calculate_dynamic_grid_levels
                candles = self._get_candles_safe(config.market, '1m', 100)
                if candles and len(candles) >= 30:
                    as_result = calculate_dynamic_grid_levels(
                        current_price=current_price,
                        candles=candles,
                        num_levels=n,
                        total_investment_eur=config.total_investment,
                        market=config.market,
                    )
                    as_levels = as_result.get('levels', [])
                    if as_levels:
                        for lvl in as_levels:
                            norm_price = self._normalize_price(config.market, lvl['price'])
                            if norm_price <= 0:
                                continue
                            side = lvl['side']
                            amount = lvl['amount_eur'] / norm_price
                            norm_amount = self._normalize_amount(config.market, amount)
                            if norm_amount <= 0:
                                continue
                            levels.append(GridLevel(
                                level_id=lvl['level_id'],
                                price=norm_price,
                                side=side,
                                amount=norm_amount,
                            ))
                        if levels:
                            log(f"[Grid A-S] {config.market}: Dynamic spacing, "
                                f"spread={as_result.get('spread', 0) * 100:.3f}%, "
                                f"{len(levels)} levels", level='info')
                            return levels
            except Exception as e:
                log(f"[Grid A-S] Fallback to static grid: {e}", level='debug')

        # ── Fallback: static arithmetic/geometric spacing ──
        if config.grid_mode == 'geometric':
            ratio = (config.upper_price / config.lower_price) ** (1 / (n - 1))
            prices = [config.lower_price * (ratio ** i) for i in range(n)]
        else:
            step = (config.upper_price - config.lower_price) / (n - 1)
            prices = [config.lower_price + step * i for i in range(n)]

        # Investment per grid level in EUR
        amount_per_level_eur = config.total_investment / n

        for i, price in enumerate(prices):
            norm_price = self._normalize_price(config.market, price)
            if norm_price <= 0:
                continue

            # Buy below current price, sell above
            side = 'buy' if norm_price < current_price else 'sell'

            # Convert EUR amount to base currency amount
            amount = amount_per_level_eur / norm_price
            norm_amount = self._normalize_amount(config.market, amount)

            if norm_amount <= 0:
                continue

            levels.append(GridLevel(
                level_id=i,
                price=norm_price,
                side=side,
                amount=norm_amount,
            ))

        return levels

    # ==================== GRID LIFECYCLE ====================

    def start_grid(self, market: str) -> bool:
        """Start grid: place all pending limit orders on Bitvavo."""
        if market not in self.grids:
            log(f"[Grid] No grid found for {market}", level='warning')
            return False

        state = self.grids[market]
        state.status = 'placing_orders'

        # Check base asset balance to decide which sells we can actually place
        base_asset = market.split('-')[0]
        base_balance = 0.0
        try:
            bals = self._safe_call(self.bitvavo.balance, {'symbol': base_asset})
            if isinstance(bals, list):
                for b in bals:
                    if isinstance(b, dict) and b.get('symbol') == base_asset:
                        base_balance = float(b.get('available', 0) or 0)
                        break
            elif isinstance(bals, dict):
                base_balance = float(bals.get('available', 0) or 0)
        except Exception:
            pass

        placed_count = 0
        error_count = 0
        skipped_sells = 0

        for level in state.levels:
            if level.status in ('pending', 'error'):
                # Skip sell orders if we don't hold enough base asset
                if level.side == 'sell' and base_balance < level.amount * 0.99:
                    level.status = 'cancelled'
                    level.error_msg = f'No {base_asset} balance at startup; will be placed via counter-order'
                    skipped_sells += 1
                    continue

                resp = self._place_limit_order(
                    market, level.side, level.amount, level.price
                )
                if resp and isinstance(resp, dict) and resp.get('orderId'):
                    level.order_id = resp['orderId']
                    level.status = 'placed'
                    level.placed_at = time.time()
                    placed_count += 1
                    if level.side == 'sell':
                        base_balance -= level.amount
                else:
                    level.status = 'error'
                    level.error_msg = str(resp)[:200] if resp else 'No response'
                    error_count += 1

                # Small delay between orders to respect rate limits
                time.sleep(0.2)

        if skipped_sells:
            log(f"[Grid] {market}: skipped {skipped_sells} sells (no {base_asset} balance)", level='info')

        if placed_count > 0:
            state.status = 'running'
            log(f"[Grid] Started {market}: {placed_count} orders placed, {error_count} errors", level='info')
        else:
            state.status = 'error'
            log(f"[Grid] Failed to start {market}: 0 orders placed", level='error')

        state.last_update = time.time()
        self._save_states()
        return placed_count > 0

    def stop_grid(self, market: str, cancel_orders: bool = True) -> bool:
        """Stop grid and optionally cancel all open orders."""
        if market not in self.grids:
            return False

        state = self.grids[market]

        if cancel_orders:
            for level in state.levels:
                if level.status == 'placed' and level.order_id:
                    self._cancel_order(market, level.order_id)
                    level.status = 'cancelled'
                    time.sleep(0.1)

        state.status = 'stopped'
        self._save_states()
        log(f"[Grid] Stopped grid for {market}", level='info')
        return True

    def delete_grid(self, market: str) -> bool:
        """Stop and delete a grid."""
        self.stop_grid(market, cancel_orders=True)
        if market in self.grids:
            del self.grids[market]
            self._save_states()
            log(f"[Grid] Deleted grid for {market}", level='info')
            return True
        return False

    # ==================== CORE UPDATE LOOP ====================

    def update_grid(self, market: str) -> Dict[str, Any]:
        """
        Check order statuses and handle fills for a single grid.
        This is the core ping-pong logic:
        - When a buy fills -> place a sell at next higher grid level
        - When a sell fills -> place a buy at next lower grid level
        """
        if market not in self.grids:
            return {'error': 'Grid not found'}

        state = self.grids[market]
        if state.status != 'running':
            return {'status': state.status, 'actions': []}

        # Rate limit order status checks
        now = time.time()
        if (now - state.last_order_check) < self.ORDER_CHECK_INTERVAL:
            return {'status': 'running', 'actions': [], 'throttled': True}
        state.last_order_check = now

        current_price = self._get_current_price(market)
        if not current_price:
            return {'error': 'Cannot get price'}

        state.current_price = current_price
        state.last_update = now
        actions = []
        config = state.config

        # Check stop loss
        if config.stop_loss_pct and config.stop_loss_pct > 0:
            mid_price = (config.lower_price + config.upper_price) / 2
            loss_pct = (mid_price - current_price) / mid_price
            if loss_pct >= config.stop_loss_pct:
                actions.append({'type': 'stop_loss_triggered', 'loss_pct': round(loss_pct, 4)})
                self.stop_grid(market)
                return {'status': 'stopped', 'actions': actions, 'reason': 'stop_loss'}

        # Check take profit (with optional trailing)
        if config.take_profit_pct and state.total_profit > 0:
            profit_pct = state.total_profit / config.total_investment if config.total_investment > 0 else 0

            if config.trailing_tp_enabled:
                # Trailing TP: activate when profit exceeds threshold, then trail peak
                if profit_pct >= config.take_profit_pct:
                    if not state.trailing_tp_active:
                        state.trailing_tp_active = True
                        state.trailing_tp_peak = state.total_profit
                        log(f"[Grid] {market} trailing TP activated at {profit_pct*100:.1f}% ROI "
                            f"(€{state.total_profit:.4f})", level='info')
                        actions.append({'type': 'trailing_tp_activated', 'profit_pct': round(profit_pct, 4)})
                    else:
                        # Update peak
                        if state.total_profit > state.trailing_tp_peak:
                            state.trailing_tp_peak = state.total_profit

                if state.trailing_tp_active and state.trailing_tp_peak > 0:
                    # Check callback: did profit drop X% from peak?
                    callback = (state.trailing_tp_peak - state.total_profit) / state.trailing_tp_peak
                    if callback >= config.trailing_tp_callback_pct:
                        actions.append({
                            'type': 'trailing_tp_triggered',
                            'peak_profit': round(state.trailing_tp_peak, 4),
                            'exit_profit': round(state.total_profit, 4),
                            'callback_pct': round(callback * 100, 2),
                        })
                        log(f"[Grid] {market} trailing TP triggered: peak €{state.trailing_tp_peak:.4f}, "
                            f"exit €{state.total_profit:.4f}, callback {callback*100:.1f}%", level='info')
                        self.stop_grid(market)
                        return {'status': 'stopped', 'actions': actions, 'reason': 'trailing_take_profit'}
            else:
                # Fixed TP: stop immediately at threshold
                if profit_pct >= config.take_profit_pct:
                    actions.append({'type': 'take_profit_triggered', 'profit_pct': round(profit_pct, 4)})
                    self.stop_grid(market)
                    return {'status': 'stopped', 'actions': actions, 'reason': 'take_profit'}

        # Check each placed order for fills
        # CRITICAL: snapshot the list to avoid infinite loop when counter-orders
        # are appended to state.levels during iteration
        levels_snapshot = list(state.levels)
        for level in levels_snapshot:
            if level.status != 'placed' or not level.order_id:
                continue

            order_info = self._check_order_status(market, level.order_id)
            if not order_info or not isinstance(order_info, dict):
                continue

            order_status = order_info.get('status', '').lower()
            filled_amount = float(order_info.get('filledAmount', 0) or 0)

            if order_status == 'filled' or (filled_amount > 0 and order_status in ('filled', 'canceled', 'cancelled')):
                # Order filled!
                fill_price = float(order_info.get('price', level.price) or level.price)
                actual_amount = filled_amount if filled_amount > 0 else level.amount

                level.status = 'filled'
                level.filled_at = now
                level.filled_price = fill_price
                state.total_trades += 1

                # Calculate fee
                fee_eur = actual_amount * fill_price * MAKER_FEE_PCT
                state.total_fees += fee_eur

                if level.side == 'buy':
                    # Buy filled -> track balance
                    state.base_balance += actual_amount
                    state.quote_balance -= actual_amount * fill_price + fee_eur

                    # Place counter sell at next higher grid level
                    sell_price = self._find_next_higher_price(state, level.price)
                    if sell_price:
                        # === INVENTORY SKEW ===
                        # If we hold excess inventory, raise the sell price less aggressively
                        # to sell faster and reduce risk
                        if config.inventory_skew and state.base_balance > 0:
                            inv_ratio = state.base_balance * fill_price / max(1, config.total_investment)
                            if inv_ratio > 0.5:  # Heavily overweight: bring sell closer
                                skew = min(0.003, (inv_ratio - 0.5) * 0.01)  # Max 0.3% skew
                                sell_price = sell_price * (1 - skew)
                                sell_price = self._normalize_price(market, sell_price)
                                log(f"[Grid] {market} Inventory skew: sell lowered by {skew*100:.2f}% "
                                    f"to reduce overweight (inv_ratio={inv_ratio:.2f})", level='debug')

                        profit_per_unit = sell_price - fill_price - (2 * fill_price * MAKER_FEE_PCT)
                        if profit_per_unit > 0:  # Only place if profitable after fees
                            self._place_counter_order(state, market, 'sell', actual_amount, sell_price, level.level_id)

                    actions.append({
                        'type': 'buy_filled',
                        'level': level.level_id,
                        'price': fill_price,
                        'amount': actual_amount,
                        'fee': round(fee_eur, 4),
                    })

                elif level.side == 'sell':
                    # Sell filled -> track profit + balance
                    state.base_balance -= actual_amount
                    state.quote_balance += actual_amount * fill_price - fee_eur

                    # Calculate profit (difference from corresponding buy)
                    buy_cost = self._estimate_buy_cost(state, level)
                    profit = 0.0
                    if buy_cost > 0:
                        sell_revenue = actual_amount * fill_price - fee_eur
                        profit = sell_revenue - buy_cost
                        state.total_profit += profit

                    # Place counter buy at next lower grid level
                    buy_price = self._find_next_lower_price(state, level.price)
                    if buy_price:
                        # === PROFIT COMPOUNDING ===
                        # Reinvest cycle profit into the next buy order for compound growth
                        compound_extra = 0.0
                        if config.profit_compounding and profit > 0:
                            compound_extra = profit * 0.5  # Reinvest 50% of cycle profit
                            log(f"[Grid] {market} Compounding: +€{compound_extra:.4f} added to next buy",
                                level='debug')

                        base_eur = actual_amount * fill_price * 0.99 + compound_extra

                        # === INVENTORY SKEW ===
                        # If we hold too much base, lower the buy price to reduce inventory risk
                        if config.inventory_skew and state.base_balance > 0:
                            inv_ratio = state.base_balance * fill_price / max(1, config.total_investment)
                            if inv_ratio > 0.3:  # Overweight: push buy lower
                                skew = min(0.005, inv_ratio * 0.01)  # Max 0.5% skew
                                buy_price = buy_price * (1 - skew)
                                buy_price = self._normalize_price(market, buy_price)
                                log(f"[Grid] {market} Inventory skew: buy lowered by {skew*100:.2f}% "
                                    f"(inv_ratio={inv_ratio:.2f})", level='debug')

                        buy_amount = base_eur / buy_price
                        buy_amount = self._normalize_amount(market, buy_amount)
                        if buy_amount > 0:
                            self._place_counter_order(state, market, 'buy', buy_amount, buy_price, level.level_id)

                    actions.append({
                        'type': 'sell_filled',
                        'level': level.level_id,
                        'price': fill_price,
                        'amount': actual_amount,
                        'fee': round(fee_eur, 4),
                        'profit': round(profit, 4),
                    })

                log(f"[Grid] {market} {level.side.upper()} filled @ {fill_price:.2f} "
                    f"(amount={actual_amount:.6f}, fee={fee_eur:.4f} EUR)", level='info')

            elif order_status in ('canceled', 'cancelled', 'expired', 'rejected'):
                level.status = 'cancelled'
                level.error_msg = f"Order {order_status}"

        # Check if grid is out of range -> rebalance
        # Auto-rebalance when price is >0.5% outside grid range
        # (lowered from 2% to catch drifts earlier and keep grids productive)
        if config.auto_rebalance:
            _rebal_margin = 1.005  # 0.5%
            if current_price < config.lower_price / _rebal_margin or current_price > config.upper_price * _rebal_margin:
                log(f"[Grid] {market} price {current_price:.2f} outside range "
                    f"[{config.lower_price:.2f}-{config.upper_price:.2f}], rebalancing...",
                    level='info')
                rebalance_result = self._rebalance_grid(market, current_price)
                if rebalance_result.get('success'):
                    actions.append({'type': 'rebalanced', **rebalance_result})
                    # Notify via Telegram
                    try:
                        from notifier import send_telegram
                        send_telegram(
                            f"🔄 <b>Grid Rebalance: {market}</b>\n"
                            f"Prijs {current_price:.2f} buiten range\n"
                            f"Oud: {rebalance_result.get('old_lower',0):.2f}-{rebalance_result.get('old_upper',0):.2f}\n"
                            f"Nieuw: {rebalance_result.get('new_lower',0):.2f}-{rebalance_result.get('new_upper',0):.2f}\n"
                            f"Orders: {rebalance_result.get('orders_placed',0)}"
                        )
                    except Exception:
                        pass

        self._save_states()
        return {'status': state.status, 'actions': actions}

    def _find_next_higher_price(self, state: GridState, current_level_price: float) -> Optional[float]:
        """Find the next grid price level above the given price."""
        prices = sorted(set(l.price for l in state.levels))
        for p in prices:
            if p > current_level_price * 1.001:  # Small tolerance
                return p
        return None

    def _find_next_lower_price(self, state: GridState, current_level_price: float) -> Optional[float]:
        """Find the next grid price level below the given price."""
        prices = sorted(set(l.price for l in state.levels), reverse=True)
        for p in prices:
            if p < current_level_price * 0.999:
                return p
        return None

    def _estimate_buy_cost(self, state: GridState, sell_level: GridLevel) -> float:
        """Estimate the buy cost for a sell level (approximate from grid spacing)."""
        buy_price = self._find_next_lower_price(state, sell_level.price)
        if buy_price:
            fee = sell_level.amount * buy_price * MAKER_FEE_PCT
            return sell_level.amount * buy_price + fee
        return sell_level.amount * sell_level.price * 0.99  # Rough estimate

    def _place_counter_order(self, state: GridState, market: str, side: str,
                              amount: float, price: float, source_level_id: int) -> bool:
        """Place a counter order (buy->sell or sell->buy) after a fill."""
        # Prevent duplicate counter-orders for the same source level
        for existing in state.levels:
            if (existing.pair_level_id == source_level_id
                    and existing.side == side
                    and existing.status in ('placed', 'pending')):
                log(f"[Grid] {market} Skipping duplicate counter {side} for level {source_level_id} "
                    f"(already exists as level {existing.level_id})", level='debug')
                return False

        resp = self._place_limit_order(market, side, amount, price)
        if resp and isinstance(resp, dict) and resp.get('orderId'):
            # Add new level to the grid
            new_level = GridLevel(
                level_id=len(state.levels),
                price=price,
                side=side,
                amount=amount,
                status='placed',
                order_id=resp['orderId'],
                placed_at=time.time(),
                pair_level_id=source_level_id,
            )
            state.levels.append(new_level)
            return True
        return False

    def _rebalance_grid(self, market: str, current_price: float) -> Dict[str, Any]:
        """Cancel all orders and recreate grid centered on current price."""
        if market not in self.grids:
            return {'success': False}

        state = self.grids[market]
        config = state.config

        # Cancel all placed orders
        for level in state.levels:
            if level.status == 'placed' and level.order_id:
                self._cancel_order(market, level.order_id)
                time.sleep(0.1)

        # Calculate new range centered on current price
        old_range_pct = (config.upper_price - config.lower_price) / ((config.upper_price + config.lower_price) / 2)
        half_range_pct = old_range_pct / 2
        new_lower = current_price * (1 - half_range_pct)
        new_upper = current_price * (1 + half_range_pct)

        if new_lower <= 0 or new_lower >= new_upper:
            return {'success': False, 'error': 'Invalid range'}

        old_lower = config.lower_price
        old_upper = config.upper_price
        config.lower_price = new_lower
        config.upper_price = new_upper

        # Recalculate and place new levels
        new_levels = self._calculate_grid_levels(config, current_price)
        state.levels = new_levels
        state.rebalance_count += 1
        state.last_rebalance = time.time()

        # Place new orders — only place buys immediately; sells wait for
        # counter-order after a buy fills (we typically don't hold base asset)
        base_asset = market.split('-')[0]
        base_balance = 0.0
        try:
            bals = self._safe_call(self.bitvavo.balance, {'symbol': base_asset})
            if isinstance(bals, list):
                for b in bals:
                    if isinstance(b, dict) and b.get('symbol') == base_asset:
                        base_balance = float(b.get('available', 0) or 0)
                        break
            elif isinstance(bals, dict):
                base_balance = float(bals.get('available', 0) or 0)
        except Exception:
            pass

        placed = 0
        skipped_sells = 0
        for level in state.levels:
            if level.status == 'pending':
                # Skip sell orders if we don't hold enough base asset
                if level.side == 'sell' and base_balance < level.amount * 0.99:
                    level.status = 'cancelled'
                    level.error_msg = f'No {base_asset} balance at rebalance; will be placed via counter-order'
                    skipped_sells += 1
                    continue
                resp = self._place_limit_order(market, level.side, level.amount, level.price)
                if resp and isinstance(resp, dict) and resp.get('orderId'):
                    level.order_id = resp['orderId']
                    level.status = 'placed'
                    level.placed_at = time.time()
                    placed += 1
                    if level.side == 'sell':
                        base_balance -= level.amount  # Track remaining balance
                else:
                    level.status = 'error'
                    level.error_msg = str(resp)[:200] if resp else 'No response'
                time.sleep(0.2)

        if skipped_sells:
            log(f"[Grid] Rebalance {market}: skipped {skipped_sells} sells (no {base_asset} balance)", level='info')

        log(f"[Grid] Rebalanced {market}: {old_lower:.2f}-{old_upper:.2f} -> "
            f"{new_lower:.2f}-{new_upper:.2f} ({placed} orders placed)", level='info')

        self._save_states()
        return {
            'success': True,
            'new_lower': round(new_lower, 2),
            'new_upper': round(new_upper, 2),
            'old_lower': round(old_lower, 2),
            'old_upper': round(old_upper, 2),
            'orders_placed': placed,
        }

    # ==================== AUTO-MARKET SELECTION ====================

    def _calculate_volatility(self, market: str) -> Optional[float]:
        """Calculate recent volatility (std dev of hourly returns) for a market."""
        candles = self._get_candles(market, '1h', 48)
        if not candles or len(candles) < 10:
            return None

        try:
            closes = []
            for c in candles:
                if isinstance(c, (list, tuple)) and len(c) >= 5:
                    closes.append(float(c[4]))  # Close price
                elif isinstance(c, dict):
                    closes.append(float(c.get('close', 0)))

            if len(closes) < 10:
                return None

            # Calculate hourly returns
            returns = []
            for i in range(1, len(closes)):
                if closes[i-1] > 0:
                    returns.append((closes[i] - closes[i-1]) / closes[i-1])

            if len(returns) < 5:
                return None

            return statistics.stdev(returns)
        except Exception:
            return None

    def _get_market_volume_24h(self, market: str) -> float:
        """Get 24h volume in EUR for a market."""
        if not self.bitvavo:
            return 0.0
        try:
            ticker = self._safe_call(self.bitvavo.ticker24h, {'market': market})
            if isinstance(ticker, dict):
                return float(ticker.get('volumeQuote', 0) or 0)
            elif isinstance(ticker, list) and len(ticker) > 0:
                return float(ticker[0].get('volumeQuote', 0) or 0)
        except Exception:
            pass
        return 0.0

    def auto_select_markets(self, max_grids: int = 2) -> List[Dict[str, Any]]:
        """
        Auto-select the best markets for grid trading.
        Optimized: batch-fetches 24h tickers in a single API call.
        """
        gcfg = self._get_grid_config()
        excluded = set(gcfg.get('excluded_markets', []))
        preferred = gcfg.get('preferred_markets', [])
        min_volume = gcfg.get('min_volume_24h', 50000)

        # Get existing grid markets
        active_markets = set(m for m, s in self.grids.items()
                            if s.status in ('running', 'placing_orders', 'initialized'))

        # Also exclude markets used by trailing bot
        trailing_open = set()
        try:
            trade_log_path = 'data/trade_log.json'
            if os.path.exists(trade_log_path):
                with open(trade_log_path, 'r', encoding='utf-8') as f:
                    tl = json.load(f)
                    ot = tl.get('open', {}) if isinstance(tl, dict) else {}
                    trailing_open = set(ot.keys())
        except Exception:
            pass

        # Exclude HODL/DCA scheduled markets from AUTO-selection (not manual)
        # Note: HODL DCA (small weekly buys) runs alongside grid without conflict
        # as long as budget reservation is respected. Log for visibility.
        hodl_markets = set()
        try:
            hodl_cfg = self.bot_config.get('HODL_SCHEDULER', {})
            if hodl_cfg.get('enabled', False):
                for sched in hodl_cfg.get('schedules', []):
                    m = sched.get('market', '').upper()
                    if m and not sched.get('dry_run', True):
                        hodl_markets.add(m)
                if hodl_markets:
                    log(f"[Grid] HODL markets active: {hodl_markets} (coexists with grid)", level='info')
        except Exception:
            pass

        # Batch-fetch all 24h tickers in one API call (fast!)
        all_tickers = {}
        try:
            tickers = self._safe_call(self.bitvavo.ticker24h, {})
            if isinstance(tickers, list):
                for t in tickers:
                    if isinstance(t, dict) and t.get('market', '').endswith('-EUR'):
                        all_tickers[t['market']] = {
                            'price': float(t.get('last', 0) or 0),
                            'volume': float(t.get('volumeQuote', 0) or 0),
                        }
        except Exception as e:
            log(f"[Grid] Failed to fetch batch tickers: {e}", level='warning')

        candidates = []

        # Check preferred markets first, then defaults
        markets_to_check = list(preferred) if preferred else []
        default_markets = [
            'BTC-EUR', 'ETH-EUR', 'XRP-EUR', 'SOL-EUR', 'ADA-EUR',
            'DOGE-EUR', 'DOT-EUR', 'AVAX-EUR', 'LINK-EUR',
            'ATOM-EUR', 'UNI-EUR', 'LTC-EUR', 'NEAR-EUR', 'ARB-EUR',
        ]
        for m in default_markets:
            if m not in markets_to_check:
                markets_to_check.append(m)

        log(f"[Grid] Market selection: checking {len(markets_to_check)} markets, "
            f"excluding active={active_markets}, trailing={trailing_open}", level='info')

        for market in markets_to_check:
            if market in excluded or market in active_markets or market in trailing_open:
                continue

            # Use batch ticker data (fast) or fall back to individual call
            ticker_data = all_tickers.get(market, {})
            price = ticker_data.get('price', 0)
            volume = ticker_data.get('volume', 0)

            if not price:
                price = self._get_current_price(market)
            if not price:
                continue

            if volume < min_volume:
                if not ticker_data:
                    volume = self._get_market_volume_24h(market)
                if volume < min_volume:
                    continue

            # Only fetch candles for high-volume markets (this is the expensive call)
            vol = self._calculate_volatility(market)
            if vol is None:
                # Use default volatility for preferred markets
                if market in preferred:
                    vol = 0.008  # Assume medium volatility
                else:
                    continue

            # Ideal volatility: 0.003-0.015 (0.3%-1.5% hourly std dev)
            vol_score = 0.0
            if 0.003 <= vol <= 0.015:
                vol_score = 1.0 - abs(vol - 0.008) / 0.012  # Peak at 0.8%
            elif vol < 0.003:
                vol_score = vol / 0.003 * 0.5
            else:
                vol_score = max(0, 0.5 - (vol - 0.015) / 0.020)

            # Volume score (log scale)
            vol_eur_score = min(1.0, math.log10(max(1, volume)) / 7)  # Peak at 10M EUR

            # Prefer preferred markets
            pref_bonus = 0.3 if market in preferred else 0

            composite_score = vol_score * 0.5 + vol_eur_score * 0.3 + pref_bonus

            # Calculate suggested range based on volatility
            range_pct = max(0.05, min(0.20, vol * 48 * 2.5))  # ~2.5x daily range
            suggested_lower = price * (1 - range_pct / 2)
            suggested_upper = price * (1 + range_pct / 2)

            candidates.append({
                'market': market,
                'price': price,
                'volatility': vol,
                'volume_24h': volume,
                'score': composite_score,
                'suggested_lower': suggested_lower,
                'suggested_upper': suggested_upper,
                'range_pct': range_pct,
            })

            time.sleep(0.15)  # Rate limit

        # Sort by composite score
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:max_grids]

    # ==================== FULL AUTO-MANAGE ====================

    def auto_manage(self) -> Dict[str, Any]:
        """
        Main entry point -- call every bot loop cycle.

        Fully autonomous operation:
        1. Creates grids if none exist (auto-selects markets)
        2. Updates running grids (checks fills, places counter-orders)
        3. Handles rebalancing and error recovery

        Returns summary of actions taken.
        """
        gcfg = self._get_grid_config()
        if not gcfg.get('enabled', False):
            return {'enabled': False}

        if not self.bitvavo:
            return {'error': 'No Bitvavo client'}

        # Check regime grid_pause: skip NEW grid creation but still manage existing
        regime_adj = self.bot_config.get('_REGIME_ADJ', {})
        grid_paused = bool(regime_adj.get('grid_pause', False))

        results = {}

        # Step 0: Sync runtime config from bot_config to existing grid configs
        # This ensures config changes (like enabling trailing TP) apply to running grids
        for market, state in self.grids.items():
            cfg = state.config
            cfg.trailing_tp_enabled = bool(gcfg.get('trailing_tp_enabled', cfg.trailing_tp_enabled))
            cfg.trailing_tp_callback_pct = float(gcfg.get('trailing_tp_callback_pct', cfg.trailing_tp_callback_pct))
            cfg.take_profit_pct = float(gcfg.get('take_profit_pct', cfg.take_profit_pct))
            cfg.stop_loss_pct = float(gcfg.get('stop_loss_pct', cfg.stop_loss_pct))
            cfg.profit_compounding = bool(gcfg.get('profit_compounding', cfg.profit_compounding))
            cfg.volatility_adaptive = bool(gcfg.get('volatility_adaptive', cfg.volatility_adaptive))
            cfg.inventory_skew = bool(gcfg.get('inventory_skew', cfg.inventory_skew))

        # Step 1: Auto-create grids if needed (skip when grid_paused by regime)
        max_grids = int(gcfg.get('max_grids', 2))
        active_count = sum(1 for s in self.grids.values()
                          if s.status in ('running', 'placing_orders', 'initialized'))

        if active_count < max_grids and not grid_paused:
            results['auto_create'] = self._auto_create_grids(max_grids - active_count, gcfg)
        elif grid_paused and active_count < max_grids:
            results['grid_paused'] = True

        # Step 2: Start any initialized grids
        for market, state in list(self.grids.items()):
            if state.status == 'initialized':
                started = self.start_grid(market)
                results[f'start_{market}'] = started

        # Step 2a: Auto-recover stopped/error grids that have trade history
        # These were likely stopped by zombie detection or temporary API issues
        for market, state in list(self.grids.items()):
            if state.status in ('stopped', 'error') and state.config.enabled and state.total_trades > 0:
                # Only retry if the grid was updated recently (last 24h) — not ancient stale grids
                if (time.time() - state.last_update) < 86400:
                    log(f"[Grid] Auto-recovering {market} (was {state.status}, "
                        f"{state.total_trades} trades, profit €{state.total_profit:.4f})",
                        level='info')
                    current_price = self._get_current_price(market)
                    if current_price and current_price > 0:
                        rebal = self._rebalance_grid(market, current_price)
                        if rebal.get('success') and rebal.get('orders_placed', 0) > 0:
                            state.status = 'running'
                            self._save_states()
                            results[f'recover_{market}'] = rebal
                            log(f"[Grid] {market} recovered: {rebal.get('orders_placed')} orders placed",
                                level='info')
                        else:
                            log(f"[Grid] {market} recovery failed: {rebal}", level='warning')

        # Step 2b: Retry pending/error/cancelled-sell levels in running grids
        for market, state in list(self.grids.items()):
            if state.status == 'running':
                # Also retry cancelled sells when base balance may now be available
                retry_levels = [l for l in state.levels if l.status in ('pending', 'error')]
                cancelled_sells = [l for l in state.levels
                                   if l.status == 'cancelled' and l.side == 'sell'
                                   and l.error_msg and 'balance' in str(l.error_msg).lower()]
                retry_levels.extend(cancelled_sells)
                if retry_levels:
                    # Only retry buy orders OR sell orders we have sufficient coin balance for
                    base_asset = market.split('-')[0]
                    base_balance = 0.0
                    try:
                        bals = self._safe_call(self.bitvavo.balance, {'symbol': base_asset})
                        if isinstance(bals, list):
                            for b in bals:
                                if isinstance(b, dict) and b.get('symbol') == base_asset:
                                    base_balance = float(b.get('available', 0) or 0)
                                    break
                        elif isinstance(bals, dict):
                            base_balance = float(bals.get('available', 0) or 0)
                    except Exception:
                        pass
                    placeable = [l for l in retry_levels
                                 if l.side == 'buy' or (l.side == 'sell' and base_balance >= l.amount * 0.99)]
                    skipped_sells = len(retry_levels) - len(placeable)
                    if skipped_sells:
                        log(f"[Grid] Skipping {skipped_sells} sell retries for {market}: "
                            f"insufficient {base_asset} balance ({base_balance:.6f})", level='info')
                        # Mark them as cancelled so they don't retry endlessly; counter-sells will be placed after buys fill
                        for l in retry_levels:
                            if l.side == 'sell' and base_balance < l.amount * 0.99:
                                l.status = 'cancelled'
                                l.error_msg = f'No {base_asset} balance at startup; will be placed via counter-order'
                        self._save_states()
                    if not placeable:
                        continue
                    log(f"[Grid] Retrying {len(placeable)} pending/error levels for {market}", level='info')
                    retried = 0
                    for level in placeable:
                        resp = self._place_limit_order(market, level.side, level.amount, level.price)
                        if resp and isinstance(resp, dict) and resp.get('orderId'):
                            level.order_id = resp['orderId']
                            level.status = 'placed'
                            level.placed_at = time.time()
                            level.error_msg = None
                            retried += 1
                        else:
                            level.status = 'error'
                            level.error_msg = str(resp)[:200] if resp else 'No response'
                        time.sleep(0.2)
                    log(f"[Grid] Retry result for {market}: {retried}/{len(placeable)} placed", level='info')
                    self._save_states()
                    if retried:
                        results[f'retry_{market}'] = retried

        # Step 3: Update all running grids
        for market, state in list(self.grids.items()):
            if state.status == 'running':
                update_result = self.update_grid(market)
                if update_result.get('actions'):
                    results[f'update_{market}'] = update_result

        # Step 3b: Volatility-adaptive grid density
        # Auto-adjust num_grids if real-time volatility deviates >30% from grid creation
        # Cooldown: only check every 6 hours to prevent over-triggering
        vol_adapt_cooldown = 6 * 3600  # 6 hours
        for market, state in list(self.grids.items()):
            if state.status != 'running':
                continue
            config = state.config
            if not config.volatility_adaptive:
                continue
            # Cooldown check: skip if rebalanced recently
            if state.last_rebalance and (time.time() - state.last_rebalance) < vol_adapt_cooldown:
                continue
            try:
                from core.avellaneda_stoikov import get_volatility_adjusted_num_grids, should_widen_grid
                candles = self._get_candles(market, '1h', 72)
                if not candles or len(candles) < 24:
                    continue
                adjusted = get_volatility_adjusted_num_grids(config.num_grids, candles)
                # Only rebalance if difference is significant (>= 2 grids)
                if abs(adjusted - config.num_grids) >= 2:
                    old_num = config.num_grids
                    config.num_grids = adjusted
                    log(f"[Grid] Vol-adaptive: {market} num_grids {old_num}→{adjusted} "
                        f"(volatility change detected)", level='info')
                    rebal = self._rebalance_grid(market, state.current_price)
                    if rebal.get('success'):
                        results[f'vol_adapt_{market}'] = {'old': old_num, 'new': adjusted}
                    continue  # Skip should_widen if we already adjusted
                # Also check if grid spacing is too narrow for current vol
                price_range_pct = 0.0
                if state.levels and len(state.levels) >= 2:
                    prices = sorted(set(l.price for l in state.levels if l.price > 0))
                    if len(prices) >= 2:
                        price_range_pct = (prices[1] - prices[0]) / prices[0] * 100
                if price_range_pct > 0:
                    widen, suggested = should_widen_grid(price_range_pct, candles)
                    if widen and config.num_grids > 3:
                        config.num_grids -= 1
                        log(f"[Grid] Vol-adaptive: {market} spacing too narrow "
                            f"({price_range_pct:.2f}% vs suggested {suggested:.2f}%), "
                            f"reducing to {config.num_grids} grids", level='info')
                        rebal = self._rebalance_grid(market, state.current_price)
                        if rebal.get('success'):
                            results[f'vol_widen_{market}'] = config.num_grids
            except ImportError:
                pass  # A-S module not available
            except Exception as e:
                log(f"[Grid] Vol-adaptive check error for {market}: {e}", level='debug')

        # Step 3c: Scale-up grid investment if dynamic budget grew >25%
        try:
            budget_cfg = self.bot_config.get('BUDGET_RESERVATION', {})
            if budget_cfg.get('enabled') and budget_cfg.get('mode') == 'dynamic':
                total_eur = self._get_total_eur_balance()
                grid_pct = float(budget_cfg.get('grid_pct', 25)) / 100.0
                reserve_eur = float(budget_cfg.get('min_reserve_eur', 0))
                grid_budget = max(0, (total_eur - reserve_eur) * grid_pct)
                grid_profit = self.get_total_grid_profit() if budget_cfg.get('reinvest_grid_profits', True) else 0
                max_grid_investment = grid_budget + max(0, grid_profit)
                new_per_grid = max_grid_investment / max(1, max_grids)
                for market, state in list(self.grids.items()):
                    if state.status != 'running':
                        continue
                    current_inv = float(state.config.total_investment or 0)
                    if current_inv > 0 and new_per_grid > current_inv * 1.25 and new_per_grid >= 30:
                        log(f"[Grid] Budget meegegroeid: {market} €{current_inv:.0f}→€{new_per_grid:.0f}, herbalanceren", level='info')
                        state.config.total_investment = round(new_per_grid, 2)
                        rebalance_result = self._rebalance_grid(market, state.current_price)
                        if rebalance_result.get('success'):
                            results[f'budget_scale_{market}'] = round(new_per_grid, 2)
        except Exception as e:
            log(f"[Grid] Budget scale check fout: {e}", level='warning')

        # Step 4: Cleanup broken/stale grids
        cutoff = time.time() - 86400
        for market in list(self.grids.keys()):
            state = self.grids[market]
            is_broken = (state.status in ('stopped', 'error') and state.total_trades == 0
                         and all(l.status in ('pending', 'error') for l in state.levels))
            is_stale = (state.status in ('stopped', 'error') and state.last_update < cutoff)
            # Detect "zombie" grids: status=running but no active orders on exchange
            # IMPORTANT: Don't count cancelled sells that are waiting for counter-order
            # (these have 'balance' in their error_msg and are expected behavior)
            is_zombie = False
            if state.status == 'running':
                placed_levels = [l for l in state.levels if l.status == 'placed' and l.order_id]
                # Only count truly broken cancelled/error levels, not sells waiting for counter
                real_cancelled = [l for l in state.levels
                                  if l.status == 'cancelled'
                                  and not (l.side == 'sell' and l.error_msg
                                           and ('balance' in str(l.error_msg).lower()
                                                or 'counter-order' in str(l.error_msg).lower()))]
                error_levels = [l for l in state.levels if l.status == 'error']
                if len(placed_levels) == 0 and (len(real_cancelled) + len(error_levels)) > 0:
                    # Before declaring zombie, try to restart error levels once
                    if error_levels:
                        log(f"[Grid] {market}: 0 placed orders with {len(error_levels)} errors, "
                            f"attempting restart...", level='warning')
                        restarted = 0
                        for level in error_levels:
                            if level.side == 'buy':  # Only retry buys
                                resp = self._place_limit_order(market, level.side, level.amount, level.price)
                                if resp and isinstance(resp, dict) and resp.get('orderId'):
                                    level.order_id = resp['orderId']
                                    level.status = 'placed'
                                    level.placed_at = time.time()
                                    level.error_msg = None
                                    restarted += 1
                                time.sleep(0.2)
                        if restarted > 0:
                            log(f"[Grid] {market}: restarted {restarted} buy orders", level='info')
                            self._save_states()
                            continue  # Skip zombie detection, we just placed orders

                    is_zombie = True
                    log(f"[Grid] Zombie grid detected: {market} (running but 0 placed orders, "
                        f"{len(real_cancelled)} cancelled, {len(error_levels)} errors)", level='warning')
            if is_broken or is_stale or is_zombie:
                kind = 'zombie' if is_zombie else 'broken' if is_broken else 'stale'
                log(f"[Grid] {kind.capitalize()} grid {market} paused "
                    f"(status={state.status}, trades={state.total_trades}). "
                    f"State preserved — use dashboard to restart or delete.", level='warning')
                # Pause, don't delete — preserves trade history and allows manual restart
                self.stop_grid(market, cancel_orders=not is_zombie)
                results[f'cleanup_{market}'] = 'paused'

        return results

    def _auto_create_grids(self, count: int, gcfg: dict) -> List[str]:
        """Auto-create grids for the best available markets."""
        investment_per_grid = float(gcfg.get('investment_per_grid', 50))
        num_grids = int(gcfg.get('num_grids', 8))
        grid_mode = gcfg.get('grid_mode', 'arithmetic')
        max_grids = int(gcfg.get('max_grids', 2))

        # Check EUR balance
        available_eur = self._get_eur_balance()

        # Budget reservation: dynamic or static mode
        budget_cfg = {}
        try:
            import json as _json
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'bot_config.json')
            with open(cfg_path, 'r', encoding='utf-8-sig') as _f:
                budget_cfg = _json.load(_f).get('BUDGET_RESERVATION', {})
        except Exception:
            pass
        if budget_cfg.get('enabled', False):
            mode = budget_cfg.get('mode', 'static')
            if mode == 'dynamic':
                # Dynamic: calculate grid budget as percentage of total EUR (available + inOrder)
                total_eur = self._get_total_eur_balance()
                grid_pct = float(budget_cfg.get('grid_pct', 40)) / 100.0
                reserve_eur = float(budget_cfg.get('min_reserve_eur', 10))
                grid_max_base = max(0, (total_eur - reserve_eur) * grid_pct)
                grid_profit = self.get_total_grid_profit() if budget_cfg.get('reinvest_grid_profits', True) else 0
                max_grid_investment = grid_max_base + max(0, grid_profit)
                # Auto-size investment_per_grid based on budget and max_grids
                active_grid_count = len([s for s in self.grids.values()
                                          if s.status in ('running', 'placing_orders', 'initialized')])
                grids_to_fill = max(1, max_grids - active_grid_count)
                auto_invest = max_grid_investment / max(1, max_grids)
                if auto_invest >= 30:  # minimum viable per grid
                    investment_per_grid = round(auto_invest, 2)
                log(f"[Grid] Dynamic budget: total_eur={total_eur:.2f}, grid_pct={grid_pct*100:.0f}%, "
                    f"grid_budget={grid_max_base:.2f}, profit={grid_profit:.2f}, "
                    f"effective={max_grid_investment:.2f}, per_grid={investment_per_grid:.2f}", level='info')
            else:
                grid_max_base = float(budget_cfg.get('grid_bot_max_eur', 120))
                grid_profit = self.get_total_grid_profit() if budget_cfg.get('reinvest_grid_profits', True) else 0
                max_grid_investment = grid_max_base + max(0, grid_profit)
                log(f"[Grid] Static budget: base={grid_max_base:.0f}, profit={grid_profit:.2f}, "
                    f"effective_max={max_grid_investment:.2f}", level='info')
        else:
            max_grid_investment = float(gcfg.get('max_total_investment', 100))

        # Already invested in grids
        grid_invested = sum(s.config.total_investment for s in self.grids.values()
                           if s.status in ('running', 'placing_orders', 'initialized'))
        remaining_budget = min(available_eur * 0.8, max_grid_investment - grid_invested)

        log(f"[Grid] Budget check: EUR={available_eur:.2f}, max_invest={max_grid_investment:.0f}, "
            f"already_invested={grid_invested:.0f}, remaining={remaining_budget:.2f}, "
            f"need={investment_per_grid:.0f}/grid", level='info')

        if remaining_budget < investment_per_grid:
            log(f"[Grid] Insufficient budget for new grids: {remaining_budget:.2f} EUR available "
                f"(need {investment_per_grid:.0f})", level='info')
            return []

        # Ensure each order is >= 5.50 EUR (Bitvavo min = 5 EUR + safety margin)
        min_order_value = 5.50
        while num_grids > 3 and (investment_per_grid / num_grids) < min_order_value:
            num_grids -= 1
        if (investment_per_grid / num_grids) < min_order_value:
            log(f"[Grid] Cannot create grids: investment {investment_per_grid:.0f} EUR / {num_grids} grids "
                f"= {investment_per_grid/num_grids:.2f} EUR/order < {min_order_value} EUR min", level='warning')
            return []

        log(f"[Grid] Auto-create: budget {remaining_budget:.0f} EUR, {investment_per_grid:.0f}/grid, {num_grids} levels", level='info')

        # Select best markets
        candidates = self.auto_select_markets(max_grids=count)
        created = []

        for candidate in candidates:
            if remaining_budget < investment_per_grid:
                break

            market = candidate['market']
            actual_investment = min(investment_per_grid, remaining_budget)

            state = self.create_grid(
                market=market,
                lower_price=candidate['suggested_lower'],
                upper_price=candidate['suggested_upper'],
                num_grids=num_grids,
                total_investment=actual_investment,
                grid_mode=grid_mode,
                auto_rebalance=True,
                stop_loss_pct=float(gcfg.get('stop_loss_pct', 0.15)),
                take_profit_pct=float(gcfg.get('take_profit_pct', 0.20)),
                trailing_tp_enabled=bool(gcfg.get('trailing_tp_enabled', True)),
                trailing_tp_callback_pct=float(gcfg.get('trailing_tp_callback_pct', 0.03)),
                profit_compounding=bool(gcfg.get('profit_compounding', True)),
                volatility_adaptive=bool(gcfg.get('volatility_adaptive', True)),
                inventory_skew=bool(gcfg.get('inventory_skew', True)),
                auto_created=True,
            )

            if state:
                created.append(market)
                remaining_budget -= actual_investment
                log(f"[Grid] Auto-created grid for {market}: "
                    f"{candidate['suggested_lower']:.2f}-{candidate['suggested_upper']:.2f}, "
                    f"{actual_investment:.0f} EUR investment", level='info')

        return created

    # ==================== STATUS & REPORTING ====================

    def get_grid_status(self, market: str) -> Optional[Dict[str, Any]]:
        """Get detailed status for a grid."""
        if market not in self.grids:
            return None

        state = self.grids[market]
        config = state.config

        filled_buys = sum(1 for l in state.levels if l.status == 'filled' and l.side == 'buy')
        filled_sells = sum(1 for l in state.levels if l.status == 'filled' and l.side == 'sell')
        placed_orders = sum(1 for l in state.levels if l.status == 'placed')
        error_orders = sum(1 for l in state.levels if l.status == 'error')

        roi_pct = (state.total_profit / config.total_investment * 100) if config.total_investment > 0 else 0

        return {
            'market': market,
            'status': state.status,
            'config': {
                'lower_price': config.lower_price,
                'upper_price': config.upper_price,
                'num_grids': config.num_grids,
                'total_investment': config.total_investment,
                'grid_mode': config.grid_mode,
                'auto_rebalance': config.auto_rebalance,
                'auto_created': config.auto_created,
            },
            'current_price': state.current_price,
            'in_range': config.lower_price <= state.current_price <= config.upper_price if state.current_price else False,
            'total_profit': round(state.total_profit, 4),
            'total_fees': round(state.total_fees, 4),
            'net_profit': round(state.total_profit - state.total_fees, 4),
            'roi_pct': round(roi_pct, 2),
            'total_trades': state.total_trades,
            'filled_buys': filled_buys,
            'filled_sells': filled_sells,
            'placed_orders': placed_orders,
            'error_orders': error_orders,
            'base_balance': state.base_balance,
            'quote_balance': state.quote_balance,
            'rebalance_count': state.rebalance_count,
            'last_update': state.last_update,
            'levels': [
                {
                    'id': l.level_id,
                    'price': l.price,
                    'side': l.side,
                    'amount': l.amount,
                    'status': l.status,
                    'order_id': l.order_id,
                    'filled_price': l.filled_price,
                }
                for l in state.levels
            ],
        }

    def get_all_grids_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all grids."""
        summaries = []
        for market in self.grids:
            status = self.get_grid_status(market)
            if status:
                summaries.append({
                    'market': market,
                    'status': status['status'],
                    'profit': status['total_profit'],
                    'net_profit': status['net_profit'],
                    'roi_pct': status['roi_pct'],
                    'trades': status['total_trades'],
                    'in_range': status['in_range'],
                    'investment': status['config']['total_investment'],
                    'placed_orders': status['placed_orders'],
                })
        return summaries

    def get_grid_order_ids(self) -> set:
        """Get set of all active grid order IDs (for conflict avoidance with trailing bot)."""
        order_ids = set()
        for state in self.grids.values():
            if state.status in ('running', 'placing_orders', 'initialized'):
                for level in state.levels:
                    if level.order_id and level.status == 'placed':
                        order_ids.add(level.order_id)
        return order_ids

    def get_grid_markets(self) -> set:
        """Get set of all active grid markets (for conflict avoidance)."""
        return set(m for m, s in self.grids.items()
                   if s.status in ('running', 'placing_orders', 'initialized'))

    def get_grid_assets(self) -> set:
        """Get set of base asset symbols used by active grids (e.g. {'ETH', 'BTC'})."""
        assets = set()
        for m, s in self.grids.items():
            if s.status in ('running', 'placing_orders', 'initialized'):
                assets.add(m.replace('-EUR', ''))
        return assets

    def get_total_grid_investment(self) -> float:
        """Get total EUR invested in active grids."""
        return sum(s.config.total_investment for s in self.grids.values()
                   if s.status in ('running', 'placing_orders', 'initialized'))

    def get_total_grid_profit(self) -> float:
        """Get total profit from all grids."""
        return sum(s.total_profit for s in self.grids.values())


# ================= UTILITY FUNCTIONS =================

def calculate_optimal_grid_range(
    current_price: float,
    volatility_pct: float = 0.10,
    grid_width_multiplier: float = 2.0,
) -> Tuple[float, float]:
    """Calculate optimal grid range based on volatility."""
    range_pct = volatility_pct * grid_width_multiplier
    lower = current_price * (1 - range_pct / 2)
    upper = current_price * (1 + range_pct / 2)
    return lower, upper


def estimate_grid_profit(
    lower_price: float,
    upper_price: float,
    num_grids: int,
    investment: float,
    num_cycles: int = 1,
    fee_pct: float = MAKER_FEE_PCT,
) -> Dict[str, float]:
    """Estimate potential profit from grid trading, accounting for fees."""
    grid_spacing_pct = (upper_price - lower_price) / lower_price / num_grids
    profit_per_grid_raw = investment / num_grids * grid_spacing_pct
    fee_per_trade = investment / num_grids * fee_pct
    profit_per_grid = profit_per_grid_raw - 2 * fee_per_trade  # Buy + sell fee
    max_profit_per_cycle = profit_per_grid * (num_grids // 2)

    return {
        'grid_spacing_pct': grid_spacing_pct * 100,
        'profit_per_grid_eur': round(profit_per_grid, 4),
        'fee_per_round_trip': round(2 * fee_per_trade, 4),
        'max_profit_per_cycle': round(max_profit_per_cycle, 4),
        'estimated_total': round(max_profit_per_cycle * num_cycles, 4),
        'estimated_roi_pct': round((max_profit_per_cycle * num_cycles / investment) * 100, 2) if investment > 0 else 0,
    }


# ================= SINGLETON INSTANCE =================

_grid_manager: Optional[GridManager] = None


def get_grid_manager(bitvavo_client=None, config: dict = None) -> GridManager:
    """Get or create the singleton grid manager instance."""
    global _grid_manager
    if _grid_manager is None:
        _grid_manager = GridManager(bitvavo_client, config)
    else:
        if bitvavo_client is not None and _grid_manager.bitvavo is None:
            _grid_manager.bitvavo = bitvavo_client
        if config is not None:
            _grid_manager.bot_config = config
    return _grid_manager


def reset_grid_manager() -> None:
    """Reset singleton (for testing)."""
    global _grid_manager
    _grid_manager = None
