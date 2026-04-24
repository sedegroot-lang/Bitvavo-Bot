"""
Variant of train_conformal_supervisor.py — Option B.

Instead of treating EVERY 1h bar as a candidate entry (the original blind
universe of 32k samples), this script first applies a 'bot-trigger proxy':
only bars that meet realistic buy conditions (the kind that would have
fired the bot's signal-pack) are used as candidates. Then the same
XGBoost + Split-Conformal pipeline is trained and backtested on that
much smaller, much more realistic universe.

Trigger proxy (bar i triggers a buy if 4 of 6 hold):
  - RSI in [40, 65]            -> not overbought
  - MACD diff > 0              -> bullish momentum
  - ret_6 > 0                  -> last 6h positive
  - vol_ratio > 1.05           -> above-avg volume
  - 0.30 < pos_in_range < 0.85 -> mid-range, not at extremes
  - slope > 0                  -> upward trend

Goal: see whether Conformal Prediction is profitable on the subset of bars
where the bot actually would have considered entering.
"""
from __future__ import annotations
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse all helpers from the base script
from scripts.train_conformal_supervisor import (  # noqa: E402
    FEE_PCT,
    TP_PCT,
    SL_PCT,
    HORIZON_BARS,
    LOOKBACK,
    TRADE_SIZE_EUR,
    FEATURE_NAMES,
    build_dataset,
    simulate_pnl,
)

MODEL_OUT = ROOT / "ai" / "conformal_signalfilter.json"
META_OUT = ROOT / "ai" / "conformal_signalfilter_meta.json"


def trigger_mask(df: pd.DataFrame) -> np.ndarray:
    """Return boolean array: True where row meets >=4 of 6 buy conditions."""
    rsi = df["rsi"].to_numpy()
    macd = df["macd_diff"].to_numpy()
    ret6 = df["ret_6"].to_numpy()
    vr = df["vol_ratio"].to_numpy()
    pos = df["pos_in_range"].to_numpy()
    slope = df["slope"].to_numpy()

    c1 = (rsi >= 40) & (rsi <= 65)
    c2 = macd > 0
    c3 = ret6 > 0
    c4 = vr > 1.05
    c5 = (pos > 0.30) & (pos < 0.85)
    c6 = slope > 0
    score = c1.astype(int) + c2.astype(int) + c3.astype(int) + c4.astype(int) + c5.astype(int) + c6.astype(int)
    return score >= 4


def main():
    print("Building dataset from historical candles ...", flush=True)
    ds = build_dataset()
    print(f"Total raw samples: {len(ds)}", flush=True)
    if len(ds) < 1000:
        print("Not enough samples — abort.")
        return

    mask = trigger_mask(ds)
    ds_f = ds[mask].reset_index(drop=True)
    print(
        f"After bot-trigger filter: {len(ds_f)} samples "
        f"({len(ds_f) / max(len(ds), 1) * 100:.1f}% of universe)",
        flush=True,
    )
    if len(ds_f) < 500:
        print("Not enough triggered samples — abort.")
        return

    print(f"Filtered label dist: {ds_f['label'].value_counts().to_dict()}", flush=True)
    base_winrate = ds_f["label"].mean()
    # Expected EV per trade if we take ALL filtered signals
    ev_takeall = base_winrate * (TP_PCT - FEE_PCT) + (1 - base_winrate) * (SL_PCT - FEE_PCT)
    print(f"Filtered base win-rate: {base_winrate*100:.2f}%  EV/trade(€): {ev_takeall*TRADE_SIZE_EUR:+.4f}", flush=True)
    # Break-even win-rate
    be_wr = (-(SL_PCT - FEE_PCT)) / ((TP_PCT - FEE_PCT) - (SL_PCT - FEE_PCT))
    print(f"Break-even win-rate needed: {be_wr*100:.2f}%", flush=True)

    feature_cols = list(FEATURE_NAMES)
    ds_f = ds_f.sort_values("ts_ms").reset_index(drop=True)

    n = len(ds_f)
    n_train = int(n * 0.70)
    n_calib = int(n * 0.15)
    train = ds_f.iloc[:n_train]
    calib = ds_f.iloc[n_train : n_train + n_calib]
    test = ds_f.iloc[n_train + n_calib :]

    print(f"\nSplit -- train: {len(train)}, calib: {len(calib)}, test: {len(test)}", flush=True)
    print(
        f"Train period: {pd.to_datetime(train['ts_ms'].min(), unit='ms')} .. "
        f"{pd.to_datetime(train['ts_ms'].max(), unit='ms')}",
        flush=True,
    )
    print(
        f"Test period : {pd.to_datetime(test['ts_ms'].min(), unit='ms')} .. "
        f"{pd.to_datetime(test['ts_ms'].max(), unit='ms')}",
        flush=True,
    )

    from xgboost import XGBClassifier

    pos_weight = (train["label"] == 0).sum() / max((train["label"] == 1).sum(), 1)
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=pos_weight,
        eval_metric="logloss",
        n_jobs=-1,
        random_state=42,
    )
    model.fit(train[feature_cols], train["label"])

    test_proba_all = model.predict_proba(test[feature_cols])
    test_proba_pos = test_proba_all[:, 1]

    take_all_stats = simulate_pnl(test, np.ones(len(test), dtype=int))
    base_stats = simulate_pnl(test, (test_proba_pos >= 0.5).astype(int))

    # Manual Split Conformal LAC
    alpha = 0.10
    calib_proba = model.predict_proba(calib[feature_cols])
    calib_y = calib["label"].to_numpy()
    calib_scores = 1.0 - calib_proba[np.arange(len(calib_y)), calib_y]
    n_cal = len(calib_scores)
    q_level = min(np.ceil((n_cal + 1) * (1 - alpha)) / n_cal, 1.0)
    q_hat = float(np.quantile(calib_scores, q_level, method="higher"))

    test_scores_mat = 1.0 - test_proba_all
    ps = test_scores_mat <= q_hat
    test_y = test["label"].to_numpy()
    coverage = float(ps[np.arange(len(test_y)), test_y].mean())

    set_has_0 = ps[:, 0]
    set_has_1 = ps[:, 1]
    cof_strict = simulate_pnl(test, (set_has_1 & ~set_has_0).astype(int))
    cof_loose = simulate_pnl(test, set_has_1.astype(int))

    threshold_results = {}
    for thr in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        decisions = (test_proba_pos >= thr).astype(int)
        threshold_results[f"proba>={thr:.2f}"] = simulate_pnl(test, decisions)

    test_days = (test["ts_ms"].max() - test["ts_ms"].min()) / 86_400_000

    print("\n" + "=" * 78)
    print("BACKTEST RESULTS  (bot-trigger filtered universe, walk-forward)")
    print("=" * 78)
    print(f"Test universe : {len(test)} entries across {ds_f['market'].nunique()} markets, {test_days:.1f} days")
    print(f"Trade size    : EUR{TRADE_SIZE_EUR}, fee {FEE_PCT*100:.2f}%, TP {TP_PCT*100:.1f}%, SL {SL_PCT*100:.1f}%")
    print(f"Calibration   : n={n_cal}, q_hat={q_hat:.4f}, empirical coverage={coverage:.3f} (target {1-alpha:.0%})")
    print()
    print(f"{'Strategy':<35} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>11}")
    print("-" * 78)
    rows = [
        ("1. Take EVERY filtered signal", take_all_stats),
        ("2. XGBoost gate (proba>=0.5)", base_stats),
        ("3. Conformal STRICT ({1} only)", cof_strict),
        ("4. Conformal LOOSE (1 in set)", cof_loose),
    ]
    for label, s in rows:
        print(
            f"{label:<35} {s['trades']:>7} {s['win_rate']*100:>7.1f}% "
            f"EUR{s['avg_pnl_eur']:>+7.3f} EUR{s['pnl_eur']:>+9.2f}"
        )

    print("\nProbability-threshold sweep:")
    print(f"{'Threshold':<35} {'Trades':>7} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>11}")
    print("-" * 78)
    for label, s in threshold_results.items():
        print(
            f"{label:<35} {s['trades']:>7} {s['win_rate']*100:>7.1f}% "
            f"EUR{s['avg_pnl_eur']:>+7.3f} EUR{s['pnl_eur']:>+9.2f}"
        )

    print("\nAnnualised:")
    for label, s in rows + [(k, v) for k, v in threshold_results.items()]:
        if s["trades"] == 0:
            continue
        roi = s["pnl_eur"] / (s["trades"] * TRADE_SIZE_EUR) * 100
        ann = (s["pnl_eur"] / test_days * 365) if test_days > 0 else 0
        print(f"  {label:<35} ROI={roi:+.2f}%  annual=EUR{ann:+.0f}")

    model.save_model(str(MODEL_OUT))
    meta = {
        "trigger": "bot-proxy: 4 of 6 (RSI 40-65, MACD>0, ret6>0, vol>1.05, mid-range, slope>0)",
        "feature_cols": feature_cols,
        "fee_pct": FEE_PCT,
        "tp_pct": TP_PCT,
        "sl_pct": SL_PCT,
        "horizon_bars": HORIZON_BARS,
        "lookback": LOOKBACK,
        "raw_samples": int(len(ds)),
        "filtered_samples": int(len(ds_f)),
        "filter_rate": float(len(ds_f) / max(len(ds), 1)),
        "filtered_base_winrate": float(base_winrate),
        "break_even_winrate": float(be_wr),
        "trained_samples": int(len(train)),
        "calib_samples": int(len(calib)),
        "test_samples": int(len(test)),
        "test_days": float(test_days),
        "alpha": alpha,
        "q_hat": q_hat,
        "empirical_coverage": coverage,
        "results": {
            "take_all_filtered": take_all_stats,
            "xgb_only": base_stats,
            "conformal_strict": cof_strict,
            "conformal_loose": cof_loose,
            "threshold_sweep": threshold_results,
        },
    }
    with META_OUT.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"\nModel saved: {MODEL_OUT.name}")
    print(f"Meta saved : {META_OUT.name}")


if __name__ == "__main__":
    main()
