"""
Backtest Framework for Bitvavo Bot
- Simulates live trading logic using historical candle data
- Uses same entry/exit logic as trailing_bot.py
- Outputs trade log, performance metrics, and Sharpe ratio
"""
import json
import numpy as np
from datetime import datetime
from trailing_bot import get_candles, close_prices, volumes
from modules.ml import predict_xgboost_signal
from modules.trading_risk import RiskManager
from modules.config import load_config

CONFIG = load_config() or {}

class BacktestResult:
    def __init__(self):
        self.trades = []
        self.pnl = []
        self.dates = []
    def add_trade(self, profit, date):
        self.trades.append(profit)
        self.pnl.append(profit)
        self.dates.append(date)
    def sharpe_ratio(self):
        returns = np.array(self.pnl)
        if len(returns) < 2:
            return 0.0
        mean = np.mean(returns)
        std = np.std(returns)
        return mean / std if std > 0 else 0.0
    def sharpe_ratio_by_period(self, period='day'):
        import pandas as pd
        if not self.trades or not self.dates:
            return {}
        df = pd.DataFrame({'pnl': self.pnl, 'date': [datetime.utcfromtimestamp(ts) for ts in self.dates]})
        if period == 'day':
            df['period'] = df['date'].dt.date
        elif period == 'week':
            df['period'] = df['date'].dt.isocalendar().week
        else:
            df['period'] = df['date'].dt.date
        ratios = {}
        for grp, group_df in df.groupby('period'):
            returns = group_df['pnl'].values
            mean = np.mean(returns)
            std = np.std(returns)
            ratios[grp] = mean / std if std > 0 else 0.0
        return ratios

def has_volume_surge(candles):
    if not candles or len(candles) < 51:
        return False
    last_vol = candles[-1]['volume'] if 'volume' in candles[-1] else 0
    avg_vol = sum(c['volume'] for c in candles[-51:-1] if 'volume' in c) / max(1, len(candles[-51:-1]))
    return last_vol >= 1.5 * avg_vol if avg_vol > 0 else False

def kelly_criterion(win_rate, avg_win, avg_loss):
    if avg_loss == 0:
        return 0.0
    b = avg_win / abs(avg_loss)
    p = win_rate
    q = 1 - p
    f = (b * p - q) / b if b > 0 else 0.0
    return max(0.0, min(f, 0.15))  # Max 15% portfolio

def atr(candles, window=14):
    highs = [float(x[2]) for x in candles if len(x)>2]
    lows = [float(x[3]) for x in candles if len(x)>3]
    closes = close_prices(candles)
    trs = [max(h-l, abs(h-c), abs(l-c)) for h,l,c in zip(highs, lows, closes)]
    return np.mean(trs[-window:]) if len(trs) >= window else 0.0

def get_trend_alignment(candles_1h, candles_4h, candles_1d):
    def trend(candles):
        closes = close_prices(candles)
        if len(closes) < 2:
            return 0
        return np.sign(closes[-1] - closes[0])
    return trend(candles_1h) == trend(candles_4h) == trend(candles_1d)

def run_backtest(market, start=None, end=None):
    candles = get_candles(market, '1m', 2000, start, end)
    candles_1h = get_candles(market, '1h', 50, start, end)
    candles_4h = get_candles(market, '4h', 50, start, end)
    candles_1d = get_candles(market, '1d', 50, start, end)
    result = BacktestResult()
    position = None
    entry_price = 0
    position_size = 1.0
    for i in range(60, len(candles)):
        window = candles[i-60:i]
        prices = close_prices(window)
        rsi_val = 0 if not prices else np.nan_to_num(np.mean(prices[-14:]))
        macd_val = 0
        sma_short_val = 0
        sma_long_val = 0
        volume_val = sum(volumes(window)) if window else 0
        features = [rsi_val, macd_val, sma_short_val, sma_long_val, volume_val]
        signal = predict_xgboost_signal(features)
        score = 9  # placeholder
        min_score = max(CONFIG.get('MIN_SCORE_TO_BUY', 7), 8)
        # Calculate Kelly position size
        if len(result.pnl) > 10:
            wins = [x for x in result.pnl if x > 0]
            losses = [x for x in result.pnl if x < 0]
            win_rate = len(wins) / len(result.pnl)
            avg_win = np.mean(wins) if wins else 0.0
            avg_loss = np.mean(losses) if losses else 0.0
            position_size = kelly_criterion(win_rate, avg_win, avg_loss)
        # ATR regime-specific stop-loss
        stop_loss_pct = 0.02
        if len(window) >= 14:
            stop_loss_pct = min(0.05, max(0.01, atr(window, 14) / prices[-1]))
        if (
            signal == 1
            and score >= min_score
            and rsi_val < 65
            and volume_val > CONFIG.get('MIN_AVG_VOLUME_1M', 100)
            and has_volume_surge(window)
            and get_trend_alignment(candles_1h, candles_4h, candles_1d)
        ):
            if not position:
                entry_price = prices[-1]
                position = True
                print(f"Entry at {entry_price}, position size: {position_size:.2%}")
        elif position:
            # Exit condition: price drops below regime-specific stop-loss
            if prices[-1] < entry_price * (1 - stop_loss_pct):
                profit = prices[-1] - entry_price
                result.add_trade(profit, candles[i]['timestamp'])
                position = None
    print(f"Backtest {market}: {len(result.trades)} trades, Sharpe ratio: {result.sharpe_ratio():.2f}")
    # write results CSV
    try:
        import csv
        with open(f'backtest_{market.replace("/","-")}_results.csv', 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['index','pnl','timestamp'])
            for idx, (pnl, ts) in enumerate(zip(result.pnl, result.dates)):
                writer.writerow([idx, pnl, ts])
        print(f"Results saved to backtest_{market.replace('/','-')}_results.csv")
    except Exception:
        pass
    return result

class RLAgent:
    def __init__(self):
        self.best_score = -np.inf
        self.best_params = {}
    def optimize(self, param_grid, run_fn):
        for params in param_grid:
            score = run_fn(**params)
            if score > self.best_score:
                self.best_score = score
                self.best_params = params
        print(f"RL best params: {self.best_params}, best score: {self.best_score}")

if __name__ == "__main__":
    market = "BTC-EUR"
    start = "2025-01-01T00:00:00Z"
    end = "2025-10-01T00:00:00Z"
    result = run_backtest(market, start, end)
    print("Sharpe ratio per dag:")
    print(result.sharpe_ratio_by_period('day'))
    print("Sharpe ratio per week:")
    print(result.sharpe_ratio_by_period('week'))
