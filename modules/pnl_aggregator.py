"""
P/L Aggregator Module
Calculates total and daily profit/loss from trading activity.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def compute_total_pnl(
    open_trades: Dict[str, Any], closed_trades: List[Dict[str, Any]], last_prices: Dict[str, float]
) -> Tuple[float, float, float]:
    """
    Compute total P/L from all trades.

    Args:
        open_trades: Dictionary of open trades (market -> trade data)
        closed_trades: List of closed trades
        last_prices: Dictionary of current prices (market -> price)

    Returns:
        Tuple of (total_pnl, realized_pnl, unrealized_pnl)
    """
    realized_pnl = 0.0
    unrealized_pnl = 0.0

    # Calculate realized P/L from closed trades
    for trade in closed_trades:
        profit = trade.get("profit", 0)
        try:
            realized_pnl += float(profit)
        except (ValueError, TypeError):
            continue

    # Calculate unrealized P/L from open trades
    for market, trade in (open_trades or {}).items():
        try:
            # Get entry details
            amount = float(trade.get("amount", 0))
            entry_price = float(trade.get("buy_price", 0))
            invested = float(trade.get("invested_eur", 0) or trade.get("total_invested_eur", 0))

            # Use invested if available, otherwise calculate
            if invested <= 0:
                invested = amount * entry_price

            # Get current price
            current_price = last_prices.get(market, 0.0)
            if current_price <= 0:
                continue

            # Calculate current value
            current_value = amount * current_price

            # Calculate fees (approximate)
            fee_pct = 0.0025  # 0.25% taker fee
            entry_fee = invested * fee_pct
            exit_fee = current_value * fee_pct

            # Unrealized P/L = current value - invested - fees
            trade_pnl = current_value - invested - entry_fee - exit_fee
            unrealized_pnl += trade_pnl

        except (ValueError, TypeError, KeyError):
            continue

    total_pnl = realized_pnl + unrealized_pnl

    return total_pnl, realized_pnl, unrealized_pnl


def compute_pnl_today(
    open_trades: Dict[str, Any],
    closed_trades: List[Dict[str, Any]],
    last_prices: Dict[str, float],
    timezone_offset: int = 0,
) -> Tuple[float, float, float]:
    """
    Compute P/L for today only.

    Args:
        open_trades: Dictionary of open trades
        closed_trades: List of closed trades
        last_prices: Dictionary of current prices
        timezone_offset: Timezone offset in hours (default 0 = UTC)

    Returns:
        Tuple of (total_today, realized_today, unrealized_today)
    """
    # Get start of today in specified timezone
    now = datetime.now(timezone.utc) + timedelta(hours=timezone_offset)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day_utc = start_of_day - timedelta(hours=timezone_offset)
    start_ts = start_of_day_utc.timestamp()

    realized_today = 0.0

    # Calculate realized P/L from trades closed today
    for trade in closed_trades:
        # Check if trade was closed today
        exit_ts = trade.get("exit_ts") or trade.get("timestamp")
        if exit_ts is None:
            continue

        try:
            # Handle both float timestamps and ISO string timestamps
            if isinstance(exit_ts, (int, float)):
                exit_ts = float(exit_ts)
            elif isinstance(exit_ts, str):
                try:
                    dt = datetime.fromisoformat(exit_ts.replace("Z", "+00:00"))
                    exit_ts = dt.timestamp()
                except Exception:
                    exit_ts = float(exit_ts)  # Try parsing numeric string
            else:
                continue

            if exit_ts >= start_ts:
                profit = float(trade.get("profit", 0))
                realized_today += profit
        except (ValueError, TypeError):
            continue

    # For unrealized P/L today, we use current unrealized P/L from trades opened today
    unrealized_today = 0.0
    for market, trade in (open_trades or {}).items():
        # Check if trade was opened today
        entry_ts = trade.get("opened_ts") or trade.get("entry_ts")
        if entry_ts is None:
            timestamp_str = trade.get("timestamp")
            if timestamp_str:
                try:
                    if isinstance(timestamp_str, (int, float)):
                        entry_ts = float(timestamp_str)
                    else:
                        dt = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
                        entry_ts = dt.timestamp()
                except Exception:
                    continue
            else:
                continue

        try:
            entry_ts = float(entry_ts)
            if entry_ts >= start_ts:
                # Calculate unrealized P/L for this trade
                amount = float(trade.get("amount", 0))
                entry_price = float(trade.get("buy_price", 0))
                invested = float(trade.get("invested_eur", 0) or trade.get("total_invested_eur", 0))

                if invested <= 0:
                    invested = amount * entry_price

                current_price = last_prices.get(market, 0.0)
                if current_price <= 0:
                    continue

                current_value = amount * current_price
                fee_pct = 0.0025
                entry_fee = invested * fee_pct
                exit_fee = current_value * fee_pct

                trade_pnl = current_value - invested - entry_fee - exit_fee
                unrealized_today += trade_pnl

        except (ValueError, TypeError, KeyError):
            continue

    total_today = realized_today + unrealized_today

    return total_today, realized_today, unrealized_today


def load_trades_from_log(trade_log_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Load open and closed trades from trade log.

    Args:
        trade_log_path: Path to trade_log.json

    Returns:
        Tuple of (open_trades dict, closed_trades list)
    """
    try:
        with open(trade_log_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        open_trades = data.get("open", {})
        closed_trades = data.get("closed", [])

        return open_trades, closed_trades

    except Exception as e:
        print(f"Error loading trade log: {e}")
        return {}, []


def get_last_prices(markets: List[str], bitvavo_client: Optional[Any] = None) -> Dict[str, float]:
    """
    Fetch current prices for markets.

    Args:
        markets: List of market symbols
        bitvavo_client: Optional Bitvavo client instance

    Returns:
        Dictionary mapping market -> current price
    """
    prices = {}

    if bitvavo_client is None:
        # Try to get prices from a cached source if no client provided
        return prices

    try:
        # Fetch ticker prices for all markets
        for market in markets:
            try:
                ticker = bitvavo_client.tickerPrice({"market": market})
                price = float(ticker.get("price", 0))
                if price > 0:
                    prices[market] = price
            except Exception:
                continue

    except Exception as e:
        print(f"Error fetching prices: {e}")

    return prices


def compute_pnl_metrics(
    trade_log_path: Path, bitvavo_client: Optional[Any] = None, timezone_offset: int = 0
) -> Dict[str, Any]:
    """
    Compute comprehensive P/L metrics.

    Args:
        trade_log_path: Path to trade_log.json
        bitvavo_client: Optional Bitvavo client for price fetching
        timezone_offset: Timezone offset in hours

    Returns:
        Dictionary with P/L metrics
    """
    open_trades, closed_trades = load_trades_from_log(trade_log_path)

    # Get current prices for open positions
    markets = list(open_trades.keys())
    last_prices = get_last_prices(markets, bitvavo_client) if bitvavo_client else {}

    # Compute total P/L
    total_pnl, realized_pnl, unrealized_pnl = compute_total_pnl(open_trades, closed_trades, last_prices)

    # Compute today's P/L
    total_today, realized_today, unrealized_today = compute_pnl_today(
        open_trades, closed_trades, last_prices, timezone_offset
    )

    return {
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_today": round(total_today, 2),
        "realized_today": round(realized_today, 2),
        "unrealized_today": round(unrealized_today, 2),
        "open_positions": len(open_trades),
        "closed_trades": len(closed_trades),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
