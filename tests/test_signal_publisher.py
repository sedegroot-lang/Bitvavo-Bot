"""Tests for modules/signal_publisher.py — signal formatting, rate limiting, delayed send."""

import time
import pytest
from unittest.mock import patch, MagicMock

import modules.signal_publisher as sp


@pytest.fixture(autouse=True)
def _reset_module():
    """Reset module state before each test."""
    sp._token = ""
    sp._channel_id = ""
    sp._enabled = False
    sp._delay_seconds = 0
    sp._include_price = True
    sp._include_score = False
    sp._include_regime = True
    sp._affiliate_link = ""
    sp._init_done = False
    sp._msg_timestamps.clear()
    yield


def _make_config(**overrides):
    """Create a SIGNAL_PUBLISHER config dict."""
    sp_cfg = {
        "enabled": True,
        "bot_token": "test-token-123",
        "channel_id": "@test_channel",
        "delay_seconds": 0,
        "include_price": True,
        "include_score": False,
        "include_regime": True,
        "affiliate_link": "",
    }
    sp_cfg.update(overrides)
    return {"SIGNAL_PUBLISHER": sp_cfg}


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_with_valid_config(self):
        sp.init(_make_config())
        assert sp._enabled is True
        assert sp._token == "test-token-123"
        assert sp._channel_id == "@test_channel"
        assert sp._init_done is True

    def test_init_disabled(self):
        sp.init(_make_config(enabled=False))
        assert sp._enabled is False
        assert sp._init_done is True

    def test_init_fallback_bot_token(self):
        """Falls back to TELEGRAM_BOT_TOKEN if sp-specific token is empty."""
        cfg = {"SIGNAL_PUBLISHER": {"enabled": True, "channel_id": "@ch", "bot_token": ""}, "TELEGRAM_BOT_TOKEN": "fallback-tok"}
        sp.init(cfg)
        assert sp._token == "fallback-tok"

    def test_init_empty_config(self):
        sp.init({})
        assert sp._enabled is False
        assert sp._token == ""
        assert sp._init_done is True

    def test_init_delay_seconds(self):
        sp.init(_make_config(delay_seconds=30))
        assert sp._delay_seconds == 30

    def test_init_affiliate_link(self):
        sp.init(_make_config(affiliate_link="https://bitvavo.com?a=ref123"))
        assert sp._affiliate_link == "https://bitvavo.com?a=ref123"

    def test_init_include_flags(self):
        sp.init(_make_config(include_price=False, include_score=True, include_regime=False))
        assert sp._include_price is False
        assert sp._include_score is True
        assert sp._include_regime is False


# ---------------------------------------------------------------------------
# _rate_limited()
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_under_limit(self):
        sp._msg_timestamps.extend([time.time()] * 5)
        assert sp._rate_limited() is False

    def test_at_limit(self):
        sp._msg_timestamps.extend([time.time()] * 20)
        assert sp._rate_limited() is True

    def test_old_timestamps_pruned(self):
        old = time.time() - 120  # 2 minutes ago
        sp._msg_timestamps.extend([old] * 25)
        assert sp._rate_limited() is False
        assert len(sp._msg_timestamps) == 0


# ---------------------------------------------------------------------------
# _send()
# ---------------------------------------------------------------------------

class TestSend:
    @patch("modules.signal_publisher.requests.post")
    def test_send_success(self, mock_post):
        sp.init(_make_config())
        mock_post.return_value = MagicMock(ok=True)

        result = sp._send("Test message")

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["chat_id"] == "@test_channel"
        assert call_kwargs[1]["json"]["text"] == "Test message"
        assert call_kwargs[1]["json"]["parse_mode"] == "HTML"

    @patch("modules.signal_publisher.requests.post")
    def test_send_disabled(self, mock_post):
        sp.init(_make_config(enabled=False))
        result = sp._send("Test")
        assert result is False
        mock_post.assert_not_called()

    @patch("modules.signal_publisher.requests.post")
    def test_send_no_channel(self, mock_post):
        sp.init(_make_config(channel_id=""))
        result = sp._send("Test")
        assert result is False
        mock_post.assert_not_called()

    @patch("modules.signal_publisher.requests.post")
    def test_send_rate_limited(self, mock_post):
        sp.init(_make_config())
        sp._msg_timestamps.extend([time.time()] * 20)
        result = sp._send("Test")
        assert result is False
        mock_post.assert_not_called()

    @patch("modules.signal_publisher.requests.post")
    def test_send_api_error(self, mock_post):
        sp.init(_make_config())
        mock_post.return_value = MagicMock(ok=False, text='{"error": "bad request"}')
        result = sp._send("Test")
        assert result is False

    @patch("modules.signal_publisher.requests.post")
    def test_send_exception(self, mock_post):
        sp.init(_make_config())
        mock_post.side_effect = ConnectionError("network down")
        result = sp._send("Test")
        assert result is False


# ---------------------------------------------------------------------------
# _send_delayed()
# ---------------------------------------------------------------------------

class TestSendDelayed:
    @patch("modules.signal_publisher._send")
    def test_no_delay(self, mock_send):
        sp.init(_make_config(delay_seconds=0))
        sp._send_delayed("msg")
        mock_send.assert_called_once_with("msg")

    @patch("modules.signal_publisher.threading.Thread")
    def test_with_delay(self, mock_thread_cls):
        sp.init(_make_config(delay_seconds=30))
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        sp._send_delayed("msg")

        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()


# ---------------------------------------------------------------------------
# _footer()
# ---------------------------------------------------------------------------

class TestFooter:
    def test_no_affiliate(self):
        sp._affiliate_link = ""
        assert sp._footer() == ""

    def test_with_affiliate(self):
        sp._affiliate_link = "https://bitvavo.com?a=ref"
        footer = sp._footer()
        assert "bitvavo.com" in footer
        assert "href" in footer


# ---------------------------------------------------------------------------
# publish_buy()
# ---------------------------------------------------------------------------

class TestPublishBuy:
    @patch("modules.signal_publisher._send_delayed")
    def test_buy_full_message(self, mock_send):
        sp.init(_make_config(include_score=True))

        sp.publish_buy("BTC-EUR", 65000.1234, 50.0, score=8.5, regime="trending_up")

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "BUY SIGNAL: BTC" in msg
        assert "65000.1234" in msg
        assert "€50.00" in msg
        assert "8.5" in msg
        assert "Trending Up" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_buy_no_price(self, mock_send):
        sp.init(_make_config(include_price=False))

        sp.publish_buy("ETH-EUR", 3000.0, 25.0)

        msg = mock_send.call_args[0][0]
        assert "Entry" not in msg
        assert "BUY SIGNAL: ETH" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_buy_disabled(self, mock_send):
        sp.init(_make_config(enabled=False))
        sp.publish_buy("BTC-EUR", 65000.0, 50.0)
        mock_send.assert_not_called()

    @patch("modules.signal_publisher._send_delayed")
    def test_buy_no_regime(self, mock_send):
        sp.init(_make_config(include_regime=False))
        sp.publish_buy("BTC-EUR", 65000.0, 50.0, regime="bearish")
        msg = mock_send.call_args[0][0]
        assert "Regime" not in msg


# ---------------------------------------------------------------------------
# publish_sell()
# ---------------------------------------------------------------------------

class TestPublishSell:
    @patch("modules.signal_publisher._send_delayed")
    def test_sell_profit(self, mock_send):
        sp.init(_make_config())

        sp.publish_sell("BTC-EUR", 60000.0, 65000.0, 12.50, 8.3,
                        reason="trailing_stop", hold_time_hours=4.5, dca_count=2)

        msg = mock_send.call_args[0][0]
        assert "SELL SIGNAL: BTC" in msg
        assert "✅" in msg
        assert "+€12.50" in msg
        assert "+8.3%" in msg
        assert "Trailing Stop" in msg
        assert "4.5 uur" in msg
        assert "DCA buys: 2x" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_sell_loss(self, mock_send):
        sp.init(_make_config())

        sp.publish_sell("ETH-EUR", 3000.0, 2800.0, -5.00, -6.7, reason="stop_loss")

        msg = mock_send.call_args[0][0]
        assert "🔴" in msg
        assert "-€5.00" not in msg  # sign is "" for negative
        assert "-6.7%" in msg
        assert "Stop Loss" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_sell_hold_time_minutes(self, mock_send):
        sp.init(_make_config())
        sp.publish_sell("BTC-EUR", 60000.0, 60500.0, 2.0, 0.8, hold_time_hours=0.5)
        msg = mock_send.call_args[0][0]
        assert "30 min" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_sell_hold_time_days(self, mock_send):
        sp.init(_make_config())
        sp.publish_sell("BTC-EUR", 60000.0, 60500.0, 2.0, 0.8, hold_time_hours=72)
        msg = mock_send.call_args[0][0]
        assert "3.0 dagen" in msg


# ---------------------------------------------------------------------------
# publish_dca()
# ---------------------------------------------------------------------------

class TestPublishDCA:
    @patch("modules.signal_publisher._send_delayed")
    def test_dca_message(self, mock_send):
        sp.init(_make_config())

        sp.publish_dca("XRP-EUR", 2, 0.52, 10.0, 0.55, 5.5)

        msg = mock_send.call_args[0][0]
        assert "DCA #2: XRP" in msg
        assert "0.5200" in msg
        assert "€10.00" in msg
        assert "0.5500" in msg
        assert "5.5%" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_dca_disabled(self, mock_send):
        sp.init(_make_config(enabled=False))
        sp.publish_dca("XRP-EUR", 1, 0.5, 10.0, 0.5, 3.0)
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# publish_partial_tp()
# ---------------------------------------------------------------------------

class TestPublishPartialTP:
    @patch("modules.signal_publisher._send_delayed")
    def test_partial_tp(self, mock_send):
        sp.init(_make_config())

        sp.publish_partial_tp("BTC-EUR", 2, 0.25, 68000.0, 15.0)

        msg = mock_send.call_args[0][0]
        assert "PARTIAL TP L2: BTC" in msg
        assert "25%" in msg
        assert "68000.0000" in msg
        assert "+€15.00" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_partial_tp_disabled(self, mock_send):
        sp.init(_make_config(enabled=False))
        sp.publish_partial_tp("BTC-EUR", 1, 0.2, 70000.0, 5.0)
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# publish_regime_change()
# ---------------------------------------------------------------------------

class TestPublishRegimeChange:
    @patch("modules.signal_publisher._send_delayed")
    def test_regime_change(self, mock_send):
        sp.init(_make_config())

        sp.publish_regime_change("ranging", "trending_up", 0.85)

        msg = mock_send.call_args[0][0]
        assert "REGIME WIJZIGING" in msg
        assert "Ranging" in msg
        assert "Trending Up" in msg
        assert "85%" in msg
        assert "Overweeg long trades" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_regime_change_bearish(self, mock_send):
        sp.init(_make_config())

        sp.publish_regime_change("trending_up", "bearish", 0.92)

        msg = mock_send.call_args[0][0]
        assert "📉" in msg
        assert "vermijd nieuwe posities" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_regime_change_disabled(self, mock_send):
        sp.init(_make_config(include_regime=False))
        sp.publish_regime_change("ranging", "bearish", 0.9)
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# publish_daily_summary()
# ---------------------------------------------------------------------------

class TestPublishDailySummary:
    @patch("modules.signal_publisher._send_delayed")
    def test_daily_summary_profit(self, mock_send):
        sp.init(_make_config())

        sp.publish_daily_summary(10, 7, 3, 25.50, best_trade="BTC +€12", worst_trade="ETH -€3", regime="trending_up")

        msg = mock_send.call_args[0][0]
        assert "DAGELIJKS OVERZICHT" in msg
        assert "+€25.50" in msg
        assert "W: 7 / L: 3" in msg
        assert "70%" in msg
        assert "BTC +€12" in msg
        assert "ETH -€3" in msg
        assert "Trending Up" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_daily_summary_loss(self, mock_send):
        sp.init(_make_config())
        sp.publish_daily_summary(5, 1, 4, -8.30)
        msg = mock_send.call_args[0][0]
        assert "🔴" in msg

    @patch("modules.signal_publisher._send_delayed")
    def test_daily_summary_no_trades(self, mock_send):
        sp.init(_make_config())
        sp.publish_daily_summary(0, 0, 0, 0.0)
        msg = mock_send.call_args[0][0]
        assert "N/A" in msg


# ---------------------------------------------------------------------------
# test_signal()
# ---------------------------------------------------------------------------

class TestTestSignal:
    @patch("modules.signal_publisher._send")
    def test_test_signal(self, mock_send):
        sp.init(_make_config())
        mock_send.return_value = True

        result = sp.test_signal()

        assert result is True
        msg = mock_send.call_args[0][0]
        assert "TEST SIGNAAL" in msg
        assert "succesvol geconfigureerd" in msg
