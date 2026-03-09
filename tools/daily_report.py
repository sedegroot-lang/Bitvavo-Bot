#!/usr/bin/env python3
"""Generate a daily operational report for the bot.

Produces JSON and Markdown summary files in `reports/`.
This is an MVP: parses logs and data files to surface key issues.
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
import re

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / 'logs'
DATA = ROOT / 'data'
REPORTS = ROOT / 'reports'
CONFIG = ROOT / 'config' / 'bot_config.json'
TRADE_ARCHIVE = DATA / 'trade_archive.json'
TRADE_LOG = DATA / 'trade_log.json'
BOT_LOG = LOGS / 'bot_log.txt'
PERF_METRICS = LOGS / 'perf_metrics.jsonl'

REPORTS.mkdir(parents=True, exist_ok=True)


def load_config():
    try:
        with open(CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def tail_file(path, seconds=24*3600):
    """Read lines from file that were written within the last `seconds`.
    Heuristic: look for timestamps in epoch or ISO in lines; fallback to last N lines.
    """
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return []
    now = time.time()
    recent = []
    ts_regex = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
    for ln in reversed(lines):
        # try to find ISO-like timestamp
        m = ts_regex.search(ln)
        if m:
            try:
                t = datetime.fromisoformat(m.group(1)).timestamp()
                if (now - t) <= seconds:
                    recent.append(ln)
                    continue
                else:
                    break
            except Exception:
                pass
        # fallback: include last 2000 lines if no timestamps
        if len(recent) < 2000:
            recent.append(ln)
    return list(reversed(recent))


def parse_bot_log_for_counts(lines):
    stats = {
        'desyncs': 0,
        'errors': 0,
        'optimizer_crashes': 0,
        'buy_limit_orders': 0,
        'buy_market_orders': 0,
    }
    for ln in lines:
        if 'DESYNC' in ln or 'DESYNC:' in ln:
            stats['desyncs'] += 1
        if 'ERROR:' in ln or 'Traceback' in ln:
            stats['errors'] += 1
        if 'failed to persist changes' in ln or 'AttributeError' in ln:
            stats['optimizer_crashes'] += 1
        if 'BUY resp=' in ln and '(MAKER' in ln:
            stats['buy_limit_orders'] += 1
        if 'BUY resp=' in ln and '(TAKER' in ln:
            stats['buy_market_orders'] += 1
    return stats


def summarize_trades_window(hours=24):
    now = time.time()
    since = now - hours * 3600
    summary = {
        'closed_count': 0,
        'closed_profit_total': 0.0,
        'stops': [],
    }
    if not TRADE_ARCHIVE.exists():
        return summary
    try:
        with open(TRADE_ARCHIVE, 'r', encoding='utf-8') as f:
            trades = json.load(f)
    except Exception:
        return summary
    for t in trades:
        try:
            ts = float(t.get('timestamp') or 0)
            if ts >= since:
                summary['closed_count'] += 1
                profit = float(t.get('profit') or 0)
                summary['closed_profit_total'] += profit
                if t.get('reason') == 'stop':
                    summary['stops'].append({'market': t.get('market'), 'profit': profit, 'timestamp': ts})
        except Exception:
            continue
    # Sort stops by worst profit
    summary['stops'] = sorted(summary['stops'], key=lambda x: x.get('profit', 0))[:10]
    return summary


def count_open_trades():
    # from trade_log.json
    try:
        if TRADE_LOG.exists():
            with open(TRADE_LOG, 'r', encoding='utf-8') as f:
                data = json.load(f)
            open_tr = data.get('open') or {}
            return len(open_tr), list(open_tr.keys())
    except Exception:
        pass
    return 0, []


def perf_metrics_summary(hours=24):
    if not PERF_METRICS.exists():
        return {}
    now = time.time()
    since = now - hours * 3600
    cpu_vals = []
    mem_vals = []
    try:
        with open(PERF_METRICS, 'r', encoding='utf-8') as f:
            for ln in f:
                try:
                    obj = json.loads(ln)
                    ts = float(obj.get('ts') or 0)
                    if ts >= since:
                        if 'cpu' in obj:
                            cpu_vals.append(float(obj.get('cpu') or 0))
                        if 'mem_mb' in obj:
                            mem_vals.append(float(obj.get('mem_mb') or 0))
                except Exception:
                    continue
    except Exception:
        return {}
    return {
        'cpu_max': max(cpu_vals) if cpu_vals else None,
        'cpu_avg': sum(cpu_vals)/len(cpu_vals) if cpu_vals else None,
        'mem_max_mb': max(mem_vals) if mem_vals else None,
        'mem_avg_mb': sum(mem_vals)/len(mem_vals) if mem_vals else None,
    }


def generate_report():
    cfg = load_config()
    now = time.time()
    date_str = datetime.utcfromtimestamp(now).strftime('%Y%m%d')
    human_date = datetime.utcfromtimestamp(now).strftime('%d-%m-%Y')
    # Use a human-friendly filename with dashes: daily_DD-MM-YYYY.json/md
    file_date = datetime.utcfromtimestamp(now).strftime('%d-%m-%Y')
    report = {
        'generated_ts': now,
        'generated_at': datetime.utcfromtimestamp(now).isoformat() + 'Z',
        'config': {},
        'open_trades': {},
        'bot_log_stats': {},
        'trades_summary_24h': {},
        'perf_summary_24h': {},
        'alerts': [],
    }
    report['config'] = {
        'MAX_OPEN_TRADES': cfg.get('MAX_OPEN_TRADES'),
        'LIMIT_ORDER_TIMEOUT_SECONDS': cfg.get('LIMIT_ORDER_TIMEOUT_SECONDS'),
    }
    # open trades
    open_count, open_keys = count_open_trades()
    report['open_trades']['count'] = open_count
    report['open_trades']['markets'] = open_keys
    if cfg.get('MAX_OPEN_TRADES') is not None and open_count > int(cfg.get('MAX_OPEN_TRADES')):
        report['alerts'].append(f"Open trades exceed MAX_OPEN_TRADES: {open_count} > {cfg.get('MAX_OPEN_TRADES')}")

    # bot log recent
    bot_lines = tail_file(BOT_LOG, seconds=24*3600)
    bot_stats = parse_bot_log_for_counts(bot_lines)
    report['bot_log_stats'] = bot_stats
    if bot_stats.get('optimizer_crashes'):
        report['alerts'].append('Optimizer persistence crash detected in logs')
    if bot_stats.get('desyncs'):
        report['alerts'].append(f"{bot_stats.get('desyncs')} DESYNC events detected in last 24h")

    # detect specific recurring API error patterns
    cancel_order_errors = sum(1 for ln in bot_lines if 'Bitvavo.cancelOrder' in ln and 'missing' in ln)
    if cancel_order_errors:
        report['bot_log_stats']['cancel_order_errors'] = cancel_order_errors
        report['alerts'].append(f"{cancel_order_errors} Bitvavo.cancelOrder() invocation errors detected")

    # trades summary
    trades_sum = summarize_trades_window(24)
    report['trades_summary_24h'] = trades_sum
    if trades_sum.get('stops') and len(trades_sum.get('stops')) > 0:
        report['alerts'].append(f"{len(trades_sum.get('stops'))} stop-loss trades closed in last 24h")

    # perf
    perf = perf_metrics_summary(24)
    report['perf_summary_24h'] = perf
    if perf.get('cpu_max') and perf.get('cpu_max') > 80:
        report['alerts'].append(f"High CPU observed: {perf.get('cpu_max')}%")

    # exceptions: collect top unique error lines from bot_lines
    errors = [ln for ln in bot_lines if 'Traceback' in ln or 'ERROR:' in ln or 'Exception' in ln]
    report['sample_errors'] = errors[-50:]

    # Build actionable recommendations based on alerts and common patterns
    recs = []
    # Open trades > max
    try:
        max_open = int(cfg.get('MAX_OPEN_TRADES')) if cfg.get('MAX_OPEN_TRADES') is not None else None
    except Exception:
        max_open = None
    if max_open is not None and open_count > max_open:
        recs.append({
            'issue': 'Open trades exceed configured MAX_OPEN_TRADES',
            'detail': f'Open trades={open_count} > MAX_OPEN_TRADES={max_open}',
            'recommendations': [
                'Inspect `data/trade_log.json` and `data/trade_archive.json` to confirm which positions are expected.',
                'Run `tools/check_running_scripts.py` to ensure only one bot instance is running (duplicate bots can open extra trades).',
                'If safe, run `scripts/helpers/force_cancel_order.py` or use the dashboard to cancel stale limit buy orders, or restart the bot to pick up fixes.',
                'Consider temporarily pausing AI auto-apply or market scans (disable ai_supervisor or set AI_AUTO_APPLY=false) while you debug.'
            ]
        })

    # Cancel order API errors
    if cancel_order_errors:
        recs.append({
            'issue': 'Failed cancelOrder API invocations',
            'detail': f'{cancel_order_errors} lines matching Bitvavo.cancelOrder() missing args',
            'recommendations': [
                'Restart `trailing_bot.py` to ensure the patched code is the one running (old process may still be active).',
                'Verify that `trailing_bot.py` contains `safe_call(bitvavo.cancelOrder, market, orderId)` (patched).',
                'Check logs in `logs/start_bot` and `logs/bot_log.txt` for cancel responses after restart.',
                'If cancellations still fail, run `scripts/helpers/force_cancel_order.py` with explicit orderIds to clear stuck orders.'
            ]
        })

    # High error rate
    if bot_stats.get('errors', 0) > 20:
        recs.append({
            'issue': 'High number of logged errors',
            'detail': f"{bot_stats.get('errors')} errors in last 24h",
            'recommendations': [
                'Open recent log tail to inspect frequent error messages: `Get-Content logs/bot_log.txt -Tail 300`.',
                'If errors originate from the optimizer or AI modules, consider disabling AI auto-apply and rerunning training manually.',
                'Ensure disk space and file permission issues are not causing write errors.'
            ]
        })

    # No closed trades in 24h
    if trades_sum.get('closed_count', 0) == 0 and open_count > 0:
        recs.append({
            'issue': 'Positions open but no closed trades in last 24h',
            'detail': 'No closed trades in last 24h while portfolio has open positions',
            'recommendations': [
                'Verify market conditions and whether trailing activation thresholds are met.',
                'Temporarily lower `DEFAULT_TRAILING` or review `TRAILING_ACTIVATION_PCT` only after understanding the risk.',
                'Consider manual review and staged closes for long-running positions.'
            ]
        })

    # High CPU
    if perf.get('cpu_max') and perf.get('cpu_max') > 80:
        recs.append({
            'issue': 'High CPU usage',
            'detail': f"Max CPU observed {perf.get('cpu_max')}%",
            'recommendations': [
                'Identify heavy processes with `Get-Process python | Sort WorkingSet -Descending` or use `tools/check_running_scripts.py`.',
                'If `auto_retrain` triggers heavy training jobs, reduce its frequency or run on a separate machine.',
            ]
        })

    report['recommendations'] = recs

    # write report as JSON + markdown
    out_json = REPORTS / f'daily_{file_date}.json'
    out_md = REPORTS / f'daily_{file_date}.md'
    try:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        # Markdown summary
        with open(out_md, 'w', encoding='utf-8') as f:
            f.write(f"# Daily Bot Report {human_date}\n\n")
            f.write(f"Generated: {report['generated_at']}\n\n")
            f.write(f"## Summary\n\n")
            f.write(f"- Open trades: {open_count}\n")
            f.write(f"- MAX_OPEN_TRADES: {cfg.get('MAX_OPEN_TRADES')}\n")
            f.write(f"- Alerts: {len(report['alerts'])}\n")
            if report['alerts']:
                f.write('\n### Alerts\n')
                for a in report['alerts']:
                    f.write(f"- {a}\n")
            f.write('\n## Bot Log Stats\n')
            for k, v in bot_stats.items():
                f.write(f"- {k}: {v}\n")
            f.write('\n## Trades summary (24h)\n')
            f.write(f"- closed_count: {trades_sum.get('closed_count')}\n")
            f.write(f"- closed_profit_total: {trades_sum.get('closed_profit_total'):.2f}\n")
            f.write('\nTop stop losses:\n')
            for s in trades_sum.get('stops', []):
                ts = datetime.utcfromtimestamp(s['timestamp']).isoformat() + 'Z'
                f.write(f"- {s.get('market')}: {s.get('profit'):.2f} at {ts}\n")
            
            
            # Actionable recommendations
            f.write('\n## Actionable Recommendations\n')
            recs = report.get('recommendations') or []
            if not recs:
                f.write('\n- None detected. No immediate actions required.\n')
            else:
                for r in recs:
                    try:
                        f.write(f"\n### {r.get('issue')}\n")
                        detail = r.get('detail')
                        if detail:
                            f.write(f"- Detail: {detail}\n")
                        f.write("- Recommended actions:\n")
                        for act in (r.get('recommendations') or []):
                            f.write(f"  - {act}\n")
                    except Exception:
                        continue
    except Exception as e:
        print('Failed to write report:', e, file=sys.stderr)
        return 1

    print('Report written:', out_json)
    return 0


if __name__ == '__main__':
    sys.exit(generate_report())
