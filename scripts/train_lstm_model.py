"""LSTM Price Predictor Training Script
========================================

Fetches recent 1-minute candles for the configured whitelist markets,
builds sequence/label arrays, and trains the LSTM model used by
``modules.ml.predict_ensemble``.

Output:
    models/lstm_price_model.h5
    models/lstm_price_model.scaler.json

Usage:
    python scripts/train_lstm_model.py
    python scripts/train_lstm_model.py --epochs 20 --markets BTC-EUR,ETH-EUR

Designed to be safe to run repeatedly: if Bitvavo is unreachable or
insufficient data is gathered, the script EXITS WITHOUT touching the
existing ``models/lstm_price_model.h5`` so the bot keeps running.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.config import load_config  # noqa: E402
from modules.logging_utils import log  # noqa: E402

LOOKBACK = 60          # candles per sequence (matches LSTMPricePredictor default)
HORIZON = 5            # predict price movement N candles ahead
UP_THRESHOLD = 0.003   # +0.3% → UP
DOWN_THRESHOLD = -0.003  # -0.3% → DOWN
MIN_SEQUENCES = 200    # do nothing if we can't gather at least this many


def _safe_print(msg: str) -> None:
    print(f"[train_lstm] {msg}", flush=True)
    try:
        log(f"train_lstm: {msg}")
    except Exception:
        pass


def _fetch_candles(market: str, interval: str = "1m", limit: int = 1440) -> Optional[List[List[float]]]:
    """Return raw Bitvavo candles [[ts, open, high, low, close, vol], ...] or None."""
    try:
        from python_bitvavo_api.bitvavo import Bitvavo
    except Exception as exc:
        _safe_print(f"python_bitvavo_api not available: {exc}")
        return None

    api_key = os.getenv("BITVAVO_API_KEY", "")
    api_secret = os.getenv("BITVAVO_API_SECRET", "")
    bv = Bitvavo({
        "APIKEY": api_key,
        "APISECRET": api_secret,
        "RESTURL": "https://api.bitvavo.com/v2",
    })
    try:
        candles = bv.candles(market, interval, {"limit": limit})
        if not candles or not isinstance(candles, list):
            return None
        # Bitvavo returns newest first; reverse to chronological
        return list(reversed(candles))
    except Exception as exc:
        _safe_print(f"candle fetch failed for {market}: {exc}")
        return None


def _rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes, prepend=closes[0])
    gain = np.maximum(deltas, 0.0)
    loss = -np.minimum(deltas, 0.0)
    avg_gain = np.zeros_like(closes)
    avg_loss = np.zeros_like(closes)
    if len(closes) > period:
        avg_gain[period] = gain[1:period + 1].mean()
        avg_loss[period] = loss[1:period + 1].mean()
        for i in range(period + 1, len(closes)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = np.where(avg_loss > 0, avg_gain / np.where(avg_loss == 0, 1, avg_loss), 0.0)
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    out = np.zeros_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _macd(closes: np.ndarray) -> np.ndarray:
    return _ema(closes, 12) - _ema(closes, 26)


def _bb_position(closes: np.ndarray, period: int = 20) -> np.ndarray:
    out = np.zeros_like(closes)
    for i in range(period, len(closes)):
        window = closes[i - period:i]
        mid = window.mean()
        sd = window.std()
        if sd > 0:
            upper = mid + 2 * sd
            lower = mid - 2 * sd
            out[i] = (closes[i] - lower) / max(upper - lower, 1e-9)
    return out


def _build_sequences(candles: List[List[float]]) -> Tuple[np.ndarray, np.ndarray]:
    """Convert candles into (X, y) tensors.

    X: (n, LOOKBACK, 5)  features = [close, volume, rsi, macd, bb_position]
    y: (n, 3)            one-hot DOWN / NEUTRAL / UP
    """
    if len(candles) < LOOKBACK + HORIZON + 30:
        return np.empty((0, LOOKBACK, 5)), np.empty((0, 3))

    arr = np.asarray(candles, dtype=np.float64)
    closes = arr[:, 4]
    volumes = arr[:, 5]
    rsi = _rsi(closes)
    macd = _macd(closes)
    bbp = _bb_position(closes)

    feat = np.stack([closes, volumes, rsi, macd, bbp], axis=1)

    X_list, y_list = [], []
    n = len(closes) - HORIZON
    for i in range(LOOKBACK, n):
        seq = feat[i - LOOKBACK:i]
        future_ret = (closes[i + HORIZON] - closes[i]) / closes[i]
        if future_ret > UP_THRESHOLD:
            label = [0, 0, 1]   # UP
        elif future_ret < DOWN_THRESHOLD:
            label = [1, 0, 0]   # DOWN
        else:
            label = [0, 1, 0]   # NEUTRAL
        X_list.append(seq)
        y_list.append(label)

    if not X_list:
        return np.empty((0, LOOKBACK, 5)), np.empty((0, 3))
    return np.asarray(X_list, dtype=np.float32), np.asarray(y_list, dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the LSTM price predictor.")
    parser.add_argument("--epochs", type=int, default=10, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--markets",
        type=str,
        default="",
        help="Comma-separated markets. Defaults to WHITELIST_MARKETS from config (capped at 10).",
    )
    parser.add_argument("--limit", type=int, default=1440, help="Candles per market (max 1440 = 1 day)")
    args = parser.parse_args()

    cfg = load_config() or {}
    if args.markets:
        markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    else:
        wl = cfg.get("WHITELIST_MARKETS") or []
        markets = [m for m in wl if isinstance(m, str)][:10]

    if not markets:
        _safe_print("no markets configured; aborting (existing model untouched).")
        return 0

    _safe_print(f"fetching candles for {len(markets)} markets ({args.limit}/each)...")

    X_all: List[np.ndarray] = []
    y_all: List[np.ndarray] = []
    for mkt in markets:
        candles = _fetch_candles(mkt, "1m", args.limit)
        if not candles:
            _safe_print(f"  {mkt}: no candles; skipping")
            continue
        X, y = _build_sequences(candles)
        if len(X) == 0:
            _safe_print(f"  {mkt}: insufficient data; skipping")
            continue
        X_all.append(X)
        y_all.append(y)
        _safe_print(f"  {mkt}: +{len(X)} sequences (UP={int(y[:,2].sum())}, NEU={int(y[:,1].sum())}, DOWN={int(y[:,0].sum())})")

    if not X_all:
        _safe_print("no training data gathered; aborting (existing model untouched).")
        return 0

    X = np.concatenate(X_all, axis=0)
    y = np.concatenate(y_all, axis=0)

    if len(X) < MIN_SEQUENCES:
        _safe_print(f"only {len(X)} sequences (need >= {MIN_SEQUENCES}); aborting (existing model untouched).")
        return 0

    # Shuffle
    rng = np.random.default_rng(42)
    perm = rng.permutation(len(X))
    X = X[perm]
    y = y[perm]

    # Train/val split (80/20)
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    _safe_print(f"training: {len(X_train)} train / {len(X_val)} val sequences over {args.epochs} epochs")

    try:
        from modules.ml_lstm import LSTMPricePredictor, TENSORFLOW_AVAILABLE
    except Exception as exc:
        _safe_print(f"cannot import LSTMPricePredictor: {exc}")
        return 1

    if not TENSORFLOW_AVAILABLE:
        _safe_print("TensorFlow not available; install with `pip install tensorflow`. Aborting.")
        return 1

    predictor = LSTMPricePredictor(lookback_window=LOOKBACK, prediction_horizon=HORIZON)
    predictor.build_model()
    t0 = time.time()
    predictor.train(X_train, y_train, X_val=X_val, y_val=y_val, epochs=args.epochs, batch_size=args.batch_size)
    predictor.save_model()
    _safe_print(f"done in {time.time() - t0:.1f}s. saved {predictor.model_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
