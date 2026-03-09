import unittest
from trailing_bot import safe_mul

class TestSafeMul(unittest.TestCase):
    def test_both_numbers(self):
        self.assertEqual(safe_mul(2, 3), 6)
        self.assertEqual(safe_mul(2.5, 4), 10.0)

    def test_none_operand(self):
        self.assertIsNone(safe_mul(None, 5))
        self.assertIsNone(safe_mul(5, None))
        self.assertIsNone(safe_mul(None, None))

    def test_invalid_types(self):
        self.assertIsNone(safe_mul('a', 2))
        self.assertIsNone(safe_mul(2, 'b'))

if __name__ == '__main__':
    unittest.main()
