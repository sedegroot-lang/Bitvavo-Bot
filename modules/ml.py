import xgboost as xgb
import numpy as np
from modules.logging_utils import log
from modules.config import load_config
from typing import Dict, Tuple, Optional

# Regular model (7 market-indicator features) is used for entry signals.
# Enhanced model (5 trade-outcome features) is for post-trade analysis only.
DEFAULT_MODEL_PATH = "ai/ai_xgb_model.json"
_FALLBACK_MODEL_PATH = "ai/ai_xgb_model_enhanced.json"

# Allow overriding model path via config with backward compatibility for legacy key
try:
    import os as _os
    _cfg = load_config()
    MODEL_PATH = (
        _cfg.get("XGB_MODEL_PATH")
        or _cfg.get("MODEL_PATH")
        or (DEFAULT_MODEL_PATH if _os.path.exists(DEFAULT_MODEL_PATH) else _FALLBACK_MODEL_PATH)
    )
    USE_LSTM = _cfg.get("USE_LSTM", False)
    USE_RL_AGENT = _cfg.get("USE_RL_AGENT", False)
except Exception:
    MODEL_PATH = DEFAULT_MODEL_PATH
    USE_LSTM = False
    USE_RL_AGENT = False

# Lazy load LSTM en RL modules
_lstm_predictor = None
_rl_agent = None
_xgb_model = None  # Cached XGB model
_xgb_num_features = None  # Expected feature count from model

def _get_xgb_model():
    """Lazy load and cache XGBoost model"""
    global _xgb_model, _xgb_num_features
    if _xgb_model is None:
        try:
            _xgb_model = xgb.XGBClassifier()
            _xgb_model.load_model(MODEL_PATH)
            # Get expected feature count from model
            _xgb_num_features = _xgb_model.n_features_in_
        except Exception as e:
            log(f"XGBoost model laden mislukt: {e}", level='error')
            _xgb_num_features = 7  # Default fallback
    return _xgb_model, _xgb_num_features

def validate_features(features, expected_count=None) -> bool:
    """
    Valideert feature array op NaN, inf en juiste lengte.
    """
    arr = np.array(features)
    if np.any(np.isnan(arr)) or np.any(np.isinf(arr)):
        log("Features bevatten NaN of inf!", level='error')
        return False
    # Use dynamic feature count from model, or fallback
    if expected_count is None:
        _, expected_count = _get_xgb_model()
        if expected_count is None:
            expected_count = 7  # Model default
    if arr.shape[0] != expected_count:
        log(f"Feature shape mismatch, expected: {expected_count}, got {arr.shape[0]}", level='error')
        return False
    return True

def feature_engineering(raw: dict):
    """
    Zet ruwe indicatoren om naar ML feature array (7 features).
    Volgorde: rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k
    """
    features = [
        raw.get('rsi', 0),
        raw.get('macd', 0),
        raw.get('sma_short', 0),
        raw.get('sma_long', 0),
        raw.get('volume', 0),
        raw.get('bb_position', 0.5),   # Bollinger Bands positie (0=under lower, 1=above upper)
        raw.get('stochastic_k', 50.0), # Stochastic %K
    ]
    return features

def model_explainability(model, features) -> dict:
    """
    Geeft feature importances terug voor model explainability.
    """
    # Return feature importances
    try:
        importances = model.feature_importances_
        return dict(zip(['rsi','macd','sma_short','sma_long','volume','bb_position','stochastic_k'], importances))
    except Exception as e:
        log(f"Explainability mislukt: {e}", level='error')
        return {}

def retrain_xgboost(X, y):
    """
    Traint XGBoost model opnieuw en slaat op.
    """
    # X: features, y: labels
    model = xgb.XGBClassifier()
    model.fit(X, y)
    model.save_model(MODEL_PATH)
    log("XGBoost model opnieuw getraind en opgeslagen.")
    return model

def predict_xgboost_signal(features) -> int:
    """
    Voorspelt trading signaal met XGBoost, incl. validatie.
    """
    model, expected_features = _get_xgb_model()
    if model is None:
        return 0
    if not validate_features(features, expected_features):
        return 0
    try:
        features = np.array(features).reshape(1, -1)
        signal = model.predict(features)[0]
        return signal
    except Exception as e:
        log(f"XGBoost predictie mislukt: {e}", level='error')
        return 0


def get_lstm_predictor():
    """Lazy load LSTM predictor"""
    global _lstm_predictor
    if _lstm_predictor is None and USE_LSTM:
        try:
            from modules.ml_lstm import LSTMPricePredictor
            _lstm_predictor = LSTMPricePredictor()
            _lstm_predictor.load_model()
        except Exception as e:
            log(f"LSTM predictor laden mislukt: {e}", level='warning')
    return _lstm_predictor


def get_rl_agent():
    """Lazy load RL agent"""
    global _rl_agent
    if _rl_agent is None and USE_RL_AGENT:
        try:
            from modules.reinforcement_learning import QLearningAgent
            _rl_agent = QLearningAgent()
        except Exception as e:
            log(f"RL agent laden mislukt: {e}", level='warning')
    return _rl_agent


def prepare_lstm_sequence(candles: list, features_dict: dict, lookback_window: int = 60) -> Optional[np.ndarray]:
    """
    Prepares raw candle data into LSTM-compatible sequence format.
    
    Args:
        candles: Raw candle list with OHLCV data
        features_dict: Pre-calculated features (rsi, macd, etc.)
        lookback_window: Number of historical points (default 60)
    
    Returns:
        numpy array of shape (lookback_window, 5) or None if insufficient data
    """
    if candles is None or len(candles) < lookback_window:
        return None
    
    try:
        # Extract last lookback_window candles
        recent_candles = candles[-lookback_window:]
        
        # Prepare 5 features: price, volume, rsi, macd, bb_position
        prices = []
        volumes = []
        
        for c in recent_candles:
            # Handle both list and dict candle formats
            if isinstance(c, dict):
                prices.append(float(c.get('close', c.get('c', 0))))
                volumes.append(float(c.get('volume', c.get('v', 0))))
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                prices.append(float(c[4]))  # close price
                volumes.append(float(c[5]) if len(c) > 5 else 0.0)  # volume
            else:
                prices.append(float(c) if isinstance(c, (int, float)) else 0.0)
                volumes.append(0.0)
        
        # Get RSI, MACD from pre-calculated features (use as constant for sequence)
        rsi = features_dict.get('rsi', 50.0)
        macd = features_dict.get('macd', 0.0)
        
        # Calculate BB position for each price point
        if len(prices) >= 20:
            prices_arr = np.array(prices)
            sma_20 = np.mean(prices_arr[-20:])
            std_20 = np.std(prices_arr[-20:])
            if std_20 > 0:
                bb_upper = sma_20 + 2 * std_20
                bb_lower = sma_20 - 2 * std_20
                bb_positions = [(p - bb_lower) / (bb_upper - bb_lower) for p in prices]
            else:
                bb_positions = [0.5] * len(prices)
        else:
            bb_positions = [0.5] * len(prices)
        
        # Repeat RSI/MACD for each timepoint (they're computed once for the period)
        rsi_values = [rsi] * lookback_window
        macd_values = [macd] * lookback_window
        
        # Stack into (lookback_window, 5) array
        sequence = np.column_stack([
            prices,
            volumes,
            rsi_values,
            macd_values,
            bb_positions
        ])
        
        return sequence.astype(np.float32)
        
    except Exception as e:
        log(f"LSTM sequence preparation failed: {e}", level='debug')
        return None


def predict_ensemble(features: list, 
                     market_data: Optional[Dict] = None,
                     price_sequence: Optional[np.ndarray] = None) -> Dict[str, any]:
    """
    Ensemble predictie: combineer XGBoost, LSTM en RL
    
    Args:
        features: XGBoost features (11-dim array)
        market_data: Market state voor RL agent
        price_sequence: Price sequence voor LSTM (lookback_window x 5)
    
    Returns:
        {
            'signal': int (0=HOLD, 1=BUY, -1=SELL),
            'confidence': float (0-1),
            'xgb_signal': int,
            'lstm_prediction': str,
            'lstm_confidence': float,
            'rl_action': str,
            'rl_q_value': float
        }
    """
    result = {
        'signal': 0,
        'confidence': 0.0,
        'xgb_signal': 0,
        'lstm_prediction': 'NEUTRAL',
        'lstm_confidence': 0.33,
        'rl_action': 'HOLD',
        'rl_q_value': 0.0
    }
    
    # 1. XGBoost prediction (altijd)
    xgb_signal = predict_xgboost_signal(features)
    result['xgb_signal'] = xgb_signal
    
    # 2. LSTM prediction (optioneel)
    lstm_pred = None
    lstm_conf = 0.33
    if USE_LSTM and price_sequence is not None:
        lstm = get_lstm_predictor()
        if lstm:
            try:
                import numpy as np
                # Ensure price_sequence is numpy array
                if isinstance(price_sequence, list):
                    price_sequence = np.array(price_sequence)
                
                # Validate shape: must be (lookback_window, 5) or (1, lookback_window, 5)
                expected_features = lstm.features_count  # 5
                expected_lookback = lstm.lookback_window  # 60
                
                if price_sequence.ndim == 1:
                    # Raw price array - try to reshape if size is multiple of features
                    if len(price_sequence) >= expected_lookback * expected_features:
                        # Truncate to last expected_lookback * expected_features elements
                        truncated = price_sequence[-(expected_lookback * expected_features):]
                        price_sequence = truncated.reshape(expected_lookback, expected_features)
                        lstm_pred, lstm_conf = lstm.predict(price_sequence)
                        result['lstm_prediction'] = lstm_pred
                        result['lstm_confidence'] = lstm_conf
                    # Else: skip silently (wrong input format)
                elif price_sequence.ndim == 2:
                    # (rows, features) shape - truncate if too long
                    if price_sequence.shape[1] == expected_features:
                        if price_sequence.shape[0] > expected_lookback:
                            # Truncate to last 60 candles
                            price_sequence = price_sequence[-expected_lookback:]
                        if price_sequence.shape[0] == expected_lookback:
                            lstm_pred, lstm_conf = lstm.predict(price_sequence)
                            result['lstm_prediction'] = lstm_pred
                            result['lstm_confidence'] = lstm_conf
                    # Else: wrong feature count, skip
                elif price_sequence.ndim == 3:
                    # Already batched (batch, lookback, features)
                    if price_sequence.shape[2] == expected_features:
                        seq = price_sequence[0]
                        if seq.shape[0] > expected_lookback:
                            seq = seq[-expected_lookback:]
                        if seq.shape[0] == expected_lookback:
                            lstm_pred, lstm_conf = lstm.predict(seq)
                            result['lstm_prediction'] = lstm_pred
                            result['lstm_confidence'] = lstm_conf
                # No more noisy debug logs for shape mismatches
            except Exception as e:
                log(f"LSTM predictie fout: {e}", level='warning')
    
    # 3. RL agent decision (optioneel)
    rl_action = None
    rl_q_value = 0.0
    if USE_RL_AGENT and market_data:
        agent = get_rl_agent()
        if agent:
            try:
                state = agent.get_state(market_data)
                rl_action = agent.choose_action(state, explore=False)
                _, rl_q_value = agent.get_best_action_value(state)
                result['rl_action'] = rl_action
                result['rl_q_value'] = rl_q_value
            except Exception as e:
                log(f"RL agent fout: {e}", level='warning')
    
    # 4. Ensemble voting
    votes = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
    weights = {'BUY': 0.0, 'SELL': 0.0, 'HOLD': 0.0}
    
    # XGBoost stem (weight: 1.0)
    if xgb_signal == 1:
        votes['BUY'] += 1
        weights['BUY'] += 1.0
    elif xgb_signal == -1:
        votes['SELL'] += 1
        weights['SELL'] += 1.0
    else:
        votes['HOLD'] += 1
        weights['HOLD'] += 1.0
    
    # LSTM stem (weight: lstm_confidence)
    if lstm_pred:
        if lstm_pred == 'UP':
            votes['BUY'] += 1
            weights['BUY'] += lstm_conf
        elif lstm_pred == 'DOWN':
            votes['SELL'] += 1
            weights['SELL'] += lstm_conf
        else:
            votes['HOLD'] += 1
            weights['HOLD'] += lstm_conf * 0.5  # Lagere weight voor NEUTRAL
    
    # RL agent stem (weight: 0.8)
    if rl_action:
        votes[rl_action] += 1
        weights[rl_action] += 0.8
    
    # Bepaal finale beslissing op basis van gewogen stemmen
    max_weight = max(weights.values())
    final_decision = max(weights, key=weights.get)
    
    # Converteer naar signaal
    signal_map = {'BUY': 1, 'SELL': -1, 'HOLD': 0}
    result['signal'] = signal_map[final_decision]
    
    # Bereken confidence (0-1)
    total_weight = sum(weights.values())
    result['confidence'] = max_weight / total_weight if total_weight > 0 else 0.0
    
    log(f"Ensemble: XGB={xgb_signal}, LSTM={lstm_pred}({lstm_conf:.2f}), RL={rl_action}({rl_q_value:.2f}) → {final_decision} (conf={result['confidence']:.2f})")
    
    return result


def update_rl_agent(state: str, action: str, reward: float, next_state: str):
    """
    Update RL agent met trade resultaat
    
    Args:
        state: Market state bij trade entry
        action: Genomen actie (BUY/SELL/HOLD)
        reward: Behaalde reward (gebaseerd op P/L)
        next_state: Market state bij trade exit
    """
    if not USE_RL_AGENT:
        return
    
    agent = get_rl_agent()
    if agent:
        try:
            agent.update(state, action, reward, next_state)
            agent.save_q_table()
            log(f"RL agent geüpdatet: {state} → {action} (reward={reward:.2f})")
        except Exception as e:
            log(f"RL agent update fout: {e}", level='error')
