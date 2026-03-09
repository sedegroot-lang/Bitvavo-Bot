"""Generate ML training data from trade archive.

Reads data/trade_archive.json + data/trade_log.json and creates a proper
training CSV with real features (where available) for XGBoost retraining.

Usage:
    python scripts/ml/generate_training_from_archive.py
"""

import json
import csv
import os
import time
from pathlib import Path

ARCHIVE_FILE = "data/trade_archive.json"
TRADE_LOG_FILE = "data/trade_log.json"
OUTPUT_CSV = "trade_features.csv"
OUTPUT_ENHANCED = "ai/training_data/archive_training_data.csv"

def load_all_closed_trades() -> list:
    """Load all closed trades from both archive and trade_log."""
    trades = []
    
    # Load archive
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        archive_trades = data.get("trades", []) if isinstance(data, dict) else data
        trades.extend(archive_trades)
    
    # Load trade_log closed
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        closed = data.get("closed", []) if isinstance(data, dict) else []
        # De-duplicate by (market, timestamp)
        archive_keys = {(t.get("market", ""), round(t.get("timestamp", 0), 1)) for t in trades}
        for t in closed:
            key = (t.get("market", ""), round(t.get("timestamp", 0), 1))
            if key not in archive_keys:
                trades.append(t)
    
    return trades


def classify_trade(trade: dict) -> int:
    """Classify trade outcome: 1=profitable (BUY signal was correct), 0=loss."""
    profit = float(trade.get("profit", 0) or 0)
    reason = trade.get("reason", "")
    
    # Bug-related closes are not representative of signal quality
    if reason in ("saldo_flood_guard", "saldo_error", "sync_removed"):
        return -1  # Skip
    
    return 1 if profit > 0 else 0


def extract_features(trade: dict) -> dict:
    """Extract ML features from a trade record."""
    features = {}
    
    # Price-based features (always available)
    buy_price = float(trade.get("buy_price", 0) or 0)
    sell_price = float(trade.get("sell_price", 0) or 0)
    
    if buy_price <= 0:
        return None
    
    # Return percentage
    features["return_pct"] = ((sell_price - buy_price) / buy_price * 100) if sell_price > 0 else 0
    
    # Hold duration
    opened = float(trade.get("opened_ts", trade.get("timestamp", 0)) or 0)
    closed_ts = float(trade.get("timestamp", 0) or 0)
    if opened > 0 and closed_ts > opened:
        features["hold_hours"] = (closed_ts - opened) / 3600
    else:
        features["hold_hours"] = 0
    
    # DCA info
    features["dca_buys"] = int(trade.get("dca_buys", 0) or 0)
    
    # Entry metadata (stored at buy time - newer trades have these)
    features["score"] = float(trade.get("score", 0) or 0)
    features["rsi_at_entry"] = float(trade.get("rsi_at_entry", 50) or 50)
    features["volatility"] = float(trade.get("volatility_at_entry", 0) or 0)
    features["volume_24h"] = float(trade.get("volume_24h_eur", 0) or 0)
    features["macd_at_entry"] = float(trade.get("macd_at_entry", 0) or 0)
    features["sma_short"] = float(trade.get("sma_short_at_entry", 0) or 0)
    features["sma_long"] = float(trade.get("sma_long_at_entry", 0) or 0)
    
    # Regime
    regime = trade.get("opened_regime", "unknown")
    features["regime_aggressive"] = 1 if regime == "aggressive" else 0
    features["regime_defensive"] = 1 if regime == "defensive" else 0
    
    # Invested amount (proxy for confidence)
    features["invested_eur"] = float(trade.get("invested_eur", 0) or 0)
    
    # Max profit seen (how high did it go before close)
    max_profit_pct = float(trade.get("max_profit_pct", 0) or 0)
    features["max_profit_pct"] = max_profit_pct
    
    # Market encoding (one-hot for top markets)
    features["market"] = trade.get("market", "UNKNOWN")
    
    return features


def generate_basic_csv(trades: list) -> int:
    """Generate basic training CSV compatible with existing XGBoost pipeline."""
    rows = []
    for t in trades:
        label = classify_trade(t)
        if label < 0:
            continue
        
        feats = extract_features(t)
        if feats is None:
            continue
        
        rows.append({
            "rsi": feats["rsi_at_entry"],
            "macd": feats["macd_at_entry"],
            "sma_short": feats["sma_short"] if feats["sma_short"] > 0 else float(t.get("buy_price", 0) or 0),
            "sma_long": feats["sma_long"] if feats["sma_long"] > 0 else float(t.get("buy_price", 0) or 0),
            "volume": feats["volume_24h"],
            "label": label,
        })
    
    if not rows:
        print("No valid trades for basic CSV")
        return 0
    
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rsi", "macd", "sma_short", "sma_long", "volume", "label"])
        writer.writeheader()
        writer.writerows(rows)
    
    return len(rows)


def generate_enhanced_csv(trades: list) -> int:
    """Generate enhanced training CSV with all available features."""
    rows = []
    for t in trades:
        label = classify_trade(t)
        if label < 0:
            continue
        
        feats = extract_features(t)
        if feats is None:
            continue
        
        row = {
            "market": feats["market"],
            "score": feats["score"],
            "rsi_at_entry": feats["rsi_at_entry"],
            "macd_at_entry": feats["macd_at_entry"],
            "sma_short": feats["sma_short"],
            "sma_long": feats["sma_long"],
            "volatility": feats["volatility"],
            "volume_24h": feats["volume_24h"],
            "dca_buys": feats["dca_buys"],
            "invested_eur": feats["invested_eur"],
            "hold_hours": round(feats["hold_hours"], 2),
            "max_profit_pct": feats["max_profit_pct"],
            "regime_aggressive": feats["regime_aggressive"],
            "regime_defensive": feats["regime_defensive"],
            "return_pct": round(feats["return_pct"], 4),
            "label": label,
        }
        rows.append(row)
    
    if not rows:
        print("No valid trades for enhanced CSV")
        return 0
    
    os.makedirs(os.path.dirname(OUTPUT_ENHANCED), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(OUTPUT_ENHANCED, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return len(rows)


def main():
    print("=== ML Training Data Generator ===")
    trades = load_all_closed_trades()
    print(f"Total closed trades loaded: {len(trades)}")
    
    # Stats
    by_reason = {}
    for t in trades:
        r = t.get("reason", "unknown")
        by_reason[r] = by_reason.get(r, 0) + 1
    print("By reason:", dict(sorted(by_reason.items(), key=lambda x: -x[1])))
    
    # Generate CSVs
    basic_count = generate_basic_csv(trades)
    print(f"Basic CSV ({OUTPUT_CSV}): {basic_count} rows")
    
    enhanced_count = generate_enhanced_csv(trades)
    print(f"Enhanced CSV ({OUTPUT_ENHANCED}): {enhanced_count} rows")
    
    # Feature quality report
    has_real_features = sum(1 for t in trades 
                          if t.get("score") or t.get("rsi_at_entry") or t.get("macd_at_entry"))
    print(f"\nFeature quality: {has_real_features}/{len(trades)} trades have real indicator data")
    if has_real_features < len(trades) * 0.5:
        print("NOTE: Most trades lack real features (stored before metadata tracking).")
        print("      New trades will have full features. Retrain after accumulating ~200 feature-rich trades.")
    
    print("\nDone!")


if __name__ == "__main__":
    main()
