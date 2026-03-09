"""bot/ — modular package for trailing_bot.py decomposition.

Current state: Phase 1 of incremental extraction.
See bot/SPLIT_PLAN.md for the full decomposition roadmap.
"""

from bot.helpers import as_bool, as_int, as_float, clamp, coerce_positive_float

__all__ = ['as_bool', 'as_int', 'as_float', 'clamp', 'coerce_positive_float']
