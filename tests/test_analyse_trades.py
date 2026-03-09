import unittest
from trailing_bot import analyse_trades

class TestAnalyseTrades(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(analyse_trades([]), (0.0, 0.0, 0.0, 0.0))

    def test_values(self):
        trades = [{'profit': 10}, {'profit': -5}, {'profit': 0}]
        w, aw, al, ap = analyse_trades(trades)
        self.assertAlmostEqual(w, 1/3)
        self.assertAlmostEqual(aw, 10.0)
        self.assertAlmostEqual(al, -2.5)
        self.assertAlmostEqual(ap, (10-5+0)/3)

if __name__ == '__main__':
    unittest.main()
