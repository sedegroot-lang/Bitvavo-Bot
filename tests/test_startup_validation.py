"""Tests for the extracted bot.startup_validation.validate_config."""
from __future__ import annotations

from bot.startup_validation import validate_config


def test_clean_config_returns_no_issues():
    cfg = {
        'WHITELIST': ['BTC-EUR'],
        'BLACKLIST': ['DOGE-EUR'],
        'TP_PCT_MIN': 0.01, 'TP_PCT_MAX': 0.05,
        'TIERS': [{'min_buy': 5, 'max_buy': 20}],
        'DCA_MAX_BUYS': 3,
        'AI_ENABLED': False,
        'MAX_TOTAL_EXPOSURE_EUR': 500,
        'BASE_AMOUNT_EUR': 8, 'MAX_OPEN_TRADES': 5,
        'RISK_MAX_DAILY_LOSS': 30, 'RISK_MAX_WEEKLY_LOSS': 100,
    }
    issues = validate_config(cfg)
    assert issues == []


def test_whitelist_blacklist_overlap_flagged():
    issues = validate_config({'WHITELIST': ['BTC-EUR'], 'BLACKLIST': ['BTC-EUR']})
    assert any('WHITELIST' in i and 'BLACKLIST' in i for i in issues)


def test_tp_min_above_max_flagged():
    issues = validate_config({'TP_PCT_MIN': 0.10, 'TP_PCT_MAX': 0.05})
    assert any('TP_PCT_MIN' in i and 'TP_PCT_MAX' in i for i in issues)


def test_tiers_min_above_max_flagged():
    issues = validate_config({'TIERS': [{'min_buy': 50, 'max_buy': 10}]})
    assert any('TIERS[0]' in i for i in issues)


def test_dca_max_below_one_flagged():
    issues = validate_config({'DCA_MAX_BUYS': 0})
    assert any('DCA_MAX_BUYS' in i for i in issues)


def test_ai_min_above_max_flagged():
    issues = validate_config({
        'AI_ENABLED': True,
        'AI_MIN_CONFIDENCE': 0.95,
        'AI_MAX_CONFIDENCE': 0.60,
    })
    assert any('AI_MIN_CONFIDENCE' in i for i in issues)


def test_max_exposure_disabled_flagged():
    issues = validate_config({'MAX_TOTAL_EXPOSURE_EUR': 9999})
    assert any('DISABLED' in i for i in issues)


def test_daily_above_weekly_loss_flagged():
    issues = validate_config({
        'RISK_MAX_DAILY_LOSS': 200, 'RISK_MAX_WEEKLY_LOSS': 100,
    })
    assert any('RISK_MAX_DAILY_LOSS' in i and 'RISK_MAX_WEEKLY_LOSS' in i for i in issues)


def test_exposure_too_low_for_trades():
    issues = validate_config({
        'MAX_TOTAL_EXPOSURE_EUR': 20,
        'BASE_AMOUNT_EUR': 8, 'MAX_OPEN_TRADES': 5,
        'RISK_MAX_DAILY_LOSS': 30, 'RISK_MAX_WEEKLY_LOSS': 100,
    })
    assert any('MAX_TOTAL_EXPOSURE_EUR' in i and '<' in i for i in issues)


def test_invalid_tiers_entry_skipped():
    # Non-dict tier entry must not crash
    issues = validate_config({'TIERS': ['not-a-dict', None, {'min_buy': 1, 'max_buy': 10}]})
    assert isinstance(issues, list)
