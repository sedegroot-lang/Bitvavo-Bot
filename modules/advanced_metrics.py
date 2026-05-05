"""
Advanced Performance Metrics Module
====================================

Provides sophisticated trading metrics including:
- Risk-adjusted returns (Sharpe, Sortino, Calmar ratios)
- Drawdown analysis (max, average, recovery time)
- Win/loss streak tracking
- MAE/MFE (Maximum Adverse/Favorable Excursion)
- Time-based performance analysis
- Trade quality metrics
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class AdvancedMetrics:
    """Calculate advanced trading performance metrics"""

    def __init__(self, trade_log_path: str = "data/trade_log.json"):
        self.trade_log_path = Path(trade_log_path)
        self.trades_data = self._load_trades()
        self.closed_trades = self.trades_data.get("closed", [])
        self.open_trades = self.trades_data.get("open", {})

    def _load_trades(self) -> Dict:
        """Load trade data"""
        if not self.trade_log_path.exists():
            return {"open": {}, "closed": []}

        try:
            with open(self.trade_log_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ADVANCED_METRICS] Error loading trades: {e}")
            return {"open": {}, "closed": []}

    def refresh(self):
        """Reload trade data"""
        self.trades_data = self._load_trades()
        self.closed_trades = self.trades_data.get("closed", [])
        self.open_trades = self.trades_data.get("open", {})

    def filter_by_days(self, trades: List[Dict], days: Optional[int]) -> List[Dict]:
        """Filter trades by date range"""
        if days is None:
            return trades

        cutoff = datetime.now().timestamp() - (days * 86400)
        return [t for t in trades if t.get("timestamp", 0) > cutoff]

    # ========== RISK-ADJUSTED RETURNS ==========

    def sharpe_ratio(self, days: Optional[int] = None, risk_free_rate: float = 0.02) -> float:
        """
        Sharpe Ratio = (Return - Risk Free Rate) / Standard Deviation
        Measures risk-adjusted return (annualized)

        Args:
            days: Optional lookback period
            risk_free_rate: Annual risk-free rate (default 2%)

        Returns:
            Sharpe ratio (higher is better, >1 is good, >2 is excellent)
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if len(trades) < 2:
            return 0.0

        # Calculate daily returns
        returns = []
        for trade in trades:
            invested = trade.get("total_invested_eur") or trade.get("initial_invested_eur") or 1
            profit = trade.get("profit", 0)
            ret = profit / invested if invested > 0 else 0
            returns.append(ret)

        if not returns:
            return 0.0

        avg_return = np.mean(returns)
        std_dev = np.std(returns)

        if std_dev == 0:
            return 0.0

        # Annualize (assuming ~250 trading days)
        daily_rf = (1 + risk_free_rate) ** (1 / 250) - 1
        annualized_return = avg_return * 250
        annualized_std = std_dev * np.sqrt(250)
        annualized_rf = risk_free_rate

        sharpe = (annualized_return - annualized_rf) / annualized_std
        return round(sharpe, 3)

    def sortino_ratio(self, days: Optional[int] = None, risk_free_rate: float = 0.02) -> float:
        """
        Sortino Ratio = (Return - Risk Free Rate) / Downside Deviation
        Like Sharpe but only penalizes downside volatility

        Returns:
            Sortino ratio (higher is better, typically higher than Sharpe)
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if len(trades) < 2:
            return 0.0

        # Calculate returns
        returns = []
        for trade in trades:
            invested = trade.get("total_invested_eur") or trade.get("initial_invested_eur") or 1
            profit = trade.get("profit", 0)
            ret = profit / invested if invested > 0 else 0
            returns.append(ret)

        if not returns:
            return 0.0

        avg_return = np.mean(returns)

        # Only consider downside (negative) returns
        downside_returns = [r for r in returns if r < 0]
        if not downside_returns:
            return float("inf") if avg_return > 0 else 0.0

        downside_dev = np.std(downside_returns)

        if downside_dev == 0:
            return 0.0

        # Annualize
        daily_rf = (1 + risk_free_rate) ** (1 / 250) - 1
        annualized_return = avg_return * 250
        annualized_downside = downside_dev * np.sqrt(250)

        sortino = (annualized_return - risk_free_rate) / annualized_downside
        return round(sortino, 3)

    def calmar_ratio(self, days: Optional[int] = None) -> float:
        """
        Calmar Ratio = Annual Return / Maximum Drawdown
        Measures return per unit of drawdown risk

        Returns:
            Calmar ratio (higher is better, >3 is good)
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return 0.0

        # Calculate total return
        total_profit = sum(t.get("profit", 0) for t in trades)
        total_invested = sum(t.get("total_invested_eur", 0) or t.get("initial_invested_eur", 0) or 0 for t in trades)

        if total_invested == 0:
            return 0.0

        # Annualize return (based on time period)
        first_ts = min(t.get("timestamp", float("inf")) for t in trades)
        last_ts = max(t.get("timestamp", 0) for t in trades)
        days_elapsed = (last_ts - first_ts) / 86400
        years = max(days_elapsed / 365, 1 / 365)  # Minimum 1 day

        annual_return = (total_profit / total_invested) / years if total_invested > 0 else 0

        # Calculate max drawdown - returns (eur, pct, recovery_days)
        max_dd_eur, _, _ = self.max_drawdown(days)

        if max_dd_eur == 0:
            return float("inf") if annual_return > 0 else 0.0

        calmar = annual_return / (max_dd_eur / total_invested) if total_invested > 0 else 0
        return round(calmar, 3)

    # ========== DRAWDOWN ANALYSIS ==========

    def max_drawdown(self, days: Optional[int] = None) -> Tuple[float, float, int]:
        """
        Maximum Drawdown Analysis

        Returns:
            (drawdown_eur, drawdown_pct, recovery_days)
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return (0.0, 0.0, 0)

        # Sort by timestamp
        sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

        cumulative = 0
        peak = 0
        max_dd_eur = 0
        max_dd_pct = 0
        dd_start_idx = 0
        dd_end_idx = 0
        in_drawdown = False

        for idx, trade in enumerate(sorted_trades):
            cumulative += trade.get("profit", 0)

            if cumulative > peak:
                peak = cumulative
                in_drawdown = False
            else:
                if not in_drawdown:
                    dd_start_idx = idx
                    in_drawdown = True

                drawdown = peak - cumulative
                if drawdown > max_dd_eur:
                    max_dd_eur = drawdown
                    dd_end_idx = idx
                    max_dd_pct = (drawdown / peak * 100) if peak > 0 else 0

        # Calculate recovery time
        recovery_days = 0
        if dd_end_idx > dd_start_idx:
            start_ts = sorted_trades[dd_start_idx].get("timestamp", 0)
            end_ts = sorted_trades[dd_end_idx].get("timestamp", 0)
            recovery_days = int((end_ts - start_ts) / 86400)

        return (round(max_dd_eur, 2), round(max_dd_pct, 2), recovery_days)

    def average_drawdown(self, days: Optional[int] = None) -> Tuple[float, float]:
        """
        Average drawdown across all drawdown periods

        Returns:
            (avg_dd_eur, avg_dd_pct)
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return (0.0, 0.0)

        sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

        cumulative = 0
        peak = 0
        drawdowns = []
        current_dd = 0

        for trade in sorted_trades:
            cumulative += trade.get("profit", 0)

            if cumulative > peak:
                if current_dd > 0:
                    drawdowns.append(current_dd)
                    current_dd = 0
                peak = cumulative
            else:
                current_dd = peak - cumulative

        if current_dd > 0:
            drawdowns.append(current_dd)

        if not drawdowns:
            return (0.0, 0.0)

        avg_dd_eur = float(np.mean(drawdowns))
        avg_dd_pct = float(np.mean([dd / peak * 100 if peak > 0 else 0 for dd in drawdowns]))

        return round(avg_dd_eur, 2), round(avg_dd_pct, 2)

    def drawdown_duration(self, days: Optional[int] = None) -> Dict[str, int]:
        """
        Drawdown duration statistics

        Returns:
            Dict with max, avg, and current drawdown days
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {"max_days": 0, "avg_days": 0, "current_days": 0}

        sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

        cumulative = 0
        peak = 0
        peak_ts = sorted_trades[0].get("timestamp", 0)
        durations = []
        current_dd_start = None

        for trade in sorted_trades:
            ts = trade.get("timestamp", 0)
            cumulative += trade.get("profit", 0)

            if cumulative > peak:
                if current_dd_start:
                    duration = int((ts - current_dd_start) / 86400)
                    durations.append(duration)
                    current_dd_start = None
                peak = cumulative
                peak_ts = ts
            else:
                if current_dd_start is None:
                    current_dd_start = peak_ts

        # Current drawdown
        current_days = 0
        if current_dd_start:
            current_days = int((datetime.now().timestamp() - current_dd_start) / 86400)

        return {
            "max_days": max(durations) if durations else 0,
            "avg_days": int(np.mean(durations)) if durations else 0,
            "current_days": current_days,
        }

    # ========== WIN/LOSS STREAKS ==========

    def win_loss_streaks(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze winning and losing streaks

        Returns:
            Dict with current, max win/loss streaks and distribution
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {
                "current_streak": 0,
                "current_type": "none",
                "max_win_streak": 0,
                "max_loss_streak": 0,
                "avg_win_streak": 0.0,
                "avg_loss_streak": 0.0,
                "streak_distribution": [],
            }

        sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

        current_streak = 0
        current_type = "none"
        max_win_streak = 0
        max_loss_streak = 0
        win_streaks = []
        loss_streaks = []
        temp_streak = 0
        temp_type = None

        for trade in sorted_trades:
            profit = trade.get("profit", 0)
            is_win = profit > 0

            if temp_type is None:
                temp_type = "win" if is_win else "loss"
                temp_streak = 1
            elif (temp_type == "win" and is_win) or (temp_type == "loss" and not is_win):
                temp_streak += 1
            else:
                # Streak ended
                if temp_type == "win":
                    win_streaks.append(temp_streak)
                    max_win_streak = max(max_win_streak, temp_streak)
                else:
                    loss_streaks.append(temp_streak)
                    max_loss_streak = max(max_loss_streak, temp_streak)

                temp_type = "win" if is_win else "loss"
                temp_streak = 1

        # Last streak (still ongoing)
        if temp_type:
            current_streak = temp_streak
            current_type = temp_type
            if temp_type == "win":
                max_win_streak = max(max_win_streak, temp_streak)
            else:
                max_loss_streak = max(max_loss_streak, temp_streak)

        return {
            "current_streak": current_streak,
            "current_type": current_type,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "avg_win_streak": round(np.mean(win_streaks), 1) if win_streaks else 0.0,
            "avg_loss_streak": round(np.mean(loss_streaks), 1) if loss_streaks else 0.0,
            "streak_distribution": {"wins": win_streaks, "losses": loss_streaks},
        }

    # ========== MAE/MFE ANALYSIS ==========

    def mae_mfe_analysis(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Maximum Adverse Excursion (MAE) / Maximum Favorable Excursion (MFE)
        Analyzes how far trades moved against/for you before closing

        Note: Requires trade_log to store lowest_price and highest_price

        Returns:
            Dict with MAE/MFE statistics
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {"avg_mae_pct": 0.0, "avg_mfe_pct": 0.0, "mae_mfe_ratio": 0.0, "trades_analyzed": 0}

        mae_values = []
        mfe_values = []

        for trade in trades:
            buy_price = trade.get("buy_price", 0)
            sell_price = trade.get("sell_price", 0)
            lowest_price = trade.get("lowest_price")  # Lowest price during trade
            highest_price = trade.get("highest_price")  # Highest price during trade

            if not all([buy_price, sell_price, highest_price]):
                continue

            # MAE: Maximum Adverse Excursion (worst drawdown)
            if lowest_price and buy_price > 0:
                mae_pct = ((lowest_price - buy_price) / buy_price) * 100
                mae_values.append(mae_pct)

            # MFE: Maximum Favorable Excursion (best peak)
            if highest_price and buy_price > 0:
                mfe_pct = ((highest_price - buy_price) / buy_price) * 100
                mfe_values.append(mfe_pct)

        if not mae_values or not mfe_values:
            return {
                "avg_mae_pct": 0.0,
                "avg_mfe_pct": 0.0,
                "mae_mfe_ratio": 0.0,
                "trades_analyzed": 0,
                "note": "Requires lowest_price and highest_price in trade_log",
            }

        avg_mae = np.mean([abs(m) for m in mae_values])
        avg_mfe = np.mean(mfe_values)
        ratio = avg_mfe / avg_mae if avg_mae > 0 else 0

        return {
            "avg_mae_pct": round(avg_mae, 2),
            "avg_mfe_pct": round(avg_mfe, 2),
            "mae_mfe_ratio": round(ratio, 2),
            "trades_analyzed": len(mae_values),
            "interpretation": "Ratio > 2 suggests good trade management",
        }

    # ========== TIME-BASED ANALYSIS ==========

    def time_in_trade_stats(self, days: Optional[int] = None) -> Dict[str, float]:
        """
        Statistics on how long trades are held

        Returns:
            Dict with min, max, avg, median hold times in hours
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {"min_hours": 0, "max_hours": 0, "avg_hours": 0, "median_hours": 0}

        hold_times = []
        for trade in trades:
            opened_ts = trade.get("opened_ts") or trade.get("timestamp", 0)
            closed_ts = trade.get("timestamp", 0)

            if opened_ts and closed_ts and closed_ts > opened_ts:
                hours = (closed_ts - opened_ts) / 3600
                hold_times.append(hours)

        if not hold_times:
            return {"min_hours": 0, "max_hours": 0, "avg_hours": 0, "median_hours": 0}

        return {
            "min_hours": round(min(hold_times), 1),
            "max_hours": round(max(hold_times), 1),
            "avg_hours": round(np.mean(hold_times), 1),
            "median_hours": round(np.median(hold_times), 1),
        }

    def performance_by_weekday(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """
        Performance statistics by day of week

        Returns:
            Dict mapping weekday name to stats
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {}

        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        by_weekday = defaultdict(lambda: {"trades": 0, "profit": 0, "wins": 0})

        for trade in trades:
            ts = trade.get("timestamp", 0)
            if not ts:
                continue

            dt = datetime.fromtimestamp(ts)
            weekday = weekdays[dt.weekday()]

            by_weekday[weekday]["trades"] += 1
            by_weekday[weekday]["profit"] += trade.get("profit", 0)
            if trade.get("profit", 0) > 0:
                by_weekday[weekday]["wins"] += 1

        # Calculate rates
        result = {}
        for day in weekdays:
            if day in by_weekday:
                data = by_weekday[day]
                result[day] = {
                    "trades": data["trades"],
                    "profit": round(data["profit"], 2),
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1) if data["trades"] > 0 else 0,
                    "avg_profit": round(data["profit"] / data["trades"], 2) if data["trades"] > 0 else 0,
                }

        return result

    def performance_by_hour(self, days: Optional[int] = None) -> Dict[int, Dict]:
        """
        Performance statistics by hour of day

        Returns:
            Dict mapping hour (0-23) to stats
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {}

        by_hour = defaultdict(lambda: {"trades": 0, "profit": 0, "wins": 0})

        for trade in trades:
            ts = trade.get("timestamp", 0)
            if not ts:
                continue

            dt = datetime.fromtimestamp(ts)
            hour = dt.hour

            by_hour[hour]["trades"] += 1
            by_hour[hour]["profit"] += trade.get("profit", 0)
            if trade.get("profit", 0) > 0:
                by_hour[hour]["wins"] += 1

        result = {}
        for hour in range(24):
            if hour in by_hour:
                data = by_hour[hour]
                result[hour] = {
                    "trades": data["trades"],
                    "profit": round(data["profit"], 2),
                    "win_rate": round((data["wins"] / data["trades"]) * 100, 1) if data["trades"] > 0 else 0,
                }

        return result

    # ========== TRADE QUALITY METRICS ==========

    def trade_efficiency(self, days: Optional[int] = None) -> Dict[str, float]:
        """
        Measure trade execution efficiency

        Returns:
            Dict with efficiency metrics
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return {"avg_slippage_pct": 0.0, "execution_score": 0.0, "optimal_exits": 0.0}

        # Calculate how close exits were to highest_price (optimal exit)
        optimal_exits = 0
        total_with_high = 0

        for trade in trades:
            sell_price = trade.get("sell_price", 0)
            highest_price = trade.get("highest_price")

            if sell_price and highest_price and highest_price > 0:
                total_with_high += 1
                exit_efficiency = (sell_price / highest_price) * 100
                if exit_efficiency >= 95:  # Within 5% of peak
                    optimal_exits += 1

        optimal_exit_rate = (optimal_exits / total_with_high * 100) if total_with_high > 0 else 0

        return {
            "optimal_exit_rate": round(optimal_exit_rate, 1),
            "trades_analyzed": total_with_high,
            "interpretation": ">70% suggests good exit timing",
        }

    def risk_reward_ratio(self, days: Optional[int] = None) -> float:
        """
        Average risk/reward ratio across all trades

        Returns:
            Average R:R ratio
        """
        trades = self.filter_by_days(self.closed_trades, days)
        if not trades:
            return 0.0

        ratios = []
        for trade in trades:
            profit = trade.get("profit", 0)
            invested = trade.get("total_invested_eur") or trade.get("initial_invested_eur") or 0

            if invested > 0:
                ratio = abs(profit / invested)
                ratios.append(ratio)

        if not ratios:
            return 0.0

        return round(np.mean(ratios), 2)

    # ========== COMPREHENSIVE REPORT ==========

    def generate_report(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate comprehensive performance report

        Returns:
            Dict with all metrics
        """
        return {
            "generated_at": datetime.now().isoformat(),
            "period_days": days or "all_time",
            "total_trades": len(self.filter_by_days(self.closed_trades, days)),
            # Risk-adjusted returns
            "risk_adjusted": {
                "sharpe_ratio": self.sharpe_ratio(days),
                "sortino_ratio": self.sortino_ratio(days),
                "calmar_ratio": self.calmar_ratio(days),
            },
            # Drawdown analysis
            "drawdown": {
                "max_drawdown": self.max_drawdown(days),
                "avg_drawdown": self.average_drawdown(days),
                "duration": self.drawdown_duration(days),
            },
            # Streaks
            "streaks": self.win_loss_streaks(days),
            # MAE/MFE
            "mae_mfe": self.mae_mfe_analysis(days),
            # Time analysis
            "time_analysis": {
                "hold_times": self.time_in_trade_stats(days),
                "by_weekday": self.performance_by_weekday(days),
                "by_hour": self.performance_by_hour(days),
            },
            # Trade quality
            "quality": {
                "efficiency": self.trade_efficiency(days),
                "risk_reward_ratio": self.risk_reward_ratio(days),
            },
        }

    def save_report(self, filepath: str = "reports/advanced_metrics.json", days: Optional[int] = None):
        """Save comprehensive report to JSON file"""
        report = self.generate_report(days)

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"[ADVANCED_METRICS] Report saved to {filepath}")
        return filepath


# ========== CLI INTERFACE ==========

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate advanced performance metrics")
    parser.add_argument("--days", type=int, help="Lookback period in days (default: all time)")
    parser.add_argument("--output", default="reports/advanced_metrics.json", help="Output file path")
    parser.add_argument("--print", action="store_true", help="Print report to console")

    args = parser.parse_args()

    metrics = AdvancedMetrics()
    report = metrics.generate_report(args.days)

    if args.print:
        import pprint

        pprint.pprint(report)

    metrics.save_report(args.output, args.days)

    print("\n✅ Advanced metrics generated successfully")
    print(f"📊 Sharpe Ratio: {report['risk_adjusted']['sharpe_ratio']}")
    print(f"📉 Max Drawdown: €{report['drawdown']['max_drawdown'][0]} ({report['drawdown']['max_drawdown'][1]}%)")
    print(f"🔥 Current Streak: {report['streaks']['current_streak']} {report['streaks']['current_type']}s")
