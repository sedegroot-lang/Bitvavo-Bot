import json, os, statistics
BASE = os.path.dirname(os.path.dirname(__file__))
trade_file = os.path.join(BASE, 'data', 'trade_log.json')
log_file = os.path.join(BASE, 'bot_log.txt')
with open(trade_file, 'r', encoding='utf-8') as f:
    trades = json.load(f)
closed = trades.get('closed', [])
n = len(closed)
wins = [t for t in closed if t.get('profit', 0) > 0]
losses = [t for t in closed if t.get('profit', 0) < 0]
zeros = [t for t in closed if t.get('profit', 0) == 0]

total_profit = sum(t.get('profit', 0) for t in closed)
win_rate = len(wins) / n if n else 0
avg_profit = statistics.mean([t.get('profit',0) for t in closed]) if n else 0
avg_win = statistics.mean([t.get('profit') for t in wins]) if wins else 0
avg_loss = statistics.mean([t.get('profit') for t in losses]) if losses else 0
saldo_errors = [t for t in closed if t.get('reason') == 'saldo_error']
num_saldo = len(saldo_errors)

top_losses = sorted(losses, key=lambda x: x.get('profit',0))[:10]
top_wins = sorted(wins, key=lambda x: x.get('profit',0), reverse=True)[:10]
recent = sorted(closed, key=lambda x: x.get('timestamp',0), reverse=True)[:10]

error_lines = []
if os.path.exists(log_file):
    with open(log_file, 'r', encoding='utf-8', errors='replace') as lf:
        for line in lf:
            if 'ERROR' in line or 'Traceback' in line or 'Bot gestopt' in line:
                error_lines.append(line.strip())

print('TRADE SUMMARY')
print('Total closed trades:', n)
print('Wins:', len(wins), 'Losses:', len(losses), 'Zeros:', len(zeros))
print('Win rate: {:.2%}'.format(win_rate))
print('Total profit (EUR):', round(total_profit,4))
print('Avg profit per trade:', round(avg_profit,4))
print('Avg win:', round(avg_win,4), 'Avg loss:', round(avg_loss,4))
print('Saldo_error count:', num_saldo)
print('\nTop 10 losses (worst first):')
for t in top_losses:
    print(f"{t.get('market')} profit={t.get('profit')} reason={t.get('reason')}")
print('\nTop 10 wins:')
for t in top_wins:
    print(f"{t.get('market')} profit={t.get('profit')} reason={t.get('reason')}")
print('\nRecent closed trades (last 10):')
for t in recent:
    ts = t.get('timestamp')
    print(f"{t.get('market')} profit={t.get('profit')} reason={t.get('reason')} ts={ts}")
print('\nRecent ERROR lines from bot_log (last 50):')
for line in error_lines[-50:]:
    print(line)

result = {
    'total_closed': n,
    'wins': len(wins),
    'losses': len(losses),
    'win_rate': win_rate,
    'total_profit': total_profit,
    'avg_profit': avg_profit,
    'num_saldo_errors': num_saldo,
}
print('\n---RESULT-JSON---')
print(json.dumps(result))
