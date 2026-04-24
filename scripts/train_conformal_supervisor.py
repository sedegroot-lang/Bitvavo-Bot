"""
Train XGBoost on historical Bitvavo candles, wrap in Mapie Conformal Prediction,
walk-forward backtest with realistic fees + slippage.

Pipeline:
1. Load all CSVs from data/historical_candles/
2. Per market, generate features per row from past 50 candles
3. Label: setup is 'win' if (max high in next 24h - entry) / entry >= +1.5%
   AND (min low in next 24h - entry) / entry > -2.0%   (didn't stop out first)
   Else 'loss'.
4. Time-series split (train on first 70%, calibrate on next 15%, test on last 15%)
5. Train XGBClassifier; wrap in MapieClassifier (split conformal, alpha=0.10)
6. Backtest: simulate buying every test-row signal, fee=0.25% round-trip,
   exit at +1.5% TP or -2% SL (whichever hit first in next 24h candles).
7. Compare PnL: baseline = always buy when XGB says >=0.5; conformal = only
   buy when prediction set is {1} singleton (i.e., model is confident).

Run:
    python scripts/train_conformal_supervisor.py
"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CANDLES_DIR = ROOT / "data" / "historical_candles"
MODEL_OUT = ROOT / "ai" / "conformal_supervisor.json"
META_OUT = ROOT / "ai" / "conformal_supervisor_meta.json"

# ─── Trading params (realistic Bitvavo) ──────────────────────────────────
FEE_PCT = 0.0025          # 0.25% round-trip
TP_PCT = 0.015            # +1.5%
SL_PCT = -0.02            # -2.0%
HORIZON_BARS = 24         # 24× 1h = 24h hold-window
LOOKBACK = 50             # bars used for features
TRADE_SIZE_EUR = 35       # matches BASE_AMOUNT_EUR


# ─── Feature engineering ─────────────────────────────────────────────────
def rsi_(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    d = np.diff(closes[-period - 1 :])
    gains = np.maximum(d, 0).mean()
    losses = -np.minimum(d, 0).mean()
    if losses == 0:
        return 100.0
    rs = gains / losses
    return float(100 - 100 / (1 + rs))


def ema_(arr: np.ndarray, period: int) -> float:
    if len(arr) < period:
        return float(arr.mean()) if len(arr) else 0.0
    k = 2 / (period + 1)
    e = arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return float(e)


def features_for_row(window: pd.DataFrame) -> dict | None:
    """window has LOOKBACK rows ending at the entry-candle."""
    if len(window) < LOOKBACK:
        return None
    closes = window["close"].to_numpy()
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    vols = window["volume"].to_numpy()

    cur = closes[-1]
    if cur <= 0:
        return None

    # returns
    ret_1 = (closes[-1] / closes[-2] - 1) if len(closes) >= 2 else 0.0
    ret_6 = (closes[-1] / closes[-7] - 1) if len(closes) >= 7 else 0.0
    ret_24 = (closes[-1] / closes[-25] - 1) if len(closes) >= 25 else 0.0

    # volatility
    rets = np.diff(closes) / closes[:-1]
    vol = float(rets[-24:].std()) if len(rets) >= 24 else 0.0

    # range/position
    hi24, lo24 = highs[-24:].max(), lows[-24:].min()
    pos_in_range = (cur - lo24) / (hi24 - lo24 + 1e-9)

    # MA stack
    ema_short = ema_(closes[-12:], 12)
    ema_long = ema_(closes[-26:], 26)
    macd_diff = (ema_short - ema_long) / cur

    # RSI
    rsi_v = rsi_(closes, 14)

    # Volume
    vol_avg = vols[-24:].mean()
    vol_ratio = vols[-1] / (vol_avg + 1e-9)
    vol_trend = (vols[-6:].mean() / (vols[-24:-6].mean() + 1e-9)) - 1

    # Trend strength: linear slope on log-prices
    x = np.arange(min(24, len(closes)))
    lp = np.log(closes[-len(x):] + 1e-9)
    slope = float(np.polyfit(x, lp, 1)[0]) if len(x) >= 2 else 0.0

    return {
        "ret_1": ret_1, "ret_6": ret_6, "ret_24": ret_24,
        "vol": vol, "pos_in_range": pos_in_range,
        "macd_diff": macd_diff, "rsi": rsi_v,
        "vol_ratio": vol_ratio, "vol_trend": vol_trend,
        "slope": slope,
    }


def label_for_row(future: pd.DataFrame, entry: float) -> int | None:
    """Look ahead HORIZON_BARS. 1=TP-first, 0=SL-first or stagnation."""
    if len(future) < HORIZON_BARS:
        return None
    tp = entry * (1 + TP_PCT)
    sl = entry * (1 + SL_PCT)
    for _, row in future.iterrows():
        if row["low"] <= sl:
            return 0
        if row["high"] >= tp:
            return 1
    return 0  # neither hit → treat as loss (can't close positive)


# ─── Build dataset (vectorized via NumPy) ────────────────────────────────
def build_features_vec(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, vols: np.ndarray) -> np.ndarray:
    """Returns shape (N, n_features) where row i uses data up to index i (inclusive).
    Rows 0..LOOKBACK-1 are filled with zeros (will be masked out)."""
    n = len(closes)
    F = np.zeros((n, 10), dtype=np.float32)

    # ret_1
    F[1:, 0] = closes[1:] / np.maximum(closes[:-1], 1e-9) - 1
    # ret_6
    F[6:, 1] = closes[6:] / np.maximum(closes[:-6], 1e-9) - 1
    # ret_24
    F[24:, 2] = closes[24:] / np.maximum(closes[:-24], 1e-9) - 1

    # vol = std of last 24 returns
    rets = np.zeros(n, dtype=np.float32)
    rets[1:] = closes[1:] / np.maximum(closes[:-1], 1e-9) - 1
    s = pd.Series(rets)
    F[:, 3] = s.rolling(24, min_periods=24).std().fillna(0).to_numpy()

    # pos in 24h range
    hi24 = pd.Series(highs).rolling(24, min_periods=24).max().to_numpy()
    lo24 = pd.Series(lows).rolling(24, min_periods=24).min().to_numpy()
    F[:, 4] = np.where(np.isfinite(hi24) & (hi24 > lo24), (closes - lo24) / (hi24 - lo24 + 1e-9), 0.5)

    # MACD diff via EMA12/EMA26
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().to_numpy()
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().to_numpy()
    F[:, 5] = (ema12 - ema26) / np.maximum(closes, 1e-9)

    # RSI 14
    delta = np.zeros(n, dtype=np.float32); delta[1:] = closes[1:] - closes[:-1]
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_g = pd.Series(gain).rolling(14, min_periods=14).mean().to_numpy()
    avg_l = pd.Series(loss).rolling(14, min_periods=14).mean().to_numpy()
    rs = np.where(avg_l > 0, avg_g / np.maximum(avg_l, 1e-9), 100)
    F[:, 6] = np.where(np.isfinite(rs), 100 - 100 / (1 + rs), 50)

    # vol_ratio: vol[i] / mean(vol[i-23:i+1])
    vol_ma24 = pd.Series(vols).rolling(24, min_periods=24).mean().to_numpy()
    F[:, 7] = np.where(vol_ma24 > 0, vols / np.maximum(vol_ma24, 1e-9), 1)

    # vol_trend: mean(last6) / mean(prev18) - 1
    vol_ma6 = pd.Series(vols).rolling(6, min_periods=6).mean().to_numpy()
    vol_prev18_mean = (pd.Series(vols).rolling(24, min_periods=24).sum().to_numpy() - pd.Series(vols).rolling(6, min_periods=6).sum().to_numpy()) / 18
    F[:, 8] = np.where(vol_prev18_mean > 0, vol_ma6 / np.maximum(vol_prev18_mean, 1e-9) - 1, 0)

    # slope of log-prices over 24
    logp = np.log(np.maximum(closes, 1e-9))
    x = np.arange(24)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    # rolling slope
    slopes = np.zeros(n, dtype=np.float32)
    for i in range(23, n):
        y = logp[i - 23 : i + 1]
        slopes[i] = ((x - x_mean) * (y - y.mean())).sum() / x_var
    F[:, 9] = slopes

    return F


def build_labels_vec(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each entry index i (using opens[i] as entry), look ahead HORIZON_BARS bars (i..i+H-1).
    Returns (labels, valid_mask). label=1 if TP hit before SL within horizon."""
    n = len(opens)
    labels = np.zeros(n, dtype=np.int8)
    valid = np.zeros(n, dtype=bool)
    for i in range(n - HORIZON_BARS):
        entry = opens[i]
        if entry <= 0:
            continue
        tp = entry * (1 + TP_PCT)
        sl = entry * (1 + SL_PCT)
        fut_low = lows[i : i + HORIZON_BARS]
        fut_high = highs[i : i + HORIZON_BARS]
        # find first bar where SL or TP triggers
        sl_hit = np.argmax(fut_low <= sl) if (fut_low <= sl).any() else -1
        tp_hit = np.argmax(fut_high >= tp) if (fut_high >= tp).any() else -1
        valid[i] = True
        if tp_hit == -1 and sl_hit == -1:
            labels[i] = 0
        elif tp_hit == -1:
            labels[i] = 0
        elif sl_hit == -1:
            labels[i] = 1
        else:
            labels[i] = 1 if tp_hit < sl_hit else 0
    return labels, valid


FEATURE_NAMES = ["ret_1", "ret_6", "ret_24", "vol", "pos_in_range",
                 "macd_diff", "rsi", "vol_ratio", "vol_trend", "slope"]


def build_dataset() -> pd.DataFrame:
    frames = []
    for csv_path in sorted(CANDLES_DIR.glob("*_1h.csv")):
        market = csv_path.stem.replace("_1h", "")
        df = pd.read_csv(csv_path).sort_values("ts_ms").reset_index(drop=True)
        if len(df) < LOOKBACK + HORIZON_BARS + 1:
            continue
        closes = df["close"].to_numpy(dtype=np.float64)
        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)
        opens = df["open"].to_numpy(dtype=np.float64)
        vols = df["volume"].to_numpy(dtype=np.float64)
        ts = df["ts_ms"].to_numpy(dtype=np.int64)

        F = build_features_vec(closes, highs, lows, vols)
        # entry-bar features = bar i-1's features (so we don't peek at bar i's open)
        # We use bar i-1 indicators to decide "buy at bar i open"
        labels, valid = build_labels_vec(opens, highs, lows)

        # Index alignment: entry index i uses features from i-1 (no leakage), buys opens[i], measures future i..i+H-1
        keep = np.zeros(len(df), dtype=bool)
        keep[LOOKBACK : len(df) - HORIZON_BARS] = True
        keep &= valid
        idx = np.where(keep)[0]
        if len(idx) == 0:
            continue

        feats = F[idx - 1]
        sub = pd.DataFrame(feats, columns=FEATURE_NAMES)
        sub["market"] = market
        sub["ts_ms"] = ts[idx]
        sub["entry"] = opens[idx]
        sub["label"] = labels[idx]
        frames.append(sub)
        print(f"  {market}: {len(sub)} samples (label-rate={sub['label'].mean():.3f})", flush=True)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ─── Backtest helper ─────────────────────────────────────────────────────
def simulate_pnl(df_test: pd.DataFrame, decisions: np.ndarray) -> dict:
    """decisions: 1=take trade, 0=skip. Returns aggregate PnL."""
    taken = df_test[decisions == 1]
    if len(taken) == 0:
        return {"trades": 0, "pnl_eur": 0.0, "win_rate": 0.0, "avg_pnl_eur": 0.0}
    # PnL per trade: TP -> +1.5% - fees, SL -> -2.0% - fees
    pnl_per = np.where(taken["label"].to_numpy() == 1, TP_PCT - FEE_PCT, SL_PCT - FEE_PCT)
    pnl_eur = pnl_per * TRADE_SIZE_EUR
    return {
        "trades": int(len(taken)),
        "pnl_eur": float(pnl_eur.sum()),
        "win_rate": float((taken["label"] == 1).mean()),
        "avg_pnl_eur": float(pnl_eur.mean()),
    }


# ─── Main ────────────────────────────────────────────────────────────────
def main():
    print("Building dataset from historical candles ...")
    ds = build_dataset()
    print(f"Total samples: {len(ds)}, label dist: {ds['label'].value_counts().to_dict()}")
    if len(ds) < 1000:
        print("Not enough samples — abort.")
        return

    feature_cols = [c for c in ds.columns if c not in ("market", "ts_ms", "entry", "label")]
    ds = ds.sort_values("ts_ms").reset_index(drop=True)

    # Time-series split
    n = len(ds)
    n_train = int(n * 0.70)
    n_calib = int(n * 0.15)
    train = ds.iloc[:n_train]
    calib = ds.iloc[n_train : n_train + n_calib]
    test = ds.iloc[n_train + n_calib :]

    print(f"\nSplit — train: {len(train)}, calib: {len(calib)}, test: {len(test)}")
    print(f"Train period: {pd.to_datetime(train['ts_ms'].min(), unit='ms')} .. {pd.to_datetime(train['ts_ms'].max(), unit='ms')}")
    print(f"Test period:  {pd.to_datetime(test['ts_ms'].min(), unit='ms')} .. {pd.to_datetime(test['ts_ms'].max(), unit='ms')}")

    # Train XGBoost
    from xgboost import XGBClassifier
    pos_weight = (train["label"] == 0).sum() / max((train["label"] == 1).sum(), 1)
    model = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=pos_weight,
        eval_metric="logloss", n_jobs=-1, random_state=42,
    )
    model.fit(train[feature_cols], train["label"])

    # Baseline strategy: predict_proba >= 0.5 → take trade
    test_proba = model.predict_proba(test[feature_cols])[:, 1]
    baseline_decisions = (test_proba >= 0.5).astype(int)
    base_stats = simulate_pnl(test, baseline_decisions)

    # Take-all (no model) baseline
    take_all_stats = simulate_pnl(test, np.ones(len(test), dtype=int))

    # Conformal wrap — manual Split Conformal Prediction (LAC score)
    # Reference: Vovk et al., "Algorithmic Learning in a Random World"
    # LAC nonconformity score: s(x, y) = 1 - p_hat(y | x)
    # For each calib sample, compute s_i = 1 - p_hat(y_true_i | x_i)
    # Quantile q = ceil((n+1)(1-alpha)) / n  of {s_i}
    # Prediction set for x_test: { y : 1 - p_hat(y | x_test) <= q }
    print("\nFitting Split Conformal Predictor (LAC, manual implementation) ...")
    alpha = 0.10  # target miscoverage = 10%, i.e. 90% coverage

    calib_proba = model.predict_proba(calib[feature_cols])
    calib_y = calib["label"].to_numpy()
    # nonconformity = 1 - prob assigned to the TRUE label
    calib_scores = 1.0 - calib_proba[np.arange(len(calib_y)), calib_y]
    n_cal = len(calib_scores)
    q_level = np.ceil((n_cal + 1) * (1 - alpha)) / n_cal
    q_level = min(q_level, 1.0)
    q_hat = np.quantile(calib_scores, q_level, method="higher")
    print(f"  Calibration n={n_cal}, q_level={q_level:.4f}, q_hat={q_hat:.4f}")

    # For each test sample, build prediction set: which classes have score <= q_hat
    test_proba = model.predict_proba(test[feature_cols])
    # ps[i, c] = True if class c is in prediction set for sample i
    test_scores = 1.0 - test_proba   # shape (n_test, 2)
    ps = (test_scores <= q_hat)      # bool array

    # Empirical coverage check
    test_y = test["label"].to_numpy()
    coverage = ps[np.arange(len(test_y)), test_y].mean()
    print(f"  Empirical coverage on test (target {1-alpha:.0%}): {coverage:.3f}")
    # Confident-buy: prediction set is {1} only (i.e., set excludes 0)
    set_has_0 = ps[:, 0].astype(bool)
    set_has_1 = ps[:, 1].astype(bool)
    conformal_buy = (set_has_1 & ~set_has_0).astype(int)
    # Also try: any time 1 is in set → buy
    conformal_buy_loose = set_has_1.astype(int)

    cof_stats = simulate_pnl(test, conformal_buy)
    cof_loose_stats = simulate_pnl(test, conformal_buy_loose)

    # Probability-threshold sweep (find profitable subset, if any)
    test_proba_pos = test_proba[:, 1]
    threshold_results = {}
    for thr in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        decisions = (test_proba_pos >= thr).astype(int)
        threshold_results[f"proba>={thr:.2f}"] = simulate_pnl(test, decisions)

    print("\n" + "=" * 75)
    print("BACKTEST RESULTS  (test period, walk-forward)")
    print("=" * 75)
    print(f"Test universe : {len(test)} entry opportunities across {ds['market'].nunique()} markets")
    print(f"Trade size    : EUR{TRADE_SIZE_EUR}, fee {FEE_PCT*100:.2f}%, TP {TP_PCT*100:.1f}%, SL {SL_PCT*100:.1f}%")
    print()
    print(f"{'Strategy':<35} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>11}")
    print("-" * 75)
    for label, s in [
        ("1. Take EVERY signal (no AI)", take_all_stats),
        ("2. XGBoost only (proba>=0.5)", base_stats),
        ("3. Conformal STRICT ({1} only)", cof_stats),
        ("4. Conformal LOOSE (1 in set)", cof_loose_stats),
    ]:
        print(f"{label:<35} {s['trades']:>7} {s['win_rate']*100:>7.1f}% EUR{s['avg_pnl_eur']:>+7.3f} EUR{s['pnl_eur']:>+9.2f}")
    print()

    print("Probability-threshold sweep:")
    print(f"{'Threshold':<35} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>11}")
    print("-" * 75)
    for label, s in threshold_results.items():
        print(f"{label:<35} {s['trades']:>7} {s['win_rate']*100:>7.1f}% EUR{s['avg_pnl_eur']:>+7.3f} EUR{s['pnl_eur']:>+9.2f}")
    print()

    # Annualize: how much PnL per €1000 deployed per year?
    test_days = (test["ts_ms"].max() - test["ts_ms"].min()) / 86_400_000
    print(f"Test window   : {test_days:.1f} days")
    for label, s in [
        ("Take all", take_all_stats),
        ("XGB only", base_stats),
        ("Conformal strict", cof_stats),
        ("Conformal loose", cof_loose_stats),
    ]:
        if s["trades"] == 0:
            continue
        roi = s["pnl_eur"] / (s["trades"] * TRADE_SIZE_EUR) * 100
        annualized = (s["pnl_eur"] / test_days * 365) if test_days > 0 else 0
        print(f"  {label:<22} ROI={roi:+.2f}%  annual_EUR={annualized:+.0f}")

    # Save model + meta
    model.save_model(str(MODEL_OUT))
    meta = {
        "feature_cols": feature_cols,
        "fee_pct": FEE_PCT, "tp_pct": TP_PCT, "sl_pct": SL_PCT,
        "horizon_bars": HORIZON_BARS, "lookback": LOOKBACK,
        "trained_samples": int(len(train)),
        "calib_samples": int(len(calib)),
        "test_samples": int(len(test)),
        "alpha": alpha,
        "q_hat": float(q_hat),
        "empirical_coverage": float(coverage),
        "results": {
            "take_all": take_all_stats,
            "xgb_only": base_stats,
            "conformal_strict": cof_stats,
            "conformal_loose": cof_loose_stats,
            "threshold_sweep": threshold_results,
        },
    }
    with META_OUT.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"\nModel saved: {MODEL_OUT.name}\nMeta saved : {META_OUT.name}")


if __name__ == "__main__":
    main()
