import unittest
from trailing_bot import analyse_trades

class TestAnalyseTradesMalformed(unittest.TestCase):
    def test_missing_and_non_numeric(self):
        trades = [
            {},
            {'profit': None},
            {'profit': '5.0'},
            {'profit': -2},
        ]
        w, aw, al, ap = analyse_trades(trades)
        # Should not raise and should return four floats
        self.assertIsInstance(w, float)
        self.assertIsInstance(aw, float)
        self.assertIsInstance(al, float)
        self.assertIsInstance(ap, float)
        # Check that averages make sense: avg_profit equals numeric interpretation
        self.assertAlmostEqual(ap, (0.0 + 0.0 + 5.0 -2.0)/4)

if __name__ == '__main__':
    unittest.main()
