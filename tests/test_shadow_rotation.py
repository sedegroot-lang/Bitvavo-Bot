"""Unit tests for bot.shadow_rotation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from bot import shadow_rotation as sr


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    p = tmp_path / "shadow_rotation.jsonl"
    monkeypatch.setattr(sr, "LOG_PATH", p)
    yield p


def _trade(buy_price=1.0, age_hours=72.0):
    return {
        "buy_price": buy_price,
        "amount": 10.0,
        "opened_ts": time.time() - age_hours * 3600,
    }


def test_no_rotation_when_slot_available():
    open_t = {"BTC-EUR": _trade()}
    cands = [{"market": "ETH-EUR", "score": 9.0}]
    out = sr.evaluate(open_t, cands, max_open_trades=4, current_prices={"BTC-EUR": 1.005})
    assert out == []


def test_no_rotation_when_candidate_score_too_low():
    open_t = {"BTC-EUR": _trade()}
    cands = [{"market": "ETH-EUR", "score": 7.0}]
    out = sr.evaluate(open_t, cands, max_open_trades=1, current_prices={"BTC-EUR": 1.005})
    assert out == []


def test_no_rotation_when_trade_too_young():
    open_t = {"BTC-EUR": _trade(age_hours=10)}
    cands = [{"market": "ETH-EUR", "score": 9.0}]
    out = sr.evaluate(open_t, cands, max_open_trades=1, current_prices={"BTC-EUR": 1.005})
    assert out == []


def test_no_rotation_when_trade_negative():
    open_t = {"BTC-EUR": _trade()}
    cands = [{"market": "ETH-EUR", "score": 9.0}]
    out = sr.evaluate(open_t, cands, max_open_trades=1, current_prices={"BTC-EUR": 0.99})
    assert out == []


def test_rotation_logged_when_all_conditions_met(isolated_log):
    open_t = {"BTC-EUR": _trade(buy_price=1.0, age_hours=72)}
    cands = [{"market": "ETH-EUR", "score": 9.0, "expected_pct": 5.0}]
    out = sr.evaluate(
        open_t, cands,
        max_open_trades=1,
        current_prices={"BTC-EUR": 1.005},
        price_history_6h={"BTC-EUR": [1.005, 1.0051, 1.0049, 1.005]},
    )
    assert len(out) == 1
    s = out[0]
    assert s["close_market"] == "BTC-EUR"
    assert s["candidate_market"] == "ETH-EUR"
    assert isolated_log.exists()
    rows = [json.loads(l) for l in isolated_log.read_text().splitlines()]
    assert len(rows) == 1


def test_rotation_blocked_when_market_still_moving(isolated_log):
    open_t = {"BTC-EUR": _trade(buy_price=1.0, age_hours=72)}
    cands = [{"market": "ETH-EUR", "score": 9.0, "expected_pct": 5.0}]
    out = sr.evaluate(
        open_t, cands,
        max_open_trades=1,
        current_prices={"BTC-EUR": 1.005},
        price_history_6h={"BTC-EUR": [1.0, 1.005, 1.01, 1.005]},  # 1% move
    )
    assert out == []


def test_kelly_edge_required():
    open_t = {"BTC-EUR": _trade(buy_price=1.0, age_hours=72)}
    cands = [{"market": "ETH-EUR", "score": 9.0, "expected_pct": 1.0}]  # too low
    out = sr.evaluate(
        open_t, cands,
        max_open_trades=1,
        current_prices={"BTC-EUR": 1.01},  # +1% existing
        price_history_6h={"BTC-EUR": [1.01, 1.011, 1.01]},
    )
    assert out == []  # 1.0 < 1.0*2 + 0.5


def test_analyse_summary(isolated_log):
    rows = [
        {"ts": time.time(), "close_market": "BTC-EUR", "candidate_market": "ETH-EUR",
         "close_age_hours": 60, "close_pnl_pct": 0.4},
        {"ts": time.time(), "close_market": "BTC-EUR", "candidate_market": "SOL-EUR",
         "close_age_hours": 100, "close_pnl_pct": 0.8},
    ]
    isolated_log.parent.mkdir(parents=True, exist_ok=True)
    isolated_log.write_text("\n".join(json.dumps(r) for r in rows))
    s = sr.analyse(window_days=14)
    assert s["total"] == 2
    assert s["by_close_market"]["BTC-EUR"] == 2
    assert s["age_buckets"]["48-72h"] == 1
    assert s["age_buckets"]["72-120h"] == 1
    assert s["pnl_buckets"]["0-0.5%"] == 1
    assert s["pnl_buckets"]["0.5-1%"] == 1
