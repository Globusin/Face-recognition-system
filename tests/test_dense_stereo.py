"""StereoSGBM на синтетической текстуре, не доказательство работы на коже"""

import time
import unittest

import cv2
import numpy as np

from utils.dense_stereo import disparity_consistency, measure_dense_depth, plane_statistics
from utils.frame_pairing import CameraFrame, FramePair
from utils.two_view_pad import DEFAULT_LIMITS


class DenseStereoTests(unittest.TestCase):
    def example(self, width=320, height=240, disparity=16, textured=True):
        camera = np.array([[240., 0, width / 2], [0, 240, height / 2], [0, 0, 1]])
        p1 = np.column_stack((camera, np.zeros(3)))
        p2 = np.column_stack((camera, camera @ [-40., 0, 0]))
        y, x = np.indices((height, width), dtype=np.float32)
        arrays = dict(k1=camera, k2=camera, d1=np.zeros(5), d2=np.zeros(5), R1=np.eye(3), R2=np.eye(3),
                      P1=p1, P2=p2, map1_x=x, map1_y=y, map2_x=x.copy(), map2_y=y.copy())
        image = np.random.default_rng(3).integers(0, 256, (height, width), dtype=np.uint8)
        if not textured:
            image.fill(100)
        right = np.zeros_like(image)
        right[:, :-disparity] = image[:, disparity:]
        left = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        right = cv2.cvtColor(right, cv2.COLOR_GRAY2BGR)
        timestamp = time.monotonic_ns()
        pair = FramePair(1, CameraFrame('primary', 1, timestamp, left),
                         CameraFrame('secondary', 1, timestamp, right), 0)
        angles = np.linspace(0, 2 * np.pi, 31, endpoint=False)
        points = np.column_stack((width * .6 + 35 * np.cos(angles), height * .5 + 25 * np.sin(angles)))
        return pair, arrays, {'primary': points, 'secondary': points - [disparity, 0]}

    def test_textured_plane_depth_and_repeatability(self):
        pair, arrays, points = self.example()
        result, previews = measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'measured', result)
        self.assertGreater(result['valid_fraction'], .8)
        self.assertAlmostEqual(result['metrics']['mean_depth_mm'], 600, delta=4)
        self.assertLess(result['metrics']['plane_rms_mm'], 3)
        repeated, _ = measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)
        self.assertEqual(result['metrics'], repeated['metrics'])
        self.assertEqual(set(previews), {'dense_depth', 'dense_relief'})
        self.assertTrue(previews['dense_depth'].startswith('data:image/jpeg;base64,'))
        self.assertFalse(result['stationarity_verified'])

    def test_low_texture_is_not_a_flat_surface_verdict(self):
        pair, arrays, points = self.example(textured=False)
        result, previews = measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'not_measurable')
        self.assertNotIn('metrics', result)
        self.assertEqual(previews, {})

    def test_scaled_geometry_keeps_millimetres(self):
        pair, arrays, points = self.example(width=800, height=301, disparity=16)
        result, _ = measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'measured', result)
        self.assertEqual(result['resolution'], [640, 241])
        self.assertAlmostEqual(result['metrics']['mean_depth_mm'], 600, delta=10)

    def test_left_right_consistency_and_invalid_disparities(self):
        left = np.full((4, 10), 2, dtype=np.float32)
        right = np.full_like(left, -2)
        valid, _ = disparity_consistency(left, right, 0, -15)
        self.assertFalse(valid[:, :2].any())
        self.assertTrue(valid[:, 2:].all())
        right.fill(-16)
        self.assertFalse(disparity_consistency(left, right, 0, -15)[0].any())

    def test_plane_fit_distinguishes_synthetic_relief(self):
        x, y = np.meshgrid(np.linspace(-40, 40, 20), np.linspace(-30, 30, 20))
        z = 600 + x * .1
        flat = np.column_stack((x.ravel(), y.ravel(), z.ravel()))
        curved = flat.copy()
        curved[:, 2] -= 15 * np.exp(-(x.ravel() ** 2 + y.ravel() ** 2) / 300)
        self.assertLess(plane_statistics(flat)[0]['plane_rms_mm'], 1e-8)
        self.assertGreater(plane_statistics(curved)[0]['plane_rms_mm'], 2)

    def test_reversed_or_vertical_baseline_is_rejected(self):
        pair, arrays, points = self.example()
        arrays['P2'][0, 3] *= -1
        with self.assertRaises(ValueError):
            measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)
        arrays['P2'][1, 3] = -100
        with self.assertRaises(ValueError):
            measure_dense_depth(pair, arrays, points, DEFAULT_LIMITS)


if __name__ == '__main__':
    unittest.main()
