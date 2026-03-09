import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple, Set

import numpy as np
from sklearn.model_selection import ParameterGrid

from modules.json_compat import write_json_compat

TRADE_LOG_PATH = Path('data') / 'trade_log.json'
BOT_CONFIG_PATH = Path('config') / 'bot_config.json'

# Parameters that the ML optimizer can tune (must be subset of AI_ALLOW_PARAMS)
# CRITICAL: Session 12 optimized RSI, MIN_SCORE, TRAILING manually - DO NOT override!
ML_TUNABLE_PARAMS = {
    'SMA_SHORT',
    'SMA_LONG',
    'MARKET_PERFORMANCE_MIN_TRADES',
    'PERFORMANCE_FILTER_MIN_WINRATE',
}

# Parameters that should NEVER be auto-modified (Session 12 optimizations)
PROTECTED_PARAMS = {
    'RSI_MIN_BUY',
    'RSI_MAX_BUY',
    'MIN_SCORE_TO_BUY',
    'DEFAULT_TRAILING',
    'TRAILING_ACTIVATION_PCT',
    'STOP_LOSS_ENABLED',
    'HARD_SL_ALT_PCT',
    'HARD_SL_BTCETH_PCT',
}


def _load_config(path: Path = BOT_CONFIG_PATH) -> Dict[str, Any]:
    """Load bot config to check AI_ALLOW_PARAMS."""
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as fh:
        config = json.load(fh)
    return config if isinstance(config, dict) else {}


def _get_allowed_params(config: Dict[str, Any]) -> Set[str]:
    """Get parameters that AI is allowed to modify."""
    allowed = set(config.get('AI_ALLOW_PARAMS', []))
    # Only return params that are BOTH in allowed list AND in ML_TUNABLE_PARAMS
    # Never return protected params even if somehow in allowed list
    return (allowed & ML_TUNABLE_PARAMS) - PROTECTED_PARAMS


def _load_closed_trades(path: Path = TRADE_LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return []
    return list(data.get('closed', []))


def _evaluate_params(trades: Iterable[dict[str, Any]], params: Dict[str, Any], base_config: Dict[str, Any]) -> float:
    """Evaluate params using existing config values for non-tunable parameters."""
    min_score = params.get('MIN_SCORE_TO_BUY', base_config.get('MIN_SCORE_TO_BUY', 5))
    pnl = [t.get('profit', 0) for t in trades if (t.get('score', 0) or 0) >= min_score]
    if not pnl:
        return float('-inf')
    return float(np.mean(pnl))


def grid_search_parameters(trades: Iterable[dict[str, Any]], allowed_params: Set[str] = None) -> Tuple[Dict[str, Any], float]:
    """Grid search only for allowed parameters."""
    config = _load_config()
    if allowed_params is None:
        allowed_params = _get_allowed_params(config)
    
    # Build param grid only for allowed params
    full_param_grid = {
        'SMA_SHORT': [7, 10, 14],
        'SMA_LONG': [20, 30, 50],
        'MARKET_PERFORMANCE_MIN_TRADES': [3, 5, 10],
        'PERFORMANCE_FILTER_MIN_WINRATE': [0.4, 0.5, 0.6],
    }
    
    # Filter to only allowed params
    param_grid = {k: v for k, v in full_param_grid.items() if k in allowed_params}
    
    if not param_grid:
        # No allowed params to optimize
        return {}, float('-inf')
    
    best_score = float('-inf')
    best_params: Dict[str, Any] | None = None
    for params in ParameterGrid(param_grid):
        score = _evaluate_params(trades, params, config)
        if score > best_score:
            best_score = score
            best_params = dict(params)
    return (best_params or {}), best_score


def update_bot_config(params: Dict[str, Any], path: Path = BOT_CONFIG_PATH) -> None:
    """Update config, respecting AI_ALLOW_PARAMS and PROTECTED_PARAMS."""
    if not path.exists() or not params:
        return
    with path.open('r', encoding='utf-8') as fh:
        config = json.load(fh)
    if not isinstance(config, dict):
        config = {}
    
    # Get allowed params from config
    allowed = _get_allowed_params(config)
    
    # Filter params to only update allowed ones
    safe_params = {k: v for k, v in params.items() 
                   if k in allowed and k not in PROTECTED_PARAMS}
    
    if not safe_params:
        print(f"[ML Optimizer] Geen parameters om te updaten (blocked: {list(params.keys())})")
        return
    
    config.update(safe_params)
    write_json_compat(str(path), config, indent=2)
    print(f"[ML Optimizer] Updated: {list(safe_params.keys())}")


def optimize_ml_parameters() -> Tuple[Dict[str, Any], float]:
    trades = _load_closed_trades()
    params, score = grid_search_parameters(trades)
    if params:
        update_bot_config(params)
    return params, score


async def optimize_ml_parameters_async() -> Tuple[Dict[str, Any], float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, optimize_ml_parameters)


if __name__ == '__main__':
    result_params, result_score = asyncio.run(optimize_ml_parameters_async())
    if result_params:
        print(f"Beste parameters: {result_params} (gemiddelde winst: {result_score:.2f} EUR)")
        print('Config automatisch bijgewerkt!')
    else:
        print('Geen optimale parameters gevonden (te weinig data?).')
