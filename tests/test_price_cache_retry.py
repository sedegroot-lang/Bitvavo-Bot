import unittest
import os, json, time
import importlib
import trailing_bot

try:
    bot_api = importlib.import_module("bot.api")
except ModuleNotFoundError:
    bot_api = trailing_bot

class TestPriceCacheRetry(unittest.TestCase):
    def setUp(self):
        # ensure fresh cache file
        self.cache_file = trailing_bot.CONFIG.get('PRICE_CACHE_FILE', 'data/price_cache.json')
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except Exception:
            pass

    def test_disk_cache_write_and_read_retry(self):
        # Monkeypatch _fetch_price_once in both locations (strangler fig pattern)
        orig_fetch = bot_api._fetch_price_once
        calls = {'n':0}
        def fake_fetch(m):
            calls['n'] += 1
            if calls['n'] == 1:
                return None
            return 12.34
        try:
            bot_api._fetch_price_once = fake_fetch
            trailing_bot._fetch_price_once = fake_fetch
            market = '__TEST_RETRY__-EUR'
            p = trailing_bot.get_current_price(market)
            # Should return 12.34 (second attempt)
            self.assertAlmostEqual(p, 12.34)
            # Disk cache should contain the price
            with open(self.cache_file, 'r', encoding='utf-8') as fh:
                d = json.load(fh)
            self.assertIn(market, d)
            self.assertEqual(float(d[market]['price']), 12.34)
        finally:
            bot_api._fetch_price_once = orig_fetch
            trailing_bot._fetch_price_once = orig_fetch

if __name__ == '__main__':
    unittest.main()
