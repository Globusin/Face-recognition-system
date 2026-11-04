"""Геометрия калибровки и правила сохранения пар без реальных камер"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from utils.maintenance import MaintenanceMode
from utils.stereo_calibration import (
    CalibrationSession, board_points, find_board, load_calibration, solve_calibration,
)


def synthetic_pairs(count=22):
    rng = np.random.default_rng(42)
    camera = np.array([[600., 0, 320], [0, 610., 240], [0, 0, 1]])
    stereo_rotation, _ = cv2.Rodrigues(np.array([0.005, 0.01, -0.003]))
    translation = np.array([[-120.], [0.], [0.]])
    pairs = []
    for _ in range(count):
        rvec = rng.uniform(-0.35, 0.35, 3)
        tvec = np.array([[rng.uniform(-150, 20)], [rng.uniform(-140, 20)], [rng.uniform(800, 1400)]])
        rboard, _ = cv2.Rodrigues(rvec)
        secondary_rvec, _ = cv2.Rodrigues(stereo_rotation @ rboard)
        primary, _ = cv2.projectPoints(board_points(), rvec, tvec, camera, None)
        secondary, _ = cv2.projectPoints(board_points(), secondary_rvec,
                                       stereo_rotation @ tvec + translation, camera, None)
        pairs.append(dict(primary=primary.astype(np.float32), secondary=secondary.astype(np.float32)))
    return pairs


class CalibrationGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = synthetic_pairs()
        cls.arrays, cls.metrics = solve_calibration(cls.pairs[:18], cls.pairs[18:], (640, 480))

    def test_known_baseline_and_held_out_error(self):
        self.assertAlmostEqual(self.metrics['baseline_mm'], 120, delta=1)
        self.assertLess(self.metrics['stereo_rms_px'], 0.1)
        self.assertLess(self.metrics['validation_vertical_mean_px'], 0.1)
        self.assertLess(self.metrics['validation_reprojection_mean_px'], 0.1)
        self.assertEqual(self.arrays['map1_x'].shape, (480, 640))

    def test_minimum_training_and_validation(self):
        with self.assertRaises(ValueError):
            solve_calibration(self.pairs[:14], self.pairs[18:], (640, 480))
        with self.assertRaises(ValueError):
            solve_calibration(self.pairs[:18], self.pairs[18:20], (640, 480))

    def test_custom_square_changes_metric_scale(self):
        _, metrics = solve_calibration(self.pairs[:18], self.pairs[18:], (640, 480), 20)
        self.assertAlmostEqual(metrics['baseline_mm'], 120 * 20 / 45, delta=0.1)

    def test_loader_rejects_other_mode_and_unconfirmed_mount(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            metadata = dict(version=1, cameras={'primary': 'test'}, image_size=[640, 480], status='requires_review')
            (path / 'metadata.json').write_text(json.dumps(metadata))
            np.savez(path / 'parameters.npz', **self.arrays)
            with self.assertRaises(ValueError):
                load_calibration(path, metadata['cameras'])
            with self.assertRaises(ValueError):
                load_calibration(path, {}, mounting_confirmed=True)
            with self.assertRaises(ValueError):
                load_calibration(path, metadata['cameras'], mounting_confirmed=True)
            _, arrays = load_calibration(path, metadata['cameras'], mounting_confirmed=True, allow_unvalidated=True)
            self.assertEqual(arrays['Q'].shape, (4, 4))
            metadata['status'] = 'invalidated'
            (path / 'metadata.json').write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):
                load_calibration(path, metadata['cameras'], mounting_confirmed=True)

    def test_board_detection_and_grid_rotation(self):
        image = np.full((400, 400, 3), 255, np.uint8)
        for row in range(8):
            for column in range(8):
                if (row + column) % 2 == 0:
                    image[40 + row * 40:80 + row * 40, 40 + column * 40:80 + column * 40] = 0
        corners = find_board(image)
        self.assertIsNotNone(corners)
        rotated = find_board(image, 2)
        np.testing.assert_allclose(corners[::-1], rotated)


class CalibrationSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gate = MaintenanceMode()
        self.patches = [
            patch('utils.stereo_calibration.maintenance', self.gate),
            patch('utils.stereo_calibration.load_config', return_value={'stereo_calibration': {'output_dir': self.directory.name}}),
            patch('utils.stereo_calibration.annotated_preview', return_value='data:image/jpeg;base64,test'),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.session = CalibrationSession()
        self.session.start()
        self.manager = Mock()
        self.manager.sources = {'primary': 'camera-a', 'secondary': 'camera-b'}
        camera = dict(status='online', width=640, height=480, reported_format='MJPG', reported_fps=30)
        self.manager.cameras_config = {'pair_max_delta_ms': 80}
        self.manager.get_status.return_value = dict(started=True, pairing={'paired_frames': 10}, cameras={'primary': camera, 'secondary': camera})
        manager_patch = patch('utils.stereo_calibration.get_camera_manager', return_value=self.manager)
        manager_patch.start()
        self.addCleanup(manager_patch.stop)
        image = np.zeros((480, 640, 3), np.uint8)
        timestamp = time.monotonic_ns()
        self.pair = SimpleNamespace(number=11, delta_ms=12,
                                    primary=SimpleNamespace(image=image, sequence=20, timestamp_ns=timestamp),
                                    secondary=SimpleNamespace(image=image, sequence=21, timestamp_ns=timestamp))
        self.manager.get_pair.return_value = self.pair
        self.corners = np.zeros((49, 1, 2), np.float32)

    def observe(self):
        with patch('utils.stereo_calibration.get_camera_manager', return_value=self.manager), \
                patch('utils.stereo_calibration.find_board', return_value=self.corners):
            return self.session.observe(self.session.session_id, 0)

    def test_saved_pair_requires_confirmation_and_cannot_be_reused(self):
        observation = self.observe()
        with self.assertRaises(ValueError):
            self.session.save_pair(self.session.session_id, observation['observation_id'], False, False)
        result = self.session.save_pair(self.session.session_id, observation['observation_id'], False, True)
        self.assertEqual(result['training_pairs'], 1)
        self.assertTrue((Path(self.directory.name) / self.session.session_id / '001_primary.png').exists())
        with self.assertRaises(ValueError):
            self.session.save_pair(self.session.session_id, observation['observation_id'], False, True)

    def test_stale_observation_and_wrong_session_rejected(self):
        observation = self.observe()
        self.session.observation['created'] -= 31
        with self.assertRaises(ValueError):
            self.session.save_pair(self.session.session_id, observation['observation_id'], False, True)
        with self.assertRaises(ValueError):
            self.session.finish('old-session')

    def test_missing_camera_has_no_usable_observation(self):
        self.manager.get_pair.return_value = None
        with self.assertRaises(ValueError):
            self.observe()
        self.assertIsNone(self.session.observation)

    def test_excessive_timestamp_difference_rejected(self):
        self.pair.delta_ms = 100
        with self.assertRaises(ValueError):
            self.observe()

    def test_changed_camera_mode_rejected_before_saving(self):
        observation = self.observe()
        self.manager.get_status.return_value['cameras']['primary']['width'] = 800
        with self.assertRaises(ValueError):
            self.session.save_pair(self.session.session_id, observation['observation_id'], False, True)

    def test_calculation_saves_maps_metadata_and_control_previews(self):
        self.session.image_size = (640, 480)
        self.session.signature = self.session._camera_signature(self.manager)
        self.session.samples = [dict(pair, validation=index >= 18)
                                for index, pair in enumerate(synthetic_pairs())]
        folder = self.session._session_folder()
        folder.mkdir(parents=True)
        image = np.zeros((480, 640, 3), np.uint8)
        for role in ('primary', 'secondary'):
            cv2.imwrite(str(folder / f'019_{role}.png'), image)
        self.session._write_samples()
        result = self.session.calculate(self.session.session_id)
        self.assertEqual(result['result']['status'], 'requires_review')
        self.assertEqual(set(result['rectified_previews']), {'primary', 'secondary'})
        metadata, arrays = load_calibration(folder, self.session.signature, mounting_confirmed=True, allow_unvalidated=True)
        self.assertEqual(metadata['units'], 'mm')
        self.assertEqual(arrays['map2_y'].shape, (480, 640))
        # Новый процесс/объект видит сохранённую дату и результат
        restored = CalibrationSession().status()
        self.assertEqual(restored['result']['session_id'], self.session.session_id)

    def test_pause_blocks_recognition_until_finish(self):
        with self.assertRaises(RuntimeError):
            with self.gate.recognition():
                self.fail('Распознавание не должно запускаться')
        self.session.finish(self.session.session_id)
        with self.gate.recognition():
            self.assertFalse(self.gate.requested.is_set())

    def test_open_door_prevents_calibration(self):
        gate = MaintenanceMode()
        gate.door_open.set()
        with self.assertRaises(RuntimeError):
            gate.begin()
        self.assertFalse(gate.requested.is_set())


if __name__ == '__main__':
    unittest.main()
