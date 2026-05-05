---
applyTo: "modules/signals/**/*.py"
description: "Signal provider plugin conventions"
---

# Signal provider conventions

## Protocol contract
All signal providers implement the `SignalProvider` Protocol from `modules/signals/base.py`:
```python
def my_signal(ctx: SignalContext) -> SignalResult: ...
```

`SignalContext` (read-only):
- `market: str`
- `candles_1m`, `closes_1m`, `highs_1m`, `lows_1m`, `volumes_1m`: Sequence
- `config: MutableMapping[str, Any]`

`SignalResult` (dataclass with slots):
- `name: str` — provider identifier
- `score: float = 0.0`
- `active: bool = False`
- `reason: str = ""`
- `details: Dict[str, Any] = field(default_factory=dict)`

## Mandatory rules
1. **Pure function** — no I/O, no API calls, no global state mutation, no logging beyond `details`.
2. Use `_safe_cfg_float`, `_safe_cfg_int`, `_safe_cfg_bool` from `.base` for ALL config access. Never `ctx.config['KEY']` directly — config values may be wrong type.
3. **Relative imports only** within the package: `from .base import ...`, `from .indicators import ...`.
4. Return a `SignalResult` even on insufficient data — set `active=False`, `reason="insufficient_data"`.
5. Never raise exceptions — catch and convert to `active=False, reason="error: ..."`.

## Registration
Add the provider function to `PROVIDERS` list in `modules/signals/__init__.py`. Order does not affect scoring (all run independently).

## Naming
- Function: `<concept>_signal` (e.g. `range_signal`, `mean_reversion_scalper_signal`).
- `result.name`: same as function name without `_signal` suffix (e.g. `"range"`, `"mean_reversion_scalper"`).

## Testing a new provider
Create `tests/test_signal_<name>.py` with at least:
- Insufficient candles → `active=False`.
- Bullish setup → `active=True, score>0`.
- Neutral setup → `active=False`.
- Config override applied → behavior changes accordingly.
