"""Portfolio business logic service."""
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import logging

from .data_service import DataService
from .price_service import PriceService

logger = logging.getLogger(__name__)


@dataclass
class TradeCard:
    """Trade card data structure for display."""
    market: str
    symbol: str
    crypto_name: str
    logo_url: str
    buy_price: float
    amount: float
    live_price: Optional[float]
    invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    status: str
    status_label: str
    dca_level: int
    dca_max_levels: int
    trailing_activated: bool
    trailing_progress: float
    activation_price: float
    highest_price: Optional[float]
    stop_price: Optional[float]
    dca_next_price: Optional[float] = None
    dca_buy_amount: float = 0.0
    trailing_stop: Optional[float] = None
    bought_at: Optional[Any] = None
    status_class: str = 'badge-neutral'
    dca_progress_pct: float = 0.0
    dca_remaining: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'market': self.market,
            'symbol': self.symbol,
            'crypto_name': self.crypto_name,
            'logo_url': self.logo_url,
            'buy_price': self.buy_price,
            'amount': self.amount,
            'live_price': self.live_price,
            'invested': self.invested,
            'current_value': self.current_value,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'status': self.status,
            'status_label': self.status_label,
            'dca_level': self.dca_level,
            'dca_max_levels': self.dca_max_levels,
            'trailing_activated': self.trailing_activated,
            'trailing_progress': self.trailing_progress,
            'activation_price': self.activation_price,
            'highest_price': self.highest_price,
            'stop_price': self.stop_price,
            'dca_next_price': self.dca_next_price,
            'dca_buy_amount': self.dca_buy_amount,
            'trailing_stop': self.trailing_stop or self.stop_price,
            'bought_at': self.bought_at,
            'status_class': self.status_class,
            'dca_progress_pct': self.dca_progress_pct,
            'dca_remaining': self.dca_remaining,
        }


@dataclass 
class PortfolioTotals:
    """Portfolio totals data structure."""
    total_invested: float
    total_current: float
    total_pnl: float
    total_pnl_pct: float
    trade_count: int
    eur_balance: float
    total_deposited: float
    real_profit: float
    real_profit_pct: float
    account_value: float
    winning_trades: int = 0
    losing_trades: int = 0
    trailing_active_count: int = 0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    weekly_pnl: float = 0.0
    weekly_pnl_pct: float = 0.0
    monthly_pnl: float = 0.0
    monthly_pnl_pct: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'total_invested': self.total_invested,
            'total_current': self.total_current,
            'total_pnl': self.total_pnl,
            'total_pnl_pct': self.total_pnl_pct,
            'trade_count': self.trade_count,
            'eur_balance': self.eur_balance,
            'total_deposited': self.total_deposited,
            'real_profit': self.real_profit,
            'real_profit_pct': self.real_profit_pct,
            'account_value': self.account_value,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'trailing_active_count': self.trailing_active_count,
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': self.daily_pnl_pct,
            'weekly_pnl': self.weekly_pnl,
            'weekly_pnl_pct': self.weekly_pnl_pct,
            'monthly_pnl': self.monthly_pnl,
            'monthly_pnl_pct': self.monthly_pnl_pct,
        }


# Crypto name mapping
CRYPTO_NAMES = {
    'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana',
    'ADA': 'Cardano', 'DOT': 'Polkadot', 'AVAX': 'Avalanche',
    'LINK': 'Chainlink', 'MATIC': 'Polygon', 'UNI': 'Uniswap',
    'XRP': 'Ripple', 'DOGE': 'Dogecoin', 'SHIB': 'Shiba Inu',
    'LTC': 'Litecoin', 'ATOM': 'Cosmos', 'XLM': 'Stellar',
    'ALGO': 'Algorand', 'NEAR': 'NEAR Protocol', 'FTM': 'Fantom',
    'HBAR': 'Hedera', 'VET': 'VeChain', 'ICP': 'Internet Computer',
    'FIL': 'Filecoin', 'SAND': 'The Sandbox', 'MANA': 'Decentraland',
    'AXS': 'Axie Infinity', 'AAVE': 'Aave', 'MKR': 'Maker',
    'COMP': 'Compound', 'SNX': 'Synthetix', 'CRV': 'Curve',
    'SUSHI': 'SushiSwap', 'YFI': 'yearn.finance', 'GRT': 'The Graph',
    'ENJ': 'Enjin', 'CHZ': 'Chiliz', 'BAT': 'Basic Attention Token',
    'ZEC': 'Zcash', 'XMR': 'Monero', 'DASH': 'Dash',
    'EOS': 'EOS', 'TRX': 'TRON', 'XTZ': 'Tezos',
    'EGLD': 'MultiversX', 'THETA': 'Theta Network', 'KSM': 'Kusama',
    'RUNE': 'THORChain', 'KAVA': 'Kava', 'CELO': 'Celo',
    'ONE': 'Harmony', 'QTUM': 'Qtum', 'ZIL': 'Zilliqa',
    'ICX': 'ICON', 'ONT': 'Ontology', 'SC': 'Siacoin',
    'ZRX': '0x', 'OMG': 'OMG Network', 'ANKR': 'Ankr',
    'SKL': 'SKALE', 'STORJ': 'Storj', 'NKN': 'NKN',
    'BAND': 'Band Protocol', 'REN': 'Ren', 'LRC': 'Loopring',
    'OCEAN': 'Ocean Protocol', 'CTSI': 'Cartesi', 'OGN': 'Origin Protocol',
    'NU': 'NuCypher', 'MASK': 'Mask Network', 'PERP': 'Perpetual Protocol',
    'DYDX': 'dYdX', 'IMX': 'Immutable X', 'ENS': 'Ethereum Name Service',
    'APE': 'ApeCoin', 'GMT': 'STEPN', 'OP': 'Optimism',
    'ARB': 'Arbitrum', 'SUI': 'Sui', 'APT': 'Aptos',
    'SEI': 'Sei', 'TIA': 'Celestia', 'JUP': 'Jupiter',
    'WIF': 'dogwifhat', 'BONK': 'Bonk', 'PEPE': 'Pepe',
    'FLOKI': 'Floki Inu', 'RENDER': 'Render Token', 'FET': 'Fetch.ai',
    'INJ': 'Injective', 'STX': 'Stacks', 'RNDR': 'Render',
}


class PortfolioService:
    """Service for portfolio calculations and trade cards."""
    
    def __init__(self, data_service: DataService, price_service: PriceService):
        self.data_service = data_service
        self.price_service = price_service
    
    def get_trade_cards(self, config: Optional[Dict] = None) -> List[TradeCard]:
        """Build trade cards for all open positions."""
        if config is None:
            config = self.data_service.load_config()
        
        trades = self.data_service.load_trades()
        open_trades = trades.get('open', {})
        
        if not open_trades:
            return []
        
        # Prefetch all prices at once
        markets = list(open_trades.keys())
        prices = self.price_service.get_prices_batch(markets)
        
        cards = []
        for market, trade in open_trades.items():
            card = self._build_trade_card(market, trade, prices, config)
            if card:
                cards.append(card)
        
        # Sort by P/L descending
        cards.sort(key=lambda x: x.pnl, reverse=True)
        return cards
    
    def _build_trade_card(
        self,
        market: str,
        trade: Dict[str, Any],
        prices: Dict[str, float],
        config: Dict[str, Any]
    ) -> Optional[TradeCard]:
        """Build a single trade card."""
        try:
            live_price = prices.get(market)
            buy_price = float(trade.get('buy_price', 0))
            
            # CRITICAL: Use remaining_amount from partial_tp_events if available
            partial_tp_events = trade.get('partial_tp_events', [])
            if partial_tp_events and len(partial_tp_events) > 0:
                # After partial TPs, use remaining_amount from last event
                last_event = partial_tp_events[-1]
                amount = float(last_event.get('remaining_amount', 0) or 0)
            else:
                # No partial TPs, use original amount
                amount = float(trade.get('amount', 0))
            
            # Calculate invested - BULLETPROOF: always cross-check against buy_price * amount
            # invested_eur can be stale/wrong after sync, so we verify
            invested_eur_val = float(trade.get('invested_eur', 0) or 0)
            total_invested_val = float(trade.get('total_invested_eur', 0) or 0)
            computed_invested = buy_price * amount if buy_price > 0 and amount > 0 else 0.0
            
            # Pick best value with cross-check
            if invested_eur_val > 0:
                invested = invested_eur_val
            elif total_invested_val > 0:
                invested = total_invested_val
            else:
                invested = computed_invested
            
            # Cross-check: if stored invested diverges >20% from reality, use computed
            if computed_invested > 0 and invested > 0:
                divergence = abs(computed_invested - invested) / max(invested, 0.01)
                if divergence > 0.20:
                    invested = computed_invested
            
            if live_price:
                current_value = live_price * amount
                pnl = current_value - invested
                pnl_pct = ((current_value / invested) - 1) * 100 if invested > 0 else 0
            else:
                current_value = invested
                pnl = 0
                pnl_pct = 0
            
            # Trailing info - COMPATIBILITY: Support both flat fields and trailing_info object
            # Old format: trade['trailing_activated'], trade['activation_price']
            # New format: trade['trailing_info']['activated'], trade['trailing_info']['activation_price']
            trailing_info = trade.get('trailing_info', {})
            activation_price = trailing_info.get('activation_price') or trade.get('activation_price')
            trailing_activated = trailing_info.get('activated', False) or trade.get('trailing_activated', False)
            highest_price = trailing_info.get('highest_price') or trade.get('highest_price') or trade.get('highest_since_activation')
            stop_price = trailing_info.get('stop_price') or trailing_info.get('trailing_stop') or trade.get('trailing_stop')
            
            # Calculate trailing stop price for dashboard if not stored by bot
            if trailing_activated and not stop_price and highest_price and buy_price:
                try:
                    _hw = float(highest_price)
                    _default_trail = float(config.get('DEFAULT_TRAILING', 0.04))
                    _stepped_raw = config.get('STEPPED_TRAILING_LEVELS', [])
                    _stepped = []
                    for _s in (_stepped_raw or []):
                        if isinstance(_s, (list, tuple)) and len(_s) >= 2:
                            _stepped.append({'profit_pct': float(_s[0]), 'trailing_pct': float(_s[1])})
                        elif isinstance(_s, dict):
                            _stepped.append(_s)
                    if _hw > buy_price:
                        _profit_pct = (_hw - buy_price) / buy_price
                        _trail_pct = _default_trail
                        for _lvl in reversed(_stepped):
                            if _profit_pct >= float(_lvl['profit_pct']):
                                _trail_pct = min(_trail_pct, float(_lvl['trailing_pct']))
                                break
                        stop_price = _hw * (1 - _trail_pct)
                except Exception:
                    pass
            
            # Calculate activation price from config if not set
            # First check if trade has its own trailing_activation_pct
            if not activation_price and buy_price:
                trailing_pct = trade.get('trailing_activation_pct')
                if trailing_pct is None:
                    trailing_pct = float(config.get('TRAILING_ACTIVATION_PCT', 0.02))
                activation_price = buy_price * (1 + float(trailing_pct))
            else:
                activation_price = activation_price or 0
            
            # Calculate trailing progress
            trailing_progress = 0
            if activation_price and buy_price and live_price and activation_price > buy_price:
                trailing_progress = (
                    (live_price - buy_price) / (activation_price - buy_price) * 100
                )
                trailing_progress = max(0, min(100, trailing_progress))
            
            # DCA info — cap dca_level to dca_max so corrupted legacy trades
            # (dca_buys=50, dca_max_config=9) never display nonsense.
            dca_max = int(config.get('DCA_MAX_BUYS', 4))
            _dca_level_raw = int(trade.get('dca_buys', trade.get('dca_level', 0)) or 0)
            dca_level = min(_dca_level_raw, dca_max) if dca_max else _dca_level_raw
            
            # DCA next price and buy amount
            dca_next_price = trade.get('dca_next_price')
            dca_step_pct = float(config.get('DCA_STEP_PCT', 0.06))
            dca_buy_eur = float(config.get('DCA_ORDER_EUR', 5.0))
            if not dca_next_price and buy_price:
                dca_next_price = buy_price * (1 - dca_step_pct)
            
            dca_progress_pct = (dca_level / dca_max * 100) if dca_max else 0
            dca_remaining = max(dca_max - dca_level, 0) if dca_max else 0
            
            # Symbol and name
            symbol = market.replace('-EUR', '')
            crypto_name = CRYPTO_NAMES.get(symbol, symbol)
            
            # Status - bepaal op basis van daadwerkelijke trade state
            is_external = trade.get('is_external', False) or trade.get('external', False)
            
            if is_external:
                status = 'external'
                status_label = 'EXTERNE POSITIE'
            elif trailing_activated and live_price and buy_price and live_price >= buy_price:
                status = 'trailing'
                status_label = 'TRAILING ACTIEF'
            elif dca_level > 0:
                status = 'dca'
                status_label = f'DCA {dca_level}'
            else:
                status = 'active'
                status_label = 'ACTIEF'
            
            return TradeCard(
                market=market,
                symbol=symbol,
                crypto_name=crypto_name,
                logo_url=self._get_logo_url(symbol),
                buy_price=buy_price,
                amount=amount,
                live_price=live_price,
                invested=invested,
                current_value=current_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
                status=status,
                status_label=status_label,
                dca_level=dca_level,
                dca_max_levels=dca_max,
                trailing_activated=trailing_activated,
                trailing_progress=trailing_progress,
                activation_price=activation_price,
                highest_price=highest_price,
                stop_price=stop_price,
                dca_next_price=dca_next_price,
                dca_buy_amount=dca_buy_eur,
                trailing_stop=stop_price,
                bought_at=trade.get('timestamp') or trade.get('opened_ts'),
                dca_progress_pct=dca_progress_pct,
                dca_remaining=dca_remaining,
            )
        except Exception as e:
            logger.error(f"Error building trade card for {market}: {e}")
            return None
    
    def _get_logo_url(self, symbol: str) -> str:
        """Get crypto logo URL."""
        symbol_lower = symbol.lower()
        return f"https://cryptologos.cc/logos/{self._get_logo_name(symbol_lower)}-{symbol_lower}-logo.png"
    
    def _get_logo_name(self, symbol: str) -> str:
        """Get logo name for crypto symbol."""
        logo_names = {
            'btc': 'bitcoin', 'eth': 'ethereum', 'sol': 'solana',
            'ada': 'cardano', 'dot': 'polkadot', 'avax': 'avalanche',
            'link': 'chainlink', 'matic': 'polygon', 'uni': 'uniswap',
            'xrp': 'xrp', 'doge': 'dogecoin', 'shib': 'shiba-inu',
            'ltc': 'litecoin', 'atom': 'cosmos', 'xlm': 'stellar',
        }
        return logo_names.get(symbol, symbol)
    
    def calculate_totals(
        self,
        cards: List[TradeCard],
        heartbeat: Optional[Dict] = None
    ) -> PortfolioTotals:
        """Calculate portfolio totals from trade cards."""
        if heartbeat is None:
            heartbeat = self.data_service.load_heartbeat()
        
        # Ensure heartbeat is a dict (can be None if file missing)
        if not isinstance(heartbeat, dict):
            heartbeat = {}
        
        total_invested = sum(c.invested for c in cards)
        total_current = sum(c.current_value for c in cards)
        total_pnl = sum(c.pnl for c in cards)
        eur_balance = float(heartbeat.get('eur_balance', 0) or 0)
        total_deposited = self.data_service.get_total_deposited()
        
        # Compute real total from ALL Bitvavo balances × live prices (like Bitvavo does)
        account_value = total_current + eur_balance  # fallback
        try:
            all_balances = self.price_service.get_all_balances()
            if all_balances:
                live_total = 0.0
                for bal in all_balances:
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
                        price = self.price_service.get_price(market)
                        if price:
                            live_total += total_amount * price
                if live_total > 0:
                    account_value = live_total
        except Exception as e:
            logger.debug(f"Live portfolio total calc error: {e}")
        
        # Count winning/losing/trailing trades
        winning_trades = sum(1 for c in cards if c.pnl > 0)
        losing_trades = sum(1 for c in cards if c.pnl < 0)
        trailing_active_count = sum(1 for c in cards if c.trailing_activated)
        
        real_profit = account_value - total_deposited
        
        # Calculate period P&L from closed trades
        import time as _time
        import json as _json
        _now = _time.time()
        _day_ago = _now - 86400
        _week_ago = _now - 7 * 86400
        _month_ago = _now - 30 * 86400
        daily_pnl = daily_inv = weekly_pnl = weekly_inv = monthly_pnl = monthly_inv = 0.0
        try:
            _trades_data = self.data_service.load_trades()
            _closed = list(_trades_data.get('closed', []) or [])
            _archive_path = self.data_service._project_root / 'data' / 'trade_archive.json'
            if _archive_path.exists():
                try:
                    with _archive_path.open('r', encoding='utf-8') as _af:
                        _arch = _json.load(_af)
                    if isinstance(_arch, list):
                        _closed = _closed + _arch
                    elif isinstance(_arch, dict):
                        _closed = _closed + (_arch.get('closed', []) or [])
                except Exception:
                    pass
            for _t in _closed:
                _ts = float(_t.get('timestamp', 0) or 0)
                if _ts <= 0:
                    continue
                _profit = float(_t.get('profit', 0) or 0)
                _inv = float(_t.get('initial_invested_eur', 0) or _t.get('invested_eur', 0) or 0)
                if _ts >= _month_ago:
                    monthly_pnl += _profit
                    monthly_inv += _inv
                if _ts >= _week_ago:
                    weekly_pnl += _profit
                    weekly_inv += _inv
                if _ts >= _day_ago:
                    daily_pnl += _profit
                    daily_inv += _inv
        except Exception as _e:
            logger.debug(f"Period P&L calc error: {_e}")

        def _pct(pnl, inv):
            return (pnl / inv * 100) if inv > 0 else 0.0

        return PortfolioTotals(
            total_invested=total_invested,
            total_current=total_current,
            total_pnl=total_pnl,
            total_pnl_pct=(
                ((total_current / total_invested) - 1) * 100
                if total_invested > 0 else 0
            ),
            trade_count=len(cards),
            eur_balance=eur_balance,
            total_deposited=total_deposited,
            real_profit=real_profit,
            real_profit_pct=(
                ((account_value / total_deposited) - 1) * 100
                if total_deposited > 0 else 0
            ),
            account_value=account_value,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            trailing_active_count=trailing_active_count,
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(_pct(daily_pnl, daily_inv), 2),
            weekly_pnl=round(weekly_pnl, 2),
            weekly_pnl_pct=round(_pct(weekly_pnl, weekly_inv), 2),
            monthly_pnl=round(monthly_pnl, 2),
            monthly_pnl_pct=round(_pct(monthly_pnl, monthly_inv), 2),
        )
    
    def get_portfolio_data(self) -> Dict[str, Any]:
        """Get complete portfolio data for API/template."""
        config = self.data_service.load_config()
        heartbeat = self.data_service.load_heartbeat()
        
        cards = self.get_trade_cards(config)
        totals = self.calculate_totals(cards, heartbeat)
        
        return {
            'cards': [c.to_dict() for c in cards],
            'totals': totals.to_dict(),
            'config': config,
            'heartbeat': heartbeat,
            'bot_online': self.data_service.is_bot_online(),
        }
