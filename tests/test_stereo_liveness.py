"""Классификатор объёма лица и диагностический замер без оборудования"""

import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from utils.authentication import AuthenticationSession
from utils.frame_pairing import CameraFrame, FramePair
from utils.stereo_liveness import (
    LIVE,
    SPOOF,
    UNKNOWN,
    StereoDiagnosticsCollector,
    StereoLivenessDiagnostics,
    check_status,
    liveness_settings,
    measure_pair,
    rule_based_classifier,
)
from utils.two_view_pad import DEFAULT_LIMITS


def inspection(status='measured', dense=None, reason=None, **metrics):
    values = dict(points=31, plane_rms_mm=5.0, nose_eye_plane_difference_mm=6.0,
                  reprojection_max_px=0.4, vertical_max_px=1.0, mean_depth_mm=600.0)
    values.update(metrics)
    result = dict(status=status, metrics=values, dense_depth=dense or {'status': 'not_requested'})
    if status != 'measured':
        result.pop('metrics')
        result['reason'] = reason or 'Геометрия не измерена'
    return result


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.settings = liveness_settings({})['classifier']

    def classify(self, result, calibration_status='validated'):
        return rule_based_classifier(result, self.settings, calibration_status)

    def test_flat_surface_is_spoof(self):
        decision, reason, features = self.classify(
            inspection(plane_rms_mm=0.5, nose_eye_plane_difference_mm=0.2),
        )
        self.assertEqual(decision, SPOOF)
        self.assertIn('Плоская', reason)
        self.assertAlmostEqual(features['plane_rms_mm'], 0.5)

    def test_plausible_relief_is_live(self):
        self.assertEqual(self.classify(inspection())[0], LIVE)

    def test_excessive_relief_is_not_live(self):
        decision, reason, _ = self.classify(
            inspection(plane_rms_mm=20.0, nose_eye_plane_difference_mm=25.0),
        )
        self.assertEqual(decision, UNKNOWN)
        self.assertIn('диапазону', reason)

    def test_transition_band_is_unknown(self):
        decision, reason, _ = self.classify(
            inspection(plane_rms_mm=2.0, nose_eye_plane_difference_mm=1.5),
        )
        self.assertEqual(decision, UNKNOWN)
        self.assertIn('переходной', reason)

    def test_measurement_failure_is_unknown_not_spoof(self):
        decision, reason, _ = self.classify(
            inspection(status='not_measurable', reason='Мало точек'),
        )
        self.assertEqual(decision, UNKNOWN)
        self.assertEqual(reason, 'Мало точек')

    def test_poor_correspondence_is_unknown(self):
        cases = {
            'точек': inspection(points=20),
            'репроекции': inspection(reprojection_max_px=5.0),
            'вертикали': inspection(vertical_max_px=9.0),
        }
        for word, result in cases.items():
            with self.subTest(word=word):
                decision, reason, _ = self.classify(result)
                self.assertEqual(decision, UNKNOWN)
                self.assertIn(word, reason)

    def test_dense_quality_gate(self):
        dense = {'status': 'measured', 'valid_fraction': 0.1, 'valid_pixels': 50}
        decision, reason, _ = self.classify(inspection(dense=dense))
        self.assertEqual(decision, UNKNOWN)
        self.assertIn('пикселей', reason)

    def test_unvalidated_calibration_is_unknown(self):
        decision, reason, _ = self.classify(inspection(), 'requires_review')
        self.assertEqual(decision, UNKNOWN)
        self.assertIn('Калибровка', reason)

    def test_status_mapping(self):
        self.assertEqual(check_status(LIVE), 'PASS')
        self.assertEqual(check_status(SPOOF), 'FAIL')
        self.assertEqual(check_status(UNKNOWN), 'NOT_AVAILABLE')
        self.assertEqual(check_status('unexpected'), 'NOT_AVAILABLE')

    def test_settings_validation(self):
        custom = liveness_settings({'stereo_liveness': {
            'enabled': True, 'calibration_id': 'a' * 32, 'mounting_confirmed': True,
            'classifier': {'live_plane_rms_mm': 4.0},
        }})
        self.assertTrue(custom['enabled'])
        self.assertAlmostEqual(custom['classifier']['live_plane_rms_mm'], 4.0)

        invalid = (
            {'measurement_timeout_s': 0},
            {'calibration_id': 'short'},
            {'classifier': {'min_points': 2}},
            {'classifier': {'live_plane_rms_mm': 1.0}},
            {'classifier': {'max_nose_eye_mm': 1.0}},
            {'classifier': {'min_valid_fraction': 1.5}},
        )
        for section in invalid:
            with self.subTest(section=section):
                with self.assertRaises(ValueError):
                    liveness_settings({'stereo_liveness': section})


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        camera = np.array([[800., 0, 640], [0, 800, 360], [0, 0, 1]])
        primary = np.column_stack((camera, np.zeros(3)))
        secondary = np.column_stack((camera, camera @ [-120., 0, 0]))
        self.arrays = dict(k1=camera, k2=camera, d1=np.zeros(5), d2=np.zeros(5),
                           R1=np.eye(3), R2=np.eye(3), P1=primary, P2=secondary)
        angle = np.linspace(0, 2 * np.pi, 31, endpoint=False)
        self.flat = np.column_stack((60 * np.cos(angle), 45 * np.sin(angle),
                                     650 + 12 * np.cos(angle)))
        self.curved = self.flat.copy()
        self.curved[14:19, 2] -= 25
        self.image = np.zeros((720, 1280, 3), np.uint8)
        timestamp = time.monotonic_ns()
        self.pair = FramePair(
            8, CameraFrame('primary', 11, timestamp, self.image),
            CameraFrame('secondary', 12, timestamp, self.image), 0,
        )
        self.settings = liveness_settings({})['classifier']

    def project(self, points):
        projected = []
        for matrix in (self.arrays['P1'], self.arrays['P2']):
            homogeneous = matrix @ np.vstack((points.T, np.ones(len(points))))
            projected.append((homogeneous[:2] / homogeneous[2]).T)
        return projected

    def measure(self, points):
        with patch('utils.two_view_pad.extract_face_points',
                   side_effect=self.project(points)):
            return measure_pair(self.pair, self.arrays, [1280, 720],
                                DEFAULT_LIMITS, self.settings)

    def test_flat_plane_is_spoof_and_never_grants_access(self):
        result = self.measure(self.flat)
        self.assertEqual(result['status'], 'measured')
        self.assertEqual(result['decision'], SPOOF)
        self.assertTrue(result['diagnostic_only'])
        self.assertFalse(result['access_granted'])
        self.assertFalse(result['timing_verified'])
        self.assertEqual(result['decision_source'], 'rule_based')

    def test_curved_surface_is_live(self):
        result = self.measure(self.curved)
        self.assertEqual(result['decision'], LIVE)
        self.assertGreater(result['features']['plane_rms_mm'], 4)
        self.assertGreater(result['features']['nose_eye_plane_difference_mm'], 10)

    def test_custom_classifier_replaces_rules(self):
        classifier = Mock(return_value=(UNKNOWN, 'Модель не обучена', {}))
        with patch('utils.two_view_pad.extract_face_points',
                   side_effect=self.project(self.flat)):
            result = measure_pair(self.pair, self.arrays, [1280, 720],
                                  DEFAULT_LIMITS, self.settings, classifier=classifier)
        self.assertEqual(result['decision'], UNKNOWN)
        self.assertEqual(result['decision_source'], 'ml')


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.settings = liveness_settings({'stereo_liveness': {
            'enabled': True, 'calibration_id': 'a' * 32, 'mounting_confirmed': True,
        }})
        self.pair = Mock(number=5, delta_ms=4.0)
        self.metadata = {
            'status': 'validated', 'units': 'mm', 'image_size': [1280, 720],
            'cameras': {'primary': {'device': 'one'}, 'secondary': {'device': 'two'}},
        }

    def test_missing_calibration_id_is_reported(self):
        settings = liveness_settings({'stereo_liveness': {'enabled': True}})
        diagnostics = StereoLivenessDiagnostics(
            self.manager, settings, 'data/calibration', dict(DEFAULT_LIMITS),
        )
        with self.assertRaisesRegex(ValueError, 'номер калибровки'):
            diagnostics.measure(self.pair)

    def test_mounting_must_be_confirmed(self):
        settings = dict(self.settings, mounting_confirmed=False)
        diagnostics = StereoLivenessDiagnostics(
            self.manager, settings, 'data/calibration', dict(DEFAULT_LIMITS),
        )
        with self.assertRaisesRegex(ValueError, 'крепления'):
            diagnostics.measure(self.pair)

    def test_calibration_failure_is_cached(self):
        with patch('utils.stereo_liveness.camera_signature', return_value={}), \
                patch('utils.stereo_liveness.load_calibration',
                      side_effect=ValueError('нет файла')) as load:
            diagnostics = StereoLivenessDiagnostics(
                self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
            )
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'нет файла'):
                    diagnostics.measure(self.pair)
        self.assertEqual(load.call_count, 1)

    def test_camera_mode_mismatch_is_rejected(self):
        with patch('utils.stereo_liveness.camera_signature', return_value={'other': 1}):
            with patch('utils.stereo_liveness.load_calibration',
                       return_value=(self.metadata, {})):
                diagnostics = StereoLivenessDiagnostics(
                    self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
                )
                with self.assertRaisesRegex(ValueError, 'не совпадает'):
                    diagnostics.measure(self.pair)


class CollectorTests(unittest.TestCase):
    """Замер не должен задерживать основной цикл, который закрывает замок"""

    def setUp(self):
        self.manager = Mock()
        self.manager.dual_mode = True
        self.manager.get_status.return_value = {'pairing': {'paired_frames': 5}}
        self.pair = Mock(number=6, delta_ms=3.0)
        self.manager.get_pair.return_value = self.pair
        self.session = AuthenticationSession('abc', 0.0, 0.0, 10.0)
        self.settings = {'measurement_timeout': 1.0}

    def test_measurement_runs_in_worker_and_is_stored(self):
        diagnostics = Mock()
        diagnostics.measure.return_value = {'decision': LIVE, 'reason': 'ok'}
        collector = StereoDiagnosticsCollector(diagnostics, self.manager, self.settings)

        self.assertTrue(collector.submit(self.session))
        collector.close()

        diagnostics.measure.assert_called_once_with(self.pair)
        stored = self.session.diagnostics['stereo']
        self.assertEqual(stored['decision'], LIVE)
        self.assertIn('worker_elapsed_seconds', stored)
        self.assertEqual(collector.completed, 1)

    def test_submit_returns_before_measurement_finishes(self):
        started = threading.Event()
        release = threading.Event()
        worker_thread = {}

        def measure(pair):
            worker_thread['id'] = threading.get_ident()
            started.set()
            release.wait(2.0)
            return {'decision': LIVE, 'reason': 'ok'}

        diagnostics = Mock()
        diagnostics.measure.side_effect = measure
        collector = StereoDiagnosticsCollector(diagnostics, self.manager, self.settings)

        self.assertTrue(collector.submit(self.session))
        self.assertTrue(started.wait(2.0))
        self.assertNotEqual(worker_thread['id'], threading.get_ident())
        # Второй замер во время работы пропускается, а не копится в очереди
        self.assertFalse(collector.submit(self.session))
        self.assertEqual(collector.skipped, 1)

        release.set()
        collector.close()
        self.assertEqual(diagnostics.measure.call_count, 1)

    def test_measurement_error_becomes_unknown(self):
        diagnostics = Mock()
        diagnostics.measure.side_effect = RuntimeError('Потеря лица')
        collector = StereoDiagnosticsCollector(diagnostics, self.manager, self.settings)

        collector.submit(self.session)
        collector.close()

        stored = self.session.diagnostics['stereo']
        self.assertEqual(stored['decision'], UNKNOWN)
        self.assertEqual(stored['status'], 'not_measured')
        self.assertFalse(stored['access_granted'])

    def test_missing_pair_and_single_camera_are_unknown(self):
        cases = (
            ('pair', lambda: setattr(self.manager, 'get_pair', Mock(return_value=None))),
            ('single', lambda: setattr(self.manager, 'dual_mode', False)),
        )
        for name, prepare in cases:
            with self.subTest(name=name):
                self.setUp()
                prepare()
                diagnostics = Mock()
                collector = StereoDiagnosticsCollector(
                    diagnostics, self.manager, self.settings,
                )
                collector.submit(self.session)
                collector.close()
                self.assertEqual(
                    self.session.diagnostics['stereo']['decision'], UNKNOWN,
                )
                diagnostics.measure.assert_not_called()

    def test_closed_collector_rejects_tasks(self):
        collector = StereoDiagnosticsCollector(Mock(), self.manager, self.settings)
        collector.close()
        self.assertFalse(collector.submit(self.session))
        self.assertNotIn('stereo', self.session.diagnostics)


if __name__ == '__main__':
    unittest.main()
