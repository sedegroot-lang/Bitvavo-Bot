"""bot.trade_repair — Periodic sanity check that detects + repairs corrupted trade data.

Extracted from `trailing_bot.validate_and_repair_trades` during road-to-10 #066.

Reads CONFIG + open_trades from `bot.shared.state`. Writes via `state.save_trades_fn`.
NEVER raises. Returns the number of repairs made.

Guards:
- DCA derived-fields desync via `core.dca_state.sync_derived_fields`.
- Negative invested_eur via `core.trade_investment.repair_negative`.
- Absurdly high total_invested_eur (> base × dca_max × 3 safety margin).
- invested_eur ↔ initial_invested_eur + sum(dca_events) - partial_tp consistency.
- buy_price × amount fallback when invested_eur is 0.

See FIX_LOG.md #001 for the root cause + #007 for the GUARD-unification.
"""

from __future__ import annotations

from typing import Any, Dict

from bot.shared import state


def _log(msg: str, level: str = "info") -> None:
    try:
        state.log(msg, level=level)
    except Exception:
        pass


def validate_and_repair_trades() -> int:
    """Sanity-check + repair every entry in `state.open_trades`. Returns repair count."""
    try:
        cfg: Dict[str, Any] = state.CONFIG or {}
        open_trades: Dict[str, Any] = state.open_trades or {}
    except Exception:
        return 0

    repairs_made = 0
    base_amount = float(cfg.get("BASE_AMOUNT_EUR", 8))
    dca_max_global = int(cfg.get("DCA_MAX_BUYS", 3))
    max_reasonable_invested = base_amount * (dca_max_global + 1) * 3  # 3x safety margin

    for market, trade in list(open_trades.items()):
        try:
            dca_max_local = int(trade.get("dca_max") or dca_max_global)
            dca_buys = int(trade.get("dca_buys", 0) or 0)
            invested = float(trade.get("invested_eur", 0) or 0)
            total_invested = float(trade.get("total_invested_eur", invested) or invested)

            # GUARD 0+1+4+5 UNIFIED: dca_state.sync_derived_fields = single source of truth.
            try:
                from core.dca_state import sync_derived_fields as _ds_sync

                _dca_state, _dca_repairs = _ds_sync(trade, dca_max_global)
                for _r in _dca_repairs:
                    _log(f"⚠️ DCA-REPAIR [{market}]: {_r}", level="warning")
                    repairs_made += 1
                dca_buys = trade.get("dca_buys", 0)
                dca_max_local = dca_max_global
            except Exception as _ds_err:
                _log(f"⚠️ dca_state.sync_derived_fields failed for {market}: {_ds_err}", level="error")

            # GUARD 2: Negative invested_eur
            if invested < 0:
                try:
                    from core.trade_investment import repair_negative as _ti_repair

                    if _ti_repair(trade, market):
                        repairs_made += 1
                except Exception:
                    pass

            # GUARD 3: Absurdly high total_invested_eur
            if total_invested > max_reasonable_invested:
                reasonable_value = base_amount * (1 + min(dca_buys, dca_max_local))
                _log(
                    f"⚠️ REPAIR [{market}]: total_invested_eur {total_invested:.2f} "
                    f"unreasonably high (max {max_reasonable_invested:.2f}), resetting "
                    f"invested_eur to {reasonable_value:.2f}",
                    level="warning",
                )
                trade["invested_eur"] = reasonable_value
                if total_invested > reasonable_value * 5:
                    trade["total_invested_eur"] = reasonable_value
                repairs_made += 1

            # GUARD 6: invested_eur ↔ initial + sum(dca_events) consistency.
            initial_inv = float(trade.get("initial_invested_eur", 0) or 0)
            partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
            _events = trade.get("dca_events", []) or []
            if initial_inv > 0 and _events:
                dca_eur_sum = sum(float(ev.get("amount_eur", 0) or 0) for ev in _events)
                expected_invested = initial_inv + dca_eur_sum - partial_tp_returned
                current_invested = float(trade.get("invested_eur", 0) or 0)
                if current_invested > 0 and current_invested < expected_invested - 0.5:
                    _log(
                        f"⚠️ REPAIR [{market}]: invested_eur={current_invested:.2f} too low. "
                        f"initial({initial_inv:.2f}) + DCAs({dca_eur_sum:.2f}) - tp("
                        f"{partial_tp_returned:.2f}) = {expected_invested:.2f}. Fixing.",
                        level="warning",
                    )
                    trade["invested_eur"] = round(expected_invested, 4)
                    expected_total = initial_inv + dca_eur_sum
                    trade["total_invested_eur"] = round(expected_total, 4)
                    amount = float(trade.get("amount", 0) or 0)
                    if amount > 0 and expected_total > 0:
                        trade["buy_price"] = round(expected_total / amount, 12)
                    repairs_made += 1
                elif current_invested > expected_invested + 5.0:
                    _log(
                        f"⚠️ WARN [{market}]: invested_eur={current_invested:.2f} > expected "
                        f"{expected_invested:.2f} (possible untracked DCAs). Review manually.",
                        level="warning",
                    )

            # GUARD 7: buy_price × amount consistency with invested_eur (final safety net).
            try:
                _bp = float(trade.get("buy_price") or 0)
                _amt = float(trade.get("amount") or 0)
                _inv = float(trade.get("invested_eur") or 0)
                _ptp = float(trade.get("partial_tp_returned_eur") or 0)
                if _bp > 0 and _amt > 0:
                    _expected_total = round(_bp * _amt, 4)
                    _expected_active = round(_expected_total - _ptp, 4)
                    if _inv <= 0:
                        _log(
                            f"⚠️ REPAIR [{market}]: invested_eur is 0, setting to "
                            f"buy_price({_bp:.6f}) × amount({_amt:.6f}) = €{_expected_active:.2f}",
                            level="warning",
                        )
                        trade["invested_eur"] = _expected_active
                        trade["total_invested_eur"] = _expected_total
                        repairs_made += 1
                    elif abs(_inv - _expected_active) / max(_expected_active, 0.01) > 0.10:
                        _log(
                            f"⚠️ WARN [{market}]: invested_eur €{_inv:.2f} diverges >10% from "
                            f"buy_price×amount €{_expected_active:.2f}. Sync engine will re-derive.",
                            level="warning",
                        )
            except Exception:
                pass

        except Exception as e:
            _log(f"⚠️ REPAIR [{market}]: Error during validation: {e}", level="warning")

    if repairs_made > 0:
        try:
            save_fn = getattr(state, "save_trades_fn", None)
            if callable(save_fn):
                save_fn()
        except Exception:
            pass
        _log(f"✅ Trade integrity check complete: {repairs_made} repairs made", level="warning")
    else:
        _log("✅ Trade integrity check complete: all trades valid", level="info")

    return repairs_made
