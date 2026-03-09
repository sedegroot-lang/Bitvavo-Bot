import unittest
import os
import json
from trailing_bot import get_current_price
from trailing_bot import CONFIG
PRICE_CACHE_FILE = CONFIG.get('PRICE_CACHE_FILE', 'data/price_cache.json')

class TestPriceCache(unittest.TestCase):
    def test_disk_cache_write_and_read(self):
        # simulate writing to disk by calling get_current_price for a fake market
        market = '__TEST_FAKE_MARKET__-EUR'
        # remove any existing cache file
        if os.path.exists(PRICE_CACHE_FILE):
            try:
                os.remove(PRICE_CACHE_FILE)
            except:
                pass
        # call get_current_price (will attempt API and fallback) - we don't assert the value,
        # just ensure the function runs and the cache file exists after
        _ = get_current_price(market)
        self.assertTrue(os.path.exists(PRICE_CACHE_FILE))
        with open(PRICE_CACHE_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertIn(market, data)

if __name__ == '__main__':
    unittest.main()
