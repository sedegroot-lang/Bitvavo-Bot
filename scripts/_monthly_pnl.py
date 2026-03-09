"""Analyze monthly P&L for timeline projection."""
import json, time, datetime
from collections import defaultdict

raw = json.load(open("data/trade_archive.json"))
archive = raw.get("trades", raw) if isinstance(raw, dict) else raw

def get_close_ts(t):
    """Get close timestamp from trade."""
    for field in ["archived_at", "timestamp", "close_time", "sell_time"]:
        v = t.get(field)
        if v:
            if isinstance(v, (int, float)) and v > 1e9:
                return v
            if isinstance(v, str):
                try:
                    return datetime.datetime.fromisoformat(v).timestamp()
                except:
                    pass
    return 0

trades = sorted(archive, key=get_close_ts)

monthly = defaultdict(lambda: {"pnl": 0, "count": 0, "wins": 0, "flood_loss": 0})
for t in trades:
    ts = get_close_ts(t)
    if ts == 0:
        continue
    month = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m")
    pnl = float(t.get("profit", t.get("net_profit_eur", t.get("profit_eur", 0))) or 0)
    reason = t.get("reason", "")
    monthly[month]["pnl"] += pnl
    monthly[month]["count"] += 1
    if pnl > 0:
        monthly[month]["wins"] += 1
    if "saldo" in reason.lower() or "flood" in reason.lower():
        monthly[month]["flood_loss"] += pnl

print("Monthly P&L:")
total_pnl = 0
total_adj = 0
months_count = 0
for m in sorted(monthly):
    d = monthly[m]
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    adj = d["pnl"] - d["flood_loss"]
    total_pnl += d["pnl"]
    total_adj += adj
    months_count += 1
    print(f"  {m}: EUR {d['pnl']:+8.2f} ({d['count']:3d} trades, WR {wr:4.0f}%) | No flood: EUR {adj:+8.2f} | Flood: EUR {d['flood_loss']:+.2f}")

print(f"\nTotal: EUR {total_pnl:+.2f} over {months_count} months")
print(f"Avg/month: EUR {total_pnl/months_count:+.2f}")
print(f"Without flood guard total: EUR {total_adj:+.2f}")
print(f"Without flood avg/month: EUR {total_adj/months_count:+.2f}")

# Last 2 months (most relevant with new settings)
recent_months = sorted(monthly)[-2:]
recent_pnl = sum(monthly[m]["pnl"] for m in recent_months)
recent_adj = sum(monthly[m]["pnl"] - monthly[m]["flood_loss"] for m in recent_months)
recent_n = len(recent_months)
print(f"\nLast {recent_n} months: EUR {recent_pnl:+.2f}")
print(f"Last {recent_n} months avg: EUR {recent_pnl/recent_n:+.2f}/month")
print(f"Last {recent_n} months no flood: EUR {recent_adj:+.2f}")
print(f"Last {recent_n} months no flood avg: EUR {recent_adj/recent_n:+.2f}/month")
