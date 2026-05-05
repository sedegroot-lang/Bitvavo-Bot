---
applyTo: "tests/**/*.py"
description: "Pytest conventions for Bitvavo bot test suite"
---

# Test conventions

## Framework & layout
- Use `pytest` (9.x). No async, no `pytest-asyncio` unless absolutely required.
- File naming: `test_<module>.py`. Class grouping: `class TestFeature:` with `test_<scenario>` methods. Plain functions are also fine.
- Add the project root to `sys.path` is already handled by `tests/conftest.py` — do NOT add other shared fixtures there unless necessary.

## Per-test setup
- Use `@pytest.fixture(autouse=True)` inside the test class for module init (e.g. `_api.init(mock_bv, cfg)` and clearing module-level caches).
- Tests must NOT touch real Bitvavo API or write to `data/` or `config/` — use `tmp_path` and mocked clients.

## Mocking
- Use `unittest.mock.MagicMock` and `patch`. Mock the **Bitvavo client** (`mock_bv = MagicMock()`), NOT `bot.api.safe_call` itself.
- For order/trade tests, patch `bot.api.safe_call` only when you need to bypass retry/circuit-breaker logic.
- Patch `time.time` only via `monkeypatch.setattr` — never globally.

## Assertions
- Floats: `pytest.approx(expected, rel=1e-6)` or `abs=...`.
- Use plain `assert` statements, never `assertEqual`.
- Test data factories live inside the test file as `_make_candles(closes)`, `_make_trade(**overrides)` — no shared fixture library.

## What to test for trading code
1. **Cost basis**: any change touching `invested_eur`, `derive_cost_basis`, sync, or DCA MUST have a test that verifies merging vs overwriting (see FIX_LOG #001, #075).
2. **DCA tracking**: limit-order pending paths must reconcile from history (FIX_LOG #073, #074).
3. **Sync validator**: `auto_add_missing_positions` must MERGE, never OVERWRITE existing reconciled state.
4. **Config layering**: when testing config, write to a `tmp_path` file and patch `LOCAL_OVERRIDE_PATH` — never the real OneDrive paths.

## Running
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
.\.venv\Scripts\python.exe -m pytest tests/test_<file>.py -v -k <keyword>
```

For coverage:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -n auto --cov=bot --cov=core --cov=modules --cov-report=term-missing
```
