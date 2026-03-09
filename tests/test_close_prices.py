import unittest
from trailing_bot import close_prices

class TestClosePrices(unittest.TestCase):
    def test_valid_and_malformed(self):
        # valid candles: each entry has index 4 numeric
        candles = [
            [0,0,0,0,'1.23',0],
            [0,0,0,0,'2.5',0],
            ['a','b'],  # too short
            [1,2,3,4,'r',0],  # non-numeric
            [1,2,3,4,3.14,0],
        ]
        result = close_prices(candles)
        # Expect only numeric closes parsed: 1.23, 2.5, 3.14
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 1.23)
        self.assertAlmostEqual(result[1], 2.5)
        self.assertAlmostEqual(result[2], 3.14)

if __name__ == '__main__':
    unittest.main()
