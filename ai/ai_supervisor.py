# ai_supervisor.py

from __future__ import annotations

def _pid_alive(pid: int) -> bool:
    """Cross-platform best-effort PID liveness check.

    Prefer psutil when available. On Windows fall back to tasklist; on POSIX use os.kill(pid, 0).
    """
    try:
        import psutil
    except Exception:
        psutil = None
    try:
        if psutil is not None:
            try:
                return psutil.pid_exists(int(pid))
            except Exception as e:
                _dbg(f"pid_exists failed: {e}")
        if os.name == 'nt':
            # tasklist output contains PID when running
            try:
                import subprocess
                p = subprocess.run(['tasklist', '/NH', '/FI', f'PID eq {int(pid)}'], capture_output=True, text=True, timeout=5)
                if p.returncode != 0:
                    return False
                return str(int(pid)) in p.stdout
            except Exception:
                return False
        else:
            try:
                os.kill(int(pid), 0)
                return True
            except OSError:
                return False
            except Exception:
                return False
    except Exception:
        return False


# Allow start_bot to request claiming ownership (set in __main__ block via argparse)
ALLOW_CLAIM = False


# NOTE: pid_guard logic is implemented inside main() to avoid duplicate definitions
# The single_instance check is handled via ensure_single_instance_or_exit in __main__

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import atexit

# Add project root to Python path for module imports
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from modules.logging_utils import log
from modules.json_compat import write_json_compat
# Lazy import: AIEngine imports pandas/xgboost which take time
# from modules.ai_engine import AIEngine  # Moved to main() for lazy loading
from modules import storage
from modules.trade_store import load_snapshot as load_trade_snapshot
from modules.watchlist_manager import (
    queue_market_for_watchlist,
    demote_market_to_watchlist,
    run_periodic_review,
)

# New AI intelligence modules
try:
    from modules.ai_sentiment import get_market_sentiment, get_sentiment_adjustment
    SENTIMENT_AVAILABLE = True
except ImportError:
    SENTIMENT_AVAILABLE = False
    log("[AI] Sentiment module not available", level='debug')

try:
    from modules.ai_indicator_correlation import (
        get_correlation_adjustments,
        run_full_correlation_analysis
    )
    CORRELATION_AVAILABLE = True
except ImportError:
    CORRELATION_AVAILABLE = False
    log("[AI] Indicator correlation module not available", level='debug')

try:
    from modules.ai_feedback_loop import (
        register_ai_change,
        run_feedback_cycle,
        should_apply_suggestion,
        get_feedback_adjusted_confidence,
        get_ai_performance_summary
    )
    FEEDBACK_AVAILABLE = True
except ImportError:
    FEEDBACK_AVAILABLE = False
    log("[AI] Feedback loop module not available", level='debug')
from modules.quarantine_manager import review_quarantine

# Supervisor memory (light wrapper around modules.ai.bot_memory) — optional
try:
    from modules.ai import supervisor_memory as _sup_mem
    SUP_MEM_AVAILABLE = True
except Exception:
    SUP_MEM_AVAILABLE = False
    _sup_mem = None  # type: ignore
    log("[AI] supervisor_memory not available", level='debug')

# Market analysis functions (extracted to ai/market_analysis.py)
from ai.market_analysis import (
    get_market_sector,
    calculate_portfolio_sectors,
    detect_market_regime,
    get_coin_statistics,
    calculate_risk_metrics,
    scan_all_markets_for_opportunities,
)

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
PID_FILE = os.path.join(LOG_DIR, 'ai_supervisor.pid')
DEBUG_LOG = Path(LOG_DIR) / 'ai_supervisor_debug.log'
def debug_log(msg: str):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
    try:
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass  # Cannot recurse

# CRITICAL FIX: _dbg was called 26 times but never defined â†’ NameError on every exception path
_dbg = debug_log

def main():
    def pid_guard():
        import os, atexit
        pid = os.getpid()
        # Use module-level PID_FILE (logs/ai_supervisor.pid)
        try:
            existing = 0
            if os.path.exists(PID_FILE):
                try:
                    with open(PID_FILE, 'r', encoding='utf-8') as pf:
                        existing = int(pf.read().strip() or '0')
                except Exception:
                    existing = 0
            if existing and existing != pid:
                try:
                    alive = _pid_alive(existing)
                except Exception:
                    alive = False
                if alive:
                    if ALLOW_CLAIM:
                        # try graceful termination, then force
                        try:
                            try:
                                os.kill(existing, 2)
                            except Exception:
                                try:
                                    os.kill(existing, 15)
                                except Exception as e:
                                    _dbg(f"kill failed: {e}")
                            t0 = time.time()
                            while time.time() - t0 < 5:
                                if not _pid_alive(existing):
                                    break
                                time.sleep(0.5)
                            if _pid_alive(existing):
                                try:
                                    os.kill(existing, 9)
                                except Exception as e:
                                    _dbg(f"kill failed: {e}")
                        except Exception as e:
                            _dbg(f"kill failed: {e}")
                        try:
                            os.unlink(PID_FILE)
                        except Exception as e:
                            _dbg(f"unlink failed: {e}")
                    else:
                        debug_log(f"pid_guard: exit, andere ai_supervisor actief pid={existing}")
                        print(f"[ai_supervisor] Andere ai_supervisor actief (pid={existing}), exit.")
                        sys.exit(0)
                else:
                    try:
                        os.unlink(PID_FILE)
                    except Exception as e:
                        _dbg(f"unlink failed: {e}")
            try:
                with open(PID_FILE, 'w', encoding='utf-8') as pf:
                    pf.write(str(pid))
                debug_log(f"pid_guard: pid-file aangemaakt met pid={pid}")
            except Exception as e:
                debug_log(f"pid_guard: exception bij pid-file aanmaken {e}")
        except Exception as e:
            _dbg(f"encoding failed: {e}")
        def _rm(captured_pid=pid):
            """Cleanup PID file on exit. Uses default argument to capture pid value."""
            try:
                if os.path.exists(PID_FILE):
                    try:
                        with open(PID_FILE, 'r', encoding='utf-8') as pf:
                            if int(pf.read().strip() or '0') == captured_pid:
                                os.unlink(PID_FILE)
                                debug_log(f"pid_guard: pid-file verwijderd bij exit")
                    except Exception as e:
                        _dbg(f"encoding failed: {e}")
            except Exception as e:
                _dbg(f"encoding failed: {e}")
        atexit.register(_rm)
    pid_guard()
    
    # Note: single_instance check is done in if __name__ == "__main__" (at end of file)
    # No need to check again here (removed to prevent double-check issues)
    
    # Main loop is invoked from if __name__ block at bottom of file
    # This function only sets up PID guard and returns

# Simple, safe advisor: reads heartbeat and makes bounded suggestions into ai_suggestions.json
# Guardrails: max delta per param, absolute min/max, and cooldown between suggestions

# Use absolute paths from project root
_AI_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_AI_SCRIPT_DIR)
SUGGESTIONS_FILE = os.path.join(_PROJECT_ROOT, 'data', 'ai_suggestions.json')
AI_MARKET_SUGGESTIONS_FILE = os.path.join(_PROJECT_ROOT, 'ai', 'ai_market_suggestions.json')
HEARTBEAT_FILE = os.path.join(_PROJECT_ROOT, 'data', 'heartbeat.json')
TRADE_LOG_FILE = os.path.join(_PROJECT_ROOT, 'data', 'trade_log.json')
CONFIG_FILE = os.path.join(_PROJECT_ROOT, 'config', 'bot_config.json')
CHANGE_HISTORY_FILE = os.path.join(_PROJECT_ROOT, 'data', 'ai_changes.json')
AI_HEARTBEAT_FILE = os.path.join(_PROJECT_ROOT, 'data', 'ai_heartbeat.json')
ACCOUNT_OVERVIEW_FILE = os.path.join(_PROJECT_ROOT, 'data', 'account_overview.json')
METRICS_LATEST_FILE = os.path.join(_PROJECT_ROOT, 'metrics', 'latest_metrics.json')
AI_APPLY_EVENTS_FILE = os.path.join(_PROJECT_ROOT, 'data', 'ai_apply_events.jsonl')
CHANGE_HISTORY_DATASET = 'ai_changes'
CHANGE_HISTORY_TABLE = 'changes'

# ===== SUGGESTION DEDUPLICATION SYSTEM =====
# Track recent suggestions to avoid repetition
_recent_suggestions: dict = {}  # {param: {'to': value, 'ts': timestamp, 'count': int}}
SUGGESTION_MEMORY_HOURS = 4  # Don't repeat same suggestion within 4 hours
MAX_REPEAT_COUNT = 2  # After 2 identical suggestions, require different suggestion

def _is_duplicate_suggestion(param: str, to_value: float) -> bool:
    """Check if this suggestion was made recently for the same target value."""
    if param not in _recent_suggestions:
        return False
    
    recent = _recent_suggestions[param]
    time_since = time.time() - recent.get('ts', 0)
    
    # If same target value within memory window
    if time_since < SUGGESTION_MEMORY_HOURS * 3600:
        if abs(recent.get('to', 0) - to_value) < 0.001:  # Same target value
            if recent.get('count', 0) >= MAX_REPEAT_COUNT:
                return True  # Too many repeats
    return False

def _record_suggestion(param: str, to_value: float):
    """Record that a suggestion was made."""
    if param not in _recent_suggestions:
        _recent_suggestions[param] = {'to': to_value, 'ts': time.time(), 'count': 1}
    else:
        recent = _recent_suggestions[param]
        if abs(recent.get('to', 0) - to_value) < 0.001:  # Same target
            recent['count'] = recent.get('count', 0) + 1
            recent['ts'] = time.time()
        else:  # Different target - reset counter
            _recent_suggestions[param] = {'to': to_value, 'ts': time.time(), 'count': 1}

def _clear_old_suggestions():
    """Clear suggestions older than memory window."""
    cutoff = time.time() - (SUGGESTION_MEMORY_HOURS * 3600)
    to_remove = [p for p, v in _recent_suggestions.items() if v.get('ts', 0) < cutoff]
    for p in to_remove:
        del _recent_suggestions[p]


def _load_portfolio_state() -> dict:
    """Load portfolio/balance metrics to drive balance-aware suggestions.

    Tries account_overview first, then metrics/latest_metrics as fallback.
    Returns keys: total, eur_balance, open_exposure, stale.
    """
    state = {'total': None, 'eur_balance': None, 'open_exposure': None, 'stale': True}
    try:
        if os.path.exists(ACCOUNT_OVERVIEW_FILE):
            # Check staleness â€” warn if data is older than 30 minutes
            try:
                age_sec = time.time() - os.path.getmtime(ACCOUNT_OVERVIEW_FILE)
                if age_sec > 1800:
                    log(f"[AI] âš ï¸ Portfolio data is {age_sec/60:.0f} min old (>{30} min stale threshold)", level='warning')
                else:
                    state['stale'] = False
            except Exception:
                pass
            with open(ACCOUNT_OVERVIEW_FILE, 'r', encoding='utf-8') as f:
                doc = json.load(f) or {}
            state['total'] = float(doc.get('total_portfolio_eur') or doc.get('total_value_eur') or doc.get('portfolio_total', 0))
            state['eur_balance'] = float(doc.get('eur_balance') or doc.get('available_eur') or doc.get('cash_eur', 0))
            state['open_exposure'] = float(doc.get('open_exposure_eur') or doc.get('open_trades_eur') or 0)
    except Exception as e:
        _dbg(f"exists failed: {e}")

    try:
        if (state['total'] is None or state['open_exposure'] is None) and os.path.exists(METRICS_LATEST_FILE):
            with open(METRICS_LATEST_FILE, 'r', encoding='utf-8') as f:
                doc = json.load(f) or {}
            metrics = doc.get('metrics', {}) if isinstance(doc, dict) else {}
            if state['total'] is None:
                port = metrics.get('bot_portfolio_total_exposure_eur')
                bal = metrics.get('bot_eur_balance')
                if port is not None and bal is not None:
                    try:
                        state['total'] = float(port) + float(bal)
                    except Exception as e:
                        _dbg(f"state update failed: {e}")
            if state['open_exposure'] is None and metrics.get('bot_open_exposure_eur') is not None:
                state['open_exposure'] = float(metrics.get('bot_open_exposure_eur'))
            if state['eur_balance'] is None and metrics.get('bot_eur_balance') is not None:
                state['eur_balance'] = float(metrics.get('bot_eur_balance'))
    except Exception as e:
        _dbg(f"state update failed: {e}")

    if state['total'] is None:
        log("[AI] âš ï¸ No portfolio data available â€” balance-aware tuning DISABLED this cycle", level='warning')
    else:
        log(f"[AI] Portfolio state: total=â‚¬{state['total']:.2f}, cash=â‚¬{state.get('eur_balance') or 0:.2f}, exposure=â‚¬{state.get('open_exposure') or 0:.2f}", level='info')
    return state

# Constants imported from ai/ai_constants.py (Fase 5 refactor)
from ai.ai_constants import LIMITS, CONFIG_VALIDATION_RULES, SECTOR_DEFINITIONS, COOLDOWN_MINUTES

_last_suggest = {}
_last_apply = {}
_last_good_config: dict[str, object] = {}


# Ensure existing JSON history is migrated into TinyDB on startup
try:
    storage.migrate_json_dataset(CHANGE_HISTORY_DATASET, CHANGE_HISTORY_FILE, table=CHANGE_HISTORY_TABLE)
except Exception as e:
    _dbg(f"migrate_json_dataset failed: {e}")


def _utc_now():
    return datetime.now(timezone.utc)

def _safe_load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _archive_old_suggestions(doc: dict, max_age_days: int = 1) -> dict:
    """Move suggestions older than `max_age_days` to a dated archive file.

    Keeps `ai/ai_market_suggestions.json` lean. Returns the trimmed document.
    Best-effort: any failure leaves the original document untouched.
    """
    try:
        suggestions = doc.get('suggestions') or []
        if not suggestions:
            return doc
        cutoff = int(time.time()) - int(max_age_days * 86400)
        old = [s for s in suggestions if isinstance(s, dict) and int(s.get('ts', 0)) < cutoff]
        if not old:
            return doc
        archive_dir = os.path.join(_PROJECT_ROOT, 'ai', 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        from datetime import datetime as _dt
        stamp = _dt.utcfromtimestamp(cutoff).strftime('%Y-%m-%d')
        archive_file = os.path.join(archive_dir, f'ai_market_suggestions_{stamp}.json')
        existing = _safe_load_json(archive_file, {'suggestions': []})
        if not isinstance(existing, dict):
            existing = {'suggestions': []}
        existing_list = existing.get('suggestions') or []
        existing_list.extend(old)
        existing['suggestions'] = existing_list
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
        kept = [s for s in suggestions if not (isinstance(s, dict) and int(s.get('ts', 0)) < cutoff)]
        doc['suggestions'] = kept
    except Exception:
        pass
    return doc


def suggest_market(market: str, reason: str | None = None) -> bool:
    """Append a market suggestion to `ai/ai_market_suggestions.json`.

    Returns True on success.
    """
    try:
        doc = _safe_load_json(AI_MARKET_SUGGESTIONS_FILE, {'suggestions': []})
        if not isinstance(doc, dict):
            doc = {'suggestions': []}
        # Archive entries older than 1 day to keep the live file small.
        doc = _archive_old_suggestions(doc, max_age_days=1)
        suggestions = doc.get('suggestions') or []
        ts = int(time.time())
        # avoid duplicates
        exists = any((s.get('market') == market) for s in suggestions if isinstance(s, dict))
        if exists:
            return True
        suggestions.append({'market': market, 'reason': reason or 'ai_supervisor', 'ts': ts})
        doc['suggestions'] = suggestions
        with open(AI_MARKET_SUGGESTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=2)
        return True
    except Exception:
        return False


def _load_valid_config() -> dict:
    global _last_good_config
    raw = _safe_load_json(CONFIG_FILE, {})
    if not isinstance(raw, dict) or not raw:
        if _last_good_config:
            log('ai_supervisor: config invalid JSON, using last known good snapshot', level='warning')
            return _last_good_config
        return {}
    for key, rule in CONFIG_VALIDATION_RULES.items():
        if key not in raw:
            continue
        expected = rule.get('type')
        if expected and not isinstance(raw[key], expected):
            if _last_good_config:
                log(f'ai_supervisor: config key {key} failed validation, reverting to last known good', level='warning')
                return _last_good_config
            else:
                # Drop invalid entry but keep rest
                raw[key] = CONFIG_VALIDATION_RULES.get(key, {}).get('default') or raw[key]
    _last_good_config = raw.copy()
    return raw


# get_market_sector uses imported SECTOR_DEFINITIONS from ai_constants
# NOTE: _safe_load_json is defined once above (L427) â€” duplicate removed in Fase 5 refactor


def _bounded_step(param, current, desired, check_duplicate=True):
    """Calculate bounded step for parameter change.
    
    Args:
        param: Parameter name
        current: Current value
        desired: Desired target value
        check_duplicate: If True, check for duplicate suggestions (default True)
    
    Returns:
        New value or None if no change needed or duplicate detected
    """
    lim = LIMITS.get(param)
    if not lim:
        return None
    # clamp to abs bounds
    tgt = max(lim['min'], min(lim['max'], desired))
    # clamp step size
    step = tgt - current
    if abs(step) > lim['max_delta']:
        step = lim['max_delta'] if step > 0 else -lim['max_delta']
    
    new_val = round(current + step, 6)
    
    # Check if this is a duplicate suggestion (same target repeated too often)
    if check_duplicate and _is_duplicate_suggestion(param, new_val):
        # Try alternative: suggest step in opposite direction or different magnitude
        alt_step = step * 0.5  # Try smaller step
        alt_val = round(current + alt_step, 6)
        alt_val = max(lim['min'], min(lim['max'], alt_val))
        
        if alt_val != current and not _is_duplicate_suggestion(param, alt_val):
            _record_suggestion(param, alt_val)
            return alt_val
        return None  # Skip this suggestion - too repetitive
    
    if new_val != current:
        _record_suggestion(param, new_val)
    
    return new_val


def _gather_intelligence(cfg, hb, closed_trades, pnl_list, open_exposure, out):
    """Phase 0+1: Gather intelligence from sentiment, correlation, feedback, analytics, and AI engine.

    Returns (insights, regime_meta, portfolio_advice, analytics_data).
    Appends any intelligence-driven suggestions directly to *out*.
    """
    insights = []
    regime_meta = {}
    portfolio_advice = {}
    analytics_data = {}

    # === PHASE 0: NEW INTELLIGENCE MODULES ===
    
    # Sentiment Analysis Integration
    if SENTIMENT_AVAILABLE and cfg.get('AI_SENTIMENT_ENABLED', True):
        try:
            sentiment_data = get_market_sentiment()
            sentiment_adjustments = get_sentiment_adjustment('BTC-EUR')  # Use BTC as market proxy
            
            log(f"ðŸ“Š Market Sentiment: {sentiment_data.get('overall_label', 'UNKNOWN')} "
                f"(Fear/Greed: {sentiment_data.get('fear_greed_index', 50)})", level='info')
            
            # Apply sentiment-based adjustments
            for param, adj in sentiment_adjustments.get('adjustments', {}).items():
                if param in (cfg.get('AI_ALLOW_PARAMS') or []):
                    current = float(cfg.get(param, 0))
                    if adj['direction'] == 'increase':
                        target = current * adj['magnitude']
                    elif adj['direction'] == 'decrease':
                        target = current - adj['magnitude'] if adj['magnitude'] < 1 else current / adj['magnitude']
                    else:
                        continue
                    
                    new_val = _bounded_step(param, current, target)
                    if new_val is not None and _cooldown_ok(param):
                        out.append({
                            'param': param,
                            'from': current,
                            'to': new_val,
                            'reason': f"ðŸ“° Sentiment: {adj['reason']}",
                            'source': 'sentiment'
                        })
                        _last_suggest[param] = _utc_now()
        except Exception as e:
            log(f"Sentiment analysis error: {e}", level='debug')
    
    # Indicator Correlation Integration
    if CORRELATION_AVAILABLE and cfg.get('AI_CORRELATION_ENABLED', True) and len(pnl_list) >= 12:
        try:
            # Run correlation analysis periodically (every 6 hours)
            correlation_data = run_full_correlation_analysis()
            
            # Get best performing coins from correlation
            best_coins = correlation_data.get('coin_patterns', {}).get('best_performing', [])
            if best_coins:
                log(f"ðŸ“ˆ Correlation Analysis: Best coins: {', '.join(best_coins[:3])}", level='info')
        except Exception as e:
            log(f"Correlation analysis error: {e}", level='debug')
    
    # Feedback Loop Integration - Adjust confidence based on historical effectiveness
    if FEEDBACK_AVAILABLE:
        try:
            # Run feedback evaluation periodically
            if len(pnl_list) >= 8:
                feedback_result = run_feedback_cycle()
                ai_performance = get_ai_performance_summary()
                
                if ai_performance.get('overall_success_rate'):
                    log(f"ðŸŽ¯ AI Performance: {ai_performance['overall_success_rate']:.1%} success rate, "
                        f"â‚¬{ai_performance.get('total_pnl_impact', 0):.2f} total impact", level='info')
        except Exception as e:
            log(f"Feedback loop error: {e}", level='debug')
    
    # === PHASE 1: ANALYTICS INTEGRATION (Read-only) ===
    # Use Performance Analytics for smarter decisions
    try:
        from modules.performance_analytics import get_analytics
        analytics = get_analytics()
        
        # Get comprehensive metrics
        analytics_data = {
            'sharpe': analytics.sharpe_ratio(),
            'sortino': analytics.sortino_ratio(),
            'calmar': analytics.calmar_ratio(),
            'profit_factor': analytics.profit_factor(),
            'win_rate': analytics.win_rate(),
            'expectancy': analytics.expectancy(),
            'max_dd': analytics.max_drawdown()[0],  # EUR value
            'max_dd_pct': analytics.max_drawdown()[1],  # Percentage
        }
        
        log(f"AI Analytics: Sharpe={analytics_data['sharpe']:.2f}, PF={analytics_data['profit_factor']:.2f}, WR={analytics_data['win_rate']:.1f}%", level='debug')
    except Exception as e:
        log(f"Analytics module not available: {e}", level='debug')
        analytics_data = {}
    
    try:
        # Lazy import: pandas/xgboost take time to load
        from modules.ai_engine import AIEngine
        engine = AIEngine()
        
        # Get regime-based parameter recommendations
        payload = engine.recommend_params(cfg, hb, closed_trades)
        if isinstance(payload, dict):
            if bool(cfg.get('AI_REGIME_RECOMMENDATIONS', True)):
                out.extend(payload.get('suggestions', []))
            insights = payload.get('insights', []) or []
            regime_meta = {
                'regime': payload.get('regime'),
                'regime_stats': payload.get('regime_stats', {})
            }
        
        # Get portfolio-based investment recommendations
        if bool(cfg.get('AI_PORTFOLIO_ANALYSIS', True)):
            portfolio_state = _load_portfolio_state()
            portfolio_advice = engine.get_investment_recommendations()
            risk_level = 'low'
            portfolio_total = portfolio_state.get('total') or 0
            if isinstance(portfolio_advice, dict) and 'error' not in portfolio_advice:
                risk_level = portfolio_advice.get('risk_analysis', {}).get('risk_level', 'low')
                portfolio_total = portfolio_advice.get('portfolio', {}).get('total_value_eur', portfolio_total)

            # Fallback: if no portfolio data, skip balance-driven tuning
            if portfolio_total and portfolio_total > 0:
                open_expo_eur = portfolio_state.get('open_exposure') or open_exposure
                eur_balance = portfolio_state.get('eur_balance')

                # Exposure cap: DISABLED — MAX_TOTAL_EXPOSURE_EUR is managed manually (set to 9999)
                # Do NOT auto-adjust this param; the user wants no artificial cap.

                # Budget reservation awareness: if enabled, AI uses trailing_bot_max_eur
                # instead of full portfolio for sizing calculations
                _budget_cfg = cfg.get('BUDGET_RESERVATION', {})
                _trailing_budget_eur = None
                if _budget_cfg.get('enabled', False):
                    _trailing_budget_eur = float(_budget_cfg.get('trailing_bot_max_eur', 180))
                    # Add reinvested trailing profits if enabled
                    if _budget_cfg.get('reinvest_trailing_profits', True):
                        try:
                            _tl = _safe_load_json(TRADE_LOG_FILE, {})
                            _closed_t = _tl.get('closed', []) if isinstance(_tl, dict) else []
                            _trailing_profit = max(0, sum(
                                float(t.get('profit', 0) or 0) for t in _closed_t
                                if isinstance(t, dict) and 'profit' in t
                            ))
                            _trailing_budget_eur += _trailing_profit
                        except Exception:
                            pass
                    log(f"AI budget awareness: trailing budget {_trailing_budget_eur:.2f} EUR (grid reserved separately)", level='info')

                # Use trailing budget or portfolio total for sizing
                sizing_base = _trailing_budget_eur if _trailing_budget_eur else portfolio_total

                # Base amount schalen met balans (ca. 1.5% van totale waarde), met limits
                current_base = float(cfg.get('BASE_AMOUNT_EUR', 15))
                target_base = min(max(sizing_base * 0.015, LIMITS['BASE_AMOUNT_EUR']['min']), LIMITS['BASE_AMOUNT_EUR']['max'])
                # Als risico hoog, extra conservatief
                if risk_level == 'high':
                    target_base = max(LIMITS['BASE_AMOUNT_EUR']['min'], target_base * 0.8)
                new_base = _bounded_step('BASE_AMOUNT_EUR', current_base, target_base)
                if new_base is not None and _cooldown_ok('BASE_AMOUNT_EUR'):
                    out.append({
                        'param': 'BASE_AMOUNT_EUR',
                        'from': current_base,
                        'to': new_base,
                        'reason': f'Balance-driven sizing: ~1.5% van portefeuille (risico {risk_level})'
                    })
                    _last_suggest['BASE_AMOUNT_EUR'] = _utc_now()

                # DCA amount aligneren met base (1.0x) en balans-plafond
                current_dca = float(cfg.get('DCA_AMOUNT_EUR', current_base))
                target_dca = min(max(target_base * 1.0, LIMITS['DCA_AMOUNT_EUR']['min']), LIMITS['DCA_AMOUNT_EUR']['max'])
                if risk_level == 'high':
                    target_dca = max(LIMITS['DCA_AMOUNT_EUR']['min'], target_dca * 0.9)
                new_dca = _bounded_step('DCA_AMOUNT_EUR', current_dca, target_dca)
                if new_dca is not None and _cooldown_ok('DCA_AMOUNT_EUR'):
                    out.append({
                        'param': 'DCA_AMOUNT_EUR',
                        'from': current_dca,
                        'to': float(new_dca),
                        'reason': 'Balance-driven DCA sizing (koppeling aan base amount)'
                    })
                    _last_suggest['DCA_AMOUNT_EUR'] = _utc_now()

                # Trailing aanscherpen bij hoge exposure t.o.v. balans
                exposure_ratio = 0.0
                try:
                    exposure_ratio = (open_expo_eur or 0) / portfolio_total
                except Exception:
                    exposure_ratio = 0.0
                if exposure_ratio > 0.5 or risk_level == 'high':
                    current_trail = float(cfg.get('DEFAULT_TRAILING', 0.012))
                    target_trail = max(LIMITS['DEFAULT_TRAILING']['min'], min(current_trail, 0.06))
                    new_trail = _bounded_step('DEFAULT_TRAILING', current_trail, target_trail)
                    if new_trail is not None and _cooldown_ok('DEFAULT_TRAILING'):
                        out.append({
                            'param': 'DEFAULT_TRAILING',
                            'from': current_trail,
                            'to': new_trail,
                            'reason': 'Balance/exposure: strakkere trailing bij hoge exposure'
                        })
                        _last_suggest['DEFAULT_TRAILING'] = _utc_now()

                    current_act = float(cfg.get('TRAILING_ACTIVATION_PCT', 0.02))
                    target_act = max(LIMITS['TRAILING_ACTIVATION_PCT']['min'], min(current_act, 0.014))
                    new_act = _bounded_step('TRAILING_ACTIVATION_PCT', current_act, target_act)
                    if new_act is not None and _cooldown_ok('TRAILING_ACTIVATION_PCT'):
                        out.append({
                            'param': 'TRAILING_ACTIVATION_PCT',
                            'from': current_act,
                            'to': new_act,
                            'reason': 'Balance/exposure: sneller trailing activeren'
                        })
                        _last_suggest['TRAILING_ACTIVATION_PCT'] = _utc_now()

                log(f"AI Portfolio analyse: totaal â‚¬{portfolio_total:.2f}, risico {risk_level}, exposure {open_expo_eur}", level='info')
    except Exception as e:
        log(f"AIEngine recommendations failed: {e}", level='warning')

    return insights, regime_meta, portfolio_advice, analytics_data


def _cooldown_ok(param):
    ts = _last_suggest.get(param)
    if not ts:
        return True
    return (_utc_now() - ts) >= timedelta(minutes=COOLDOWN_MINUTES)


def suggest_once():
    _clear_old_suggestions()
    hb = _safe_load_json(HEARTBEAT_FILE, {})
    cfg = _load_valid_config()
    trades_doc = load_trade_snapshot(TRADE_LOG_FILE)
    if isinstance(trades_doc, dict):
        closed_trades = trades_doc.get('closed', [])
    else:
        closed_trades = trades_doc if isinstance(trades_doc, list) else []
    if not cfg:
        return []
    log(f"AI config check: MIN_SCORE={cfg.get('MIN_SCORE_TO_BUY')}, TRAILING={cfg.get('DEFAULT_TRAILING'):.3f}", level='debug')
    open_exposure = hb.get('open_exposure_eur', 0.0)
    max_total = cfg.get('MAX_TOTAL_EXPOSURE_EUR', 100)
    open_trades = hb.get('open_trades', 0)
    recent = closed_trades[-10:] if isinstance(closed_trades, list) else []
    pnl = sum([t.get('profit', 0.0) for t in recent if isinstance(t, dict)])
    pnl_list = [t.get('profit', 0.0) for t in closed_trades if isinstance(t, dict) and 'profit' in t]

    out = []
    insights, regime_meta, portfolio_advice, analytics_data = _gather_intelligence(
        cfg, hb, closed_trades, pnl_list, open_exposure, out
    )

    # â”€â”€ Rules 1-31: delegated to ai.suggest_rules â”€â”€
    from ai.suggest_rules import (
        init as _init_rules,
        rules_basic_performance,
        rules_signal_optimization,
        rules_profit_factor,
        rules_advanced_optimization,
        rules_market_intelligence,
        rules_dynamic_learning,
        annotate_confidence,
        rules_whitelist_management,
        rules_trailing_entry_tp,
        coherence_check,
    )
    _init_rules(
        bounded_step=_bounded_step,
        cooldown_ok=_cooldown_ok,
        last_suggest=_last_suggest,
        utc_now=_utc_now,
        dbg=_dbg,
        limits=LIMITS,
    )
    _rule_ctx = {
        'cfg': cfg, 'pnl': pnl, 'pnl_list': pnl_list,
        'open_exposure': open_exposure, 'max_total': max_total,
        'open_trades': open_trades, 'closed_trades': closed_trades,
        'analytics_data': analytics_data,
        'win_rate': 0.5, 'profit_factor': 1.0,
    }
    # Inject live BTC candle data for forward-looking rules
    try:
        from modules.ai_sentiment import _fetch_btc_candles, _calculate_btc_trend
        _btc_candles = _fetch_btc_candles('1h', 48)
        if _btc_candles:
            _rule_ctx['btc_trend'] = _calculate_btc_trend(_btc_candles)
        else:
            _rule_ctx['btc_trend'] = {}
    except Exception as _btc_err:
        _dbg(f'BTC trend fetch for rules failed: {_btc_err}')
        _rule_ctx['btc_trend'] = {}
    # Run rule groups with ascending priority
    # higher priority = more authoritative (wins dedup conflicts)
    _grp_a = rules_basic_performance(_rule_ctx)
    for s in _grp_a:
        s.setdefault('priority', 20)
    out.extend(_grp_a)

    _grp_b = rules_signal_optimization(_rule_ctx)           # sets ctx win_rate/profit_factor
    for s in _grp_b:
        s.setdefault('priority', 30)
    out.extend(_grp_b)

    _grp_c = rules_profit_factor(_rule_ctx)
    for s in _grp_c:
        s.setdefault('priority', 40)
    out.extend(_grp_c)

    _grp_d = rules_advanced_optimization(_rule_ctx)
    for s in _grp_d:
        s.setdefault('priority', 50)
    out.extend(_grp_d)

    _grp_e = rules_market_intelligence(_rule_ctx)
    for s in _grp_e:
        s.setdefault('priority', 70)
    out.extend(_grp_e)

    _grp_f = rules_dynamic_learning(_rule_ctx)
    for s in _grp_f:
        s.setdefault('priority', 60)
    out.extend(_grp_f)

    _grp_f2 = rules_trailing_entry_tp(_rule_ctx)            # orphaned param rules
    for s in _grp_f2:
        s.setdefault('priority', 25)
    out.extend(_grp_f2)

    # Cross-parameter coherence check
    coherence_extra = coherence_check(out, cfg)
    for s in coherence_extra:
        s.setdefault('priority', 90)
    out.extend(coherence_extra)

    annotate_confidence(out, pnl_list)
    _wl_sugg, extras = rules_whitelist_management(_rule_ctx)
    for s in _wl_sugg:
        s.setdefault('priority', 35)
    out.extend(_wl_sugg)

    # Deduplicate: keep HIGHEST-PRIORITY suggestion per parameter
    best_per_param: dict = {}
    for idx, s in enumerate(out):
        param = s.get('param') or s.get('parameter')
        if param:
            pri = s.get('priority', 0)
            existing = best_per_param.get(param)
            if existing is None or pri > existing[0]:
                best_per_param[param] = (pri, idx)
    if len(best_per_param) < sum(1 for s in out if s.get('param') or s.get('parameter')):
        keep_indices = {v[1] for v in best_per_param.values()}
        deduped = [s for i, s in enumerate(out) if i in keep_indices or not (s.get('param') or s.get('parameter'))]
        dropped = len(out) - len(deduped)
        if dropped > 0:
            log(f"[AI] Dedup: {dropped} conflicting suggestions removed, kept highest-priority ({len(deduped)} remaining)", level='info')
        out = deduped

    if out or insights or regime_meta or portfolio_advice or extras:
        _save_suggestions(out, insights, regime_meta, portfolio_advice, extras, closed_trades, pnl_list)
    
    # CRITICAL suggestions bypass normal auto-apply cooldown and apply immediately
    critical_suggestions = [s for s in out if s.get('impact') == 'CRITICAL']
    if critical_suggestions:
        try:
            cfg_now = _safe_load_json(CONFIG_FILE, {})
            if cfg_now and cfg_now.get('AI_AUTO_APPLY_CRITICAL', True):
                applied_critical = _apply_critical_suggestions(critical_suggestions, cfg_now)
                if applied_critical:
                    log(f"ðŸš¨ {len(applied_critical)} CRITICAL suggesties ONMIDDELLIJK toegepast!", level='warning')
        except Exception as e:
            log(f"Fout bij CRITICAL suggestie toepassing: {e}", level='error')
    
    if extras:
        result = {'suggestions': out}
        result.update(extras)
        return result
    return out


def _save_suggestions(out, insights, regime_meta, portfolio_advice, extras, closed_trades, pnl_list):
    """Persist suggestions to JSON, compute regime/risk data, and log summary."""
    doc = {'ts': time.time(), 'suggestions': out}
    
    if len(pnl_list) >= 8:
        regime_data = detect_market_regime(closed_trades, _load_valid_config() or {})
        doc['market_regime'] = regime_data
        risk_metrics = calculate_risk_metrics(closed_trades, _load_valid_config() or {})
        doc['risk_metrics'] = risk_metrics
        
        if len(pnl_list) >= 12:
            coin_stats = get_coin_statistics(closed_trades)
            qualified = {m: s for m, s in coin_stats.items() if s['trades'] >= 3}
            if qualified:
                sorted_coins = sorted(qualified.items(),
                                      key=lambda x: x[1]['win_rate'] * max(x[1]['avg_pnl'], 0.1),
                                      reverse=True)
                doc['top_coins'] = [
                    {'market': c[0], 'wr': c[1]['win_rate'], 'avg_pnl': c[1]['avg_pnl']}
                    for c in sorted_coins[:3]
                ]
        
        if len(pnl_list) >= 15:
            cfg = _load_valid_config() or {}
            market_scan = scan_all_markets_for_opportunities(cfg, closed_trades)
            doc['whitelist_recommendations'] = {
                'add': market_scan.get('recommended_add', [])[:5],
                'remove': market_scan.get('recommended_remove', [])[:3],
                'scan_time': market_scan.get('scan_time'),
            }
    
    if insights:
        doc['insights'] = insights
    if regime_meta:
        doc['regime'] = regime_meta.get('regime')
        doc['regime_stats'] = regime_meta.get('regime_stats', {})
    if portfolio_advice:
        doc['portfolio_advice'] = portfolio_advice
    if extras:
        for k, v in extras.items():
            doc[k] = v

    # --- Memory hook: annotate suggestions with prior history + persist them ---
    if SUP_MEM_AVAILABLE and _sup_mem is not None:
        try:
            snap = {
                "regime": (regime_meta or {}).get("regime"),
                "ts": doc.get("ts"),
                "n_closed": len(closed_trades) if closed_trades else 0,
            }
            _sup_mem.annotate_suggestions(out)
            for s in out:
                if isinstance(s, dict):
                    _sup_mem.log_suggestion(s, applied=False, snapshot=snap)
        except Exception as _mem_e:
            log(f"[AI] supervisor_memory hook failed: {_mem_e}", level='debug')

    write_json_compat(SUGGESTIONS_FILE, doc)
    
    # Summary logging
    critical_sugg = [s for s in out if s.get('impact') == 'CRITICAL']
    high_sugg = [s for s in out if s.get('impact') == 'HIGH']
    if critical_sugg:
        log(f"ðŸš¨ CRITICAL AI-suggesties ({len(critical_sugg)}): {critical_sugg}", level='warning')
    if high_sugg:
        log(f"âš¡ HIGH-impact AI-suggesties ({len(high_sugg)}): {high_sugg}", level='info')
    log(f"AI-suggesties opgeslagen: {len(out)} totaal")
    if 'market_regime' in doc:
        regime = doc['market_regime'].get('regime')
        confidence = doc['market_regime'].get('confidence', 0)
        log(f"ðŸ“Š Market Regime: {regime} (confidence: {confidence:.0%})", level='info')
    if 'risk_metrics' in doc:
        risk_level = doc['risk_metrics'].get('risk_level')
        daily_dd = doc['risk_metrics'].get('daily_drawdown', 0)
        consecutive = doc['risk_metrics'].get('consecutive_losses', 0)
        log(f"ðŸ›¡ï¸ Risk Level: {risk_level} (DD: â‚¬{daily_dd:.1f}, Consecutive: {consecutive})", level='info')
    if 'top_coins' in doc:
        top = doc['top_coins']
        if top:
            top_str = ', '.join([f"{c['market']} ({c['wr']:.0%})" for c in top])
            log(f"ðŸ† Top performers: {top_str}", level='info')
    if insights:
        preview = [f"{i.get('market')}={i.get('score')}" for i in insights[:3]]
        log(f"AI topmarkten: {', '.join(preview)}", level='info')
    if portfolio_advice and 'summary' in portfolio_advice:
        log(f"Portfolio advies:\n{portfolio_advice['summary']}", level='info')


def _apply_critical_suggestions(critical_list: list, cfg: dict) -> list:
    """Immediately apply CRITICAL suggestions without normal cooldown.
    These are emergency situations that require immediate action.
    Returns list of applied suggestions.
    
    RESPECTS AI_PARAM_LOCK - if True, will NOT apply ANY changes."""
    if not critical_list:
        return []
    
    # HARD LOCK: If AI_PARAM_LOCK is True, NEVER modify any parameters
    if cfg.get('AI_PARAM_LOCK', False):
        log("ðŸ”’ AI_PARAM_LOCK actief - CRITICAL suggesties worden NIET toegepast", level='warning')
        return []
    
    applied = []
    new_cfg = dict(cfg)
    now_ts = time.time()
    
    # Load existing history
    hist = []
    try:
        if os.path.exists(CHANGE_HISTORY_FILE) and os.path.getsize(CHANGE_HISTORY_FILE) > 0:
            hist = _load_history()
    except Exception as e:
        _dbg(f"exists failed: {e}")
    
    allow_params = cfg.get('AI_ALLOW_PARAMS') or list(LIMITS.keys())
    
    for s in critical_list:
        p = s.get('param')
        to_v = s.get('to')
        frm_v = s.get('from')
        
        if p not in allow_params:
            log(f"âš ï¸ CRITICAL suggestie {p} niet in AI_ALLOW_PARAMS - overgeslagen", level='warning')
            continue
        
        if to_v is None:
            continue
        
        cur = new_cfg.get(p, frm_v)
        
        try:
            # Type coercion
            if isinstance(cur, int) and not isinstance(to_v, int):
                to_v = int(round(float(to_v)))
            else:
                to_v = float(to_v) if not isinstance(to_v, (int, float)) else to_v
        except Exception:
            continue
        
        if cur == to_v:
            continue
        
        # Apply guardrails
        to_v = _apply_guardrails(p, to_v)
        
        # Additional relational constraint checks (same as auto_apply_if_enabled)
        # RSI range validation: RSI_MIN_BUY must be < RSI_MAX_BUY
        if p == 'RSI_MIN_BUY':
            rsi_max = new_cfg.get('RSI_MAX_BUY', 70)
            if to_v >= rsi_max:
                log(f"âš ï¸  AI Config Guard [CRITICAL]: RSI_MIN_BUY={to_v} >= RSI_MAX_BUY={rsi_max} (invalid range) - skipping", level='warning')
                continue
        elif p == 'RSI_MAX_BUY':
            rsi_min = new_cfg.get('RSI_MIN_BUY', 35)
            if to_v <= rsi_min:
                log(f"âš ï¸  AI Config Guard [CRITICAL]: RSI_MAX_BUY={to_v} <= RSI_MIN_BUY={rsi_min} (invalid range) - skipping", level='warning')
                continue
        
        # MAX_OPEN_TRADES: bounds (min 3, max 10) - NEVER reduce below 3
        if p == 'MAX_OPEN_TRADES' and to_v < 3:
            log(f'AI Config Guard: MAX_OPEN_TRADES={to_v} < 3 (minimum floor) - clamped to 3', level='warning')
            to_v = 3
        if p == 'MAX_OPEN_TRADES' and to_v > 10:
            log(f"âš ï¸  AI Config Guard [CRITICAL]: MAX_OPEN_TRADES={to_v} > 10 (too many trades) - clamped to 10", level='warning')
            to_v = 10

        # SL vs DCA guard: HARD_SL must be WIDER than deepest DCA level (all DCAs)
        if p == 'HARD_SL_ALT_PCT':
            _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
            _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
            _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
            _deepest = _dca_drop * (_step_mult ** max(0, _max_buys - 1))
            _min_sl = min(0.25, _deepest + 0.02)
            if to_v < _min_sl:
                log(f"AI Config Guard [CRITICAL]: HARD_SL={to_v} < min required {_min_sl:.3f} (deepest DCA={_deepest:.3f}) - skipping", level='warning')
                continue
        elif p == 'DCA_DROP_PCT':
            hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
            _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
            _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
            _deepest = to_v * (_step_mult ** max(0, _max_buys - 1))
            if _deepest + 0.02 > hard_sl:
                log(f"AI Config Guard [CRITICAL]: DCA_DROP={to_v} with step={_step_mult} buys={_max_buys} → deepest={_deepest:.3f} > HARD_SL={hard_sl} - skipping", level='warning')
                continue
        elif p == 'DCA_STEP_MULTIPLIER':
            hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
            _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
            _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
            _deepest = _dca_drop * (to_v ** max(0, _max_buys - 1))
            if _deepest + 0.02 > hard_sl:
                log(f"AI Config Guard [CRITICAL]: DCA_STEP_MULT={to_v} → deepest DCA={_deepest:.3f} > HARD_SL={hard_sl} - skipping", level='warning')
                continue
        elif p == 'DCA_MAX_BUYS':
            hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
            _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
            _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
            _deepest = _dca_drop * (_step_mult ** max(0, int(to_v) - 1))
            if _deepest + 0.02 > hard_sl:
                log(f"AI Config Guard [CRITICAL]: DCA_MAX_BUYS={to_v} → deepest DCA={_deepest:.3f} > HARD_SL={hard_sl} - skipping", level='warning')
                continue
        
        # Apply the change
        new_cfg[p] = to_v
        
        # Record in history with CRITICAL marker
        hist.append({
            'ts': now_ts,
            'param': p,
            'from': cur,
            'to': to_v,
            'reason': f"ðŸš¨ CRITICAL AUTO-APPLY: {s.get('reason', '')}",
            'impact': 'CRITICAL',
            'auto_applied': True
        })
        
        _last_apply[p] = _utc_now()
        applied.append({'param': p, 'from': cur, 'to': to_v, 'reason': s.get('reason', '')})
        
        log(f"ðŸš¨ CRITICAL: {p} {cur} â†’ {to_v}: {s.get('reason', '')}", level='warning')

        try:
            _append_ai_apply_event({
                'ts': now_ts,
                'param': p,
                'from': cur,
                'to': to_v,
                'reason': s.get('reason', ''),
                'impact': 'CRITICAL',
                'mode': 'auto_apply_critical',
                'result': 'applied'
            })
        except Exception as e:
            _dbg(f"_append_ai_apply_event failed: {e}")

        if SUP_MEM_AVAILABLE and _sup_mem is not None:
            try:
                _sup_mem.log_suggestion(
                    {'param': p, 'from': cur, 'to': to_v, 'reason': s.get('reason', ''), 'impact': 'CRITICAL'},
                    applied=True,
                    snapshot={'mode': 'auto_apply_critical', 'ts': now_ts},
                )
            except Exception as _mem_e:
                _dbg(f"supervisor_memory log (critical) failed: {_mem_e}")

    if applied:
        # Atomic write
        write_json_compat(CONFIG_FILE, new_cfg)
        _save_history(hist)
        log(f"ðŸš¨ CRITICAL wijzigingen opgeslagen: {len(applied)} parameters", level='warning')
    
    return applied


def _apply_guardrails(param, value):
    """Apply safety guardrails to parameter values.
    
    Enforces:
    - Min/max bounds from LIMITS dict
    - Relational constraints (e.g., RSI_MIN < RSI_MAX)
    - Absolute safety limits (e.g., MIN_SCORE â‰¤ 10)
    
    Args:
        param: Parameter name (e.g., 'RSI_MIN_BUY')
        value: Proposed value
        
    Returns:
        Validated value clamped to safe bounds
    """
    lim = LIMITS.get(param)
    if not lim:
        return value
    
    # Apply min/max bounds from LIMITS
    clamped = max(lim['min'], min(lim['max'], value))
    
    # Additional safety constraints
    # 1. MIN_SCORE_TO_BUY: Never exceed 10 (score range is 0-12, but >10 is too restrictive)
    if param == 'MIN_SCORE_TO_BUY' and clamped > 10:
        log(f"âš ï¸  AI Config Guard: MIN_SCORE_TO_BUY={clamped} clamped to 10 (max safe limit)")
        clamped = 10
    
    # 2. RSI range validation will be checked in context of full config
    # (handled in auto_apply_if_enabled where we have access to current config)
    
    return clamped


def _load_history():
    try:
        rows = storage.fetch_all(CHANGE_HISTORY_DATASET, table=CHANGE_HISTORY_TABLE)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _save_history(entries):
    try:
        storage.replace_all(CHANGE_HISTORY_DATASET, list(entries), table=CHANGE_HISTORY_TABLE)
    except Exception as e:
        _dbg(f"replace_all failed: {e}")
    write_json_compat(CHANGE_HISTORY_FILE, entries)


def _append_ai_apply_event(event: dict) -> None:
    """Append structured AI apply/acceptance events to a JSONL trail."""
    try:
        Path(AI_APPLY_EVENTS_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(AI_APPLY_EVENTS_FILE, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + '\n')
    except Exception as e:
        _dbg(f"Path failed: {e}")


def _cooldown_apply_ok(param, minutes):
    ts = _last_apply.get(param)
    if not ts:
        return True
    return (_utc_now() - ts) >= timedelta(minutes=minutes)


def auto_apply_if_enabled(suggestions):
    """If AI_AUTO_APPLY is enabled in config, apply a filtered set of suggestions with guardrails and cooldowns.
    Records changes in CHANGE_HISTORY_FILE.
    Respects CONFIG_MANUAL_EDIT_TS to prevent overwriting recent manual changes (2 hour protection).
    Respects AI_PARAM_LOCK to completely prevent any parameter changes.
    """
    try:
        cfg = _safe_load_json(CONFIG_FILE, {})
        if not cfg:
            return False
        
        # HARD LOCK: If AI_PARAM_LOCK is True, NEVER modify any parameters
        if cfg.get('AI_PARAM_LOCK', False):
            log("ðŸ”’ AI_PARAM_LOCK actief - parameters worden NIET gewijzigd door AI", level='info')
            return False
        
        # Check for recent manual edits (2 hour protection window)
        manual_edit_ts = cfg.get('CONFIG_MANUAL_EDIT_TS', 0)
        if manual_edit_ts:
            time_since_manual_edit = time.time() - manual_edit_ts
            if time_since_manual_edit < 7200:  # 2 hours = 7200 seconds
                minutes_remaining = int((7200 - time_since_manual_edit) / 60)
                log(f"â¸ï¸  AI auto-apply uitgesteld: handmatige config wijziging {minutes_remaining} minuten geleden (2u bescherming)")
                return False
        
        auto = bool(cfg.get('AI_AUTO_APPLY', False))
        # suggestions may be a list or a dict with extras; normalize
        suggestion_list = suggestions if isinstance(suggestions, list) else (suggestions.get('suggestions', []) if isinstance(suggestions, dict) else [])
        if not auto or not suggestion_list:
            return False
        allow = cfg.get('AI_ALLOW_PARAMS') or list(LIMITS.keys())
        apply_cool_min = int(cfg.get('AI_APPLY_COOLDOWN_MIN', COOLDOWN_MINUTES))
        # Build last-apply map from history so state survives restart
        # Only rebuild from history if the JSON history file exists on disk.
        # This avoids pulling in migrated TinyDB data from unrelated environments (tests/dev).
        hist = []
        try:
            if os.path.exists(CHANGE_HISTORY_FILE) and os.path.getsize(CHANGE_HISTORY_FILE) > 0:
                hist = _load_history()
                for e in hist[-200:]:
                    if isinstance(e, dict) and not e.get('reverted'):
                        ts_val = e.get('ts')
                        if ts_val:
                            _last_apply[e.get('param')] = datetime.fromtimestamp(ts_val, timezone.utc)
        except Exception as e:
            _dbg(f"exists failed: {e}")
        changed_any = False
        # Load current config to mutate
        new_cfg = dict(cfg)
        now_ts = time.time()
        for s in suggestion_list:
            p = s.get('param')
            to_v = s.get('to')
            frm_v = s.get('from')
            if p not in allow:
                continue
            if to_v is None:
                continue
            if not _cooldown_apply_ok(p, apply_cool_min):
                continue
            cur = new_cfg.get(p, frm_v)
            try:
                # numeric coercion
                if isinstance(cur, int) and not isinstance(to_v, int):
                    to_v = int(round(float(to_v)))
                else:
                    to_v = float(to_v) if not isinstance(to_v, (int, float)) else to_v
            except Exception:
                continue
            if cur == to_v:
                continue
            to_v = _apply_guardrails(p, to_v)
            
            # Additional relational constraint checks
            # RSI range validation: RSI_MIN_BUY must be < RSI_MAX_BUY
            if p == 'RSI_MIN_BUY':
                rsi_max = new_cfg.get('RSI_MAX_BUY', 70)
                if to_v >= rsi_max:
                    log(f"âš ï¸  AI Config Guard: RSI_MIN_BUY={to_v} >= RSI_MAX_BUY={rsi_max} (invalid range) - skipping")
                    continue
            elif p == 'RSI_MAX_BUY':
                rsi_min = new_cfg.get('RSI_MIN_BUY', 35)
                if to_v <= rsi_min:
                    log(f"âš ï¸  AI Config Guard: RSI_MAX_BUY={to_v} <= RSI_MIN_BUY={rsi_min} (invalid range) - skipping")
                    continue
            
            # MAX_OPEN_TRADES: bounds (min 3, max 10) - NEVER reduce below 3
            if p == 'MAX_OPEN_TRADES' and to_v < 3:
                log(f'AI Config Guard: MAX_OPEN_TRADES={to_v} < 3 (minimum floor) - clamped to 3')
                to_v = 3
            if p == 'MAX_OPEN_TRADES' and to_v > 10:
                log(f"âš ï¸  AI Config Guard: MAX_OPEN_TRADES={to_v} > 10 (too many trades) - clamped to 10")
                to_v = 10

            # SL vs DCA guard: HARD_SL must be WIDER than deepest DCA level (all DCAs)
            if p == 'HARD_SL_ALT_PCT':
                _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
                _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
                _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
                _deepest = _dca_drop * (_step_mult ** max(0, _max_buys - 1))
                _min_sl = min(0.25, _deepest + 0.02)
                if to_v < _min_sl:
                    log(f"AI Config Guard: HARD_SL={to_v} < min required {_min_sl:.3f} (deepest DCA={_deepest:.3f}) - skipping")
                    continue
            elif p == 'DCA_DROP_PCT':
                hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
                _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
                _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
                _deepest = to_v * (_step_mult ** max(0, _max_buys - 1))
                if _deepest + 0.02 > hard_sl:
                    log(f"AI Config Guard: DCA_DROP={to_v} → deepest={_deepest:.3f} > HARD_SL={hard_sl} - skipping")
                    continue
            elif p == 'DCA_STEP_MULTIPLIER':
                hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
                _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
                _max_buys = int(new_cfg.get('DCA_MAX_BUYS', 3))
                _deepest = _dca_drop * (to_v ** max(0, _max_buys - 1))
                if _deepest + 0.02 > hard_sl:
                    log(f"AI Config Guard: DCA_STEP_MULT={to_v} → deepest={_deepest:.3f} > HARD_SL={hard_sl} - skipping")
                    continue
            elif p == 'DCA_MAX_BUYS':
                hard_sl = float(new_cfg.get('HARD_SL_ALT_PCT', 0.14))
                _dca_drop = float(new_cfg.get('DCA_DROP_PCT', 0.06))
                _step_mult = float(new_cfg.get('DCA_STEP_MULTIPLIER', 1.4))
                _deepest = _dca_drop * (_step_mult ** max(0, int(to_v) - 1))
                if _deepest + 0.02 > hard_sl:
                    log(f"AI Config Guard: DCA_MAX_BUYS={to_v} → deepest={_deepest:.3f} > HARD_SL={hard_sl} - skipping")
                    continue

            new_cfg[p] = to_v
            # record history entry
            hist.append({
                'ts': now_ts,
                'param': p,
                'from': cur,
                'to': to_v,
                'reason': s.get('reason', ''),
            })
            _last_apply[p] = _utc_now()
            changed_any = True

            try:
                _append_ai_apply_event({
                    'ts': now_ts,
                    'param': p,
                    'from': cur,
                    'to': to_v,
                    'reason': s.get('reason', ''),
                    'impact': s.get('impact') or 'AUTO',
                    'mode': 'auto_apply',
                    'result': 'applied'
                })
            except Exception as e:
                _dbg(f"_append_ai_apply_event failed: {e}")

            if SUP_MEM_AVAILABLE and _sup_mem is not None:
                try:
                    _sup_mem.log_suggestion(
                        {'param': p, 'from': cur, 'to': to_v, 'reason': s.get('reason', ''), 'impact': s.get('impact') or 'AUTO'},
                        applied=True,
                        snapshot={'mode': 'auto_apply', 'ts': now_ts},
                    )
                except Exception as _mem_e:
                    _dbg(f"supervisor_memory log (auto) failed: {_mem_e}")
            
            # Register change for feedback loop
            if FEEDBACK_AVAILABLE:
                try:
                    register_ai_change({
                        'param': p,
                        'from': cur,
                        'to': to_v,
                        'reason': s.get('reason', '')
                    })
                except Exception as e:
                    _dbg(f"register_ai_change failed: {e}")
        
        # Handle whitelist changes separately (if present in suggestions dict)
        if isinstance(suggestions, dict) and 'whitelist' in suggestions:
            wl_change = suggestions['whitelist']
            new_whitelist = wl_change.get('new_value')
            if new_whitelist and isinstance(new_whitelist, list):
                old_whitelist = new_cfg.get('WHITELIST_MARKETS', [])
                if set(new_whitelist) != set(old_whitelist):
                    new_cfg['WHITELIST_MARKETS'] = new_whitelist
                    hist.append({
                        'ts': now_ts,
                        'param': 'WHITELIST_MARKETS',
                        'from': len(old_whitelist),
                        'to': len(new_whitelist),
                        'reason': wl_change.get('reason', 'AI whitelist optimization'),
                    })
                    changed_any = True
                    log(f"AI auto-apply: WHITELIST_MARKETS updated ({len(old_whitelist)} -> {len(new_whitelist)} markets)")
        
        if changed_any:
            # Atomic writes
            write_json_compat(CONFIG_FILE, new_cfg)
            _save_history(hist)
            log("AI auto-apply doorgevoerd en geschiedenis bijgewerkt.")
        return changed_any
    except Exception as e:
        log(f"AI auto-apply fout: {e}", level='error')
        return False


def run_loop(sleep_sec=300):
    log("AI Supervisor gestart (advisor mode)")
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            suggestions = suggest_once()
            # suggestions may be a list or a dict {'suggestions': [...], ...}
            suggestion_list = suggestions if isinstance(suggestions, list) else (suggestions.get('suggestions', []) if isinstance(suggestions, dict) else [])
            auto_apply_if_enabled(suggestions)

            # Update AI heartbeat so bot can see we're online
            try:
                write_json_compat(AI_HEARTBEAT_FILE, {
                    'ts': time.time(),
                    'online': True,
                    'last_suggestion_count': len(suggestion_list),
                    'cycle': cycle_count,
                    'critical_suggestions': len([s for s in suggestion_list if s.get('impact') == 'CRITICAL'])
                })
            except Exception as e:
                _dbg(f"write_json_compat failed: {e}")

            # Periodically process persisted AI market suggestions (guarded-auto flow)
            try:
                cfg = _load_valid_config()
                # Only run processing when allowed by config
                if cfg and cfg.get('AI_AUTO_APPLY_MARKETS') and cfg.get('AI_MARKET_SCOPE') in ('guarded-auto', 'full-access'):
                    # Run every 3 cycles (~15 minutes by default) to avoid race conditions
                    if cycle_count % 3 == 0:
                        try:
                            # Lazy import to avoid heavy startup cost
                            from ai.process_ai_market_suggestions import process_pending_suggestions
                            processed = process_pending_suggestions()
                            if processed:
                                log(f"AI market suggestions processed: {len(processed)} entries", level='info')
                        except Exception as e:
                            log(f"Failed to process AI market suggestions: {e}", level='warning')
            except Exception as e:
                _dbg(f"process_pending_suggestions failed: {e}")
            
            # Every 3rd cycle (15 min with 5 min interval), run advanced analysis
            if cycle_count % 3 == 0:
                try:
                    from modules.ai_engine import AIEngine
                    engine = AIEngine()
                    
                    # Load trade history
                    trade_log = _safe_load_json(os.path.join(_PROJECT_ROOT, 'data', 'trade_log.json'), {'closed_trades': []})
                    closed_trades = trade_log.get('closed_trades', [])
                    
                    # Run advanced recommendations
                    advanced = engine.get_advanced_recommendations(closed_trades)
                    
                    if 'error' not in advanced:
                        # Log interesting findings
                        if advanced.get('momentum_shifts'):
                            shifts = advanced['momentum_shifts']
                            log(f"ðŸ”„ Momentum shifts gedetecteerd: {len(shifts)}", level='info')
                            for shift in shifts[:3]:
                                log(f"  {shift['market']}: {shift['recommendation']}", level='info')
                        
                        if advanced.get('win_predictions'):
                            predictions = advanced['win_predictions'][:3]
                            log(f"ðŸŽ¯ Top win probabilities:", level='info')
                            for pred in predictions:
                                prob = pred['win_probability'] * 100
                                log(f"  {pred['market']}: {prob:.1f}% ({pred['confidence']} confidence)", level='info')
                        
                        # Save advanced analysis
                        write_json_compat(os.path.join(_PROJECT_ROOT, 'data', 'ai_advanced_analysis.json'), advanced)
                except Exception as e:
                    log(f"Advanced AI analysis error: {e}", level='warning')

            # Periodic governance review of watchlist/whitelist performance
            if cycle_count % 6 == 0:
                try:
                    review_actions = run_periodic_review()
                    if review_actions:
                        for act in review_actions[:5]:
                            log(f"[WATCHLIST] {act.get('action')} {act.get('market')}", level='info')
                except Exception as e:
                    log(f"Watchlist review failed: {e}", level='warning')
                try:
                    quarantine_actions = review_quarantine()
                    if quarantine_actions:
                        for act in quarantine_actions:
                            log(f"[QUARANTINE] {act.get('action')} {act.get('market')}", level='info')
                except Exception as e:
                    log(f"Quarantine review failed: {e}", level='warning')
            
            # Write AI heartbeat so dashboard can show ONLINE state
            try:
                write_json_compat(AI_HEARTBEAT_FILE, {'ts': time.time()})
            except Exception as e:
                _dbg(f"write_json_compat failed: {e}")
        except Exception as e:
            log(f"AI Supervisor fout: {e}", level='error')
        time.sleep(sleep_sec)


if __name__ == '__main__':
    # Parse CLI arguments (was module-level, moved here for clean imports)
    import argparse as _ap
    _parser = _ap.ArgumentParser(add_help=False)
    _parser.add_argument('--allow-claim', action='store_true', dest='allow_claim')
    _parser.add_argument('--once', action='store_true')
    _parser.add_argument('--interval', type=int, default=300)
    _ns, _ = _parser.parse_known_args()
    if _ns.allow_claim:
        ALLOW_CLAIM = True

    # Single-instance check FIRST: prevent duplicate ai_supervisor processes
    # MUST be before main() to prevent race conditions!
    import sys
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'scripts', 'helpers'))
    try:
        from single_instance import ensure_single_instance_or_exit  # type: ignore
        ensure_single_instance_or_exit('ai_supervisor.py', allow_claim=True)
    except ImportError:
        pass  # single_instance module not available, skip check
    
    # Call main() to setup PID guard
    main()
    
    # Usage:
    #   python ai_supervisor.py --once             # run one suggestion pass and exit
    #   python ai_supervisor.py --interval 600     # loop with custom interval seconds
    if _ns.once:
        try:
            suggestions = suggest_once()
            try:
                # if auto-apply is enabled in config, attempt to apply the suggestions
                auto_apply_if_enabled(suggestions)
            except Exception as e:
                _dbg(f"auto_apply_if_enabled failed: {e}")
            # update AI heartbeat so external supervisors see a fresh timestamp
            try:
                write_json_compat(AI_HEARTBEAT_FILE, {'ts': time.time()})
            except Exception as e:
                _dbg(f"write_json_compat failed: {e}")
        finally:
            raise SystemExit(0)
    run_loop(sleep_sec=_ns.interval)
