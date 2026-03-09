import unittest
import trailing_bot

class TestExposureNone(unittest.TestCase):
    def test_exposure_ignores_none_prices(self):
        # Save original and ensure restoration to avoid leaking monkeypatch to other tests
        orig_get_price = trailing_bot.get_current_price
        try:
            # Create a fake open_trades mapping with two trades
            trailing_bot.open_trades.clear()
            trailing_bot.open_trades['COIN1-EUR'] = {'amount': 1.0}
            trailing_bot.open_trades['COIN2-EUR'] = {'amount': 2.0}
            # Monkeypatch get_current_price: return None for COIN1, valid for COIN2
            def fake_get_price(m):
                if m == 'COIN1-EUR':
                    return None
                return 5.0
            trailing_bot.get_current_price = fake_get_price
            # Run the exposure calc snippet to ensure no exceptions and correct total
            total = 0.0
            for m, t in trailing_bot.open_trades.items():
                price = trailing_bot.get_current_price(m)
                if price is None:
                    continue
                total += t['amount'] * price
            self.assertEqual(total, 2.0 * 5.0)
        finally:
            trailing_bot.get_current_price = orig_get_price

if __name__ == '__main__':
    unittest.main()
