import json, statistics
from collections import defaultdict

events = [json.loads(l) for l in open('data/partial_tp_events.jsonl')]
trade_log = json.load(open('data/trade_log.json'))
closed = trade_log['closed']
exp = json.load(open('data/expectancy_stats.json'))
cfg = json.load(open('config/bot_config.json'))

real = [t for t in closed if abs(float(t.get('profit', 0))) > 0.01]
wins = [t for t in real if float(t.get('profit', 0)) > 0]
losses = [t for t in real if float(t.get('profit', 0)) < 0]

print('=== CLOSED TRADES ANALYSE ===')
print(f'Echte trades: {len(real)} | wins: {len(wins)} | losses: {len(losses)}')
if wins:
    avg_win = statistics.mean([float(t['profit']) for t in wins])
    print(f'Avg win: EUR{avg_win:.3f}')
if losses:
    avg_loss = statistics.mean([float(t['profit']) for t in losses])
    print(f'Avg loss: EUR{avg_loss:.3f}')
if wins and losses:
    rr = abs(avg_win) / abs(avg_loss)
    print(f'Risk/Reward ratio: {rr:.2f}')

print()
print('=== PARTIAL TP EVENTS PER COIN ===')
by_coin = defaultdict(list)
for e in events:
    by_coin[e['market']].append(float(e['profit_eur']))
for coin, profits in sorted(by_coin.items(), key=lambda x: -sum(x[1])):
    print(f"  {coin}: {len(profits)}x | totaal=EUR{sum(profits):.2f} | avg=EUR{statistics.mean(profits):.3f}")

print()
print('=== PARTIAL TP EVENTS PER LEVEL ===')
by_level = defaultdict(list)
for e in events:
    by_level[e.get('level_index', e.get('level', '?'))].append(float(e['profit_eur']))
for lvl, profits in sorted(by_level.items()):
    print(f"  Level {lvl}: {len(profits)}x | totaal=EUR{sum(profits):.2f} | avg=EUR{statistics.mean(profits):.3f}")

print()
print('=== KEY CONFIG PARAMETERS ===')
keys = [
    'BASE_AMOUNT_EUR', 'DCA_AMOUNT_EUR', 'DCA_AMOUNT_RATIO',
    'STOP_LOSS_HARD_PCT', 'HARD_SL_ALT_PCT', 'TRAILING_STOP_PCT',
    'TRAILING_STOP_ACTIVATION_PCT',
    'PARTIAL_TP_1_PCT', 'PARTIAL_TP_1_SELL_RATIO',
    'PARTIAL_TP_2_PCT', 'PARTIAL_TP_2_SELL_RATIO',
    'PARTIAL_TP_3_PCT', 'PARTIAL_TP_3_SELL_RATIO',
    'RSI_DCA_THRESHOLD', 'RSI_ENTRY_MAX', 'RSI_ENTRY_MIN',
    'MIN_SCORE_TO_BUY', 'MAX_OPEN_TRADES', 'BUDGET_EUR',
    'DCA_MAX_BUYS', 'DCA_DROP_PCT', 'DCA_PYRAMID_BUYS',
    'CIRCUIT_BREAKER_MIN_WIN_RATE', 'CIRCUIT_BREAKER_WINDOW',
    'GRID_ENABLED', 'GRID_BUDGET_EUR',
]
for k in keys:
    v = cfg.get(k, 'NOT SET')
    print(f"  {k}: {v}")

print()
print('=== EXPECTANCY STATS ===')
for k, v in exp.items():
    print(f"  {k}: {v}")

print()
print('=== OPEN TRADES ===')
open_trades = trade_log.get('open', [])
print(f"  Aantal open: {len(open_trades)}")
total_invested = sum(float(t.get('invested_eur', t.get('amount_eur', 0))) for t in open_trades)
total_pnl = sum(float(t.get('unrealized_pnl', t.get('pnl', 0))) for t in open_trades)
print(f"  Totaal geinvesteerd: EUR{total_invested:.2f}")
print(f"  Totaal unrealized PnL: EUR{total_pnl:.2f}")

print()
print('=== WINS DETAIL ===')
for t in sorted(wins, key=lambda x: -float(x.get('profit', 0))):
    print(f"  {t.get('market','?')} reason={t.get('reason','?')} profit=EUR{float(t.get('profit',0)):.3f}")

print()
print('=== LOSSES DETAIL ===')
for t in sorted(losses, key=lambda x: float(x.get('profit', 0))):
    print(f"  {t.get('market','?')} reason={t.get('reason','?')} profit=EUR{float(t.get('profit',0)):.3f}")
