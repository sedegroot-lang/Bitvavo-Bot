import sys
import os
from pathlib import Path
from types import SimpleNamespace

# Add tools/dashboard to path for import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools', 'dashboard'))

import pytest

watchdog = pytest.importorskip('dashboard_watchdog', reason='dashboard_watchdog module not found')


def test_build_health_url_defaults():
    url = watchdog.build_health_url(8501, None)
    assert url == "http://127.0.0.1:8501/_stcore/health"


def test_build_health_url_override():
    custom = watchdog.build_health_url(1234, "http://example/health")
    assert custom == "http://example/health"


def test_health_ok_handles_failures(monkeypatch):
    calls = SimpleNamespace(count=0)

    def fake_get(url, timeout):
        calls.count += 1
        if calls.count == 1:
            raise RuntimeError("network error")
        return SimpleNamespace(status_code=503)

    monkeypatch.setattr(watchdog.requests, "get", fake_get)

    assert watchdog.health_ok("http://dummy", timeout=1.0) is False
    assert calls.count == 1


def test_configure_logging_creates_file(tmp_path):
    log_file = tmp_path / "logs" / "watchdog.log"
    watchdog.configure_logging(log_file)
    logger = watchdog.logging.getLogger()
    assert logger.handlers
    for handler in list(logger.handlers):
        handler.flush()
    logger.info("hello watchdog")
    assert log_file.exists()
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers = []
