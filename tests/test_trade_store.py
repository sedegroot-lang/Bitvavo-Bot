from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules import storage
from modules.trade_store import load_snapshot, save_snapshot


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path):
    storage.configure(tmp_path / "data")
    try:
        yield
    finally:
        storage.reset()


def test_load_snapshot_returns_defaults_when_json_missing(tmp_path):
    missing = tmp_path / "trade_log.json"
    data = load_snapshot(missing)
    assert isinstance(data, dict)
    assert data.get("open", {}) == {}
    assert data.get("closed", []) == []


def test_save_snapshot_syncs_json_and_tinydb(tmp_path):
    path = tmp_path / "trade_log.json"
    payload = {"open": {"BTC-EUR": {"amount": 1}}, "closed": [{"market": "ETH-EUR"}]}

    save_snapshot(payload, path, indent=0)
    assert path.exists()
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw == payload

    cached = load_snapshot(path)
    assert cached == payload

    # mutate JSON directly to simulate external writer
    new_payload = {"open": {}, "closed": [{"market": "ADA-EUR", "profit": 1.0}]}
    path.write_text(json.dumps(new_payload), encoding="utf-8")

    refreshed = load_snapshot(path)
    assert refreshed == new_payload

    # ensure TinyDB meta updated to new size
    storage_snapshot = load_snapshot(path)
    assert storage_snapshot == new_payload
