import unittest
import numpy as np
from utils import ema, bollinger_bands, stochastic, sma, rsi, macd, atr, close_prices, highs, lows, volumes

class TestUtils(unittest.TestCase):
    def test_ema_empty(self):
        self.assertIsNone(ema([], 5))
    def test_bollinger_short(self):
        upper, ma, lower = bollinger_bands([1,2,3], 20)
        self.assertIsNone(upper)
    def test_stochastic_short(self):
        self.assertIsNone(stochastic([1,2,3], 14))
    def test_sma_short(self):
        self.assertIsNone(sma([1,2], 5))
    def test_rsi_short(self):
        self.assertIsNone(rsi([1,2,3], 14))
    def test_macd_short(self):
        m,s,d = macd([1,2,3], 12, 26, 9)
        self.assertEqual((m,s,d), (None,None,None))
    def test_atr_short(self):
        self.assertIsNone(atr([1,2], [1,2], [1,2], 14))
    def test_ema(self):
        vals = [1,2,3,4,5,6,7,8,9,10]
        self.assertAlmostEqual(ema(vals, 5), np.mean(vals[-5:]), delta=2)
    def test_bollinger(self):
        vals = [1]*20
        upper, ma, lower = bollinger_bands(vals)
        self.assertEqual(upper, ma)
        self.assertEqual(lower, ma)
    def test_stochastic(self):
        vals = list(range(1,15))
        self.assertTrue(0 <= stochastic(vals, 14) <= 100)
    def test_sma(self):
        vals = [1,2,3,4,5]
        self.assertEqual(sma(vals, 5), 3)
    def test_rsi(self):
        vals = [1,2,3,4,5,6,7,8,9,10,9,8,7,6,5]
        self.assertTrue(0 <= rsi(vals, 14) <= 100)
    def test_macd(self):
        vals = list(range(1,40))
        m,s,d = macd(vals)
        self.assertIsInstance(m, float)
    def test_atr(self):
        h = [10]*15
        l = [5]*15
        c = [7]*15
        self.assertTrue(atr(h,l,c,14) >= 0)
    def test_close_prices(self):
        c = [[0,0,0,0,1]]*5
        self.assertEqual(close_prices(c), [1]*5)
    def test_highs(self):
        c = [[0,2]]*5
        self.assertEqual(highs(c), [2]*5)
    def test_lows(self):
        c = [[0,0,3]]*5
        self.assertEqual(lows(c), [3]*5)
    def test_volumes(self):
        c = [[0,0,0,0,0,4]]*5
        self.assertEqual(volumes(c), [4]*5)

if __name__ == '__main__':
    unittest.main()
