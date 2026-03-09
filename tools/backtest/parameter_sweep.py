"""
Parameter sweep script voor Bitvavo Bot backtest
- Voert de backtest uit met verschillende parametercombinaties
- Slaat resultaten (Sharpe ratio, totaal PnL, aantal trades) op in een CSV
- Toont de top N beste configuraties
"""
import itertools
import csv
from backtest_framework import run_backtest

# Parameter grid (pas aan naar wens)
PARAM_GRID = {
    'min_score': [7, 8, 9],
    'min_avg_volume': [50, 100, 200],
    'kelly_max': [0.10, 0.15],
    'stop_loss_pct': [0.01, 0.02, 0.03],
}

MARKET = "BTC-EUR"
START = "2025-01-01T00:00:00Z"
END = "2025-10-01T00:00:00Z"
TOP_N = 10

# Helper om parameters te combineren
def param_combinations(grid):
    keys = list(grid.keys())
    for values in itertools.product(*grid.values()):
        yield dict(zip(keys, values))

def run_sweep():
    results = []
    for params in param_combinations(PARAM_GRID):
        # Pas globale config aan (of geef direct door aan run_backtest als ondersteund)
        # Hier als voorbeeld via globals, pas aan als run_backtest params accepteert
        import trailing_bot
        trailing_bot.CONFIG['MIN_SCORE_TO_BUY'] = params['min_score']
        trailing_bot.CONFIG['MIN_AVG_VOLUME_1M'] = params['min_avg_volume']
        # Kelly en stop-loss limieten kun je in run_backtest of trailing_bot aanpassen indien ondersteund
        result = run_backtest(MARKET, START, END)
        sharpe = result.sharpe_ratio()
        trades = len(result.trades)
        total_pnl = sum(result.pnl)
        results.append({
            **params,
            'sharpe': sharpe,
            'trades': trades,
            'total_pnl': total_pnl,
        })
        print(f"Params: {params} | Sharpe: {sharpe:.2f} | Trades: {trades} | PnL: {total_pnl:.2f}")
    # Sorteer op Sharpe ratio
    results.sort(key=lambda x: x['sharpe'], reverse=True)
    # Schrijf naar CSV
    with open('parameter_sweep_results.csv', 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print(f"Top {TOP_N} resultaten:")
    for row in results[:TOP_N]:
        print(row)

if __name__ == "__main__":
    run_sweep()
