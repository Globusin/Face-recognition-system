"""P3: синтетическая геометрия и изолированные проверки без камер"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import cv2

from utils.frame_pairing import CameraFrame, FramePair
from utils.maintenance import maintenance
from utils.stereo_calibration import CalibrationSession
from utils.two_view_pad import (DEFAULT_LIMITS, LANDMARK_GROUPS, GROUP_LENGTHS,
                                extract_face_points, inspect_pair, measure_face_geometry,
                                measurement_limits, wait_for_measurement_pair)


class StereoFaceTests(unittest.TestCase):
    def setUp(self):
        camera = np.array([[800., 0, 640], [0, 800, 360], [0, 0, 1]])
        primary_projection = np.column_stack((camera, np.zeros(3)))
        secondary_projection = np.column_stack((camera, camera @ [-120., 0, 0]))
        self.arrays = dict(k1=camera, k2=camera, d1=np.zeros(5), d2=np.zeros(5),
                           R1=np.eye(3), R2=np.eye(3), P1=primary_projection, P2=secondary_projection)
        # 31 точка на наклонённой плоскости, порядок совпадает в обеих камерах
        angle = np.linspace(0, 2 * np.pi, 31, endpoint=False)
        self.xyz = np.column_stack((60 * np.cos(angle), 45 * np.sin(angle),
                                    650 + 12 * np.cos(angle)))
        image = np.zeros((720, 1280, 3), np.uint8)
        timestamp = time.monotonic_ns()
        self.pair = FramePair(8, CameraFrame('primary', 11, timestamp, image),
                              CameraFrame('secondary', 12, timestamp, image), 0)

    def project(self, xyz=None):
        points = self.xyz if xyz is None else xyz
        projected = [matrix @ np.vstack((points.T, np.ones(len(points))))
                     for matrix in (self.arrays['P1'], self.arrays['P2'])]
        return [(value[:2] / value[2]).T for value in projected]

    def test_plane_is_flat_despite_tilt(self):
        result = measure_face_geometry(*self.project(), self.arrays, DEFAULT_LIMITS)
        self.assertEqual(result['points'], 31)
        self.assertAlmostEqual(result['mean_depth_mm'], 650)
        self.assertLess(result['plane_max_mm'], 1e-8)
        self.assertLess(result['reprojection_max_px'], 1e-8)

    def test_wait_skips_bad_pairs_and_preserves_strict_limit(self):
        now = time.monotonic_ns()
        def pair(number, delta):
            return FramePair(number,
                CameraFrame('primary', number, now - 100_000_000, self.pair.primary.image),
                CameraFrame('secondary', number, now - 100_000_000 + int(delta * 1_000_000),
                            self.pair.secondary.image), delta)
        candidates = [pair(8, 65), pair(9, 58.2), pair(10, 12)]
        from unittest.mock import Mock
        manager = Mock()
        manager.get_status.return_value = {'pairing': {'paired_frames': 7}}
        manager.get_pair.side_effect = candidates
        selection = {}
        selected = wait_for_measurement_pair(manager, DEFAULT_LIMITS, selection)
        self.assertEqual(selected.number, 10)
        self.assertEqual(selection['checked_pairs'], 3)
        self.assertEqual(selection['skipped_pairs'], 2)
        self.assertEqual(selection['minimum_delta_ms'], 12)
        self.assertEqual([call.kwargs['after_number'] for call in manager.get_pair.call_args_list], [7, 8, 9])

    def test_wait_timeout_reports_best_delta_without_accepting_it(self):
        from unittest.mock import Mock
        manager = Mock()
        manager.get_status.return_value = {'pairing': {'paired_frames': 7}}
        self.pair.secondary.timestamp_ns -= 58_200_000
        manager.get_pair.return_value = self.pair
        selection = {}
        with patch('utils.two_view_pad.time.monotonic', side_effect=[0, 0, 0, 6, 6]):
            with self.assertRaisesRegex(ValueError, '58.2.*40.0'):
                wait_for_measurement_pair(manager, DEFAULT_LIMITS, selection)
        self.assertEqual(selection['skipped_pairs'], 1)
        manager.get_pair.assert_called_once()

    def test_wait_rejects_stale_and_repeated_frames(self):
        from unittest.mock import Mock
        manager = Mock()
        manager.get_status.return_value = {'pairing': {'paired_frames': 7}}
        self.pair.primary.timestamp_ns -= 2_000_000_000
        manager.get_pair.side_effect = [self.pair, None]
        selection = {}
        with self.assertRaisesRegex(ValueError, 'свежую пару'):
            wait_for_measurement_pair(manager, DEFAULT_LIMITS, selection)
        self.assertIsNone(selection['minimum_delta_ms'])
        repeated = FramePair(9, self.pair.primary, self.pair.secondary, 0)
        manager.get_pair.side_effect = [self.pair, repeated]
        with self.assertRaisesRegex(ValueError, 'повторные кадры'):
            wait_for_measurement_pair(manager, DEFAULT_LIMITS, {})

    def test_curved_surface_is_not_planar(self):
        curved = self.xyz.copy()
        curved[14:19, 2] -= 25
        result = measure_face_geometry(*self.project(curved), self.arrays, DEFAULT_LIMITS)
        self.assertGreater(result['plane_rms_mm'], 4)
        self.assertGreater(result['nose_eye_plane_difference_mm'], 10)

    def test_bad_correspondences_and_depth_are_rejected(self):
        primary, secondary = self.project()
        invalid_secondary = secondary.copy()
        invalid_secondary[0, 1] += 20
        cases = [(primary[:30], secondary[:30]), (primary * np.nan, secondary),
                 (primary, primary), (primary, invalid_secondary), (secondary, primary)]
        far = self.xyz.copy()
        far[:, 2] += 3000
        cases.append(tuple(self.project(far)))
        for points in cases:
            with self.subTest(points=np.shape(points)), self.assertRaises(ValueError):
                measure_face_geometry(*points, self.arrays, DEFAULT_LIMITS)

    def test_reprojection_gate(self):
        primary, secondary = self.project()
        secondary[:, 1] += 6
        limits = dict(DEFAULT_LIMITS, max_reprojection_px=1)
        with self.assertRaisesRegex(ValueError, 'репроекции'):
            measure_face_geometry(primary, secondary, self.arrays, limits)

    def test_settings_validation(self):
        self.assertEqual(measurement_limits({}), DEFAULT_LIMITS)
        for invalid in (0, -1, True, float('nan'), '40'):
            with self.assertRaises(ValueError):
                measurement_limits({'max_delta_ms': invalid})
        with self.assertRaises(ValueError):
            measurement_limits({'min_depth_mm': 3000})

    def test_landmarks_are_ordered_and_not_detected_twice(self):
        groups = {name: [(100 + index, 150)] * count
                  for index, (name, count) in enumerate(zip(LANDMARK_GROUPS, GROUP_LENGTHS))}
        with patch('face_recognition.face_locations', return_value=[(0, 200, 200, 0)]) as detect, \
                patch('face_recognition.face_landmarks', return_value=[groups]) as landmarks:
            points = extract_face_points(self.pair.primary.image)
            self.assertEqual(points.shape, (31, 2))
            self.assertEqual(points[14, 0], 103)
            detect.assert_called_once()
            self.assertEqual(landmarks.call_args.kwargs['model'], 'large')
            self.assertIn('face_locations', landmarks.call_args.kwargs)

    def test_absent_or_multiple_faces_are_not_measurable(self):
        for locations in ([], [(0, 50, 50, 0)] * 2):
            with patch('face_recognition.face_locations', return_value=locations), \
                    patch('face_recognition.face_landmarks') as landmarks:
                result = inspect_pair(self.pair, self.arrays, [1280, 720], DEFAULT_LIMITS)
                self.assertEqual(result['status'], 'not_measurable')
                self.assertNotIn('metrics', result)
                landmarks.assert_not_called()

    def test_stale_asynchronous_and_wrong_size_pairs(self):
        for mode in ('stale', 'async', 'size', 'future'):
            with self.subTest(mode=mode):
                timestamp = time.monotonic_ns()
                self.pair.primary.timestamp_ns = timestamp - (2_000_000_000 if mode == 'stale' else 0)
                self.pair.secondary.timestamp_ns = timestamp - (70_000_000 if mode == 'async' else 0)
                if mode == 'future':
                    self.pair.secondary.timestamp_ns = timestamp + 500_000_000
                size = [640, 360] if mode == 'size' else [1280, 720]
                with patch('utils.two_view_pad.extract_face_points') as extract:
                    result = inspect_pair(self.pair, self.arrays, size, DEFAULT_LIMITS)
                    self.assertEqual(result['status'], 'not_measurable')
                    extract.assert_not_called()

    def test_measured_preview_does_not_modify_original(self):
        with patch('utils.two_view_pad.extract_face_points', side_effect=self.project()):
            result = inspect_pair(self.pair, self.arrays, [1280, 720], DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'measured')
        self.assertTrue(result['previews']['primary'].startswith('data:image/jpeg;base64,'))
        self.assertFalse(self.pair.primary.image.any())

    def test_vertical_failure_keeps_diagnostics_and_both_previews(self):
        primary, secondary = self.project()
        secondary[14, 1] += 20
        with patch('utils.two_view_pad.extract_face_points', side_effect=[primary, secondary]):
            result = inspect_pair(self.pair, self.arrays, [1280, 720], DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'not_measurable')
        self.assertNotIn('metrics', result)
        diagnostics = result['diagnostics']
        self.assertEqual(diagnostics['worst_point_number'], 15)
        self.assertEqual(diagnostics['worst_point_name'], 'низ носа, точка 1')
        self.assertAlmostEqual(diagnostics['vertical_max_px'], 20)
        self.assertEqual(diagnostics['vertical_limit_px'], 8)
        self.assertEqual(diagnostics['exceeding_points'], 1)
        self.assertIn('20.00 px', result['reason'])
        self.assertIn('8.00 px', result['reason'])
        import base64
        for role in ('primary', 'secondary'):
            data = base64.b64decode(result['previews'][role].split(',')[1])
            preview = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).astype(int)
            red = (preview[:, :, 2] > preview[:, :, 1] + 60) & (preview[:, :, 2] > 100)
            self.assertTrue(red.any())
        self.assertFalse(self.pair.primary.image.any())
        self.assertFalse(self.pair.secondary.image.any())

    def test_valid_geometry_also_reports_worst_point_without_failure(self):
        diagnostics = {}
        result = measure_face_geometry(*self.project(), self.arrays, DEFAULT_LIMITS, diagnostics)
        self.assertEqual(diagnostics['exceeding_points'], 0)
        self.assertLess(diagnostics['vertical_max_px'], 1e-8)
        self.assertEqual(result['points'], 31)

    def test_preview_failure_preserves_geometry_diagnostics(self):
        primary, secondary = self.project()
        secondary[14, 1] += 20
        with patch('utils.two_view_pad.extract_face_points', side_effect=[primary, secondary]), \
                patch('utils.two_view_pad.face_point_previews', side_effect=ValueError('Ошибка JPEG')):
            result = inspect_pair(self.pair, self.arrays, [1280, 720], DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'not_measurable')
        self.assertEqual(result['diagnostics']['worst_point_number'], 15)
        self.assertEqual(result['preview_error'], 'Ошибка JPEG')
        self.assertNotIn('previews', result)

    def run_session(self, missing_pair=False, duplicate_pair=False, vertical_failure=False):
        session = CalibrationSession()
        session.active, session.session_id = True, 'test-session'
        manager = SimpleNamespace(start=lambda **kwargs: None,
                                  get_status=lambda: {'pairing': {'paired_frames': 8 if duplicate_pair else 7},
                                      'cameras': {'primary': {'actual_fps': 19.1}, 'secondary': {'actual_fps': 8.8}}},
                                  get_pair=lambda **kwargs: None if missing_pair else self.pair)
        points = self.project()
        if vertical_failure:
            points[1][14, 1] += 20
        with tempfile.TemporaryDirectory() as root, \
                patch.object(session, '_root', return_value=Path(root)), \
                patch.object(session, '_camera_signature', return_value={'test': 'camera'}), \
                patch('utils.stereo_calibration.get_camera_manager', return_value=manager), \
                patch('utils.stereo_calibration.load_calibration',
                      return_value=({'units': 'mm', 'image_size': [1280, 720]}, self.arrays)), \
                patch('utils.two_view_pad.extract_face_points', side_effect=points):
            result = session.measure_face('test-session', 'a' * 32, True, True, 'live', 'daylight', 65)
            report_path = next((Path(root) / 'test-session' / 'stereo_pad_checks').glob('*.json'))
            report = json.loads(report_path.read_text())
            failed = missing_pair or duplicate_pair or vertical_failure
            self.assertEqual(report['status'], 'not_measurable' if failed else 'measured')
            self.assertEqual(report['decision'], 'not_evaluated')
            self.assertEqual(report['actual_fps'], {'primary': 19.1, 'secondary': 8.8})
            self.assertIn('wait_seconds', report['pair_selection'])
            self.assertNotIn('previews', report)
            self.assertNotIn('landmarks', report)
            if vertical_failure:
                self.assertEqual(report['diagnostics']['worst_point_number'], 15)
                self.assertEqual(len(result['previews']), 2)
            self.assertEqual(len(list(Path(root).rglob('*.*'))), 1)
            self.assertEqual(session.samples, [])
            self.assertFalse(maintenance.stereo_measuring.is_set())
            self.assertEqual(result['report_id'], report_path.stem)

    def test_report_is_anonymous_and_calibration_is_not_changed(self):
        self.run_session()
        self.run_session(missing_pair=True)
        self.run_session(duplicate_pair=True)
        self.run_session(vertical_failure=True)

    def test_session_consent_and_mounting_are_required(self):
        session = CalibrationSession()
        with self.assertRaises(ValueError):
            session.measure_face(None, 'a' * 32, True, True, 'live', 'daylight', 65)
        session.active, session.session_id = True, 'test'
        for mounting, consent in ((False, True), (True, False)):
            with self.assertRaises(ValueError):
                session.measure_face('test', 'a' * 32, mounting, consent, 'live', 'daylight', 65)

    def test_blank_image_with_real_hog_detector(self):
        with self.assertRaisesRegex(ValueError, 'ровно одно лицо'):
            extract_face_points(np.zeros((240, 320, 3), np.uint8))

    def test_model_failure_is_not_measurable(self):
        with patch('utils.two_view_pad.extract_face_points', side_effect=ImportError('Модель недоступна')):
            result = inspect_pair(self.pair, self.arrays, [1280, 720], DEFAULT_LIMITS)
            self.assertEqual(result['status'], 'not_measurable')
            self.assertNotIn('metrics', result)

    def test_calibration_mismatch_stops_before_landmarks(self):
        session = CalibrationSession()
        session.active, session.session_id = True, 'test'
        with patch('utils.stereo_calibration.get_camera_manager'), \
                patch.object(session, '_camera_signature', return_value={}), \
                patch('utils.stereo_calibration.load_calibration', side_effect=ValueError('Другие камеры')), \
                patch('utils.two_view_pad.inspect_pair') as inspect:
            with self.assertRaisesRegex(ValueError, 'Другие камеры'):
                session.measure_face('test', 'a' * 32, True, True, 'live', 'daylight', 65)
            inspect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
