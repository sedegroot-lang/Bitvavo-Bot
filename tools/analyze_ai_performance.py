#!/usr/bin/env python3
"""
Comprehensive AI/RL/LSTM Performance Analysis
Analyzes ensemble predictions, RL Q-values, and model accuracy
"""
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

print("🤖 AI/ML/RL PERFORMANCE ANALYSIS")
print("="*70)

# Load trade archive
try:
    with open(PROJECT_ROOT / 'data' / 'trade_archive.json', 'r') as f:
        archive = json.load(f)
    trades = archive['trades'][-100:]  # Last 100 trades
    print(f"\n📊 Analyzing last {len(trades)} trades")
except Exception as e:
    print(f"❌ Could not load trade archive: {e}")
    trades = []

# Analyze XGBoost predictions
try:
    with open(PROJECT_ROOT / 'ai' / 'ai_model_metrics.json', 'r') as f:
        xgb_metrics = json.load(f)
    print(f"\n📈 XGBoost Model Metrics:")
    print(f"  Accuracy: {xgb_metrics.get('accuracy', 0)*100:.1f}%")
    print(f"  Precision: {xgb_metrics.get('precision', 0)*100:.1f}%")
    print(f"  Recall: {xgb_metrics.get('recall', 0)*100:.1f}%")
    print(f"  F1 Score: {xgb_metrics.get('f1', 0)*100:.1f}%")
    trained_at = xgb_metrics.get('trained_at', 0)
    if trained_at:
        days_ago = (datetime.now().timestamp() - trained_at) / 86400
        print(f"  Last trained: {days_ago:.1f} days ago")
except Exception as e:
    print(f"\n⚠️  XGBoost metrics not available: {e}")

# Check LSTM model
lstm_model = PROJECT_ROOT / 'models' / 'lstm_price_model.h5'
if lstm_model.exists():
    import os
    size_mb = os.path.getsize(lstm_model) / 1024 / 1024
    mtime = datetime.fromtimestamp(os.path.getmtime(lstm_model))
    print(f"\n🧠 LSTM Model:")
    print(f"  Status: ✅ Trained")
    print(f"  Size: {size_mb:.1f} MB")
    print(f"  Last updated: {mtime.strftime('%Y-%m-%d %H:%M')}")
else:
    print(f"\n🧠 LSTM Model: ❌ Not trained yet")

# Analyze RL agent
try:
    with open(PROJECT_ROOT / 'modules' / 'rl_q_table.json', 'r') as f:
        rl_data = json.load(f)
    q_table = rl_data.get('q_table', {})
    print(f"\n🎮 RL Agent (Q-Learning):")
    print(f"  States learned: {len(q_table)}")
    if q_table:
        avg_q_buy = []
        avg_q_hold = []
        for state, actions in q_table.items():
            if isinstance(actions, dict):
                avg_q_buy.append(actions.get('BUY', 0))
                avg_q_hold.append(actions.get('HOLD', 0))
        if avg_q_buy:
            print(f"  Avg Q(BUY): {sum(avg_q_buy)/len(avg_q_buy):.3f}")
            print(f"  Avg Q(HOLD): {sum(avg_q_hold)/len(avg_q_hold):.3f}")
        
    episode = rl_data.get('episode', 0)
    total_reward = rl_data.get('total_reward', 0)
    print(f"  Episodes: {episode}")
    print(f"  Total reward: {total_reward:.2f}")
except Exception as e:
    print(f"\n🎮 RL Agent: ⚠️  Data not available ({e})")

# Analyze market-specific performance
market_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0, 'trades': 0})
for trade in trades:
    market = trade.get('market', 'UNKNOWN')
    profit = trade.get('profit', 0)
    market_stats[market]['trades'] += 1
    market_stats[market]['profit'] += profit
    if profit > 0:
        market_stats[market]['wins'] += 1
    else:
        market_stats[market]['losses'] += 1

print(f"\n📊 Top 5 Markets by Win Rate (min 5 trades):")
qualified = {m: s for m, s in market_stats.items() if s['trades'] >= 5}
if qualified:
    sorted_markets = sorted(qualified.items(), 
                           key=lambda x: x[1]['wins']/x[1]['trades'], 
                           reverse=True)[:5]
    for market, stats in sorted_markets:
        wr = stats['wins']/stats['trades']*100
        print(f"  {market}: {wr:.0f}% WR ({stats['wins']}/{stats['trades']}) P/L: €{stats['profit']:.2f}")
else:
    print("  No markets with >=5 trades")

print(f"\n🔥 Worst 5 Markets (most losses):")
sorted_worst = sorted(market_stats.items(), key=lambda x: x[1]['profit'])[:5]
for market, stats in sorted_worst:
    wr = stats['wins']/stats['trades']*100 if stats['trades'] > 0 else 0
    print(f"  {market}: €{stats['profit']:.2f} ({stats['wins']}/{stats['trades']}, {wr:.0f}% WR)")

# Load current config
try:
    with open(PROJECT_ROOT / 'config' / 'bot_config.json', 'r') as f:
        config = json.load(f)
    print(f"\n⚙️  Current AI Configuration:")
    print(f"  USE_LSTM: {config.get('USE_LSTM', False)}")
    print(f"  USE_RL_AGENT: {config.get('USE_RL_AGENT', False)}")
    print(f"  RL_ENABLED: {config.get('RL_ENABLED', False)}")
    print(f"  RL_TRAINING_MODE: {config.get('RL_TRAINING_MODE', False)}")
    print(f"  AI_AUTO_RETRAIN_ENABLED: {config.get('AI_AUTO_RETRAIN_ENABLED', False)}")
    print(f"  AI_RETRAIN_INTERVAL_DAYS: {config.get('AI_RETRAIN_INTERVAL_DAYS', 7)}")
    
    print(f"\n💰 Position Sizing:")
    print(f"  BASE_AMOUNT_EUR: €{config.get('BASE_AMOUNT_EUR', 10)}")
    print(f"  MAX_OPEN_TRADES: {config.get('MAX_OPEN_TRADES', 4)}")
    print(f"  MAX_TOTAL_EXPOSURE_EUR: €{config.get('MAX_TOTAL_EXPOSURE_EUR', 80)}")
    
    print(f"\n🛡️  Risk Management:")
    print(f"  HARD_SL_ALT_PCT: {config.get('HARD_SL_ALT_PCT', 0.025)*100:.1f}%")
    print(f"  DEFAULT_TRAILING: {config.get('DEFAULT_TRAILING', 0.09)*100:.1f}%")
    print(f"  TRAILING_ACTIVATION_PCT: {config.get('TRAILING_ACTIVATION_PCT', 0.01)*100:.1f}%")
    print(f"  DCA_DROP_PCT: {config.get('DCA_DROP_PCT', 0.06)*100:.1f}%")
    print(f"  DCA_MAX_BUYS: {config.get('DCA_MAX_BUYS', 2)}")
    
except Exception as e:
    print(f"⚠️  Could not load config: {e}")

print(f"\n{'='*70}")
print("✅ Analysis complete")
