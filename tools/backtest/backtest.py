import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np


def load_trades(path: Path):
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        return data.get('closed', [])
    return data


def load_history(path: Path):
    if not path.exists():
        return []
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def assign_segments(trades, history):
    # History entries assumed sorted oldest -> newest
    history_sorted = sorted(history, key=lambda e: e.get('ts', 0))
    segments = []
    if not history_sorted:
        segments.append({'label': 'baseline', 'start': 0, 'changes': []})
    else:
        segments.append({'label': 'baseline', 'start': 0, 'changes': []})
        for idx, change in enumerate(history_sorted, start=1):
            segments.append({
                'label': f"change_{idx}",
                'start': change.get('ts', 0),
                'changes': [change]
            })
    # Assign trades
    for trade in trades:
        ts = trade.get('timestamp', 0)
        seg = segments[0]
        for candidate in segments[1:]:
            if ts >= candidate['start']:
                seg = candidate
            else:
                break
        seg.setdefault('trades', []).append(trade)
    return segments


def compute_metrics(segment):
    trades = segment.get('trades', []) or []
    pnl_list = [t.get('profit', 0.0) for t in trades]
    if not pnl_list:
        return {
            'count': 0,
            'total_profit': 0.0,
            'avg_profit': 0.0,
            'win_rate': 0.0,
            'max_drawdown': 0.0
        }
    cumulative = np.cumsum(pnl_list)
    max_dd = float(np.max(cumulative) - np.min(cumulative)) if len(cumulative) > 1 else 0.0
    wins = [p for p in pnl_list if p > 0]
    return {
        'count': len(pnl_list),
        'total_profit': float(sum(pnl_list)),
        'avg_profit': float(statistics.mean(pnl_list)),
        'win_rate': float(len(wins) / len(pnl_list)),
        'max_drawdown': max_dd
    }


def main():
    parser = argparse.ArgumentParser(description='Evaluate AI parameter schedules vs baseline.')
    parser.add_argument('--trades', default='trade_log.json', help='Path to trade log (default trade_log.json).')
    parser.add_argument('--history', default='ai_changes.json', help='AI change history file.')
    parser.add_argument('--output', default='ai_backtest_report.json', help='Output JSON report path.')
    args = parser.parse_args()

    trades = load_trades(Path(args.trades))
    history = load_history(Path(args.history))

    segments = assign_segments(trades, history)
    report = {'generated_at': int(time.time()), 'segments': []}
    baseline_metrics = None

    print("AI backtest: baseline vs AI-driven segments")
    for seg in segments:
        metrics = compute_metrics(seg)
        if seg['label'] == 'baseline':
            baseline_metrics = metrics
        delta = {}
        if baseline_metrics and seg['label'] != 'baseline':
            delta = {
                'delta_total_profit': metrics['total_profit'] - baseline_metrics['total_profit'],
                'delta_avg_profit': metrics['avg_profit'] - baseline_metrics['avg_profit'],
                'delta_win_rate': metrics['win_rate'] - baseline_metrics['win_rate']
            }
        entry = {
            'label': seg['label'],
            'start_ts': seg.get('start', 0),
            'metrics': metrics,
            'delta_vs_baseline': delta,
            'change_summary': seg.get('changes', [])
        }
        report['segments'].append(entry)
        print(f"Segment {seg['label']}: count={metrics['count']} total={metrics['total_profit']:.2f} avg={metrics['avg_profit']:.2f} win_rate={metrics['win_rate']:.2f} drawdown={metrics['max_drawdown']:.2f}")
        if delta:
            print(f"  Δ vs baseline: total {delta['delta_total_profit']:.2f}, avg {delta['delta_avg_profit']:.2f}, win_rate {delta['delta_win_rate']:.2f}")

    with open(args.output, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)
    print(f"Rapport opgeslagen naar {args.output}")


if __name__ == '__main__':
    main()
