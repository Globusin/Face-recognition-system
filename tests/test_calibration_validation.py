"""Подтверждение по новым парам, запрет неподтверждённых и изменённых параметров"""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from utils.stereo_calibration import CalibrationSession, calibration_fingerprint, load_calibration, write_json


class CalibrationValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.calibration_id = 'a' * 32
        self.folder = self.root / self.calibration_id
        self.folder.mkdir()
        self.cameras = {'primary': 'test', 'secondary': 'test'}
        self.metadata = dict(version=1, created_at='2026-11-04T10:00:00Z', units='mm', board=[7, 7],
                             square_mm=20, session_id=self.calibration_id, image_size=[160, 120],
                             cameras=self.cameras, status='requires_review')
        write_json(self.folder / 'metadata.json', self.metadata)
        camera = np.array([[800., 0, 80], [0, 800, 60], [0, 0, 1]])
        arrays = dict(k1=camera, k2=camera, d1=np.zeros(5), d2=np.zeros(5), R=np.eye(3),
                      T=np.array([[-120.], [0], [0]]), R1=np.eye(3), R2=np.eye(3), Q=np.eye(4),
                      P1=np.column_stack((camera, np.zeros(3))),
                      P2=np.column_stack((camera, camera @ [-120., 0, 0])))
        arrays.update({key: np.zeros((120, 160), np.float32)
                       for key in ('map1_x', 'map1_y', 'map2_x', 'map2_y')})
        np.savez(self.folder / 'parameters.npz', **arrays)
        self.session = CalibrationSession()
        self.session.active, self.session.session_id = True, 'b' * 32
        self.session.signature, self.session.image_size = self.cameras, (160, 120)
        for patcher in (patch.object(self.session, '_root', return_value=self.root),
                        patch.object(self.session, '_camera_signature', return_value=self.cameras),
                        patch('utils.stereo_calibration.get_camera_manager'),
                        patch('utils.stereo_calibration.load_config', return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def record(self, number, offset=None, error_percent=0.5):
        corners = np.indices((7, 7)).reshape(2, -1).T.reshape(49, 1, 2).astype(float)
        corners += number * 20 if offset is None else offset
        self.session.observation = dict(id=f'{number:032x}', created=time.monotonic(),
            corners={'primary': corners, 'secondary': corners.copy()})
        geometry = dict(mean_error_percent=error_percent, vertical_max_px=1.0, plane_rms_mm=0.5,
                        mean_error_mm=0.1, max_error_mm=0.3)
        with patch('utils.stereo_calibration.measure_board_geometry', return_value=geometry):
            return self.session.verify_observation(self.session.session_id, f'{number:032x}',
                                                   self.calibration_id, True, True)

    def confirm(self):
        return self.session.validate(self.session.session_id, self.calibration_id, True, True)

    def test_loader_fails_closed_until_independent_confirmation(self):
        with self.assertRaisesRegex(ValueError, 'не подтверждена'):
            load_calibration(self.folder, self.cameras, mounting_confirmed=True)
        metadata, _ = load_calibration(self.folder, self.cameras, mounting_confirmed=True, allow_unvalidated=True)
        self.assertEqual(metadata['status'], 'requires_review')
        for number in range(1, 4):
            self.record(number)
        result = self.confirm()
        self.assertEqual(result['result']['status'], 'validated')
        metadata, _ = load_calibration(self.folder, self.cameras, mounting_confirmed=True)
        self.assertEqual(metadata['validation']['checks_count'], 3)
        self.assertEqual(metadata['validation']['source_session_id'], self.session.session_id)

    def test_fewer_pairs_or_repeated_observation_cannot_confirm(self):
        self.record(1)
        self.record(1)
        self.record(2)
        with self.assertRaisesRegex(ValueError, 'минимум три'):
            self.confirm()

    def test_same_pose_is_not_three_independent_positions(self):
        for number in range(1, 4):
            self.record(number, offset=0)
        with self.assertRaisesRegex(ValueError, 'слишком похожи'):
            self.confirm()

    def test_bad_quality_cannot_be_approved_by_checkbox(self):
        for number in range(1, 4):
            self.record(number, error_percent=6.29)
        with self.assertRaisesRegex(ValueError, 'ошибка размера клетки'):
            self.confirm()
        self.assertEqual(json.loads((self.folder / 'metadata.json').read_text())['status'], 'requires_review')

    def test_training_session_is_not_independent(self):
        self.session.session_id = self.calibration_id
        self.assertIsNone(self.record(1)['independent_check_id'])
        with self.assertRaisesRegex(ValueError, 'отдельная сессия'):
            self.confirm()

    def test_changed_parameters_invalidate_checks_and_validation(self):
        for number in range(1, 4):
            self.record(number)
        self.confirm()
        parameters = self.folder / 'parameters.npz'
        parameters.write_bytes(parameters.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'параметры изменились'):
            load_calibration(self.folder, self.cameras, mounting_confirmed=True)
        with self.assertRaisesRegex(ValueError, 'изменились после проверки'):
            self.confirm()

    def test_invalidated_unknown_status_or_fabricated_status_are_not_usable(self):
        for status in ('invalidated', 'unknown', 'validated'):
            self.metadata['status'] = status
            write_json(self.folder / 'metadata.json', self.metadata)
            with self.subTest(status=status), self.assertRaises(ValueError):
                load_calibration(self.folder, self.cameras, mounting_confirmed=True)

    def test_manual_confirmation_and_mounting_are_required(self):
        for mounting, reviewed in ((False, True), (True, False)):
            with self.assertRaises(ValueError):
                self.session.validate(self.session.session_id, self.calibration_id, mounting, reviewed)

    def test_face_cannot_opt_into_unvalidated_diagnostic_loading(self):
        with patch('utils.two_view_pad.inspect_pair') as inspect:
            with self.assertRaisesRegex(ValueError, 'не подтверждена'):
                self.session.measure_face(self.session.session_id, self.calibration_id,
                                          True, True, 'live', 'daylight', 65)
            inspect.assert_not_called()

    def test_loader_uses_the_same_bytes_it_verified(self):
        for number in range(1, 4):
            self.record(number)
        self.confirm()
        def replace_after_hash(folder, metadata, parameter_bytes=None):
            fingerprint = calibration_fingerprint(folder, metadata, parameter_bytes)
            (self.folder / 'parameters.npz').write_bytes(b'not-an-archive')
            return fingerprint
        with patch('utils.stereo_calibration.calibration_fingerprint', side_effect=replace_after_hash):
            _, arrays = load_calibration(self.folder, self.cameras, mounting_confirmed=True)
            self.assertEqual(arrays['Q'].shape, (4, 4))
        with self.assertRaises(ValueError):
            load_calibration(self.folder, self.cameras, mounting_confirmed=True)


if __name__ == '__main__':
    unittest.main()
