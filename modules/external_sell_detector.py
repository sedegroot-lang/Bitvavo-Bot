"""
External Sell Detector

Monitors Bitvavo for sells that happened outside the bot and resets trades accordingly.
This prevents invested_eur from accumulating old DCA history after manual sells.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from core.trade_investment import set_initial as _ti_set_initial

logger = logging.getLogger(__name__)


def detect_external_sells(bitvavo_client, trade_log_path: Path, markets: list[str]) -> dict[str, dict]:
    """
    Check if any open trades have been sold externally.

    Args:
        bitvavo_client: Bitvavo API client
        trade_log_path: Path to trade_log.json
        markets: List of markets to check

    Returns:
        Dict of {market: {last_sell_ts, buys_after_sell, new_invested, new_opened_ts}}
    """
    results = {}

    # Load current trade log
    with open(trade_log_path, "r", encoding="utf-8") as f:
        trade_log = json.load(f)

    open_trades = trade_log.get("open", {})

    for market in markets:
        if market not in open_trades:
            continue

        trade = open_trades[market]
        current_opened_ts = float(trade.get("opened_ts", 0))

        try:
            # Get trade history
            trades_response = bitvavo_client.trades(market, {"limit": 500})

            if not trades_response or isinstance(trades_response, dict):
                continue

            # Find last sell
            last_sell_ts = None
            last_sell_trade = None
            for t in sorted(
                trades_response,
                key=lambda x: (
                    float(x.get("timestamp", 0) or 0) / (1000 if float(x.get("timestamp", 0) or 0) > 10000000000 else 1)
                ),
                reverse=True,
            ):
                if str(t.get("side", "")).lower() == "sell":
                    ts_raw = t.get("timestamp", 0)
                    last_sell_ts = float(ts_raw) / 1000 if ts_raw > 10000000000 else float(ts_raw)
                    last_sell_trade = t
                    break

            # If there's a sell AFTER our opened_ts, we need to reset
            if last_sell_ts and last_sell_ts > current_opened_ts:
                logger.warning(f"[{market}] External sell detected at {datetime.fromtimestamp(last_sell_ts)}")

                # Count buys after that sell
                buys_after = []
                base_currency = market.split("-")[0].upper()

                for t in trades_response:
                    ts_raw = t.get("timestamp", 0)
                    ts = float(ts_raw) / 1000 if ts_raw > 10000000000 else float(ts_raw)

                    if str(t.get("side", "")).lower() == "buy" and ts > last_sell_ts:
                        amount = float(t.get("amount", 0))
                        fee = float(t.get("fee", 0))
                        fee_currency = str(t.get("feeCurrency", "")).upper()

                        if fee_currency == base_currency:
                            amount = max(0, amount - fee)

                        cost = float(t.get("price", 0)) * float(t.get("amount", 0))
                        if fee_currency == "EUR":
                            cost += fee

                        buys_after.append(
                            {"timestamp": ts, "amount": amount, "cost": cost, "price": float(t.get("price", 0))}
                        )

                if buys_after:
                    buys_after.sort(key=lambda x: x["timestamp"])

                    new_invested = sum(b["cost"] for b in buys_after)
                    new_opened_ts = buys_after[0]["timestamp"]
                    new_dca_count = max(0, len(buys_after) - 1)

                    sell_snapshot = {}
                    if last_sell_trade:
                        try:
                            sell_amount = float(last_sell_trade.get("amount", 0) or 0)
                            sell_price = float(last_sell_trade.get("price", 0) or 0)
                            sell_fee = float(last_sell_trade.get("fee", 0) or 0)
                            fee_currency = str(last_sell_trade.get("feeCurrency", "")).upper()
                            order_id = (
                                last_sell_trade.get("orderId")
                                or last_sell_trade.get("orderID")
                                or last_sell_trade.get("order_id")
                            )
                            base_currency = market.split("-")[0].upper()
                            net_amount = sell_amount
                            if fee_currency == base_currency:
                                net_amount = max(0, sell_amount - sell_fee)
                            gross = sell_price * net_amount
                            net_proceeds = gross
                            if fee_currency == "EUR":
                                net_proceeds = max(0.0, gross - sell_fee)
                            sell_snapshot = {
                                "sell_amount": net_amount,
                                "sell_price": sell_price,
                                "sell_order_id": order_id,
                                "sell_gross": gross,
                                "sell_net": net_proceeds,
                            }
                        except Exception:
                            sell_snapshot = {}

                    results[market] = {
                        "last_sell_ts": last_sell_ts,
                        "last_sell_date": datetime.fromtimestamp(last_sell_ts).strftime("%Y-%m-%d %H:%M"),
                        "buys_after_sell": len(buys_after),
                        "new_invested": new_invested,
                        "new_opened_ts": new_opened_ts,
                        "new_opened_date": datetime.fromtimestamp(new_opened_ts).strftime("%Y-%m-%d %H:%M"),
                        "new_dca_count": new_dca_count,
                        "new_original_price": buys_after[0]["price"],
                        "sell_snapshot": sell_snapshot,
                    }

                    logger.info(
                        f"[{market}] Reset needed: new invested=EUR{new_invested:.2f}, opened={results[market]['new_opened_date']}"
                    )

        except Exception as e:
            logger.error(f"[{market}] Error checking external sells: {e}")
            continue

    return results


def apply_external_sell_resets(trade_log_path: Path, resets: dict[str, dict]) -> int:
    """
    Apply trade resets for external sells.

    Args:
        trade_log_path: Path to trade_log.json
        resets: Dict from detect_external_sells()

    Returns:
        Number of trades reset
    """
    if not resets:
        return 0

    with open(trade_log_path, "r", encoding="utf-8") as f:
        trade_log = json.load(f)

    open_trades = trade_log.get("open", {})
    count = 0

    for market, reset_data in resets.items():
        if market not in open_trades:
            continue

        trade = open_trades[market]
        sell_snapshot = reset_data.get("sell_snapshot") or {}
        if sell_snapshot.get("sell_price") and sell_snapshot.get("sell_amount"):
            try:
                total_invested = float(trade.get("total_invested_eur") or trade.get("invested_eur") or 0)
                if total_invested <= 0:
                    total_invested = float(trade.get("buy_price", 0) or 0) * float(trade.get("amount", 0) or 0)
                profit = float(sell_snapshot.get("sell_net", 0) or 0) - total_invested
                closed_entry = {
                    "market": market,
                    "buy_price": trade.get("buy_price", 0.0),
                    "buy_order_id": trade.get("buy_order_id"),
                    "sell_price": sell_snapshot.get("sell_price", 0.0),
                    "sell_order_id": sell_snapshot.get("sell_order_id"),
                    "amount": sell_snapshot.get("sell_amount", 0.0),
                    "profit": round(profit, 4),
                    "profit_calculated": round(profit, 4),
                    "total_invested": round(total_invested, 4),
                    "timestamp": reset_data.get("last_sell_ts", datetime.now().timestamp()),
                    "reason": "external_sell",
                    "profit_eur": round(profit, 4),
                    "sell_date": datetime.fromtimestamp(
                        reset_data.get("last_sell_ts", datetime.now().timestamp())
                    ).isoformat(),
                    "sell_reason": "external_sell",
                }
                trade_log.setdefault("closed", []).append(closed_entry)
            except Exception as e:
                logger.error(f"[{market}] Error adding external sell to trade_log: {e}")

        # Update trade — use TradeInvestment for invested_eur fields
        # Clear initial_invested_eur first so set_initial can write
        trade.pop("initial_invested_eur", None)
        _ti_set_initial(trade, reset_data["new_invested"], source=f"external_sell_{market}")
        trade["opened_ts"] = reset_data["new_opened_ts"]
        trade["dca_buys"] = reset_data["new_dca_count"]
        trade["original_buy_price"] = reset_data["new_original_price"]

        logger.info(
            f"[{market}] Trade reset applied: invested=EUR{reset_data['new_invested']:.2f}, opened={reset_data['new_opened_date']}"
        )
        count += 1

    # Save via trade_store (with validation + atomic write)
    backup_path = trade_log_path.parent / f"trade_log.json.bak.{int(datetime.now().timestamp())}"
    try:
        from modules.trade_store import save_snapshot

        save_snapshot(trade_log, str(trade_log_path), backup_path=str(backup_path))
    except ImportError:
        # Fallback if trade_store not available
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        with open(trade_log_path, "w", encoding="utf-8") as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)

    return count
