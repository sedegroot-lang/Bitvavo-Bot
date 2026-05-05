"""
Performance Analytics Module
Comprehensive metrics and statistics for trading bot performance
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import trade archive for complete history
try:
    from modules.trade_archive import get_all_trades, get_archive_stats

    ARCHIVE_AVAILABLE = True
except ImportError:
    ARCHIVE_AVAILABLE = False


class PerformanceAnalytics:
    """Calculate advanced trading performance metrics"""

    def __init__(self, trade_log_path: str = "data/trade_log.json", use_archive: bool = True):
        self.trade_log_path = Path(trade_log_path)
        self.use_archive = use_archive and ARCHIVE_AVAILABLE
        self.trades_data = self._load_trades()

    def _load_trades(self) -> Dict:
        """Load trade data from archive (preferred) or trade_log.json"""
        if self.use_archive:
            try:
                # Load from permanent archive
                all_trades = get_all_trades(exclude_sync_removed=False)

                # Reconstruct trade_log format for compatibility
                return {
                    "open": {},  # Archive only stores closed trades
                    "closed": all_trades,
                }
            except Exception as e:
                print(f"[ANALYTICS] Archive load failed, falling back to trade_log.json: {e}")
                self.use_archive = False

        # Fallback to trade_log.json
        if not self.trade_log_path.exists():
            return {"open": {}, "closed": []}

        try:
            with open(self.trade_log_path, "r") as f:
                return json.load(f)
        except Exception:
            return {"open": {}, "closed": []}

    def refresh(self):
        """Reload trade data"""
        self.trades_data = self._load_trades()

    def get_closed_trades(self, days: Optional[int] = None) -> List[Dict]:
        """Get closed trades, optionally filtered by days"""
        closed = self.trades_data.get("closed", [])

        if days is None:
            return closed

        cutoff = datetime.now().timestamp() - (days * 86400)
        return [t for t in closed if t.get("timestamp", 0) > cutoff]

    def get_open_trades(self) -> Dict[str, Dict]:
        """Get currently open trades"""
        return self.trades_data.get("open", {})

    # ========== BASIC METRICS ==========

    def total_trades(self, days: Optional[int] = None) -> int:
        """Total number of closed trades"""
        return len(self.get_closed_trades(days))

    def win_rate(self, days: Optional[int] = None) -> float:
        """Win rate percentage"""
        trades = self.get_closed_trades(days)
        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.get("profit", 0) > 0)
        return (wins / len(trades)) * 100

    def total_pnl(self, days: Optional[int] = None) -> float:
        """Total profit/loss in EUR"""
        trades = self.get_closed_trades(days)
        return sum(t.get("profit", 0) for t in trades)

    def avg_win(self, days: Optional[int] = None) -> float:
        """Average winning trade in EUR"""
        trades = self.get_closed_trades(days)
        wins = [t.get("profit", 0) for t in trades if t.get("profit", 0) > 0]
        return sum(wins) / len(wins) if wins else 0.0

    def avg_loss(self, days: Optional[int] = None) -> float:
        """Average losing trade in EUR (absolute value)"""
        trades = self.get_closed_trades(days)
        losses = [abs(t.get("profit", 0)) for t in trades if t.get("profit", 0) < 0]
        return sum(losses) / len(losses) if losses else 0.0

    def profit_factor(self, days: Optional[int] = None) -> float:
        """Profit factor (gross profit / gross loss)"""
        trades = self.get_closed_trades(days)

        gross_profit = sum(t.get("profit", 0) for t in trades if t.get("profit", 0) > 0)
        gross_loss = abs(sum(t.get("profit", 0) for t in trades if t.get("profit", 0) < 0))

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def expectancy(self, days: Optional[int] = None) -> float:
        """Expected value per trade in EUR"""
        trades = self.get_closed_trades(days)
        if not trades:
            return 0.0

        wins = [t.get("profit", 0) for t in trades if t.get("profit", 0) > 0]
        losses = [t.get("profit", 0) for t in trades if t.get("profit", 0) < 0]

        win_rate = len(wins) / len(trades)
        loss_rate = len(losses) / len(trades)

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        return (win_rate * avg_win) + (loss_rate * avg_loss)

    # ========== RISK METRICS ==========

    def max_drawdown(self, days: Optional[int] = None) -> Tuple[float, float]:
        """
        Maximum drawdown in EUR and percentage
        Returns: (drawdown_eur, drawdown_pct)
        """
        trades = self.get_closed_trades(days)
        if not trades:
            return (0.0, 0.0)

        # Calculate cumulative P/L
        cumulative = 0
        peak = 0
        max_dd = 0
        max_dd_pct = 0

        for trade in trades:
            cumulative += trade.get("profit", 0)

            if cumulative > peak:
                peak = cumulative

            drawdown = peak - cumulative
            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_pct = (drawdown / peak * 100) if peak > 0 else 0

        return (max_dd, max_dd_pct)

    def sharpe_ratio(self, days: Optional[int] = None, risk_free_rate: float = 0.0) -> float:
        """
        Sharpe ratio (risk-adjusted returns)
        Assumes daily returns, annualized
        """
        trades = self.get_closed_trades(days)
        if len(trades) < 2:
            return 0.0

        returns = [t.get("profit", 0) for t in trades]

        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return 0.0

        # Annualize (assuming ~250 trading days)
        annualized_return = avg_return * 250
        annualized_std = std_dev * math.sqrt(250)

        return (annualized_return - risk_free_rate) / annualized_std

    def sortino_ratio(self, days: Optional[int] = None, risk_free_rate: float = 0.0) -> float:
        """
        Sortino ratio (downside risk-adjusted returns)
        Only considers negative volatility
        """
        trades = self.get_closed_trades(days)
        if len(trades) < 2:
            return 0.0

        returns = [t.get("profit", 0) for t in trades]
        avg_return = sum(returns) / len(returns)

        # Only negative returns
        downside_returns = [r for r in returns if r < 0]
        if not downside_returns:
            return float("inf") if avg_return > 0 else 0.0

        downside_variance = sum(r**2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance)

        if downside_std == 0:
            return 0.0

        # Annualize
        annualized_return = avg_return * 250
        annualized_downside = downside_std * math.sqrt(250)

        return (annualized_return - risk_free_rate) / annualized_downside

    def calmar_ratio(self, days: Optional[int] = None) -> float:
        """
        Calmar ratio (return / max drawdown)
        Higher is better
        """
        total_return = self.total_pnl(days)
        max_dd, _ = self.max_drawdown(days)

        if max_dd == 0:
            return float("inf") if total_return > 0 else 0.0

        return total_return / max_dd

    def consecutive_wins(self, days: Optional[int] = None) -> int:
        """Maximum consecutive winning trades"""
        trades = self.get_closed_trades(days)
        if not trades:
            return 0

        max_streak = 0
        current_streak = 0

        for trade in trades:
            profit = trade.get("profit", 0)
            if profit > 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        return max_streak

    def consecutive_losses(self, days: Optional[int] = None) -> int:
        """Maximum consecutive losing trades"""
        trades = self.get_closed_trades(days)
        if not trades:
            return 0

        max_streak = 0
        current_streak = 0

        for trade in trades:
            profit = trade.get("profit", 0)
            if profit <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        return max_streak

    def avg_hold_time(self, days: Optional[int] = None) -> float:
        """Average trade duration in hours"""
        trades = self.get_closed_trades(days)
        if not trades:
            return 0.0

        durations = []
        for trade in trades:
            open_ts = trade.get("timestamp", 0)
            close_ts = trade.get("close_timestamp", open_ts)
            duration_hours = (close_ts - open_ts) / 3600
            durations.append(duration_hours)

        return sum(durations) / len(durations) if durations else 0.0

    def calculate_advanced_metrics(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculate comprehensive performance metrics.

        Returns dictionary with all advanced metrics:
        - Return metrics (total, avg, median)
        - Risk metrics (Sharpe, Sortino, Calmar, max drawdown)
        - Win/loss analysis (win rate, profit factor, expectancy)
        - Trade duration (avg hold time, by outcome)
        - Consecutive streaks
        """
        trades = self.get_closed_trades(days)

        if not trades:
            return {"error": "No trades available", "total_trades": 0}

        # Calculate trade durations by outcome
        win_times = []
        loss_times = []
        for trade in trades:
            open_ts = trade.get("timestamp", 0)
            close_ts = trade.get("close_timestamp", open_ts)
            duration_hours = (close_ts - open_ts) / 3600

            if trade.get("profit", 0) > 0:
                win_times.append(duration_hours)
            else:
                loss_times.append(duration_hours)

        max_dd_eur, max_dd_pct = self.max_drawdown(days)

        metrics = {
            # Basic stats
            "total_trades": len(trades),
            "period_days": days if days else "all_time",
            # Returns
            "total_return_eur": self.total_pnl(days),
            "avg_return_eur": sum(t.get("profit", 0) for t in trades) / len(trades),
            "median_return_eur": sorted([t.get("profit", 0) for t in trades])[len(trades) // 2],
            # Risk metrics
            "max_drawdown_eur": max_dd_eur,
            "max_drawdown_pct": max_dd_pct,
            "sharpe_ratio": self.sharpe_ratio(days),
            "sortino_ratio": self.sortino_ratio(days),
            "calmar_ratio": self.calmar_ratio(days),
            # Win/Loss analysis
            "win_rate_pct": self.win_rate(days),
            "profit_factor": self.profit_factor(days),
            "expectancy_eur": self.expectancy(days),
            "avg_win_eur": self.avg_win(days),
            "avg_loss_eur": self.avg_loss(days),
            # Trade duration
            "avg_hold_time_hours": self.avg_hold_time(days),
            "avg_win_time_hours": sum(win_times) / len(win_times) if win_times else 0.0,
            "avg_loss_time_hours": sum(loss_times) / len(loss_times) if loss_times else 0.0,
            # Consecutive streaks
            "max_win_streak": self.consecutive_wins(days),
            "max_loss_streak": self.consecutive_losses(days),
            # Best/worst trades
            "best_trade_eur": max(t.get("profit", 0) for t in trades),
            "worst_trade_eur": min(t.get("profit", 0) for t in trades),
        }

        return metrics

    # ========== MARKET-SPECIFIC METRICS ==========

    def market_statistics(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """
        Performance statistics per market
        Returns: {
            'BTC-EUR': {
                'trades': 10,
                'win_rate': 60.0,
                'total_pnl': 25.5,
                'avg_pnl': 2.55,
                'best_trade': 10.2,
                'worst_trade': -5.1
            },
            ...
        }
        """
        trades = self.get_closed_trades(days)

        stats = {}
        for trade in trades:
            market = trade.get("market", "UNKNOWN")
            if market not in stats:
                stats[market] = {"trades": [], "wins": 0, "losses": 0}

            profit = trade.get("profit", 0)
            stats[market]["trades"].append(profit)

            if profit > 0:
                stats[market]["wins"] += 1
            else:
                stats[market]["losses"] += 1

        # Calculate aggregates
        result = {}
        for market, data in stats.items():
            trades_list = data["trades"]
            total = len(trades_list)

            result[market] = {
                "trades": total,
                "win_rate": (data["wins"] / total * 100) if total > 0 else 0.0,
                "total_pnl": sum(trades_list),
                "avg_pnl": sum(trades_list) / total if total > 0 else 0.0,
                "best_trade": max(trades_list) if trades_list else 0.0,
                "worst_trade": min(trades_list) if trades_list else 0.0,
            }

        return result

    def best_markets(self, top_n: int = 5, days: Optional[int] = None) -> List[Tuple[str, float]]:
        """Get top N markets by total P/L"""
        stats = self.market_statistics(days)
        sorted_markets = sorted(stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
        return [(m, data["total_pnl"]) for m, data in sorted_markets[:top_n]]

    def worst_markets(self, top_n: int = 5, days: Optional[int] = None) -> List[Tuple[str, float]]:
        """Get bottom N markets by total P/L"""
        stats = self.market_statistics(days)
        sorted_markets = sorted(stats.items(), key=lambda x: x[1]["total_pnl"])
        return [(m, data["total_pnl"]) for m, data in sorted_markets[:top_n]]

    # ========== TIME-BASED ANALYSIS ==========

    def daily_pnl(self, days: int = 30) -> Dict[str, float]:
        """
        Daily P/L for last N days
        Returns: {'2025-11-20': 5.2, '2025-11-19': -2.1, ...}
        """
        trades = self.get_closed_trades(days)

        daily = {}
        for trade in trades:
            timestamp = trade.get("timestamp", 0)
            date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

            if date not in daily:
                daily[date] = 0.0

            daily[date] += trade.get("profit", 0)

        return daily

    def win_streak(self, days: Optional[int] = None) -> Tuple[int, int]:
        """
        Current and maximum win streak
        Returns: (current_streak, max_streak)
        """
        trades = self.get_closed_trades(days)
        if not trades:
            return (0, 0)

        current = 0
        max_streak = 0

        for trade in reversed(trades):  # Most recent first
            if trade.get("profit", 0) > 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                if current > 0:
                    break
                current = 0

        # Also check entire history for max
        temp_streak = 0
        for trade in trades:
            if trade.get("profit", 0) > 0:
                temp_streak += 1
                max_streak = max(max_streak, temp_streak)
            else:
                temp_streak = 0

        return (current, max_streak)

    def loss_streak(self, days: Optional[int] = None) -> Tuple[int, int]:
        """
        Current and maximum loss streak
        Returns: (current_streak, max_streak)
        """
        trades = self.get_closed_trades(days)
        if not trades:
            return (0, 0)

        current = 0
        max_streak = 0

        for trade in reversed(trades):
            if trade.get("profit", 0) <= 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                if current > 0:
                    break
                current = 0

        temp_streak = 0
        for trade in trades:
            if trade.get("profit", 0) <= 0:
                temp_streak += 1
                max_streak = max(max_streak, temp_streak)
            else:
                temp_streak = 0

        return (current, max_streak)

    # ========== COMPREHENSIVE REPORT ==========

    def fee_summary(self, days: Optional[int] = None) -> Dict[str, float]:
        """Summarize fees paid across all closed trades."""
        trades = self.get_closed_trades(days)
        total_sell_fees = 0.0
        total_invested = 0.0
        trades_with_fee_data = 0
        for t in trades:
            sf = t.get("sell_fee", 0)
            if sf and isinstance(sf, (int, float)):
                total_sell_fees += sf
                trades_with_fee_data += 1
            inv = t.get("invested_eur", 0)
            if inv and isinstance(inv, (int, float)):
                total_invested += inv
        # Estimate buy fees from invested (taker fee 0.25%)
        est_buy_fees = total_invested * 0.0025
        return {
            "total_sell_fees": round(total_sell_fees, 2),
            "estimated_buy_fees": round(est_buy_fees, 2),
            "estimated_total_fees": round(total_sell_fees + est_buy_fees, 2),
            "trades_with_fee_data": trades_with_fee_data,
        }

    def total_pnl_excluding_sync(self, days: Optional[int] = None) -> float:
        """Total P&L excluding sync_removed trades (more accurate)."""
        trades = self.get_closed_trades(days)
        return sum(t.get("profit", 0) for t in trades if t.get("reason") != "sync_removed")

    def win_rate_excluding_sync(self, days: Optional[int] = None) -> float:
        """Win rate excluding sync_removed trades."""
        trades = [t for t in self.get_closed_trades(days) if t.get("reason") != "sync_removed"]
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("profit", 0) > 0)
        return (wins / len(trades)) * 100

    def generate_report(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate comprehensive performance report
        """
        max_dd_eur, max_dd_pct = self.max_drawdown(days)
        win_streak_cur, win_streak_max = self.win_streak(days)
        loss_streak_cur, loss_streak_max = self.loss_streak(days)

        return {
            "period": f"Last {days} days" if days else "All time",
            "timestamp": datetime.now().isoformat(),
            # Basic metrics
            "total_trades": self.total_trades(days),
            "win_rate": round(self.win_rate(days), 2),
            "total_pnl": round(self.total_pnl(days), 2),
            "avg_win": round(self.avg_win(days), 2),
            "avg_loss": round(self.avg_loss(days), 2),
            "profit_factor": round(self.profit_factor(days), 2),
            "expectancy": round(self.expectancy(days), 2),
            # Fee-aware metrics
            "total_pnl_excl_sync": round(self.total_pnl_excluding_sync(days), 2),
            "win_rate_excl_sync": round(self.win_rate_excluding_sync(days), 2),
            "fee_summary": self.fee_summary(days),
            # Risk metrics
            "max_drawdown_eur": round(max_dd_eur, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio(days), 2),
            "sortino_ratio": round(self.sortino_ratio(days), 2),
            "calmar_ratio": round(self.calmar_ratio(days), 2),
            # Streaks
            "current_win_streak": win_streak_cur,
            "max_win_streak": win_streak_max,
            "current_loss_streak": loss_streak_cur,
            "max_loss_streak": loss_streak_max,
            # Market stats
            "best_markets": self.best_markets(5, days),
            "worst_markets": self.worst_markets(5, days),
            # Open positions
            "open_trades": len(self.get_open_trades()),
        }


def get_analytics() -> PerformanceAnalytics:
    """Get analytics instance (singleton pattern)"""
    return PerformanceAnalytics()
