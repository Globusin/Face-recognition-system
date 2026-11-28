"""Классификатор объёма лица и диагностический замер без оборудования"""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from utils.access.authentication import AuthenticationSession, CheckStatus
from utils.capture.frame_pairing import CameraFrame, FramePair
from utils.stereo.stereo_liveness import (
    LIVE,
    SPOOF,
    UNKNOWN,
    StereoCheck,
    StereoLivenessDiagnostics,
    StereoWorker,
    check_status,
    liveness_settings,
    measure_pair,
    rule_based_classifier,
)
from utils.stereo.two_view_pad import DEFAULT_LIMITS


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
            'mode': 'required', 'parallel': True, 'result_timeout_s': 2.0,
            'calibration_id': 'a' * 32, 'mounting_confirmed': True,
            'classifier': {'live_plane_rms_mm': 4.0},
        }})
        self.assertEqual(custom['mode'], 'required')
        self.assertTrue(custom['parallel'])
        self.assertAlmostEqual(custom['result_timeout'], 2.0)
        self.assertAlmostEqual(custom['classifier']['live_plane_rms_mm'], 4.0)

        invalid = (
            {'mode': 'always'},
            {'result_timeout_s': 0},
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
        with patch('utils.stereo.two_view_pad.extract_face_points',
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

    def test_stale_pair_has_machine_readable_reason(self):
        with patch('utils.stereo.two_view_pad.time.monotonic_ns',
                   return_value=self.pair.primary.timestamp_ns + 1_000_000_001), \
                patch('utils.stereo.two_view_pad.extract_face_points') as extract:
            result = measure_pair(self.pair, self.arrays, [1280, 720],
                                  DEFAULT_LIMITS, self.settings)
        self.assertEqual(result['decision'], UNKNOWN)
        self.assertEqual(result['reason_code'], 'stale_pair')
        self.assertGreater(result['diagnostics']['primary_age_ms'], 1000)
        extract.assert_not_called()

    def test_curved_surface_is_live(self):
        result = self.measure(self.curved)
        self.assertEqual(result['decision'], LIVE)
        self.assertGreater(result['features']['plane_rms_mm'], 4)
        self.assertGreater(result['features']['nose_eye_plane_difference_mm'], 10)

    def test_custom_classifier_replaces_rules(self):
        classifier = Mock(return_value=(UNKNOWN, 'Модель не обучена', {}))
        with patch('utils.stereo.two_view_pad.extract_face_points',
                   side_effect=self.project(self.flat)):
            result = measure_pair(self.pair, self.arrays, [1280, 720],
                                  DEFAULT_LIMITS, self.settings, classifier=classifier)
        self.assertEqual(result['decision'], UNKNOWN)
        self.assertEqual(result['decision_source'], 'ml')


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.settings = liveness_settings({'stereo_liveness': {
            'mode': 'advisory', 'calibration_id': 'a' * 32,
            'mounting_confirmed': True,
        }})
        self.pair = Mock(number=5, delta_ms=4.0)
        self.metadata = {
            'status': 'validated', 'units': 'mm', 'image_size': [1280, 720],
            'cameras': {'primary': {'device': 'one'}, 'secondary': {'device': 'two'}},
        }

    def test_missing_calibration_id_is_reported(self):
        settings = liveness_settings({'stereo_liveness': {'mode': 'required'}})
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
        with patch('utils.stereo.stereo_liveness.camera_signature', return_value={}), \
                patch('utils.stereo.stereo_liveness.load_calibration',
                      side_effect=ValueError('нет файла')) as load:
            diagnostics = StereoLivenessDiagnostics(
                self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
            )
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'нет файла'):
                    diagnostics.measure(self.pair)
        self.assertEqual(load.call_count, 1)

    def test_preload_reuses_calibration_in_first_measurement(self):
        arrays = {}
        with patch('utils.stereo.stereo_liveness.camera_signature',
                   return_value=self.metadata['cameras']), \
                patch('utils.stereo.stereo_liveness.load_calibration',
                      return_value=(self.metadata, arrays)) as load, \
                patch('utils.stereo.stereo_liveness.measure_pair',
                      return_value={'decision': LIVE}) as measure:
            diagnostics = StereoLivenessDiagnostics(
                self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
            )
            self.assertTrue(diagnostics.preload())
            load.assert_called_once()
            measure.assert_not_called()
            self.assertEqual(diagnostics.measure(self.pair)['decision'], LIVE)
            load.assert_called_once()
            self.assertIs(measure.call_args.args[1], arrays)

    def test_failed_preload_is_not_reloaded_during_measurement(self):
        with patch('utils.stereo.stereo_liveness.camera_signature',
                   return_value=self.metadata['cameras']), \
                patch('utils.stereo.stereo_liveness.load_calibration',
                      side_effect=ValueError('нет файла')) as load, \
                patch('utils.stereo.stereo_liveness.measure_pair') as measure:
            diagnostics = StereoLivenessDiagnostics(
                self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
            )
            self.assertFalse(diagnostics.preload())
            with self.assertRaisesRegex(ValueError, 'нет файла'):
                diagnostics.measure(self.pair)
            load.assert_called_once()
            measure.assert_not_called()

    def test_camera_mode_mismatch_is_rejected(self):
        with patch('utils.stereo.stereo_liveness.camera_signature', return_value={'other': 1}):
            with patch('utils.stereo.stereo_liveness.load_calibration',
                       return_value=(self.metadata, {})):
                diagnostics = StereoLivenessDiagnostics(
                    self.manager, self.settings, 'data/calibration', dict(DEFAULT_LIMITS),
                )
                with self.assertRaisesRegex(ValueError, 'не совпадает'):
                    diagnostics.measure(self.pair)


class WorkerTests(unittest.TestCase):
    def test_result_belongs_to_its_session(self):
        diagnostics = Mock()
        diagnostics.measure.return_value = {'decision': LIVE}
        worker = StereoWorker(diagnostics)

        self.assertTrue(worker.submit('session-1', object()))
        result = worker.take('session-1', 1.0)
        worker.close()

        self.assertEqual(result['decision'], LIVE)
        self.assertIsNone(worker.take('session-2', 0.05))

    def test_busy_worker_skips_new_job(self):
        started = threading.Event()
        release = threading.Event()

        def measure(pair):
            started.set()
            release.wait(2.0)
            return {'decision': LIVE}

        diagnostics = Mock()
        diagnostics.measure.side_effect = measure
        worker = StereoWorker(diagnostics)
        try:
            self.assertTrue(worker.submit('session-1', object()))
            self.assertTrue(started.wait(2.0))
            self.assertFalse(worker.submit('session-2', object()))
            self.assertEqual(worker.skipped, 1)
        finally:
            release.set()
            worker.close()
        self.assertIsNone(worker.take('session-2', 0.01))

    def test_error_becomes_unknown(self):
        diagnostics = Mock()
        diagnostics.measure.side_effect = RuntimeError('нет калибровки')
        worker = StereoWorker(diagnostics)
        worker.submit('session-1', object())
        result = worker.take('session-1', 1.0)
        worker.close()

        self.assertEqual(result['decision'], UNKNOWN)
        self.assertEqual(result['status'], 'not_measured')


class StereoCheckTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = Mock()
        self.diagnostics.measure.return_value = {'decision': LIVE, 'reason': ''}
        self.session = AuthenticationSession(
            'session-1', 0.0, 0.0, 100.0, tracked_face_id='track-1', user_id=7,
        )

    def source(self):
        source = Mock()
        source.next.return_value = SimpleNamespace(pair=object())
        return source

    def test_required_live_passes_and_is_stored(self):
        check = StereoCheck(self.diagnostics, 'required')
        check.bind(self.source())
        self.assertEqual(check(self.session).status, CheckStatus.PASS)
        self.assertEqual(self.session.diagnostics['stereo']['decision'], LIVE)

    def test_required_spoof_and_unknown_deny(self):
        for decision, status in ((SPOOF, CheckStatus.FAIL),
                                 (UNKNOWN, CheckStatus.NOT_AVAILABLE)):
            with self.subTest(decision=decision):
                diagnostics = Mock()
                diagnostics.measure.return_value = {'decision': decision, 'reason': 'x'}
                check = StereoCheck(diagnostics, 'required')
                check.bind(self.source())
                self.assertEqual(check(self.session).status, status)

    def test_advisory_spoof_fails(self):
        self.diagnostics.measure.return_value = {'decision': SPOOF, 'reason': 'x'}
        check = StereoCheck(self.diagnostics, 'advisory')
        check.bind(self.source())
        self.assertEqual(check(self.session).status, CheckStatus.FAIL)
        self.assertEqual(self.session.diagnostics['stereo']['decision'], SPOOF)

    def test_advisory_live_and_unknown_are_skipped(self):
        for decision in (LIVE, UNKNOWN):
            with self.subTest(decision=decision):
                diagnostics = Mock()
                diagnostics.measure.return_value = {'decision': decision, 'reason': ''}
                check = StereoCheck(diagnostics, 'advisory')
                check.bind(self.source())
                self.assertEqual(check(self.session).status, CheckStatus.SKIPPED)

    def test_missing_data_required_is_unavailable(self):
        check = StereoCheck(self.diagnostics, 'required')
        self.assertEqual(check(self.session).status, CheckStatus.NOT_AVAILABLE)

    def stale(self, number):
        return dict(decision=UNKNOWN, reason='Пара кадров устарела',
                    reason_code='stale_pair', pair_number=number)

    def retry_source(self, *numbers):
        source = Mock()
        source.next.side_effect = [
            SimpleNamespace(pair=SimpleNamespace(number=n), track_id='track-1')
            for n in numbers
        ]
        return source

    def test_stale_pair_is_replaced_by_new_pair_of_same_track(self):
        self.diagnostics.measure.side_effect = [
            self.stale(1), dict(decision=LIVE, pair_number=2),
        ]
        source = self.retry_source(1, 2)
        check = StereoCheck(self.diagnostics, 'required', clock=lambda: 10.0)
        check.bind(source)
        self.assertEqual(check(self.session).status, CheckStatus.PASS)
        self.assertEqual(self.session.diagnostics['stereo']['stale_retries'], 1)
        self.assertEqual(source.next.call_args.args[0], 15.0)

    def test_stale_retries_are_limited(self):
        self.diagnostics.measure.side_effect = [self.stale(n) for n in (1, 2, 3)]
        check = StereoCheck(self.diagnostics, 'required', clock=lambda: 10.0)
        check.bind(self.retry_source(1, 2, 3))
        self.assertEqual(check(self.session).status, CheckStatus.NOT_AVAILABLE)
        self.assertEqual(self.diagnostics.measure.call_count, 3)
        self.assertEqual(self.session.diagnostics['stereo']['stale_retries'], 2)

    def test_spoof_and_geometric_unknown_are_not_retried(self):
        for decision, status in ((SPOOF, CheckStatus.FAIL),
                                 (UNKNOWN, CheckStatus.SKIPPED)):
            with self.subTest(decision=decision):
                self.diagnostics.measure.reset_mock()
                self.diagnostics.measure.return_value = dict(decision=decision, pair_number=1)
                check = StereoCheck(self.diagnostics, 'advisory', clock=lambda: 10.0)
                check.bind(self.retry_source(1, 2))
                self.assertEqual(check(self.session).status, status)
                self.diagnostics.measure.assert_called_once()

    def test_retry_respects_session_deadline(self):
        self.diagnostics.measure.return_value = self.stale(1)
        check = StereoCheck(self.diagnostics, 'required', clock=lambda: 100.0)
        check.bind(self.retry_source(1, 2))
        self.assertEqual(check(self.session).status, CheckStatus.NOT_AVAILABLE)
        self.diagnostics.measure.assert_called_once()

    def test_retry_rejects_repeated_pair_and_changed_track(self):
        for number, track in ((1, 'track-1'), (2, 'other')):
            with self.subTest(number=number, track=track):
                self.diagnostics.measure.reset_mock()
                self.diagnostics.measure.return_value = self.stale(1)
                source = self.retry_source(1)
                first = SimpleNamespace(pair=SimpleNamespace(number=1), track_id='track-1')
                second = SimpleNamespace(pair=SimpleNamespace(number=number), track_id=track)
                source.next.side_effect = [first, second]
                check = StereoCheck(self.diagnostics, 'required', clock=lambda: 10.0)
                check.bind(source)
                self.assertEqual(check(self.session).status, CheckStatus.NOT_AVAILABLE)
                self.diagnostics.measure.assert_called_once()

    def test_stale_worker_result_can_be_replaced(self):
        worker = Mock()
        worker.take.return_value = self.stale(1)
        self.diagnostics.measure.return_value = dict(decision=LIVE, pair_number=2)
        check = StereoCheck(self.diagnostics, 'required', worker=worker,
                            clock=lambda: 10.0)
        check.bind(self.retry_source(2))
        self.assertEqual(check(self.session).status, CheckStatus.PASS)
        self.diagnostics.measure.assert_called_once()

    def test_parallel_uses_worker_result(self):
        worker = Mock()
        worker.take.return_value = {'decision': LIVE, 'reason': ''}
        check = StereoCheck(self.diagnostics, 'required', worker=worker, timeout=1.0)
        self.assertEqual(check(self.session).status, CheckStatus.PASS)
        worker.take.assert_called_once_with('session-1', 1.0)
        self.diagnostics.measure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
