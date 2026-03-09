# Core modules for the Bitvavo Trading Bot
# Only ACTIVE production modules are imported here.

"""
Core Package — Active Modules:
- indicators.py: Technical indicators (SMA, EMA, RSI, MACD, ATR, Bollinger, Stochastic)
- reservation_manager.py: Thread-safe market reservation system
- trade_investment.py: Single Source of Truth for invested_eur mutations
"""

from core.reservation_manager import ReservationManager, MarketReservation
from core.trade_investment import (
    set_initial as ti_set_initial,
    add_dca as ti_add_dca,
    reduce_partial_tp as ti_reduce_partial_tp,
    repair_negative as ti_repair_negative,
    get_invested as ti_get_invested,
    get_total_invested as ti_get_total_invested,
)
# core.indicators is imported directly where needed (from core.indicators import ...)

__all__ = [
    # Reservations
    'ReservationManager',
    'MarketReservation',
    # Trade investment
    'ti_set_initial',
    'ti_add_dca',
    'ti_reduce_partial_tp',
    'ti_repair_negative',
    'ti_get_invested',
    'ti_get_total_invested',
]

__version__ = "3.0.0"
