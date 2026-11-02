"""Плоская мишень и временной шум на синтетических данных"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from utils.calibration_quality import measure_planarity, measure_depth_stability
from utils.stereo_calibration import CalibrationSession, board_points


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.points = board_points(27).astype(np.float64)
        self.points[:, 2] = 600 + self.points[:, 0] * 0.2

    def test_tilted_plane_and_nonplanar_board(self):
        self.assertLess(measure_planarity(self.points)['plane_max_mm'], 1e-9)
        bent = self.points.copy()
        bent[:, 2] += ((bent[:, 0] - 81) / 81) ** 2 * 5
        self.assertGreater(measure_planarity(bent)['plane_rms_mm'], 1)
        with self.assertRaises(ValueError):
            measure_planarity(np.zeros((49, 3)))

    def test_depth_noise_is_not_removed_by_plane_fit(self):
        series = [self.points + (0, 0, offset) for offset in (-1, 0, 1)]
        result = measure_depth_stability(series)
        self.assertAlmostEqual(result['point_depth_std_mean_mm'], 1)
        self.assertAlmostEqual(result['center_depth_std_mm'], 1)
        self.assertAlmostEqual(result['center_depth_range_mm'], 2)
        self.assertEqual(measure_depth_stability([self.points] * 3)['point_depth_std_max_mm'], 0)
        for invalid in ([self.points] * 2, [self.points * np.nan] * 3):
            with self.assertRaises(ValueError):
                measure_depth_stability(invalid)

    def run_series(self, mode='ok'):
        session = CalibrationSession()
        session.active, session.session_id = True, 'test-session'
        session.image_size = (1280, 720)
        corners = np.zeros((49, 1, 2))
        def observation(number):
            return dict(rotation=0, corners={'primary': corners.copy(), 'secondary': corners.copy()},
                        pair=SimpleNamespace(primary=SimpleNamespace(sequence=number, timestamp_ns=number * 1000000000),
                                             secondary=SimpleNamespace(sequence=number, timestamp_ns=number * 1000000000),
                                             delta_ms=2))
        session.observation = observation(1)
        count = 1
        def observe(*args, **kwargs):
            nonlocal count
            count += 1
            session.observation = observation(1 if mode == 'duplicate' else count)
            if mode == 'lost':
                session.observation['corners']['secondary'] = None
            if mode == 'moved':
                session.observation['corners']['primary'] += 6

        with tempfile.TemporaryDirectory() as root, \
                patch.object(session, '_root', return_value=Path(root)), \
                patch.object(session, 'verify_observation'), \
                patch.object(session, 'observe', side_effect=observe), \
                patch('utils.stereo_calibration.load_calibration', return_value=({}, {})), \
                patch('utils.stereo_calibration.triangulate_board', return_value=(self.points, [])), \
                patch('utils.stereo_calibration.time.perf_counter',
                      side_effect=iter((0, 26, 27)) if mode == 'timeout' else time.perf_counter), \
                patch('utils.stereo_calibration.time.sleep'):
            if mode == 'ok':
                result = session.measure_quality('test-session', 'snapshot', 'a' * 32, True, True, True)
                self.assertEqual(result['quality']['frames'], 10)
                self.assertEqual(result['quality']['center_depth_range_mm'], 0)
                self.assertLess(result['quality']['plane_max_mm'], 1e-9)
            else:
                with self.assertRaises(ValueError):
                    session.measure_quality('test-session', 'snapshot', 'a' * 32, True, True, True)
            report_path = next((Path(root) / 'test-session' / 'quality_checks').glob('*.json'))
            report = json.loads(report_path.read_text())
            self.assertEqual(report['status'], 'measured' if mode == 'ok' else 'not_measurable')
            self.assertEqual(session.samples, [])
            self.assertIsNone(session.observation)
            self.assertFalse((Path(root) / 'test-session' / 'parameters.npz').exists())

    def test_fresh_series_and_read_only_calibration(self):
        self.run_series()

    def test_invalid_series_is_not_a_success(self):
        for mode in ('duplicate', 'lost', 'moved', 'timeout'):
            with self.subTest(mode=mode):
                self.run_series(mode)

    def test_stationary_confirmation_required(self):
        with self.assertRaises(ValueError):
            CalibrationSession().measure_quality(None, None, None, True, True, False)


if __name__ == '__main__':
    unittest.main()
