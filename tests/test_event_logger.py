"""Tests for modules.event_logger."""
from __future__ import annotations

import json
import os
import threading

import pytest

from modules.event_logger import log_event


@pytest.fixture()
def event_path(tmp_path, monkeypatch):
    p = tmp_path / "events.jsonl"
    monkeypatch.setenv("BOT_EVENTS_LOG", str(p))
    return p


class TestLogEvent:
    def test_writes_single_line(self, event_path):
        log_event("trade_open", market="BTC-EUR", price=43000.0)
        lines = event_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["event"] == "trade_open"
        assert rec["market"] == "BTC-EUR"
        assert rec["price"] == 43000.0
        assert "ts" in rec

    def test_multiple_appends(self, event_path):
        for i in range(5):
            log_event("scan", count=i)
        lines = event_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        first = json.loads(lines[0])
        last = json.loads(lines[4])
        assert first["count"] == 0
        assert last["count"] == 4

    def test_nonserializable_falls_back_via_default_str(self, event_path):
        class Foo:
            def __str__(self) -> str:
                return "foo-instance"

        log_event("weird", obj=Foo())
        lines = event_path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        assert rec["obj"] == "foo-instance"

    def test_thread_safe(self, event_path):
        n_threads = 10
        per_thread = 20

        def worker(tid):
            for i in range(per_thread):
                log_event("threaded", tid=tid, i=i)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        lines = event_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n_threads * per_thread
        # All lines must be valid JSON (no interleaving)
        for ln in lines:
            json.loads(ln)

    def test_does_not_raise_on_invalid_path(self, monkeypatch):
        # Set path to something that can't be written; helper must swallow.
        monkeypatch.setenv("BOT_EVENTS_LOG", "Z:\\nonexistent\\nope\\events.jsonl")
        # Should not raise:
        log_event("safe", x=1)
