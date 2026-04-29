"""Tests for the new Road-to-10 helpers (feature store, model registry,
walk-forward, demo mode, conformal wrapper, shadow report aggregator)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ai.features import FEATURE_STORE_VERSION, feature_names, schema_metadata, vectorize
from ai.model_registry import latest_model_metadata, read_metadata, register_model
from ai.conformal import MAPIE_AVAILABLE, fit_conformal, predict_with_interval
from backtest import WalkForwardConfig, run_walk_forward
from bot import demo_mode


# --- feature store ---

def test_feature_store_has_11_features():
    assert len(feature_names()) == 11
    assert "rsi" in feature_names()
    assert "macd" in feature_names()


def test_feature_store_vectorize_handles_missing():
    vec = vectorize({"rsi": 55.0, "macd": 1.2})
    assert isinstance(vec, list)
    assert len(vec) == 11
    assert vec[0] == 55.0
    assert all(isinstance(v, float) for v in vec)


def test_feature_store_vectorize_never_raises():
    assert vectorize({}) == [0.0] * 11
    assert vectorize({"rsi": "not-a-number"})[0] == 0.0


def test_schema_metadata_has_version():
    meta = schema_metadata()
    assert meta["version"] == FEATURE_STORE_VERSION
    assert meta["n_features"] == 11
    assert len(meta["features"]) == 11


# --- model registry ---

def test_register_model_writes_meta(tmp_path: Path):
    model_file = tmp_path / "fake_model.json"
    model_file.write_text("{}", encoding="utf-8")
    meta_path = register_model(model_file, n_train=1234, val_metric=0.71, notes="unit test")
    assert meta_path.exists()
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["n_train"] == 1234
    assert data["val_metric"] == pytest.approx(0.71)
    assert data["feature_store_version"] == FEATURE_STORE_VERSION


def test_read_metadata_missing_returns_none(tmp_path: Path):
    assert read_metadata(tmp_path / "nope.json") is None


def test_latest_model_metadata_picks_newest(tmp_path: Path):
    a = tmp_path / "a.json"; a.write_text("{}", encoding="utf-8")
    b = tmp_path / "b.json"; b.write_text("{}", encoding="utf-8")
    register_model(a, n_train=10, val_metric=0.5)
    time.sleep(0.01)
    register_model(b, n_train=20, val_metric=0.6)
    latest = latest_model_metadata(tmp_path)
    assert latest is not None
    assert latest["n_train"] == 20


# --- walk-forward backtest ---

def test_walk_forward_with_synthetic_trades(tmp_path: Path):
    now = time.time()
    day = 86400
    trades = []
    for i in range(120):
        trades.append({
            "closed_ts": now - (120 - i) * day / 4,  # ~30 days span
            "profit": (i % 7) - 3,                   # cycles of -3..+3 EUR
            "profit_pct": ((i % 7) - 3) / 100.0,
        })
    src = tmp_path / "trades.json"
    src.write_text(json.dumps(trades), encoding="utf-8")
    cfg = WalkForwardConfig(train_days=7, test_days=3, step_days=3, min_trades_per_window=3)
    rep = run_walk_forward(src, cfg)
    s = rep.summary()
    assert s["windows"] >= 1
    assert s["trades_total"] > 0
    assert "pnl_total_eur" in s


def test_walk_forward_empty_returns_no_windows(tmp_path: Path):
    src = tmp_path / "empty.json"
    src.write_text("[]", encoding="utf-8")
    rep = run_walk_forward(src, WalkForwardConfig())
    assert rep.windows == []
    assert rep.summary()["windows"] == 0


# --- demo mode ---

def test_demo_mode_inactive_by_default(monkeypatch):
    monkeypatch.delenv("BOT_DEMO_MODE", raising=False)
    assert demo_mode.is_active() is False
    assert demo_mode.maybe_intercept("balance") is None


def test_demo_mode_active_returns_balance_fixture(monkeypatch):
    monkeypatch.setenv("BOT_DEMO_MODE", "1")
    # cache may be polluted from other tests; clear
    demo_mode._FIXTURES_CACHE.clear()
    bal = demo_mode.maybe_intercept("balance")
    assert isinstance(bal, list)
    assert any(b.get("symbol") == "EUR" for b in bal)


def test_demo_mode_unknown_endpoint_returns_none(monkeypatch):
    monkeypatch.setenv("BOT_DEMO_MODE", "1")
    assert demo_mode.maybe_intercept("totally-not-an-endpoint") is None


# --- conformal wrapper ---

def test_conformal_no_op_without_mapie():
    # Whether or not MAPIE is installed, the wrapper must not raise.
    blob = fit_conformal(model=None, X_calib=None, y_calib=None)  # type: ignore[arg-type]
    if not MAPIE_AVAILABLE:
        assert blob is None
    preds, widths = predict_with_interval(blob, None)  # type: ignore[arg-type]
    # Always returns numpy arrays (possibly empty)
    assert hasattr(preds, "shape")
    assert hasattr(widths, "shape")


# --- shadow report aggregator ---

def test_shadow_report_aggregate_basic():
    from scripts.shadow_report import aggregate
    now = time.time()
    records = [
        {"ts": now - 100, "hypothetical_pnl_eur": 1.5, "blocked_reason": "low_confidence"},
        {"ts": now - 200, "hypothetical_pnl_eur": -0.5, "blocked_reason": "low_confidence"},
        {"ts": now - 300, "hypothetical_pnl_eur": 2.0, "blocked_reason": "no_budget"},
    ]
    s = aggregate(records, since_ts=None)
    assert s["n"] == 3
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert s["pnl_total_eur"] == pytest.approx(3.0)
    assert s["blocked_by_reason"]["low_confidence"] == 2


def test_shadow_report_aggregate_filters_by_since_ts():
    from scripts.shadow_report import aggregate
    now = time.time()
    records = [
        {"ts": now - 10, "hypothetical_pnl_eur": 1.0},
        {"ts": now - 1_000_000, "hypothetical_pnl_eur": -100.0},
    ]
    s = aggregate(records, since_ts=now - 100)
    assert s["n_with_pnl"] == 1
    assert s["pnl_total_eur"] == pytest.approx(1.0)


# --- drift monitor pure functions ---

def test_drift_monitor_detects_z_score():
    from scripts.drift_monitor import detect_drift
    baseline = {"rsi": {"mean": 50.0, "std": 5.0, "n": 100}}
    recent = {"rsi": {"mean": 80.0, "std": 4.0, "n": 30}}  # z = 6
    alerts = detect_drift(baseline, recent, z_threshold=3.0)
    assert len(alerts) == 1
    assert alerts[0]["feature"] == "rsi"
    assert alerts[0]["z_score"] == pytest.approx(6.0)


def test_drift_monitor_no_alert_when_within_threshold():
    from scripts.drift_monitor import detect_drift
    baseline = {"rsi": {"mean": 50.0, "std": 10.0, "n": 100}}
    recent = {"rsi": {"mean": 55.0, "std": 10.0, "n": 30}}  # z = 0.5
    assert detect_drift(baseline, recent, z_threshold=3.0) == []
