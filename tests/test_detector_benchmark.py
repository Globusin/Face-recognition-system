import unittest
from scripts.benchmark_face_detectors import match, rate


class BenchmarkTests(unittest.TestCase):
    def test_duplicates_and_empty(self):
        self.assertEqual(match([(0,0,10,10)]*2, [(0,0,10,10)], .5), (1,1,0))
        self.assertEqual(match([], [(0,0,10,10)], .5), (0,0,1))
        self.assertEqual(match([(0,0,10,10)], [], .5), (0,1,0))
        self.assertIsNone(rate(0,0))

    def test_matching_is_one_to_one(self):
        self.assertEqual(match([(2,0,10,10),(0,0,10,10)],
                               [(0,0,10,10),(5,0,10,10)], .5), (2,0,0))
