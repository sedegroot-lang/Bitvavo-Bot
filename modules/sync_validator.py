"""
Sync Validator - Prevents desync between bot trade_log and Bitvavo account.
Automatically detects and reports discrepancies.
"""
import os
import json
import time
from typing import Dict, List, Tuple
from pathlib import Path

from modules.cost_basis import derive_cost_basis

class SyncValidator:
    def __init__(self, bitvavo_client, trade_log_path: Path, logger=None):
        self.bitvavo = bitvavo_client
        self.trade_log_path = trade_log_path
        self.logger = logger
        
    def _log(self, msg: str, level='info'):
        """Log message."""
        if self.logger:
            getattr(self.logger, level)(msg)
        else:
            print(f"[SyncValidator] {msg}")
    
    def get_bitvavo_balances(self) -> Dict[str, float]:
        """Get all non-zero crypto balances from Bitvavo."""
        try:
            balances = self.bitvavo.balance({})
            # Validate balances is a list (safe_call can return error dict)
            if not isinstance(balances, list):
                self._log(f"API error: balances is not a list: {balances}", level='error')
                return {}
            crypto_balances = {}
            for b in balances:
                if not isinstance(b, dict):
                    continue
                symbol = b.get('symbol', '')
                if symbol == 'EUR':
                    continue
                available = float(b.get('available', 0))
                in_order = float(b.get('inOrder', 0))
                total = available + in_order
                if total > 0.0001:  # Ignore dust
                    crypto_balances[symbol] = total
            return crypto_balances
        except Exception as e:
            self._log(f"Error fetching Bitvavo balances: {e}", level='error')
            return {}
    
    def get_bot_positions(self) -> Dict[str, Dict]:
        """Get open positions from trade_log.json."""
        try:
            with open(self.trade_log_path, 'r') as f:
                trade_log = json.load(f)
            
            bot_positions = {}
            for market, pos in trade_log.get('open', {}).items():
                # Extract symbol from market (e.g., "DOT-EUR" -> "DOT")
                symbol = market.split('-')[0]
                bot_positions[symbol] = {
                    'market': market,
                    'amount': pos.get('amount', 0),
                    'buy_price': pos.get('buy_price', 0),
                    'invested_eur': pos.get('invested_eur', 0)
                }
            return bot_positions
        except Exception as e:
            self._log(f"Error reading trade_log.json: {e}", level='error')
            return {}
    
    def validate_sync(self) -> Tuple[bool, List[str]]:
        """
        Validate that bot positions match Bitvavo balances.
        Returns: (is_synced, list_of_issues)
        Skips HODL assets (BTC, ETH) - those are managed by HODL scheduler.
        Skips grid trading assets - those are managed by the grid bot.
        """
        bitvavo_balances = self.get_bitvavo_balances()
        bot_positions = self.get_bot_positions()
        
        # Load HODL assets from bot_config.json
        hodl_assets = set()
        try:
            config_path = Path('config') / 'bot_config.json'
            if config_path.exists():
                config_data = json.loads(config_path.read_text(encoding='utf-8'))
                hodl_cfg = config_data.get('HODL_SCHEDULER', {})
                if hodl_cfg.get('enabled', False):
                    for schedule in hodl_cfg.get('schedules', []):
                        market = schedule.get('market', '')
                        if market:
                            symbol = market.replace('-EUR', '')
                            hodl_assets.add(symbol)
        except Exception:
            # Fallback: hardcoded BTC/ETH as HODL
            hodl_assets = {'BTC', 'ETH'}
        
        # Load grid trading assets to skip
        grid_assets = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_assets = gm.get_grid_assets()
        except Exception:
            pass
        skip_assets = hodl_assets | grid_assets
        
        issues = []
        
        # Check: Bitvavo has coins that bot doesn't track (skip HODL + grid assets)
        for symbol, amount in bitvavo_balances.items():
            # Skip HODL and grid trading assets - they're managed separately
            if symbol in skip_assets:
                continue
            if symbol not in bot_positions:
                issues.append(
                    f"DESYNC: Bitvavo has {amount:.8f} {symbol} but bot has NO open position for {symbol}-EUR"
                )
            else:
                bot_amount = bot_positions[symbol]['amount']
                diff = abs(amount - bot_amount)
                # Allow small difference due to rounding
                if diff > 0.001:
                    issues.append(
                        f"AMOUNT MISMATCH: {symbol} - Bitvavo: {amount:.8f}, Bot: {bot_amount:.8f} (diff: {diff:.8f})"
                    )
        
        # Check: Bot tracks coins that Bitvavo doesn't have
        for symbol, pos in bot_positions.items():
            if symbol not in bitvavo_balances:
                issues.append(
                    f"PHANTOM POSITION: Bot thinks it has {pos['amount']:.8f} {symbol} but Bitvavo shows ZERO"
                )
        
        is_synced = len(issues) == 0
        
        if is_synced:
            self._log(f"✓ Sync validation passed - {len(bitvavo_balances)} positions match")
        else:
            self._log(f"✗ Sync validation FAILED - {len(issues)} issues found", level='warning')
            for issue in issues:
                self._log(f"  - {issue}", level='warning')
        
        return is_synced, issues
    
    def auto_fix_phantom_positions(self, dry_run=True) -> int:
        """
        Remove phantom positions (bot has, Bitvavo doesn't).
        Returns number of fixes applied.
        Skips grid-managed assets to avoid conflicts.
        """
        bitvavo_balances = self.get_bitvavo_balances()
        bot_positions = self.get_bot_positions()

        # Skip grid-managed assets
        grid_assets = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_assets = gm.get_grid_assets() if gm else set()
        except Exception:
            pass
        hodl_assets = set()
        try:
            config_path = Path('config') / 'bot_config.json'
            if config_path.exists():
                _cfg = json.loads(config_path.read_text(encoding='utf-8'))
                _hodl_cfg = _cfg.get('HODL_SCHEDULER', {})
                if _hodl_cfg.get('enabled', False):
                    for _sched in _hodl_cfg.get('schedules', []):
                        _mkt = _sched.get('market', '')
                        if _mkt:
                            hodl_assets.add(_mkt.replace('-EUR', ''))
        except Exception:
            hodl_assets = {'BTC', 'ETH'}
        skip_assets = hodl_assets | grid_assets
        
        fixes = []
        for symbol, pos in bot_positions.items():
            if symbol in skip_assets:
                continue
            if symbol not in bitvavo_balances:
                fixes.append({
                    'symbol': symbol,
                    'market': pos['market'],
                    'amount': pos['amount'],
                    'action': 'remove_phantom'
                })
        
        if not fixes:
            self._log("No phantom positions to fix")
            return 0
        
        if dry_run:
            self._log(f"DRY RUN: Would fix {len(fixes)} phantom positions:")
            for fix in fixes:
                self._log(f"  - Remove {fix['market']}: {fix['amount']:.8f} {fix['symbol']}")
            return 0
        
        # Actually apply fixes
        try:
            from modules.trade_store import load_snapshot, save_snapshot
            trade_log = load_snapshot(str(self.trade_log_path))
            
            # Backup
            backup_path = self.trade_log_path.parent / f"trade_log.json.bak.{int(time.time())}"
            
            # Remove phantom positions
            for fix in fixes:
                market = fix['market']
                if market in trade_log.get('open', {}):
                    del trade_log['open'][market]
                    self._log(f"Removed phantom position: {market}")
            
            # Save via trade_store (with validation + atomic write)
            save_snapshot(trade_log, str(self.trade_log_path), backup_path=str(backup_path))
            
            self._log(f"✓ Fixed {len(fixes)} phantom positions (backup: {backup_path})")
            return len(fixes)
            
        except Exception as e:
            self._log(f"Error fixing phantom positions: {e}", level='error')
            return 0
    
    def auto_add_missing_positions(self, dry_run=True) -> int:
        """
        Add missing positions (Bitvavo has, bot doesn't).
        Uses current market price as buy_price (conservative).
        Returns number of positions added.
        Skips HODL assets (BTC, ETH) - those are managed by HODL scheduler.
        Skips grid trading assets - those are managed by the grid bot.
        """
        bitvavo_balances = self.get_bitvavo_balances()
        bot_positions = self.get_bot_positions()

        # Load DCA settings for correct next price/limits
        dca_drop_pct = 0.06
        dca_max_buys = 2
        try:
            config_path = Path('config') / 'bot_config.json'
            if config_path.exists():
                config_data = json.loads(config_path.read_text(encoding='utf-8'))
                dca_drop_pct = float(config_data.get('DCA_DROP_PCT', dca_drop_pct) or dca_drop_pct)
                dca_max_buys = int(config_data.get('DCA_MAX_BUYS', dca_max_buys) or dca_max_buys)
        except Exception:
            pass
        
        # Load HODL assets from bot_config.json
        hodl_assets = set()
        try:
            config_path = Path('config') / 'bot_config.json'
            if config_path.exists():
                config_data = json.loads(config_path.read_text(encoding='utf-8'))
                hodl_cfg = config_data.get('HODL_SCHEDULER', {})
                if hodl_cfg.get('enabled', False):
                    for schedule in hodl_cfg.get('schedules', []):
                        market = schedule.get('market', '')
                        if market:
                            symbol = market.replace('-EUR', '')
                            hodl_assets.add(symbol)
        except Exception:
            # Fallback: hardcoded BTC/ETH as HODL
            hodl_assets = {'BTC', 'ETH'}
        
        # Load grid trading assets to skip
        grid_assets = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_assets = gm.get_grid_assets()
        except Exception:
            pass
        skip_assets = hodl_assets | grid_assets
        
        additions = []
        for symbol, amount in bitvavo_balances.items():
            # Skip HODL and grid trading assets - they're managed separately
            if symbol in skip_assets:
                continue
            if symbol not in bot_positions:
                market = f"{symbol}-EUR"
                # Try to get accurate cost basis from trade history (handles partial sells)
                try:
                    avg_buy_price = None
                    invested = None
                    initial_invested = None
                    total_invested = None
                    dca_buys = 1
                    result = derive_cost_basis(self.bitvavo, market, amount, tolerance=0.10)
                    if result:
                        invested = round(result.invested_eur, 2)
                        avg_buy_price = result.avg_price
                        initial_invested = invested
                        total_invested = invested
                        # FIX #004: dca_buys=0 for newly synced positions.
                        # buy_order_count includes ALL historical orders (old closed
                        # positions too), so it is NOT a reliable DCA counter.
                        # The bot has not tracked any DCAs for this new entry.
                        dca_buys = 0
                        self._log(
                            f"Cost basis for {market}: €{avg_buy_price:.6f} ({dca_buys} buy order(s))",
                            level='debug',
                        )
                    else:
                        # Fallback: use FIFO cost basis from all trades (accounts for sells)
                        try:
                            from modules.cost_basis import _compute_cost_basis_from_fills
                            trades = self.bitvavo.trades(market, {})
                            if trades and isinstance(trades, list):
                                fifo_result = _compute_cost_basis_from_fills(
                                    trades, market=market, target_amount=amount, tolerance=1.0,
                                )
                                if fifo_result and fifo_result.avg_price > 0:
                                    avg_buy_price = fifo_result.avg_price
                                    invested = round(fifo_result.invested_eur, 2)
                                    initial_invested = invested
                                    total_invested = invested
                                    # FIX #004: same as above — don't use buy_order_count as DCA counter
                                    dca_buys = 0
                                    self._log(
                                        f"Fallback FIFO cost basis for {market}: €{avg_buy_price:.6f} ({dca_buys} buy order(s))",
                                        level='debug',
                                    )
                                else:
                                    # Last resort: simple average of buy trades only
                                    buy_trades = [t for t in trades if t.get('side') == 'buy']
                                    if buy_trades:
                                        total_cost = sum(float(t.get('amount', 0)) * float(t.get('price', 0)) for t in buy_trades)
                                        total_amount = sum(float(t.get('amount', 0)) for t in buy_trades)
                                        if total_amount > 0:
                                            avg_buy_price = total_cost / total_amount
                                            self._log(
                                                f"Calculated avg buy price for {market}: €{avg_buy_price:.6f} from {len(buy_trades)} trades (WARNING: no sell history accounted)",
                                                level='warning',
                                            )
                        except Exception as te:
                            self._log(f"Could not get trade history for {market}: {te}", level='debug')
                    
                    # Fallback to current price if no trade history available
                    if avg_buy_price is None:
                        ticker = self.bitvavo.tickerPrice({'market': market})
                        avg_buy_price = float(ticker['price'])
                        self._log(f"Using current price for {market}: €{avg_buy_price:.6f} (no trade history)")
                    
                    # SANITY CHECK: if calculated buy_price is >30% above current market price,
                    # it likely includes old closed positions. Use current price instead to
                    # prevent catastrophic DCA cascades.
                    try:
                        ticker = self.bitvavo.tickerPrice({'market': market})
                        current_price = float(ticker['price'])
                        if current_price > 0 and avg_buy_price > current_price * 1.30:
                            self._log(
                                f"⚠️ SANITY CHECK: {market} calculated buy_price €{avg_buy_price:.6f} is "
                                f"{((avg_buy_price / current_price) - 1) * 100:.1f}% above current price €{current_price:.6f}. "
                                f"Using current price to prevent DCA cascade.",
                                level='warning',
                            )
                            avg_buy_price = current_price
                            invested = round(amount * current_price, 2)
                            initial_invested = invested
                            total_invested = invested
                    except Exception:
                        pass
                    
                    if invested is None:
                        invested = round(amount * avg_buy_price, 2)
                    if initial_invested is None:
                        initial_invested = invested
                    if total_invested is None:
                        total_invested = invested
                    
                    additions.append({
                        'symbol': symbol,
                        'market': market,
                        'amount': amount,
                        'price': avg_buy_price,
                        'invested': invested,
                        'initial_invested_eur': initial_invested,
                        'total_invested_eur': total_invested,
                        'dca_buys': dca_buys
                    })
                except Exception as e:
                    self._log(f"Could not get price for {market}: {e}", level='warning')
        
        if not additions:
            self._log("No missing positions to add")
            return 0

        # NOTE: We do NOT respect MAX_OPEN_TRADES here because these positions ALREADY EXIST
        # on Bitvavo - the bot bought them, they're just missing from trade_log.
        # Not syncing them would cause permanent desync and potential double-buys.
        # MAX_OPEN_TRADES should only limit NEW buys, not sync of existing positions.
        self._log(f"Syncing {len(additions)} existing Bitvavo positions to trade_log (bypass MAX_OPEN_TRADES - already bought)")
        
        if dry_run:
            self._log(f"DRY RUN: Would add {len(additions)} missing positions:")
            for add in additions:
                self._log(f"  - Add {add['market']}: {add['amount']:.8f} @ €{add['price']:.4f} = €{add['invested']:.2f}")
            return 0
        
        # Actually apply additions
        try:
            from modules.trade_store import load_snapshot, save_snapshot
            trade_log = load_snapshot(str(self.trade_log_path))
            
            # Backup
            backup_path = self.trade_log_path.parent / f"trade_log.json.bak.{int(time.time())}"
            
            # Add missing positions
            if 'open' not in trade_log:
                trade_log['open'] = {}
            
            timestamp = time.time()
            for add in additions:
                trade_log['open'][add['market']] = {
                    'market': add['market'],
                    'buy_price': add['price'],
                    'highest_price': add['price'],
                    'amount': add['amount'],
                    'timestamp': timestamp,
                    'tp_levels_done': [False, False],
                    'dca_buys': 0,  # FIX #004: new synced position, no DCAs tracked yet
                    'dca_max': dca_max_buys,  # FIX #004: use config value, never inflate
                    'dca_next_price': add['price'] * (1 - dca_drop_pct),
                    'tp_last_time': 0.0,
                    'invested_eur': add['invested'],
                    'initial_invested_eur': add.get('initial_invested_eur', add['invested']),
                    'total_invested_eur': add.get('total_invested_eur', add['invested']),
                    'opened_ts': timestamp,
                    'trailing_activated': False,
                    'activation_price': None,
                    'highest_since_activation': None,
                    'last_dca_price': add['price'],
                    'synced_at': timestamp,  # DCA cooldown: skip DCA for 5 min after sync
                }
                self._log(f"Added missing position: {add['market']} - {add['amount']:.8f} @ €{add['price']:.4f}")
            
            # Save via trade_store (with validation + atomic write)
            save_snapshot(trade_log, str(self.trade_log_path), backup_path=str(backup_path))
            
            self._log(f"✓ Added {len(additions)} missing positions (backup: {backup_path})")
            return len(additions)
            
        except Exception as e:
            self._log(f"Error adding missing positions: {e}", level='error')
            return 0
