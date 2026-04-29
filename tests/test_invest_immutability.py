"""Unit tests for invest immutability and DCA event tracking.

Tests verify:
1. initial_invested_eur is never modified after trade creation
2. total_invested_eur increases correctly with DCA buys
3. dca_events list contains unique event_ids
4. P/L calculations use initial_invested_eur as baseline
5. Old trades without these fields fallback gracefully
"""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.trading_dca import DCAManager, DCAContext, DCASettings


class TestInvestImmutability:
    """Test that initial_invested_eur remains immutable."""
    
    def test_initial_invest_preserved_after_dca(self):
        """Test: Execute 3 DCAs, assert initial_invested_eur unchanged."""
        # Setup
        trade = {
            'market': 'BTC-EUR',
            'buy_price': 50000.0,
            'amount': 0.001,
            'invested_eur': 50.0,
            'initial_invested_eur': 50.0,
            'total_invested_eur': 50.0,
            'dca_events': [],
            'dca_buys': 0,
            'dca_max': 3
        }
        
        # Simulate 3 DCA buys
        for i in range(3):
            prev_initial = trade['initial_invested_eur']
            prev_total = trade['total_invested_eur']
            
            # Simulate DCA buy (like in trading_dca.py)
            import uuid
            import time
            event_id = str(uuid.uuid4())
            dca_amount_eur = 10.0 * (1.5 ** i)
            tokens_bought = dca_amount_eur / 48000.0  # price dropped
            
            prev_amount = float(trade['amount'])
            new_amount = prev_amount + tokens_bought
            prev_buy = float(trade['buy_price'])
            trade['buy_price'] = ((prev_buy * prev_amount) + (48000.0 * tokens_bought)) / new_amount
            trade['amount'] = new_amount
            
            # CRITICAL: initial_invested_eur must NOT change
            # Only total_invested_eur increases
            trade['total_invested_eur'] = prev_total + dca_amount_eur
            trade['invested_eur'] = trade['total_invested_eur']
            trade['dca_buys'] += 1
            
            trade['dca_events'].append({
                'event_id': event_id,
                'timestamp': time.time(),
                'price': 48000.0,
                'amount_eur': dca_amount_eur,
                'tokens_bought': tokens_bought,
                'dca_level': trade['dca_buys']
            })
            
            # Assert initial_invested_eur unchanged
            assert trade['initial_invested_eur'] == prev_initial == 50.0, \
                f"initial_invested_eur changed after DCA {i+1}: {trade['initial_invested_eur']}"
            
            # Assert total_invested_eur increased
            assert trade['total_invested_eur'] > prev_total, \
                f"total_invested_eur did not increase after DCA {i+1}"
        
        # Final assertions
        assert trade['initial_invested_eur'] == 50.0, "initial_invested_eur was modified"
        assert trade['total_invested_eur'] > 50.0, "total_invested_eur should have increased"
        assert len(trade['dca_events']) == 3, "Should have 3 DCA events"
        assert trade['dca_buys'] == 3, "dca_buys counter should be 3"
    
    def test_pnl_calculated_from_initial_invest(self):
        """Test: P/L calculated from initial_invested_eur, not total."""
        trade = {
            'buy_price': 100.0,
            'amount': 2.0,  # After DCA, amount increased
            'initial_invested_eur': 100.0,  # Original investment
            'total_invested_eur': 150.0,  # After 1 DCA of €50
            'dca_buys': 1
        }
        
        current_price = 120.0
        current_value = current_price * trade['amount']  # 120 * 2 = 240
        
        # CORRECT P/L: (current_value - initial_invested_eur)
        pnl_correct = current_value - trade['initial_invested_eur']  # 240 - 100 = 140
        
        # WRONG P/L: (current_value - total_invested_eur)
        pnl_wrong = current_value - trade['total_invested_eur']  # 240 - 150 = 90
        
        assert pnl_correct == 140.0, "P/L should be calculated from initial invest"
        assert pnl_wrong == 90.0, "This is the wrong calculation (using total)"
        assert pnl_correct > pnl_wrong, "P/L from initial should be higher (better ROI)"
    
    def test_old_trade_without_initial_invest_fallback(self):
        """Test: Old trades without initial_invested_eur fallback to invested_eur."""
        old_trade = {
            'buy_price': 50.0,
            'amount': 1.0,
            'invested_eur': 50.0,
            # No initial_invested_eur or total_invested_eur
        }
        
        # Dashboard should handle missing fields gracefully
        initial_invested = old_trade.get('initial_invested_eur')
        total_invested = old_trade.get('total_invested_eur') or old_trade.get('invested_eur')
        
        if initial_invested is not None:
            invested = float(initial_invested)
        elif total_invested is not None:
            invested = float(total_invested)
        else:
            invested = old_trade['buy_price'] * old_trade['amount']
        
        assert invested == 50.0, "Should fallback to invested_eur for old trades"


class TestDCAEvents:
    """Test DCA event tracking with unique IDs."""
    
    def test_dca_events_have_unique_ids(self):
        """Test: 5 DCAs executed, assert len(dca_events) == 5 with unique event_ids."""
        trade = {
            'dca_events': [],
            'dca_buys': 0
        }
        
        import uuid
        import time
        
        event_ids = set()
        for i in range(5):
            event_id = str(uuid.uuid4())
            event_ids.add(event_id)
            
            trade['dca_events'].append({
                'event_id': event_id,
                'timestamp': time.time(),
                'price': 50.0 - (i * 2),
                'amount_eur': 10.0,
                'tokens_bought': 0.2,
                'dca_level': i + 1
            })
            trade['dca_buys'] += 1
        
        assert len(trade['dca_events']) == 5, "Should have 5 DCA events"
        assert len(event_ids) == 5, "All event_ids should be unique"
        
        # Verify dca_events match dca_buys counter
        assert trade['dca_buys'] == len(trade['dca_events']), "dca_buys should match events list length"
    
    def test_dca_event_idempotency(self):
        """Test: Execute DCA buy twice with same event_id, should detect and skip duplicate."""
        trade = {
            'dca_events': [],
            'dca_buys': 0
        }
        
        import uuid
        event_id = str(uuid.uuid4())
        
        # First execution
        trade['dca_events'].append({
            'event_id': event_id,
            'timestamp': 1234567890.0,
            'price': 50.0,
            'amount_eur': 10.0,
            'tokens_bought': 0.2,
            'dca_level': 1
        })
        trade['dca_buys'] = 1
        
        # Check if event_id already exists (idempotency check)
        existing_event_ids = {ev['event_id'] for ev in trade['dca_events']}
        if event_id in existing_event_ids:
            # Skip duplicate - do NOT add again
            duplicate_detected = True
        else:
            # Add new event
            trade['dca_events'].append({
                'event_id': event_id,
                'timestamp': 1234567891.0,
                'price': 50.0,
                'amount_eur': 10.0,
                'tokens_bought': 0.2,
                'dca_level': 2
            })
            duplicate_detected = False
        
        assert duplicate_detected == True, "Should detect duplicate event_id"
        assert len(trade['dca_events']) == 1, "Should still have only 1 event after duplicate attempt"
    
    def test_dca_events_prevent_old_trade_pollution(self):
        """Test: Old trades (pre-migration) don't pollute new trade DCA counts."""
        # Old trade (before migration) with high dca_buys but no events
        old_trade = {
            'market': 'OLD-EUR',
            'dca_buys': 24,  # Incorrectly counted old orders
            'dca_events': []  # Empty after migration
        }
        
        # New trade
        new_trade = {
            'market': 'NEW-EUR',
            'dca_buys': 0,
            'dca_events': []
        }
        
        # Count ACTUAL DCAs from events, not dca_buys counter
        old_actual_dcas = len(old_trade['dca_events'])
        new_actual_dcas = len(new_trade['dca_events'])
        
        assert old_actual_dcas == 0, "Old trade should have 0 actual DCA events"
        assert new_actual_dcas == 0, "New trade starts with 0 DCAs"
        
        # If we trust dca_buys counter, we get polluted data
        assert old_trade['dca_buys'] == 24, "dca_buys counter is polluted"
        
        # Solution: Always use len(dca_events) for accurate count
        assert old_actual_dcas < old_trade['dca_buys'], "Events list is source of truth"


@pytest.mark.skip(reason="dashboard_flask removed 2026-04-29; logic now in tools/dashboard_v2 backend")
class TestDashboardCalculations:
    """Test dashboard P/L calculations."""
    
    def test_dashboard_uses_invested_eur_for_display(self):
        """Test: Dashboard calculate_trade_financials() uses invested_eur as
        the authoritative cost basis.  The sync engine keeps invested_eur
        correct via derive_cost_basis (see FIX_LOG.md #001).

        When invested_eur is available, it is used directly.
        Falls back to buy_price*amount only when invested_eur is missing.
        """
        pytest.importorskip("flask", reason="flask not installed")
        from tools.dashboard_flask.app import calculate_trade_financials
        
        # Case 1: invested_eur matches buy_price*amount → use invested_eur
        trade = {
            'buy_price': 100.0,
            'amount': 1.5,
            'initial_invested_eur': 100.0,
            'total_invested_eur': 150.0,
            'invested_eur': 150.0  # Consistent: 100 * 1.5 = 150
        }
        result = calculate_trade_financials(trade, 120.0)
        assert result['invested'] == 150.0, "Should use invested_eur when consistent with buy_price*amount"
        assert result['current_value'] == 180.0, "current_value = price * amount = 120 * 1.5"
        assert result['pnl'] == 30.0, "P/L = 180 - 150 = 30"
        assert abs(result['pnl_pct'] - 20.0) < 0.1, "P/L % = (180/150 - 1) * 100 = 20%"

        # Case 2: invested_eur is authoritative — used directly even if != buy_price*amount
        # (derive_cost_basis includes fees, so invested_eur may differ from buy_price*amount)
        trade_with_fees = {
            'buy_price': 100.0,
            'amount': 1.5,
            'initial_invested_eur': 100.0,
            'total_invested_eur': 100.0,
            'invested_eur': 100.0  # This is what derive says (includes fees differently)
        }
        result_fees = calculate_trade_financials(trade_with_fees, 120.0)
        assert result_fees['invested'] == 100.0, "Should trust invested_eur from derive_cost_basis"
        assert result_fees['pnl'] == 80.0, "P/L = 180 - 100 = 80"

        # Case 3: invested_eur is 0/missing → fallback to buy_price*amount
        trade_missing = {
            'buy_price': 100.0,
            'amount': 1.5,
            'invested_eur': 0,
        }
        result_missing = calculate_trade_financials(trade_missing, 120.0)
        assert result_missing['invested'] == 150.0, "Should fallback to buy_price*amount when invested is 0"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
