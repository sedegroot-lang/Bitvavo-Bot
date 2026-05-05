---
applyTo: "core/**/*.py"
description: "core/ package — pure computation, no I/O"
---

# core/ package conventions

`core/` contains **pure computation only** — indicators, regime engine, Kelly sizing, order book analysis, reservation manager.

## Hard rules
1. **No I/O**: no file reads/writes, no network calls, no Bitvavo API access.
2. **No bot state**: no `from bot.shared import state`. Functions take inputs, return outputs.
3. **No logging side effects in hot paths** — log only on errors via passed-in logger or raise (caller logs).
4. Keep functions **deterministic and side-effect free** — easy to unit test.
5. **Use `from __future__ import annotations`** at top of every module.
6. Use `@dataclass(slots=True)` for data carriers.
7. Type hints required on public functions.

## Allowed dependencies
- stdlib, `numpy`, `pandas`, `dataclasses`.
- NOT allowed: `requests`, `python_bitvavo_api`, `flask`, `tinydb`, `modules.*`, `bot.*`, `ai.*`.

## Acceptable exception
- `core/reservation_manager.py` uses `threading.RLock` — that's fine; thread primitives are pure.

## Testing
Every public function in `core/` should have a unit test in `tests/test_core_<module>.py` covering normal, edge, and empty-input cases.
