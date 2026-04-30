"""Tests for road-to-10 fase 6 closure: model registry, per-market trailing, rate-limit alert."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ===================================================================
# Model Registry
# ===================================================================
class TestModelRegistry:
    def test_scan_returns_list(self, tmp_path, monkeypatch):
        from models import registry
        monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "registry.json")
        # No files → empty
        assert registry.scan_models() == []

    def test_scan_picks_up_model_with_metrics(self, tmp_path, monkeypatch):
        from models import registry
        monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "registry.json")
        ts = "20260101T120000"
        (tmp_path / f"ai_xgb_model_{ts}.json").write_text("{}", encoding="utf-8")
        (tmp_path / f"ai_xgb_metrics_{ts}.json").write_text(
            json.dumps({"trained_at": 1700000000, "auc": 0.91, "support": 1000, "positive_ratio": 0.1}),
            encoding="utf-8",
        )
        entries = registry.scan_models()
        assert len(entries) == 1
        e = entries[0]
        assert e["version_ts"] == ts
        assert e["auc"] == 0.91
        assert e["metrics_path"] == f"ai_xgb_metrics_{ts}.json"

    def test_write_registry_creates_file(self, tmp_path, monkeypatch):
        from models import registry
        monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
        target = tmp_path / "registry.json"
        monkeypatch.setattr(registry, "REGISTRY_PATH", target)
        ts = "20260301T080000"
        (tmp_path / f"ai_xgb_model_{ts}.json").write_text("{}", encoding="utf-8")
        (tmp_path / f"ai_xgb_metrics_{ts}.json").write_text(
            json.dumps({"auc": 0.85}), encoding="utf-8"
        )
        result = registry.write_registry()
        assert target.exists()
        assert result["model_count"] == 1
        assert result["latest"]["version_ts"] == ts

    def test_latest_returns_newest(self, tmp_path, monkeypatch):
        from models import registry
        monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "registry.json")
        for ts in ("20260101T000000", "20260301T000000", "20260201T000000"):
            (tmp_path / f"ai_xgb_model_{ts}.json").write_text("{}", encoding="utf-8")
        latest = registry.latest_model()
        assert latest["version_ts"] == "20260301T000000"


# ===================================================================
# Per-Market Trailing
# ===================================================================
class TestPerMarketTrailing:
    def test_btc_uses_curated_default(self):
        from bot.per_market_trailing import get_trailing_params
        params = get_trailing_params("BTC-EUR", config={})
        assert params["trailing_activation_pct"] == 1.0
        assert params["base_trailing_pct"] == 0.6

    def test_unknown_market_falls_back_to_global(self):
        from bot.per_market_trailing import get_trailing_params
        cfg = {"TRAILING_ACTIVATION_PCT": 2.0, "BASE_TRAILING_PCT": 1.0, "COST_BUFFER_PCT": 0.7}
        params = get_trailing_params("RNDR-EUR", config=cfg)
        assert params["trailing_activation_pct"] == 2.0
        assert params["base_trailing_pct"] == 1.0
        assert params["cost_buffer_pct"] == 0.7

    def test_runtime_override_wins(self):
        from bot.per_market_trailing import get_trailing_params
        cfg = {
            "PER_MARKET_TRAILING": {
                "BTC-EUR": {"trailing_activation_pct": 0.5, "base_trailing_pct": 0.3, "cost_buffer_pct": 0.2}
            }
        }
        params = get_trailing_params("BTC-EUR", config=cfg)
        assert params["trailing_activation_pct"] == 0.5
        assert params["base_trailing_pct"] == 0.3

    def test_handles_none_config(self):
        from bot.per_market_trailing import get_trailing_params
        params = get_trailing_params("BTC-EUR")
        assert params["trailing_activation_pct"] == 1.0


# ===================================================================
# Rate-limit alert
# ===================================================================
class TestRateLimitAlert:
    @pytest.fixture(autouse=True)
    def _reset(self):
        from bot.rate_limit_alert import reset_alert_state
        reset_alert_state()
        yield
        reset_alert_state()

    def test_no_alert_below_threshold(self):
        from bot.rate_limit_alert import check_and_alert
        logs = []
        snapshot = {"__global__": {"limit": 100, "window": 1.0, "used": 50, "usage_ratio": 0.5}}
        breached = check_and_alert(
            threshold=0.8, cooldown_sec=10, log_fn=lambda *a, **k: logs.append(a),
            status_fn=lambda: snapshot,
        )
        assert breached == {}
        assert logs == []

    def test_alerts_above_threshold(self):
        from bot.rate_limit_alert import check_and_alert
        logs = []
        snapshot = {"GET candles": {"limit": 100, "window": 1.0, "used": 90, "usage_ratio": 0.9}}
        breached = check_and_alert(
            threshold=0.8, cooldown_sec=10, log_fn=lambda *a, **k: logs.append(a),
            status_fn=lambda: snapshot,
        )
        assert breached == {"GET candles": 0.9}
        assert len(logs) == 1
        assert "90%" in logs[0][0] or "GET candles" in logs[0][0]

    def test_cooldown_prevents_spam(self):
        from bot.rate_limit_alert import check_and_alert
        logs = []
        snapshot = {"__global__": {"limit": 100, "window": 1.0, "used": 95, "usage_ratio": 0.95}}
        check_and_alert(threshold=0.8, cooldown_sec=300, log_fn=lambda *a, **k: logs.append(a), status_fn=lambda: snapshot)
        check_and_alert(threshold=0.8, cooldown_sec=300, log_fn=lambda *a, **k: logs.append(a), status_fn=lambda: snapshot)
        check_and_alert(threshold=0.8, cooldown_sec=300, log_fn=lambda *a, **k: logs.append(a), status_fn=lambda: snapshot)
        assert len(logs) == 1  # cooldown prevented 2nd and 3rd

    def test_handles_status_fn_exception(self):
        from bot.rate_limit_alert import check_and_alert
        def boom():
            raise RuntimeError("api dead")
        breached = check_and_alert(threshold=0.8, status_fn=boom, log_fn=lambda *a, **k: None)
        assert breached == {}


# ===================================================================
# Demo-mode integration smoke test (verify module exists & exposes expected API)
# ===================================================================
class TestDemoMode:
    def test_demo_mode_module_exists(self):
        import bot.demo_mode as dm
        # Must have at least one of these public callables
        has_api = any(hasattr(dm, name) for name in ("is_demo_mode", "DEMO_MODE", "is_enabled", "is_active", "maybe_intercept"))
        assert has_api, f"demo_mode.py present but no recognised public flag/function. Module: {dir(dm)}"


# ===================================================================
# Scheduler check_rate_limits wiring
# ===================================================================
class TestSchedulerRateLimitHook:
    def test_check_rate_limits_callable(self):
        from bot import scheduler
        assert hasattr(scheduler, "check_rate_limits")
        # Should not raise even if api isn't initialised
        result = scheduler.check_rate_limits(threshold=0.8)
        assert isinstance(result, dict)
