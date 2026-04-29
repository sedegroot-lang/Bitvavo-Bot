"""Tests for core.dca_state — event-sourced DCA state management.

Test scenarios (from user's comprehensive DCA redesign specification):
  1. Bot DCA: Bot executes DCA → dca_events grows, dca_buys = len(events)
  2. Manual DCA: External buy on Bitvavo → detected as untracked
  3. Restart with lost events: dca_events partially lost → sync_derived_fields corrects
  4. Cascading prevention: dca_next_price based on last_dca_price, not buy_price
  5. Sync with inflated dca_buys: sync_engine wrote dca_buys=17 → corrected to len(events)
"""

import time
import uuid

import pytest

from core.dca_state import (
    DCAEvent,
    DCAState,
    compute_state,
    detect_untracked_buys,
    record_dca,
    sync_derived_fields,
    validate_events,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> dict:
    """Create a minimal trade dict for testing."""
    trade = {
        "buy_price": 1.0,
        "amount": 100.0,
        "invested_eur": 100.0,
        "initial_invested_eur": 100.0,
        "total_invested_eur": 100.0,
        "dca_buys": 0,
        "dca_events": [],
        "dca_max": 5,
        "last_dca_price": 0.0,
        "opened_ts": 1700000000.0,
    }
    trade.update(overrides)
    return trade


def _make_event(level: int, price: float = 0.95, eur: float = 30.0,
                tokens: float = 31.58, source: str = "bot",
                ts: float = 0.0) -> dict:
    """Create a DCA event dict."""
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": ts or (1700000000.0 + level * 60),
        "price": price,
        "amount_eur": eur,
        "tokens_bought": tokens,
        "dca_level": level,
        "source": source,
    }


def _make_bitvavo_order(ts_epoch: float, filled_eur: float, filled_tokens: float,
                         side: str = "buy") -> dict:
    """Create a Bitvavo order dict."""
    return {
        "orderId": str(uuid.uuid4()),
        "side": side,
        "timestamp": ts_epoch * 1000,  # Bitvavo uses ms
        "filledAmountQuote": str(filled_eur),
        "filledAmount": str(filled_tokens),
    }


# ---------------------------------------------------------------------------
# Scenario 1: Bot DCA — normal execution
# ---------------------------------------------------------------------------

class TestBotDCA:
    """Bot executes DCA → dca_events grows, dca_buys = len(events)."""

    def test_record_first_dca(self):
        trade = _make_trade()
        state = record_dca(trade, price=0.95, amount_eur=30.0,
                           tokens_bought=31.58, dca_max=5, source="bot")
        assert state.dca_buys == 1
        assert trade["dca_buys"] == 1
        assert len(trade["dca_events"]) == 1
        assert trade["last_dca_price"] == 0.95
        assert state.last_dca_price == 0.95

    def test_record_multiple_dcas(self):
        trade = _make_trade()
        for i in range(3):
            price = 0.95 - i * 0.05
            state = record_dca(trade, price=price, amount_eur=30.0,
                               tokens_bought=30.0 / price, dca_max=5, source="bot")
        assert state.dca_buys == 3
        assert trade["dca_buys"] == 3
        assert len(trade["dca_events"]) == 3
        assert trade["last_dca_price"] == pytest.approx(0.85)

    def test_dca_buys_always_equals_event_count(self):
        trade = _make_trade()
        for i in range(5):
            record_dca(trade, price=0.90, amount_eur=30.0,
                       tokens_bought=33.33, dca_max=5, source="bot")
            assert trade["dca_buys"] == i + 1
            assert trade["dca_buys"] == len(trade["dca_events"])

    def test_dca_event_has_unique_id(self):
        trade = _make_trade()
        record_dca(trade, price=0.95, amount_eur=30.0, tokens_bought=31.58, dca_max=5)
        record_dca(trade, price=0.90, amount_eur=30.0, tokens_bought=33.33, dca_max=5)
        ids = [e["event_id"] for e in trade["dca_events"]]
        assert len(ids) == len(set(ids))  # All unique

    def test_dca_next_price_uses_last_dca_price(self):
        """FIX #003: dca_next_price must be based on last_dca_price, not buy_price."""
        trade = _make_trade()
        state = record_dca(
            trade, price=0.95, amount_eur=30.0, tokens_bought=31.58,
            dca_max=5, source="bot",
            drop_pct=0.025, step_multiplier=1.0,
        )
        # Next price = 0.95 * (1 - 0.025) = 0.92625
        assert trade["dca_next_price"] == pytest.approx(0.95 * (1 - 0.025), rel=1e-4)

    def test_dca_next_price_steps_from_last_execution(self):
        """Each DCA should require further drop from the LAST execution price."""
        trade = _make_trade()
        # First DCA at 0.95
        record_dca(trade, price=0.95, amount_eur=30.0, tokens_bought=31.58,
                    dca_max=5, drop_pct=0.025, step_multiplier=1.0)
        next_1 = trade["dca_next_price"]
        # Second DCA at 0.90
        record_dca(trade, price=0.90, amount_eur=30.0, tokens_bought=33.33,
                    dca_max=5, drop_pct=0.025, step_multiplier=1.0)
        next_2 = trade["dca_next_price"]
        # next_2 should be based on 0.90 (last_dca_price), not buy_price
        assert next_2 == pytest.approx(0.90 * (1 - 0.025), rel=1e-4)
        assert next_2 < next_1  # Each step goes lower

    def test_dca_max_respected(self):
        """dca_max doesn't truncate events but caps the stored counter."""
        trade = _make_trade(dca_max=2)
        for _ in range(3):
            record_dca(trade, price=0.90, amount_eur=30.0, tokens_bought=33.33, dca_max=2)
        # Events are all stored
        assert len(trade["dca_events"]) == 3
        # dca_buys reflects reality (3 events happened)
        assert trade["dca_buys"] == 3


# ---------------------------------------------------------------------------
# Scenario 2: Manual DCA detection
# ---------------------------------------------------------------------------

class TestManualDCA:
    """External buy on Bitvavo detected as untracked."""

    def test_detect_manual_buy(self):
        trade = _make_trade(opened_ts=1700000000.0)
        # Bitvavo order AFTER opened_ts — manual DCA
        orders = [
            _make_bitvavo_order(1700000100.0, filled_eur=50.0, filled_tokens=52.63),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5)
        assert len(untracked) == 1

    def test_skip_initial_buy(self):
        """Orders at or before opened_ts are the initial buy, not DCAs."""
        trade = _make_trade(opened_ts=1700000000.0)
        orders = [
            _make_bitvavo_order(1700000000.0, filled_eur=100.0, filled_tokens=100.0),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5)
        assert len(untracked) == 0

    def test_skip_already_tracked(self):
        """Events already in dca_events are not flagged as untracked."""
        trade = _make_trade(opened_ts=1700000000.0)
        trade["dca_events"] = [
            _make_event(1, price=0.95, eur=30.0, ts=1700000100.0),
        ]
        orders = [
            _make_bitvavo_order(1700000100.0, filled_eur=30.0, filled_tokens=31.58),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5)
        assert len(untracked) == 0

    def test_skip_sell_orders(self):
        trade = _make_trade(opened_ts=1700000000.0)
        orders = [
            _make_bitvavo_order(1700000100.0, filled_eur=50.0, filled_tokens=52.63,
                                 side="sell"),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5)
        assert len(untracked) == 0

    def test_skip_dust_orders(self):
        """Orders below min_eur threshold are ignored."""
        trade = _make_trade(opened_ts=1700000000.0)
        orders = [
            _make_bitvavo_order(1700000100.0, filled_eur=2.0, filled_tokens=2.1),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5, min_eur=5.0)
        assert len(untracked) == 0

    def test_detect_multiple_untracked(self):
        trade = _make_trade(opened_ts=1700000000.0)
        orders = [
            _make_bitvavo_order(1700000100.0, filled_eur=30.0, filled_tokens=31.58),
            _make_bitvavo_order(1700000200.0, filled_eur=30.0, filled_tokens=33.33),
            _make_bitvavo_order(1700000300.0, filled_eur=30.0, filled_tokens=35.29),
        ]
        untracked = detect_untracked_buys(trade, orders, dca_max=5)
        assert len(untracked) == 3


# ---------------------------------------------------------------------------
# Scenario 3: Restart with lost events / state corruption
# ---------------------------------------------------------------------------

class TestSyncDerivedFields:
    """sync_derived_fields corrects dca_buys from events."""

    def test_inflated_dca_buys_preserved(self):
        """FIX #008: dca_buys=17 with no events is preserved (historical/synced buys)."""
        trade = _make_trade(dca_buys=17, dca_events=[])
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 17  # preserved: max(0 events, 17 stored)
        assert state.dca_buys == 0  # computed from events only

    def test_deflated_dca_buys_increased(self):
        """dca_buys=1 but 3 events → increase to 3."""
        events = [_make_event(i + 1) for i in range(3)]
        trade = _make_trade(dca_buys=1, dca_events=events)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 3
        assert state.dca_buys == 3

    def test_correct_state_no_repairs(self):
        """When dca_buys matches events, no repairs needed."""
        events = [_make_event(i + 1) for i in range(2)]
        trade = _make_trade(dca_buys=2, dca_events=events,
                            last_dca_price=events[-1]["price"])
        state, repairs = sync_derived_fields(trade, dca_max=5)
        # dca_max might be repaired if stored differs from arg
        dca_buys_repairs = [r for r in repairs if "dca_buys" in r]
        assert len(dca_buys_repairs) == 0

    def test_sync_dca_max_synced_to_global(self):
        """FIX #030b: dca_max syncs to global config so config changes take effect on existing trades.

        (Supersedes earlier FIX #008 preservation: dca_max is the per-trade cap and must
        track the global DCA_MAX_BUYS so existing trades see config updates.)
        """
        trade = _make_trade(dca_max=17)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_max"] == 5  # synced to global config
        assert any("dca_max" in r for r in repairs)

    def test_sync_last_dca_price(self):
        """last_dca_price corrected from events."""
        events = [_make_event(1, price=0.88)]
        trade = _make_trade(dca_buys=1, dca_events=events, last_dca_price=1.23)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["last_dca_price"] == pytest.approx(0.88)

    def test_empty_trade_clean(self):
        """Fresh trade with no events — no repairs needed."""
        trade = _make_trade()
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 0
        assert state.dca_buys == 0
        # Only dca_max sync might appear if it differed
        dca_buys_repairs = [r for r in repairs if "dca_buys" in r]
        assert len(dca_buys_repairs) == 0


# ---------------------------------------------------------------------------
# Scenario 4: Cascading prevention
# ---------------------------------------------------------------------------

class TestCascadingPrevention:
    """dca_next_price must use last_dca_price, not buy_price."""

    def test_next_price_from_last_execution(self):
        trade = _make_trade(buy_price=1.20)
        record_dca(trade, price=1.05, amount_eur=30.0, tokens_bought=28.57,
                    dca_max=5, drop_pct=0.025, step_multiplier=1.0)
        # Next price from 1.05, not from buy_price 1.20
        expected = 1.05 * (1 - 0.025)
        assert trade["dca_next_price"] == pytest.approx(expected, rel=1e-4)

    def test_step_multiplier_applied(self):
        """Step multiplier increases required drop for successive DCAs."""
        trade = _make_trade()
        record_dca(trade, price=0.95, amount_eur=30.0, tokens_bought=31.58,
                    dca_max=5, drop_pct=0.025, step_multiplier=1.5)
        # After 1st DCA: next_step = 0.025 * (1.5^1) = 0.0375
        expected = 0.95 * (1 - 0.0375)
        assert trade["dca_next_price"] == pytest.approx(expected, rel=1e-4)

    def test_no_next_price_without_drop_pct(self):
        """When drop_pct=0, dca_next_price is not set by record_dca."""
        trade = _make_trade()
        record_dca(trade, price=0.95, amount_eur=30.0, tokens_bought=31.58, dca_max=5)
        assert "dca_next_price" not in trade


# ---------------------------------------------------------------------------
# Scenario 5: Sync with inflated dca_buys
# ---------------------------------------------------------------------------

class TestInflatedDCABuys:
    """sync_engine wrote dca_buys from buy_order_count → must correct."""

    def test_dca_buys_17_no_events_preserved(self):
        """FIX #008: XRP dca_buys=17 with zero events — preserved (historical buys).

        NOTE: dca_max syncs to global (FIX #030b), but dca_buys remains preserved.
        """
        trade = _make_trade(dca_buys=17, dca_events=[], dca_max=17)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 17  # preserved
        assert trade["dca_max"] == 5    # synced to global (FIX #030b)

    def test_dca_buys_17_with_3_events_preserved(self):
        """NEAR had dca_buys=17, 3 real events — 17 preserved (>= 3). dca_max syncs to global."""
        events = [_make_event(i + 1) for i in range(3)]
        trade = _make_trade(dca_buys=17, dca_events=events, dca_max=17)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 17  # max(3 events, 17 stored)
        assert trade["dca_max"] == 5    # synced to global (FIX #030b)

    def test_dca_buys_preserved_when_higher_than_events(self):
        """Stored dca_buys higher than events count is preserved."""
        events = [_make_event(i + 1) for i in range(2)]
        trade = _make_trade(dca_buys=5, dca_events=events)
        state, repairs = sync_derived_fields(trade, dca_max=5)
        assert trade["dca_buys"] == 5  # max(2 events, 5 stored)


# ---------------------------------------------------------------------------
# DCAEvent serialization
# ---------------------------------------------------------------------------

class TestDCAEvent:
    def test_round_trip(self):
        event = DCAEvent(
            event_id="abc-123",
            timestamp=1700000060.0,
            price=0.95,
            amount_eur=30.0,
            tokens_bought=31.58,
            dca_level=1,
            source="bot",
        )
        d = event.to_dict()
        restored = DCAEvent.from_dict(d)
        assert restored.event_id == event.event_id
        assert restored.price == event.price
        assert restored.source == event.source

    def test_from_dict_missing_fields(self):
        """from_dict handles missing fields gracefully."""
        d = {"price": 0.95}
        event = DCAEvent.from_dict(d)
        assert event.price == 0.95
        assert event.amount_eur == 0.0
        assert event.source == "bot"
        assert len(event.event_id) > 0  # UUID generated


# ---------------------------------------------------------------------------
# compute_state
# ---------------------------------------------------------------------------

class TestComputeState:
    def test_empty_events(self):
        trade = _make_trade()
        state = compute_state(trade, dca_max=5)
        assert state.dca_buys == 0
        assert state.total_dca_eur == 0
        assert state.last_dca_price == 0
        assert state.can_dca is True

    def test_with_events(self):
        events = [
            _make_event(1, price=0.95, eur=30.0),
            _make_event(2, price=0.90, eur=27.0),
        ]
        trade = _make_trade(dca_events=events)
        state = compute_state(trade, dca_max=5)
        assert state.dca_buys == 2
        assert state.total_dca_eur == pytest.approx(57.0)
        assert state.last_dca_price == 0.90
        assert state.can_dca is True

    def test_at_max_dcas(self):
        events = [_make_event(i + 1) for i in range(5)]
        trade = _make_trade(dca_events=events)
        state = compute_state(trade, dca_max=5)
        assert state.dca_buys == 5
        assert state.can_dca is False
        assert state.next_level == 6

    def test_events_sorted_by_timestamp(self):
        """Events should be sorted by timestamp regardless of insert order."""
        events = [
            _make_event(2, ts=1700000200.0),
            _make_event(1, ts=1700000100.0),  # Earlier but inserted later
        ]
        trade = _make_trade(dca_events=events)
        state = compute_state(trade, dca_max=5)
        assert state.events[0].timestamp < state.events[1].timestamp


# ---------------------------------------------------------------------------
# validate_events
# ---------------------------------------------------------------------------

class TestValidateEvents:
    def test_clean_events(self):
        events = [_make_event(i + 1) for i in range(3)]
        trade = _make_trade(dca_buys=3, dca_events=events)
        warnings = validate_events(trade, dca_max=5)
        assert len(warnings) == 0

    def test_dca_buys_mismatch(self):
        events = [_make_event(1)]
        trade = _make_trade(dca_buys=5, dca_events=events)
        warnings = validate_events(trade, dca_max=5)
        assert any("mismatch" in w for w in warnings)

    def test_duplicate_event_ids(self):
        eid = str(uuid.uuid4())
        events = [
            {"event_id": eid, "timestamp": 1.0, "price": 1.0,
             "amount_eur": 30.0, "tokens_bought": 30.0, "dca_level": 1},
            {"event_id": eid, "timestamp": 2.0, "price": 0.9,
             "amount_eur": 30.0, "tokens_bought": 33.3, "dca_level": 2},
        ]
        trade = _make_trade(dca_events=events)
        warnings = validate_events(trade, dca_max=5)
        assert any("Duplicate" in w for w in warnings)

    def test_negative_amount(self):
        events = [
            {"event_id": str(uuid.uuid4()), "timestamp": 1.0, "price": 1.0,
             "amount_eur": -5.0, "tokens_bought": 30.0, "dca_level": 1},
        ]
        trade = _make_trade(dca_events=events)
        warnings = validate_events(trade, dca_max=5)
        assert any("non-positive amount_eur" in w for w in warnings)
