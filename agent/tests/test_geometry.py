import unittest

from laptopremote_agent.geometry import normalize


class GeometryTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize(1600, 900), (1600, 900))
        self.assertEqual(normalize(333, 201), (332, 200))
        self.assertEqual(normalize(10, 10), (320, 200))
        self.assertEqual(normalize(9000, 5000), (4096, 4096))
        self.assertEqual(normalize(1601, 901), (1600, 900))
