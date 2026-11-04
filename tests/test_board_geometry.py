"""Метрическая проверка на идеальных проекциях, без реальных камер"""

import unittest
from unittest.mock import patch
import time
import tempfile
from pathlib import Path

import cv2
import numpy as np

from utils.stereo_calibration import CalibrationSession, board_points, measure_board_geometry, validate_square_mm


class BoardGeometryTests(unittest.TestCase):
    def setUp(self):
        k = np.array([[800., 0, 640], [0, 800, 360], [0, 0, 1]])
        self.arrays = dict(k1=k, k2=k, d1=np.zeros(5), d2=np.zeros(5),
                           R1=np.eye(3), R2=np.eye(3),
                           P1=k @ np.column_stack((np.eye(3), np.zeros(3))),
                           P2=k @ np.column_stack((np.eye(3), [-120., 0, 0])))
        rotation = np.array([0.12, 0.2, 0.03])
        self.primary, _ = cv2.projectPoints(board_points(), rotation, np.array([-100., -100, 1000]), k, np.zeros(5))
        self.secondary, _ = cv2.projectPoints(board_points(), rotation, np.array([-220., -100, 1000]), k, np.zeros(5))

    def test_known_square_and_wrong_scale(self):
        metrics = measure_board_geometry(self.primary, self.secondary, self.arrays)
        self.assertEqual(metrics['segments'], 84)
        self.assertLess(metrics['max_error_mm'], 0.001)
        wrong = dict(self.arrays, P2=self.arrays['P2'].copy())
        wrong['P2'][0, 3] *= 2
        metrics = measure_board_geometry(self.primary, self.secondary, wrong)
        self.assertAlmostEqual(metrics['mean_length_mm'], 90, places=3)
        self.assertAlmostEqual(metrics['mean_error_mm'], 45, places=3)

    def test_smaller_board_with_existing_camera_parameters(self):
        primary, _ = cv2.projectPoints(board_points(20), np.zeros(3), np.array([-50., -50, 600]),
                                      self.arrays['k1'], np.zeros(5))
        secondary, _ = cv2.projectPoints(board_points(20), np.zeros(3), np.array([-170., -50, 600]),
                                        self.arrays['k2'], np.zeros(5))
        metrics = measure_board_geometry(primary, secondary, self.arrays, 20)
        self.assertLess(metrics['max_error_mm'], 0.001)
        self.assertEqual(metrics['expected_mm'], 20)
        wrong = measure_board_geometry(primary, secondary, self.arrays, 45)
        self.assertAlmostEqual(wrong['mean_error_mm'], 25, places=3)

    def test_square_validation_and_session_size(self):
        for value in (0, -1, float('nan'), float('inf'), True, None, '20'):
            with self.assertRaises(ValueError):
                validate_square_mm(value)
        session = CalibrationSession()
        with patch('utils.stereo_calibration.maintenance.begin'):
            self.assertEqual(session.start(20)['square_mm'], 20)
        self.assertEqual(session.square_mm, 20)

    def test_invalid_points_and_depth(self):
        for secondary in (self.secondary[:40], self.secondary * np.nan, self.primary):
            with self.assertRaises(ValueError):
                measure_board_geometry(self.primary, secondary, self.arrays)
        with self.assertRaises(ValueError):
            measure_board_geometry(self.secondary, self.primary, self.arrays)

    def test_new_pair_uses_saved_calibration_without_training(self):
        session = CalibrationSession()
        session.active, session.session_id = True, 'new-session'
        session.signature, session.image_size = {'test': 'mode'}, (1280, 720)
        session.observation = {'id': 'new-pair', 'created': time.monotonic(),
                               'corners': {'primary': self.primary, 'secondary': self.secondary}}
        with tempfile.TemporaryDirectory() as root, \
                patch.object(session, '_root', return_value=Path(root)), \
                patch('utils.stereo_calibration.calibration_fingerprint', return_value='test-fingerprint'), \
                patch('utils.stereo_calibration.Path.read_bytes', return_value=b'test-parameters'), \
                patch.object(session, '_camera_signature', return_value=session.signature), \
                patch('utils.stereo_calibration.get_camera_manager'), \
                patch('utils.stereo_calibration.load_calibration', return_value=(
                    {'image_size': [1280, 720], 'units': 'mm', 'board': [7, 7], 'square_mm': 45}, self.arrays)) as load:
            result = session.verify_observation('new-session', 'new-pair', 'a' * 32, True, True)
            self.assertLess(result['geometry']['max_error_mm'], 0.001)
            load.assert_called_once()
            self.assertEqual(session.samples, [])
            self.assertIsNone(session.result)
            for args in [('old', 'new-pair', True, True), ('new-session', 'old', True, True),
                         ('new-session', 'new-pair', False, True), ('new-session', 'new-pair', True, False)]:
                with self.assertRaises(ValueError):
                    session.verify_observation(args[0], args[1], 'a' * 32, args[2], args[3])
            session.observation['created'] -= 31
            with self.assertRaises(ValueError):
                session.verify_observation('new-session', 'new-pair', 'a' * 32, True, True)


if __name__ == '__main__':
    unittest.main()
