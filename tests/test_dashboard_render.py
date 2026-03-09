import math

import pytest

from modules.dashboard_render import (
    calculate_trade_financials,
    determine_status_badge,
    logo_url_for_market,
    make_card_identifier,
    summarize_totals,
)


def test_calculate_trade_financials_with_dca_amount() -> None:
    invested, current_value, pnl_eur, pnl_pct = calculate_trade_financials(
        buy_price=10.0,
        amount=3.0,
        live_price=12.5,
    )
    assert pytest.approx(invested, rel=1e-6) == 30.0
    assert pytest.approx(current_value, rel=1e-6) == 37.5
    assert pytest.approx(pnl_eur, rel=1e-6) == 7.5
    assert pytest.approx(pnl_pct, rel=1e-6) == 25.0


def test_calculate_trade_financials_handles_missing_live_price() -> None:
    invested, current_value, pnl_eur, pnl_pct = calculate_trade_financials(
        buy_price=8.0,
        amount=2.0,
        live_price=None,
    )
    assert invested == 16.0
    assert math.isnan(current_value)
    assert math.isnan(pnl_eur)
    assert math.isnan(pnl_pct)


def test_determine_status_badge_affirms_trailing() -> None:
    label, css = determine_status_badge(pnl_eur=-5.0, trailing_active=True)
    assert label == "Trailing actief"
    assert css == "badge-trailing"


def test_determine_status_badge_profit_and_loss() -> None:
    label_profit, css_profit = determine_status_badge(pnl_eur=4.0, trailing_active=False)
    label_loss, css_loss = determine_status_badge(pnl_eur=-0.5, trailing_active=False)
    assert (label_profit, css_profit) == ("Winst", "badge-profit")
    assert (label_loss, css_loss) == ("Verlies", "badge-loss")


def test_summarize_totals_accumulates_multiple_trades() -> None:
    summary = summarize_totals(
        [
            {"invested_eur": 25.0, "current_value_eur": 30.0, "pnl_eur": 5.0},
            {"invested_eur": 10.0, "current_value_eur": math.nan, "pnl_eur": math.nan},
            {"invested_eur": 15.0, "current_value_eur": 12.0, "pnl_eur": -3.0},
        ]
    )
    assert pytest.approx(summary["invested_total"], rel=1e-6) == 50.0
    assert pytest.approx(summary["current_total"], rel=1e-6) == 42.0
    assert pytest.approx(summary["pnl_total"], rel=1e-6) == 2.0
    assert pytest.approx(summary["pnl_pct"], rel=1e-6) == 4.0


def test_make_card_identifier_is_stable_and_safe() -> None:
    assert make_card_identifier("BTC-EUR") == "trade-card-btc-eur"
    assert make_card_identifier("   ") == "trade-card-unknown-market"


def test_make_card_identifier_is_stable_across_renders() -> None:
    first = make_card_identifier("ADA-EUR")
    second = make_card_identifier("ADA-EUR")
    assert first == second


def test_make_card_identifier_unique_per_market() -> None:
    ids = {make_card_identifier(m) for m in ["BTC-EUR", "ETH-EUR", "XRP-EUR"]}
    assert len(ids) == 3


def test_logo_url_for_market_resolves_symbol() -> None:
    eth_url = logo_url_for_market("ETH-EUR").lower()
    doge_url = logo_url_for_market("DOGE-USDT").lower()
    assert "eth" in eth_url or "1027" in eth_url
    assert "doge" in doge_url or "74" in doge_url