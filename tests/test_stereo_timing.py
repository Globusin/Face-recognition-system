"""Временная ошибка на синтетическом движении, без аппаратных утверждений"""

import subprocess
import tempfile
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from utils.frame_pairing import CameraFrame, FramePair
from utils.stereo_timing import estimate_timing, timing_depth_uncertainty, check_timing_profile, exposure_settings
from utils.two_view_pad import DEFAULT_LIMITS, inspect_pair
from utils.stereo_calibration import CalibrationSession
from utils.maintenance import maintenance


class StereoTimingTests(unittest.TestCase):
    def samples(self, step=.04):
        times = np.arange(0, 15, step)
        values = 100 + 35 * np.sin(times * 1.8) + 18 * np.sin(times * 4.1) + 10 * np.sin(.17 * times ** 2)
        return dict(primary=np.column_stack((times, values)).tolist(),
                    secondary=np.column_stack((times + .07, values)).tolist())

    def test_known_delivery_latency_and_sampling_uncertainty(self):
        result = estimate_timing(self.samples())
        self.assertAlmostEqual(result['offset_ms'], -70, delta=2)
        self.assertLess(result['residual_rms_px'], .1)
        self.assertGreaterEqual(result['uncertainty_ms'], 20)
        self.assertFalse(result['hardware_synchronized'])
        self.assertGreater(estimate_timing(self.samples(.12))['uncertainty_ms'], 60)

    def test_static_linear_short_or_nonfinite_motion_is_not_a_time_test(self):
        for mode in ('static', 'linear', 'short', 'nan'):
            samples = self.samples()
            for role in samples:
                values = np.array(samples[role])
                if mode == 'static': values[:, 1] = 10
                if mode == 'linear': values[:, 1] = values[:, 0] * 20
                if mode == 'short': values = values[:20]
                if mode == 'nan': values[5, 1] = np.nan
                samples[role] = values.tolist()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                estimate_timing(samples)

    def profile(self):
        return dict(status='measured', calibration_id='calibration', fingerprint='hash', run_id='run',
                    created_monotonic=100, recent_fps={'primary': 30, 'secondary': 30})

    def test_missing_stale_other_run_and_fps_change_fail_closed(self):
        status = dict(run_id='run', cameras={role: {'recent_fps': 30} for role in ('primary', 'secondary')})
        check_timing_profile(self.profile(), 'calibration', 'hash', status, 110, True)
        cases = [(None, status, 110, True), (self.profile(), status, 701, True),
                 (self.profile(), dict(status, run_id='other'), 110, True),
                 (self.profile(), status, 110, False)]
        slow = dict(run_id='run', cameras={'primary': {'recent_fps': 30}, 'secondary': {'recent_fps': 8}})
        cases.append((self.profile(), slow, 110, True))
        for profile, device, now, confirmed in cases:
            with self.assertRaises(ValueError):
                check_timing_profile(profile, 'calibration', 'hash', device, now, confirmed)
        with self.assertRaises(ValueError):
            check_timing_profile(self.profile(), 'other', 'hash', status, 110, True)

    def geometry(self):
        camera = np.array([[800., 0, 640], [0, 800, 360], [0, 0, 1]])
        arrays = dict(k1=camera, k2=camera, d1=np.zeros(5), d2=np.zeros(5), R1=np.eye(3), R2=np.eye(3),
                      P1=np.column_stack((camera, np.zeros(3))), P2=np.column_stack((camera, [-96000., 0, 0])))
        angles = np.linspace(0, 2 * np.pi, 31, endpoint=False)
        xyz = np.vstack((60 * np.cos(angles), 40 * np.sin(angles), np.full(31, 650), np.ones(31)))
        points = {}
        for role, suffix in (('primary', '1'), ('secondary', '2')):
            projected = arrays['P' + suffix] @ xyz
            points[role] = (projected[:2] / projected[2]).T
        image = np.zeros((720, 1280, 3), np.uint8)
        pair = FramePair(2, CameraFrame('primary', 2, 1_000_000_000, image),
                         CameraFrame('secondary', 2, 1_000_000_000, image), 0)
        previous = dict(points={role: value.copy() for role, value in points.items()},
                        timestamps={role: 500_000_000 for role in points})
        profile = dict(estimate=dict(offset_ms=0, uncertainty_ms=5), exposure_controls={
            role: {'exposure_time_absolute': 10} for role in ('primary', 'secondary')})
        return points, pair, previous, profile, arrays

    def test_depth_uncertainty_matches_disparity_interval(self):
        points, pair, previous, profile, arrays = self.geometry()
        result = timing_depth_uncertainty(points, pair, previous, profile, arrays, DEFAULT_LIMITS)
        disparity = 96000 / 650
        error = 2 * 25 * .006
        expected = 96000 * error / (disparity * (disparity - error))
        self.assertAlmostEqual(result['timing_depth_uncertainty_mm'], expected)

    def test_motion_unknown_time_or_large_depth_error_reject(self):
        points, pair, previous, profile, arrays = self.geometry()
        previous['points']['primary'][:, 0] -= 100
        with self.assertRaisesRegex(ValueError, 'движется'):
            timing_depth_uncertainty(points, pair, previous, profile, arrays, DEFAULT_LIMITS)
        previous['points']['primary'] = points['primary'].copy()
        profile['estimate']['uncertainty_ms'] = 60
        with self.assertRaisesRegex(ValueError, 'Временная неопределённость'):
            timing_depth_uncertainty(points, pair, previous, profile, arrays, DEFAULT_LIMITS)
        profile['estimate']['uncertainty_ms'] = 5
        with self.assertRaisesRegex(ValueError, 'погрешность глубины'):
            timing_depth_uncertainty(points, pair, previous, profile, arrays,
                                     dict(DEFAULT_LIMITS, max_depth_uncertainty_mm=.1))

    def test_good_geometry_but_bad_time_does_not_produce_measurement(self):
        points, pair, previous, profile, arrays = self.geometry()
        profile['estimate']['uncertainty_ms'] = 60
        with patch('utils.two_view_pad.time.monotonic_ns', return_value=1_100_000_000), \
                patch('utils.two_view_pad.extract_face_points', side_effect=[points['primary'], points['secondary']]):
            result = inspect_pair(pair, arrays, [1280, 720], DEFAULT_LIMITS,
                                  temporal_context=dict(previous=previous, profile=profile))
        self.assertEqual(result['status'], 'not_measurable')
        self.assertNotIn('metrics', result)
        self.assertIn('previews', result)

    def test_geometry_without_time_context_is_not_a_measurement(self):
        points, pair, _, _, arrays = self.geometry()
        with patch('utils.two_view_pad.time.monotonic_ns', return_value=1_100_000_000), \
                patch('utils.two_view_pad.extract_face_points', side_effect=[points['primary'], points['secondary']]):
            result = inspect_pair(pair, arrays, [1280, 720], DEFAULT_LIMITS)
        self.assertEqual(result['status'], 'not_measurable')
        self.assertIn('временная точность', result['reason'])

    def test_exposure_is_read_only_and_auto_exposure_is_rejected(self):
        manager = SimpleNamespace(sources={'primary': '/dev/test-primary', 'secondary': '/dev/test-secondary'})
        manual = 'auto_exposure: 1\nexposure_time_absolute: 166\nexposure_dynamic_framerate: 0\n'
        with patch('utils.stereo_timing.subprocess.run', return_value=SimpleNamespace(stdout=manual)) as run:
            result = exposure_settings(manager)
            self.assertEqual(result['secondary']['exposure_time_absolute'], 166)
            self.assertNotIn('--set-ctrl', str(run.call_args_list))
        with patch('utils.stereo_timing.subprocess.run', return_value=SimpleNamespace(stdout=manual.replace('exposure: 1', 'exposure: 3'))):
            with self.assertRaisesRegex(ValueError, 'ручная выдержка'):
                exposure_settings(manager)
        with patch('utils.stereo_timing.subprocess.run', side_effect=subprocess.TimeoutExpired('v4l2-ctl', 2)):
            with self.assertRaises(ValueError):
                exposure_settings(manager)

    def test_probe_service_records_motion_or_failure_without_images(self):
        for fail_exposure in (False, True):
            session = CalibrationSession()
            session.active, session.session_id = True, 'test-session'
            clock = [100.0]
            image = np.zeros((20, 20, 3), np.uint8)
            def observe(*args, **kwargs):
                clock[0] += .25
                t = clock[0] - 100
                y = 100 + 35 * np.sin(t * 1.8) + 18 * np.sin(t * 4.1) + 10 * np.sin(.17 * t ** 2)
                corners = np.full((49, 1, 2), [50, y])
                number = round(t * 4)
                pair = FramePair(number, CameraFrame('primary', number, int(clock[0] * 1e9), image),
                    CameraFrame('secondary', number, int((clock[0] + .07) * 1e9), image), 70)
                session.observation = dict(pair=pair, corners={'primary': corners, 'secondary': corners})
            status = dict(run_id='run', cameras={role: {'recent_fps': 30} for role in ('primary', 'secondary')})
            manager = SimpleNamespace(start=lambda **kwargs: None, get_status=lambda: status)
            arrays = {'P1': np.eye(3, 4), 'P2': np.eye(3, 4)}
            with tempfile.TemporaryDirectory() as root, \
                    patch.object(session, '_root', return_value=Path(root)), \
                    patch.object(session, '_camera_signature', return_value={'test': 'camera'}), \
                    patch.object(session, 'observe', side_effect=observe), \
                    patch('utils.stereo_calibration.get_camera_manager', return_value=manager), \
                    patch('utils.stereo_calibration.load_calibration', return_value=({'validation': {'fingerprint': 'hash'}}, arrays)), \
                    patch('utils.stereo_calibration.time.monotonic', side_effect=lambda: clock[0]), \
                    patch('utils.stereo_timing.rectified_points', side_effect=lambda points, *args: points[:, 0]), \
                    patch('utils.stereo_timing.exposure_settings', return_value={},
                          side_effect=ValueError('Нужна ручная выдержка') if fail_exposure else None):
                result = session.measure_timing('test-session', 'a' * 32, True, True, 0)
                self.assertEqual(result['status'], 'not_measurable' if fail_exposure else 'measured')
                saved = json.loads(next(Path(root).rglob('*.json')).read_text())
                self.assertNotIn('images', saved)
                self.assertFalse(saved['hardware_synchronized'])
                self.assertFalse(maintenance.timing_measuring.is_set())
                if fail_exposure:
                    self.assertIsNone(session.timing_result)
                else:
                    self.assertAlmostEqual(result['estimate']['offset_ms'], -70, delta=2)

    def test_probe_without_confirmations_does_not_read_cameras(self):
        session = CalibrationSession()
        session.active, session.session_id = True, 'test'
        with patch('utils.stereo_calibration.get_camera_manager') as manager:
            with self.assertRaises(ValueError):
                session.measure_timing('test', 'a' * 32, True, False, 0)
            manager.assert_not_called()


if __name__ == '__main__':
    unittest.main()
