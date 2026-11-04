"""Проверки прав администратора и блокировки обходных операций"""

import unittest
import threading
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np
from unittest.mock import patch

from src.app import app
from utils.maintenance import MaintenanceMode
from src.monitor import run_monitoring
from utils.stereo_calibration import CalibrationSession


class CalibrationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.header = {'X-Calibration-Token': 'local-test-secret'}

    def test_disabled_without_configured_secret(self):
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': ''}), \
                patch('utils.api_security.admin_token', return_value=''):
            self.assertEqual(self.client.get('/api/calibration/status').status_code, 503)

    def test_quality_requires_token_and_stationary_confirmation(self):
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'local-test-secret'}):
            self.assertEqual(self.client.post('/api/calibration/quality', json={}).status_code, 401)
            self.assertEqual(self.client.post('/api/calibration/quality', headers=self.header, json={}).status_code, 409)

    def test_face_measurement_requires_admin_and_is_not_an_access_decision(self):
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'local-test-secret'}):
            self.assertEqual(self.client.post('/api/calibration/face', json={}).status_code, 401)
            self.assertEqual(self.client.post('/api/calibration/face', headers=self.header, json={}).status_code, 409)
            result = {'status': 'not_measurable', 'decision': 'not_evaluated', 'reason': 'Нет лица'}
            with patch('src.app.calibration_session.measure_face', return_value=result) as measure:
                response = self.client.post('/api/calibration/face', headers=self.header,
                                            json={'session_id': 'test', 'sample_type': 'print'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, result)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(measure.call_args.args[4], 'print')

    def test_stereo_measurement_has_its_own_tft_state(self):
        from utils.display import DisplayState
        gate = MaintenanceMode()
        gate.requested.set()
        gate.stereo_measuring.set()
        stop = threading.Event()
        with patch('src.monitor.maintenance', gate), \
                patch('src.monitor.initialize_display'), \
                patch('src.monitor.initialize_lock_controller'), \
                patch('src.monitor.safe_display_state') as display, \
                patch('src.monitor.wait_or_stop', side_effect=lambda *_: stop.set()), \
                patch('src.monitor.recognize_face_from_camera') as recognize:
            run_monitoring(stop)
        self.assertTrue(any(call.args[1] == DisplayState.STEREO_MEASURING for call in display.call_args_list))
        recognize.assert_not_called()

    def test_review_saved_control_pairs(self):
        session = CalibrationSession()
        session_id = 'a' * 32
        with tempfile.TemporaryDirectory() as root, patch.object(session, '_root', return_value=Path(root)), \
                patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'local-test-secret'}), \
                patch('utils.stereo_calibration.measure_board_geometry', return_value={'mean_error_mm': 0}), \
                patch('src.app.calibration_session', session):
            folder = Path(root) / session_id
            folder.mkdir()
            metadata = {'image_size': [80, 60], 'status': 'requires_review', 'square_mm': 45}
            (folder / 'metadata.json').write_text(json.dumps(metadata))
            (folder / 'samples.json').write_text(json.dumps([
                {'validation': False}, {'validation': True, 'delta_ms': 12, 'primary': [], 'secondary': []},
                {'validation': True, 'primary': [], 'secondary': []}]))
            x, y = np.meshgrid(np.arange(80, dtype=np.float32), np.arange(60, dtype=np.float32))
            np.savez(folder / 'parameters.npz', map1_x=x, map1_y=y, map2_x=x, map2_y=y)
            for index in (2, 3):
                for role in ('primary', 'secondary'):
                    cv2.imwrite(str(folder / f'{index:03d}_{role}.png'), np.zeros((60, 80, 3), np.uint8))
            def fetch(**extra):
                return self.client.post('/api/calibration/review', headers=self.header,
                                        json={'session_id': session_id, **extra})
            response = fetch()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['pair_indices'], [2, 3])
            self.assertEqual(response.json['pair_index'], 2)
            self.assertTrue(response.json['previews']['secondary'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(fetch(pair_index=3).status_code, 200)
            self.assertEqual(fetch(pair_index=1).status_code, 409)
            self.assertEqual(fetch(session_id='../bad').status_code, 409)
            metadata['status'] = 'invalidated'
            (folder / 'metadata.json').write_text(json.dumps(metadata))
            self.assertEqual(fetch().status_code, 409)
            self.assertFalse(session.active)

    def test_download_original_without_detected_board(self):
        session = CalibrationSession()
        session.active = True
        session.session_id = 'test-session'
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[123, 456] = (10, 20, 30)
        session.observation = {'id': 'test-observation', 'created': 0,
                               'images': {'primary': image, 'secondary': image},
                               'corners': {'primary': None, 'secondary': None}}
        payload = {'session_id': session.session_id, 'observation_id': 'test-observation'}
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'local-test-secret'}), \
                patch('src.app.calibration_session', session):
            self.assertEqual(self.client.post('/api/calibration/frame/secondary', json=payload).status_code, 401)
            for role in ('primary', 'secondary'):
                response = self.client.post(f'/api/calibration/frame/{role}', headers=self.header, json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/png')
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                decoded = cv2.imdecode(np.frombuffer(response.data, np.uint8), cv2.IMREAD_COLOR)
                np.testing.assert_array_equal(decoded, image)
            for bad in ({**payload, 'session_id': 'old'}, {**payload, 'observation_id': 'old'}):
                self.assertEqual(self.client.post('/api/calibration/frame/secondary', headers=self.header,
                                                  json=bad).status_code, 409)
            self.assertEqual(self.client.post('/api/calibration/frame/unknown', headers=self.header,
                                              json=payload).status_code, 409)
        self.assertIsNotNone(session.observation)

    def test_token_and_physical_confirmation_required(self):
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'local-test-secret'}):
            self.assertEqual(self.client.get('/api/calibration/status').status_code, 401)
            response = self.client.post('/api/calibration/start', headers=self.header, json={})
            self.assertEqual(response.status_code, 400)

    def test_recognition_and_enrollment_blocked_during_calibration(self):
        gate = MaintenanceMode()
        gate.requested.set()
        with patch('src.app.maintenance', gate), \
                patch('src.app.authorize_admin', return_value=None), \
                patch('utils.recognition.recognize_face_from_camera') as recognize, \
                patch('src.app.create_embeddings_from_camera') as enroll:
            self.assertEqual(self.client.post('/api/authenticate').status_code, 409)
            self.assertEqual(self.client.post('/api/add_user?name=test').status_code, 409)
        recognize.assert_not_called()
        enroll.assert_not_called()

    def test_late_result_cannot_unlock_during_calibration(self):
        gate = MaintenanceMode()
        stop = threading.Event()

        def recognize():
            gate.requested.set()
            stop.set()
            return True, 1, 0.01

        with patch('src.monitor.maintenance', gate), \
                patch('src.monitor.initialize_display'), \
                patch('src.monitor.initialize_lock_controller') as initialize, \
                patch('src.monitor.wait_for_face', return_value=True), \
                patch('src.monitor.recognize_face_from_camera', side_effect=recognize):
            run_monitoring(stop)
        initialize.return_value.unlock.assert_not_called()

    def test_calibration_pause_does_not_start_recognition(self):
        gate = MaintenanceMode()
        gate.requested.set()
        stop = threading.Event()
        with patch('src.monitor.maintenance', gate), \
                patch('src.monitor.initialize_display'), \
                patch('src.monitor.initialize_lock_controller'), \
                patch('src.monitor.wait_or_stop', side_effect=lambda *_: stop.set()), \
                patch('src.monitor.recognize_face_from_camera') as recognize:
            run_monitoring(stop)
        recognize.assert_not_called()


if __name__ == '__main__':
    unittest.main()
