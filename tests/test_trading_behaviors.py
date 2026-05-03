import json
import math
import importlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from modules.trading_dca import DCAContext, DCAManager, DCASettings
from modules.trading_liquidation import LiquidationContext, LiquidationManager
from modules import storage


def _make_candles(close_price: float = 90.0, count: int = 60) -> List[List[float]]:
    candles: List[List[float]] = []
    for i in range(count):
        price = close_price - (count - i) * 0.01
        candles.append([0, 0, price * 1.01, price * 0.99, price, 1.0])
    return candles


def test_dca_fixed_updates_weighted_average():
    place_calls: List[Any] = []
    saves: Dict[str, int] = {"count": 0}

    def place_buy(market: str, eur_amount: float, price: float, **kwargs) -> Dict[str, Any]:
        place_calls.append((market, eur_amount, price))
        # FIX #073: return a FILLED response so the new placed/filled split treats it as a market fill
        return {"orderId": "ok", "status": "filled",
                "filledAmount": str(eur_amount / price),
                "filledAmountQuote": str(eur_amount)}

    ctx = DCAContext(
        config={"MAX_TOTAL_EXPOSURE_EUR": 100, "RSI_MIN_BUY": 30},
        safe_call=lambda fn, params=None: fn(params) if params is not None else fn(),
        bitvavo=None,
        log=lambda msg: None,
        current_open_exposure_eur=lambda: 10.0,
        get_min_order_size=lambda market: 0.001,
        place_buy=place_buy,
        is_order_success=lambda result: True,
        save_trades=lambda **kw: saves.__setitem__("count", saves["count"] + 1),
        get_candles=lambda market, interval, limit: _make_candles(90.0, 60),
        close_prices=lambda candles: [float(row[4]) for row in candles],
        rsi=lambda prices, period: 25.0,
        trade_log_path="test_dca_fixed.json",
    )
    manager = DCAManager(ctx)
    trade = {"buy_price": 100.0, "amount": 0.1, "dca_buys": 0}
    settings = DCASettings(
        enabled=True,
        dynamic=False,
        max_buys=1,
        drop_pct=0.05,
        step_multiplier=1.0,
        amount_eur=20.0,
        size_multiplier=1.0,
    )

    manager.handle_trade(
        "BTC-EUR",
        trade,
        current_price=90.0,
        settings=settings,
        partial_tp_levels=[0.02, 0.04],
    )

    expected_amount = 0.1 + (20.0 / 90.0)
    assert place_calls == [("BTC-EUR", 20.0, 90.0)]
    assert math.isclose(trade["amount"], expected_amount, rel_tol=1e-6)
    weighted_buy = ((100.0 * 0.1) + (90.0 * (20.0 / 90.0))) / expected_amount
    assert math.isclose(trade["buy_price"], weighted_buy, rel_tol=1e-6)
    assert trade["dca_buys"] == 1
    assert trade["last_dca_price"] == pytest.approx(90.0)
    assert saves["count"] == 1


def test_dca_respects_exposure_headroom():
    place_calls: List[Any] = []

    def place_buy(market: str, eur_amount: float, price: float, **kwargs) -> Dict[str, Any]:
        place_calls.append((market, eur_amount, price))
        # FIX #073: filled response
        return {"orderId": "ok", "status": "filled",
                "filledAmount": str(eur_amount / price),
                "filledAmountQuote": str(eur_amount)}

    ctx = DCAContext(
        config={"MAX_TOTAL_EXPOSURE_EUR": 100, "RSI_MIN_BUY": 30},
        safe_call=lambda fn, params=None: fn(params) if params is not None else fn(),
        bitvavo=None,
        log=lambda msg: None,
        current_open_exposure_eur=lambda: 99.0,
        get_min_order_size=lambda market: 0.001,
        place_buy=place_buy,
        is_order_success=lambda result: True,
        save_trades=lambda **kw: None,
        get_candles=lambda market, interval, limit: _make_candles(90.0, 60),
        close_prices=lambda candles: [float(row[4]) for row in candles],
        rsi=lambda prices, period: 25.0,
        trade_log_path="test_dca_headroom.json",
    )
    manager = DCAManager(ctx)
    trade = {"buy_price": 100.0, "amount": 0.1, "dca_buys": 0}
    settings = DCASettings(
        enabled=True,
        dynamic=False,
        max_buys=1,
        drop_pct=0.05,
        step_multiplier=1.0,
        amount_eur=20.0,
        size_multiplier=1.0,
    )

    manager.handle_trade(
        "ETH-EUR",
        trade,
        current_price=90.0,
        settings=settings,
        partial_tp_levels=[0.02],
    )

    # Headroom only allows 1 EUR extra exposure
    assert place_calls == [("ETH-EUR", 1.0, 90.0)]
    expected_amount = 0.1 + (1.0 / 90.0)
    assert math.isclose(trade["amount"], expected_amount, rel_tol=1e-6)


def test_saldo_flood_guard_forces_losses(tmp_path):
    """Legacy flood guard (FLOODGUARD.enabled=true) now delegates to safe guard — NO force-sells."""
    pending_path = tmp_path / "pending_saldo.json"
    pending_path.write_text(json.dumps([1] * 6), encoding="utf-8")

    logs: List[Any] = []

    def log(msg, level="info"):
        logs.append((msg, level))

    prices = {"BTC-EUR": 80.0, "ETH-EUR": 40.0}

    def get_price(market: str) -> float:
        return prices.get(market)

    sold: List[Any] = []

    def place_sell(market: str, amount: float) -> bool:
        sold.append((market, amount))
        return True

    save_calls: Dict[str, int] = {"count": 0}

    ctx = LiquidationContext(
        config={
            "FLOODGUARD": {"enabled": True},
            "SALDO_FLOOD_THRESHOLD": 5,
            "SALDO_FLOOD_MAX_FORCE_CLOSE": 2,
            "SALDO_FLOOD_MIN_LOSS_PCT": 0.05,
            "SALDO_GUARD": {"enabled": True, "threshold": 5, "cooldown_seconds": 300},
        },
        log=log,
        get_current_price=get_price,
        place_sell=place_sell,
        realized_profit=lambda buy, sell, amount: (sell - buy) * amount,
        save_trades=lambda **kw: save_calls.__setitem__("count", save_calls["count"] + 1),
        cleanup_trades=lambda: save_calls.__setitem__("cleanup", save_calls.get("cleanup", 0) + 1),
        pending_saldo_path=str(pending_path),
    )
    manager = LiquidationManager(ctx)
    open_trades = {
        "BTC-EUR": {"buy_price": 100.0, "amount": 0.5, "invested_eur": 50.0, "total_invested_eur": 50.0, "initial_invested_eur": 50.0, "partial_tp_returned_eur": 0.0},
        "ETH-EUR": {"buy_price": 50.0, "amount": 1.0, "invested_eur": 50.0, "total_invested_eur": 50.0, "initial_invested_eur": 50.0, "partial_tp_returned_eur": 0.0},
    }
    closed_trades: List[Dict[str, Any]] = []
    market_profits: Dict[str, float] = {}

    manager.saldo_flood_guard(open_trades, closed_trades, market_profits)

    # Legacy flood guard is now permanently disabled — NO positions sold
    assert len(sold) == 0, "Legacy flood guard should NOT sell any positions"
    assert len(open_trades) == 2, "All positions must remain open"
    assert len(closed_trades) == 0, "No trades should be closed"
    assert any(level == "warning" for _, level in logs), "Should log warning about delegation"


def test_smart_saldo_guard_no_force_sell(tmp_path):
    """New smart saldo guard pauses entries + cancels buys, does NOT sell positions."""
    pending_path = tmp_path / "pending_saldo.json"
    pending_path.write_text(json.dumps([1] * 6), encoding="utf-8")

    logs: List[Any] = []
    cancel_calls = {"count": 0}
    refresh_calls = {"count": 0}

    ctx = LiquidationContext(
        config={
            "FLOODGUARD": {"enabled": False},
            "SALDO_GUARD": {"enabled": True, "threshold": 5, "cancel_pending_buys": True, "force_refresh_balance": True, "cooldown_seconds": 300},
        },
        log=lambda msg, level="info": logs.append((msg, level)),
        get_current_price=lambda m: 80.0,
        place_sell=lambda m, a: False,
        realized_profit=lambda buy, sell, amount: 0.0,
        save_trades=lambda **kw: None,
        cleanup_trades=lambda: None,
        pending_saldo_path=str(pending_path),
        cancel_open_buys_fn=lambda: cancel_calls.__setitem__("count", cancel_calls["count"] + 1),
        refresh_balance_fn=lambda: refresh_calls.__setitem__("count", refresh_calls["count"] + 1),
    )
    manager = LiquidationManager(ctx)
    open_trades = {"BTC-EUR": {"buy_price": 100.0, "amount": 0.5}}
    closed_trades: List[Dict[str, Any]] = []
    market_profits: Dict[str, float] = {}

    manager.saldo_flood_guard(open_trades, closed_trades, market_profits)

    # Positions NOT sold
    assert "BTC-EUR" in open_trades
    assert len(closed_trades) == 0
    # Buy orders cancelled and balance refreshed
    assert cancel_calls["count"] == 1
    assert refresh_calls["count"] == 1
    # Cooldown set
    cooldown = ctx.config.get("_SALDO_COOLDOWN_UNTIL", 0)
    assert cooldown > 0


def test_ai_auto_apply_respects_cooldown(tmp_path, monkeypatch):
    config_path = tmp_path / "bot_config.json"
    history_path = tmp_path / "ai_changes.json"

    initial_config = {
        "AI_AUTO_APPLY": True,
        "AI_ALLOW_PARAMS": ["DEFAULT_TRAILING"],
        "AI_APPLY_COOLDOWN_MIN": 30,
        "DEFAULT_TRAILING": 0.01,
    }
    config_path.write_text(json.dumps(initial_config), encoding="utf-8")

    storage.configure(tmp_path / "data")
    ai_supervisor = importlib.reload(importlib.import_module("ai.ai_supervisor"))
    try:
        monkeypatch.setattr(ai_supervisor, "CONFIG_FILE", str(config_path))
        monkeypatch.setattr(ai_supervisor, "CHANGE_HISTORY_FILE", str(history_path))
        monkeypatch.setattr(ai_supervisor, "log", lambda *args, **kwargs: None)

        current_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        def fake_now():
            return current_time

        monkeypatch.setattr(ai_supervisor, "_utc_now", fake_now)

        def fake_time() -> float:
            return current_time.timestamp()

        monkeypatch.setattr(ai_supervisor.time, "time", fake_time)
        ai_supervisor._last_apply.clear()

        first = [{"param": "DEFAULT_TRAILING", "from": 0.01, "to": 0.012, "reason": "test"}]
        applied = ai_supervisor.auto_apply_if_enabled(first)
        assert applied is True

        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        assert cfg["DEFAULT_TRAILING"] == pytest.approx(0.012)

        with open(history_path, "r", encoding="utf-8") as fh:
            history = json.load(fh)
        assert len(history) == 1

        second = [{"param": "DEFAULT_TRAILING", "from": cfg["DEFAULT_TRAILING"], "to": 0.02}]
        applied_second = ai_supervisor.auto_apply_if_enabled(second)
        assert applied_second is False

        with open(config_path, "r", encoding="utf-8") as fh:
            cfg_after_second = json.load(fh)
        assert cfg_after_second["DEFAULT_TRAILING"] == pytest.approx(0.012)

        current_time += timedelta(minutes=31)
        applied_third = ai_supervisor.auto_apply_if_enabled(second)
        assert applied_third is True

        with open(config_path, "r", encoding="utf-8") as fh:
            final_cfg = json.load(fh)
        assert final_cfg["DEFAULT_TRAILING"] == pytest.approx(0.02)

        with open(history_path, "r", encoding="utf-8") as fh:
            final_history = json.load(fh)
        assert len(final_history) == 2
    finally:
        storage.reset()
