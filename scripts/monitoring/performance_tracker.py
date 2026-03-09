#!/usr/bin/env python3
"""
Performance Monitor - Track Win Rate, Avg Profit, ROI
Monitors 30-40 trades with new optimized settings
Target: 40%+ win rate Week 1, 47-52% win rate Month 1
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
TRADE_LOG = BASE_DIR / "data" / "trade_log.json"
PERF_LOG = BASE_DIR / "data" / "performance_tracking.jsonl"
DEPOSITS = BASE_DIR / "config" / "deposits.json"

def load_trade_log() -> Dict:
    """Load trade log data."""
    with TRADE_LOG.open('r', encoding='utf-8') as f:
        return json.load(f)

def get_recent_closed_trades(days: int = 7) -> List[Dict]:
    """Get closed trades from last N days."""
    data = load_trade_log()
    closed = data.get('closed', [])
    
    cutoff = datetime.now().timestamp() - (days * 86400)
    recent = [t for t in closed if t.get('timestamp', 0) > cutoff]
    
    return sorted(recent, key=lambda x: x.get('timestamp', 0))

def calculate_metrics(trades: List[Dict]) -> Dict:
    """Calculate performance metrics for given trades."""
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'avg_profit': 0.0,
            'avg_loss': 0.0,
            'total_pnl': 0.0,
            'profit_factor': 0.0,
            'expectancy': 0.0
        }
    
    wins = [t for t in trades if t.get('profit', 0) > 0]
    losses = [t for t in trades if t.get('profit', 0) <= 0]
    
    total_win = sum(t.get('profit', 0) for t in wins)
    total_loss = abs(sum(t.get('profit', 0) for t in losses))
    
    win_rate = len(wins) / len(trades) * 100
    avg_profit = total_win / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 0
    total_pnl = sum(t.get('profit', 0) for t in trades)
    profit_factor = total_win / total_loss if total_loss > 0 else float('inf')
    expectancy = (win_rate/100 * avg_profit) - ((1-win_rate/100) * avg_loss)
    
    return {
        'total_trades': len(trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 1),
        'avg_profit': round(avg_profit, 2),
        'avg_loss': round(avg_loss, 2),
        'total_pnl': round(total_pnl, 2),
        'profit_factor': round(profit_factor, 2),
        'expectancy': round(expectancy, 2)
    }

def get_baseline_metrics() -> Dict:
    """Get baseline metrics from all historical trades."""
    data = load_trade_log()
    closed = data.get('closed', [])
    return calculate_metrics(closed)

def get_optimization_date() -> float:
    """Get timestamp when optimization was applied (today)."""
    # Check config backup file modification time
    config_backup = list(BASE_DIR.glob("config/bot_config.json.backup_*"))
    if config_backup:
        latest = max(config_backup, key=lambda p: p.stat().st_mtime)
        return latest.stat().st_mtime
    return datetime.now().timestamp()

def log_performance_snapshot():
    """Log current performance snapshot to JSONL."""
    baseline = get_baseline_metrics()
    recent_7d = calculate_metrics(get_recent_closed_trades(7))
    recent_24h = calculate_metrics(get_recent_closed_trades(1))
    
    snapshot = {
        'timestamp': datetime.now().isoformat(),
        'baseline': baseline,
        'last_7_days': recent_7d,
        'last_24_hours': recent_24h
    }
    
    # Append to JSONL
    with PERF_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(snapshot) + '\n')
    
    return snapshot

def print_performance_report():
    """Print formatted performance report."""
    print("=" * 80)
    print("BITVAVO BOT - PERFORMANCE TRACKING")
    print("Optimization Applied:", datetime.fromtimestamp(get_optimization_date()).strftime('%Y-%m-%d %H:%M'))
    print("=" * 80)
    print()
    
    baseline = get_baseline_metrics()
    recent_7d = calculate_metrics(get_recent_closed_trades(7))
    recent_24h = calculate_metrics(get_recent_closed_trades(1))
    
    # Baseline (all-time)
    print("📊 BASELINE (All-Time Historical)")
    print("-" * 80)
    print(f"  Total Trades:     {baseline['total_trades']}")
    print(f"  Win Rate:         {baseline['win_rate']:.1f}%")
    print(f"  Avg Profit:       €{baseline['avg_profit']:.2f}")
    print(f"  Total P/L:        €{baseline['total_pnl']:.2f}")
    print(f"  Profit Factor:    {baseline['profit_factor']:.2f}")
    print(f"  Expectancy:       €{baseline['expectancy']:.2f}")
    print()
    
    # Last 7 days
    print("📈 LAST 7 DAYS")
    print("-" * 80)
    print(f"  Total Trades:     {recent_7d['total_trades']}")
    print(f"  Win Rate:         {recent_7d['win_rate']:.1f}% ", end="")
    delta_wr = recent_7d['win_rate'] - baseline['win_rate']
    if delta_wr > 0:
        print(f"(+{delta_wr:.1f}% ✅)")
    else:
        print(f"({delta_wr:.1f}% ❌)")
    
    print(f"  Avg Profit:       €{recent_7d['avg_profit']:.2f} ", end="")
    delta_ap = recent_7d['avg_profit'] - baseline['avg_profit']
    if delta_ap > 0:
        print(f"(+€{delta_ap:.2f} ✅)")
    else:
        print(f"(-€{abs(delta_ap):.2f} ❌)")
    
    print(f"  Total P/L:        €{recent_7d['total_pnl']:.2f}")
    print(f"  Profit Factor:    {recent_7d['profit_factor']:.2f}")
    print()
    
    # Last 24 hours
    print("⚡ LAST 24 HOURS")
    print("-" * 80)
    print(f"  Total Trades:     {recent_24h['total_trades']}")
    print(f"  Win Rate:         {recent_24h['win_rate']:.1f}%")
    print(f"  Avg Profit:       €{recent_24h['avg_profit']:.2f}")
    print(f"  Total P/L:        €{recent_24h['total_pnl']:.2f}")
    print()
    
    # Targets
    print("🎯 WEEK 1 TARGETS")
    print("-" * 80)
    target_wr_w1 = 40.0
    target_ap_w1 = 2.00
    
    wr_progress = min(100, (recent_7d['win_rate'] / target_wr_w1) * 100) if recent_7d['total_trades'] > 0 else 0
    ap_progress = min(100, (recent_7d['avg_profit'] / target_ap_w1) * 100) if recent_7d['avg_profit'] > 0 else 0
    
    print(f"  Win Rate:         {target_wr_w1:.0f}% target → {recent_7d['win_rate']:.1f}% current ({wr_progress:.0f}%)")
    print(f"  Avg Profit:       €{target_ap_w1:.2f} target → €{recent_7d['avg_profit']:.2f} current ({ap_progress:.0f}%)")
    print()
    
    # Next milestones
    trades_done = recent_7d['total_trades']
    trades_to_30 = max(0, 30 - trades_done)
    trades_to_40 = max(0, 40 - trades_done)
    
    print("📋 MONITORING PROGRESS")
    print("-" * 80)
    print(f"  Trades completed: {trades_done}")
    print(f"  Until 30 trades:  {trades_to_30} remaining")
    print(f"  Until 40 trades:  {trades_to_40} remaining")
    print()
    
    # Recommendations
    print("💡 RECOMMENDATIONS")
    print("-" * 80)
    if recent_7d['win_rate'] < 38:
        print("  ⚠️  Win rate below 38% - Consider increasing MIN_SCORE_TO_BUY to 8.0")
    elif recent_7d['win_rate'] >= 40:
        print("  ✅ Win rate target achieved!")
    
    if recent_7d['avg_profit'] < 1.80 and recent_7d['total_trades'] >= 10:
        print("  ⚠️  Avg profit low - Consider increasing TRAILING_ACTIVATION_PCT to 0.04")
    elif recent_7d['avg_profit'] >= 2.00:
        print("  ✅ Avg profit target achieved!")
    
    if recent_7d['total_trades'] < 10:
        print("  ℹ️  Still collecting data - wait for 10+ trades before tuning")
    
    print()
    print("=" * 80)

def main():
    """Main entry point."""
    # Log snapshot
    log_performance_snapshot()
    
    # Print report
    print_performance_report()
    
    # Check if we should alert
    recent_7d = calculate_metrics(get_recent_closed_trades(7))
    if recent_7d['total_trades'] >= 30:
        print()
        print("🎉 MILESTONE: 30+ trades completed with new settings!")
        print("Review performance and decide if further tuning needed.")
        print()

if __name__ == '__main__':
    main()
