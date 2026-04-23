"""Main blueprint routes."""
import logging
from datetime import datetime
from flask import render_template, redirect, url_for, request
from . import main_bp


def _ts_to_float(v):
    """Convert a timestamp value (float, int, or datetime string) to float."""
    if not v:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.strptime(str(v), '%Y-%m-%d %H:%M:%S').timestamp()
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (ValueError, TypeError):
        return 0.0

logger = logging.getLogger(__name__)

# Import services with proper path handling
try:
    from ...services import get_portfolio_service, get_data_service
except ImportError:
    import sys
    from pathlib import Path
    services_path = Path(__file__).parent.parent.parent / 'services'
    if str(services_path.parent) not in sys.path:
        sys.path.insert(0, str(services_path.parent))
    from services import get_portfolio_service, get_data_service


@main_bp.route('/')
def index():
    """Redirect to portfolio."""
    return redirect(url_for('main.portfolio'))


@main_bp.route('/portfolio')
def portfolio():
    """Portfolio command page (new architecture)."""
    from datetime import datetime, timedelta
    import time
    
    data_service = get_data_service()
    portfolio_service = get_portfolio_service()
    
    config = data_service.load_config()
    heartbeat = data_service.load_heartbeat()
    trades = data_service.load_trades()
    
    cards = portfolio_service.get_trade_cards(config)
    totals = portfolio_service.calculate_totals(cards, heartbeat)
    
    # Generate portfolio combined chart data (14-day view)
    totals_dict = totals.to_dict()
    current_active = totals_dict.get('total_current', 0)
    current_invested = totals_dict.get('total_invested', 0)
    current_date = datetime.now()
    
    labels = []
    active_values = []
    hodl_values = []
    total_values = []
    
    # If portfolio empty, use placeholder data
    if current_active == 0 and current_invested == 0:
        for i in range(14, -1, -1):
            date = current_date - timedelta(days=i)
            labels.append(date.strftime('%d/%m'))
            active_values.append(0)
            hodl_values.append(0)
            total_values.append(0)
    else:
        pnl_pct = totals_dict.get('total_pnl_pct', 0) / 100
        daily_change = pnl_pct / 14 if pnl_pct != 0 else 0.001
        
        for i in range(14, -1, -1):
            date = current_date - timedelta(days=i)
            labels.append(date.strftime('%d/%m'))
            growth_factor = 1 - (daily_change * i)
            active_val = max(0, current_active * growth_factor)
            hodl_val = max(0, current_invested * 0.1)
            active_values.append(round(active_val, 2))
            hodl_values.append(round(hodl_val, 2))
            total_values.append(round(active_val + hodl_val, 2))
    
    portfolio_combined_data = {
        'labels': labels,
        'active_values': active_values,
        'hodl_values': hodl_values,
        'total_values': total_values
    }
    
    # Generate allocation chart data
    allocation_labels = []
    allocation_values = []
    asset_totals = {}
    
    for card_dict in [c.to_dict() for c in cards]:
        symbol = card_dict.get('symbol', 'UNKNOWN')
        current_value = card_dict.get('current_value', 0)
        asset_totals[symbol] = asset_totals.get(symbol, 0) + current_value
    
    for symbol, value in sorted(asset_totals.items(), key=lambda x: x[1], reverse=True):
        allocation_labels.append(symbol)
        allocation_values.append(round(value, 2))
    
    portfolio_allocation = {
        'labels': allocation_labels,
        'values': allocation_values
    }
    
    # Trade readiness status
    try:
        # Calculate trade readiness locally (avoid import issues)
        open_count = len(data_service.load_trades().get('open', {}))
        max_trades = int(config.get('MAX_OPEN_TRADES', 5) or 5)
        eur_balance = float((heartbeat.get('eur_balance') if heartbeat else 0) or 0)
        base_amount = float(config.get('BASE_AMOUNT_EUR', 12) or 12)
        min_balance = float(config.get('MIN_BALANCE_RESERVE', 10) or 10)
        
        # Get last scan stats for more detailed info
        last_scan = heartbeat.get('last_scan_stats', {}) if heartbeat else {}
        passed_min_score = last_scan.get('passed_min_score', 0)
        min_score_threshold = last_scan.get('min_score_threshold', 5.0)
        total_markets = last_scan.get('total_markets', 0)
        evaluated = last_scan.get('evaluated', 0)
        pending_reservations = int(heartbeat.get('pending_reservations', 0) or 0) if heartbeat else 0
        regime = last_scan.get('regime')
        regime_score_adj = float(last_scan.get('regime_score_adj', 0) or 0)
        regime_blocking = regime == 'bearish' or regime_score_adj > 50

        # ── New gate states (post-loss cooldown, BTC drawdown shield, adaptive score) ──
        cooldown_active_count = 0
        cooldown_markets_preview = []
        try:
            from bot.post_loss_cooldown import get_instance as _get_cd
            _cd = _get_cd()
            _now = __import__('time').time()
            for _m, _entry in list(getattr(_cd, '_state', {}).items())[:50]:
                _until = _entry.get('cooldown_until', 0)
                if _until and _until > _now:
                    cooldown_active_count += 1
                    if len(cooldown_markets_preview) < 3:
                        _mins = int((_until - _now) / 60)
                        cooldown_markets_preview.append(f"{_m} ({_mins}m)")
        except Exception:
            pass

        adaptive_bump = 0.0
        adaptive_reason = ''
        try:
            from bot.adaptive_score import get_instance as _get_as
            adaptive_bump, adaptive_reason = _get_as().adjustment(cfg=config)
        except Exception:
            pass

        btc_shield_blocked = False
        btc_shield_reason = ''
        try:
            from bot.shared import state as _bot_state
            _btc_candles = None
            try:
                _btc_candles = _bot_state.get_candles('BTC-EUR', '5m', 30) if hasattr(_bot_state, 'get_candles') else None
            except Exception:
                _btc_candles = None
            if _btc_candles:
                from bot.btc_drawdown_shield import evaluate as _btc_eval
                _res = _btc_eval(_btc_candles, cfg=config, market='ANY-EUR')
                btc_shield_blocked = bool(getattr(_res, 'blocked', False))
                btc_shield_reason = str(getattr(_res, 'reason', '') or '')
        except Exception:
            pass

        blocks = []
        warnings = []

        if regime_blocking:
            regime_label = (regime or 'bearish').upper().replace('_', ' ')
            blocks.append(f"Regime {regime_label}: alle nieuwe entries geblokkeerd (threshold +{regime_score_adj:.0f})")

        if btc_shield_blocked:
            blocks.append(f"🛡️ BTC drawdown shield actief: {btc_shield_reason or 'BTC daalt te snel'}")

        if open_count >= max_trades:
            blocks.append(f"Max trades bereikt: {open_count}/{max_trades}")
        elif open_count >= max_trades - 1:
            warnings.append(f"Bijna max trades: {open_count}/{max_trades}")
        
        available_for_trades = eur_balance - min_balance
        if available_for_trades < base_amount:
            blocks.append(f"Onvoldoende saldo: €{eur_balance:.2f} (nodig: €{base_amount:.0f} + €{min_balance:.0f} reserve)")
        elif available_for_trades < base_amount * 2:
            warnings.append(f"Laag saldo: €{eur_balance:.2f} — slechts 1 trade-slot betaalbaar")

        # Compute the actual MIN_SCORE the bot is using right now
        effective_min_score = float(min_score_threshold or 0) + float(adaptive_bump or 0)

        # ── Helper to surface "waarom geen trade" in BOTH yellow and green-wait states ──
        def _build_reason_lines() -> list:
            """Return informative lines explaining why no new trade is starting."""
            lines = []
            if total_markets > 0:
                if passed_min_score == 0:
                    lines.append(f'⚠️ {evaluated}/{total_markets} markets gescand — niemand scoort ≥{effective_min_score:.1f}')
                else:
                    lines.append(f'✅ {passed_min_score} market(s) voldoen aan min score ({effective_min_score:.1f})')
            else:
                lines.append('⏳ Eerste market-scan loopt nog (heartbeat heeft nog geen scan-stats)')
            if adaptive_bump and abs(adaptive_bump) >= 0.01:
                arrow = '↑' if adaptive_bump > 0 else '↓'
                lines.append(f'🎯 Adaptive MIN_SCORE {arrow} {adaptive_bump:+.1f} — {adaptive_reason or "WR-aanpassing"}')
            if cooldown_active_count > 0:
                preview = ', '.join(cooldown_markets_preview)
                extra = f' (+{cooldown_active_count - len(cooldown_markets_preview)} meer)' if cooldown_active_count > len(cooldown_markets_preview) else ''
                lines.append(f'⏸️ {cooldown_active_count} market(s) in post-loss cooldown: {preview}{extra}')
            return lines

        if blocks:
            trade_readiness = {
                'status': 'red', 'color': '#ef4444', 'icon': '🔴',
                'label': 'GEBLOKKEERD', 'message': blocks[0], 'details': blocks[1:] + warnings + _build_reason_lines()
            }
        elif warnings:
            # Build informative details — start with non-warning context (no duplicate of message)
            details = []
            remaining_slots = max_trades - open_count
            if pending_reservations > 0:
                details.append(f'🔒 {pending_reservations} market(s) gereserveerd (wordt verwerkt)')
            if remaining_slots > 0:
                details.append(f'{remaining_slots} slot(s) beschikbaar')
            if available_for_trades >= base_amount:
                details.append(f'€{available_for_trades:.2f} beschikbaar voor trades')
            details.extend(_build_reason_lines())
            # Determine a more descriptive headline message (don't repeat the warning)
            if passed_min_score == 0 and total_markets > 0:
                msg = f'Wacht op signaal — geen market scoort ≥{effective_min_score:.1f}'
            elif total_markets == 0:
                msg = 'Wacht op eerste market-scan'
            else:
                msg = warnings[0]
            trade_readiness = {
                'status': 'yellow', 'color': '#f59e0b', 'icon': '🟡',
                'label': 'BEPERKT', 'message': msg, 'details': details
            }
        else:
            remaining_slots = max_trades - open_count
            possible_trades = int(available_for_trades / base_amount) if base_amount > 0 else 0
            
            # Build details with scan info
            details = [
                f'{remaining_slots} open trade slots beschikbaar',
                f'€{available_for_trades:.2f} beschikbaar voor trades'
            ]
            details.extend(_build_reason_lines())
            
            if passed_min_score == 0 and total_markets > 0:
                trade_readiness = {
                    'status': 'green', 'color': '#10b981', 'icon': '🟢',
                    'label': 'GEREED (wacht)',
                    'message': f'Wacht op signaal — geen market scoort ≥{effective_min_score:.1f}',
                    'details': details
                }
            elif total_markets == 0:
                trade_readiness = {
                    'status': 'green', 'color': '#10b981', 'icon': '🟢',
                    'label': 'GEREED',
                    'message': 'Wacht op eerste market-scan',
                    'details': details
                }
            else:
                trade_readiness = {
                    'status': 'green', 'color': '#10b981', 'icon': '🟢',
                    'label': 'GEREED',
                    'message': f'{remaining_slots} slots vrij, {possible_trades} trades mogelijk',
                    'details': details
                }
        logger.info(f"Trade readiness: {trade_readiness['label']}")
    except Exception as e:
        logger.error(f"Trade readiness failed: {e}", exc_info=True)
        trade_readiness = {
            'status': 'unknown',
            'color': '#64748b',
            'icon': '⚪',
            'label': 'STATUS ONBEKEND',
            'message': 'Data tijdelijk niet beschikbaar',
            'details': ['Bot status wordt geladen...', 'Probeer de pagina te vernieuwen']
        }
    
    # Get closed trades — count driven by ?trades_count= query param
    try:
        trades_count = int(request.args.get('trades_count', 10))
    except (ValueError, TypeError):
        trades_count = 10
    trades_count = max(1, min(trades_count, 500))  # clamp to 1-500

    closed_trades_raw = list(trades.get('closed', []) or [])
    open_markets = set(trades.get('open', {}).keys())  # Markets that are still open

    # Merge in archived closed trades — oudere trades worden naar trade_archive.json
    # verplaatst door de bot. Zonder deze merge zie je alleen de paar trades die nog
    # in trade_log.json staan (typisch 5-10) i.p.v. de volledige historie.
    try:
        import json as _json
        from pathlib import Path as _Path
        _project_root = _Path(__file__).resolve().parent.parent.parent.parent.parent
        _archive_path = _project_root / 'data' / 'trade_archive.json'
        if _archive_path.exists():
            with _archive_path.open('r', encoding='utf-8') as _af:
                _archive = _json.load(_af)
            if isinstance(_archive, list):
                closed_trades_raw.extend(_archive)
            elif isinstance(_archive, dict):
                # Archive uses 'trades' key (canonical), but also support 'closed' for backwards compat
                closed_trades_raw.extend(_archive.get('trades', []) or [])
                closed_trades_raw.extend(_archive.get('closed', []) or [])
        # De-duplicate op (market, timestamp, sell_price)
        _seen = set()
        _deduped = []
        for _t in closed_trades_raw:
            _key = (_t.get('market'), _ts_to_float(_t.get('timestamp', 0)), float(_t.get('sell_price', 0) or 0))
            if _key in _seen:
                continue
            _seen.add(_key)
            _deduped.append(_t)
        closed_trades_raw = _deduped
        logger.info(f"[PORTFOLIO] Closed trades after archive merge: {len(closed_trades_raw)}")
    except Exception as _e:
        logger.warning(f"[PORTFOLIO] Archive merge failed: {_e}")

    # Filter out partial TP entries for trades that are still open
    # These have reason='trailing_tp' but the trade is still active
    closed_trades_filtered = [
        t for t in closed_trades_raw
        if not (t.get('market') in open_markets and t.get('reason') == 'trailing_tp')
    ]

    closed_trades_sorted = sorted(closed_trades_filtered, key=lambda x: _ts_to_float(x.get('timestamp', 0)), reverse=True)[:trades_count]
    
    # Format closed trades for display
    closed_trades = []
    for trade in closed_trades_sorted:
        amount = float(trade.get('amount', 0) or 0)
        buy_price = float(trade.get('buy_price', 0) or 0)
        sell_price = float(trade.get('sell_price', 0) or 0)
        
        # Calculate invested: Use invested_eur (current exposure) first
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
            closed_date = datetime.fromtimestamp(ts).strftime('%d-%m %H:%M') if ts else 'Onbekend'
        except:
            closed_date = 'Onbekend'
        
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
        })
    
    logger.info(f"[PORTFOLIO] Closed trades count: {len(closed_trades)}")

    totals_dict = totals.to_dict()
    # Guarantee period P&L keys exist so the template never crashes
    _period_defaults = {
        'daily_pnl': 0.0, 'daily_pnl_pct': 0.0,
        'weekly_pnl': 0.0, 'weekly_pnl_pct': 0.0,
        'monthly_pnl': 0.0, 'monthly_pnl_pct': 0.0,
    }
    for _k, _v in _period_defaults.items():
        totals_dict.setdefault(_k, _v)

    return render_template(
        'portfolio.html',
        cards=[c.to_dict() for c in cards],
        totals=totals_dict,
        config=config,
        heartbeat=heartbeat,
        bot_online=data_service.is_bot_online(),
        active_tab='portfolio',
        portfolio_combined_data=portfolio_combined_data,
        portfolio_allocation=portfolio_allocation,
        trade_readiness=trade_readiness,
        closed_trades=closed_trades,
        trades_count=trades_count,
    )
