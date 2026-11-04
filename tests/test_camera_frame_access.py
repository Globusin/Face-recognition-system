"""Доступ к снимкам только администратору в обслуживании, с общим лимитом"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.app import app
from utils.api_security import FramePreviewLimiter


class CameraFrameAccessTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.headers = {'X-Admin-Token': 'test-' + 'a' * 40}
        self.mode = SimpleNamespace(active=True, lock=threading.RLock())
        self.requested = threading.Event()
        self.requested.set()
        for patcher in (
            patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': self.headers['X-Admin-Token']}),
            patch('utils.api_security.load_config', return_value={}),
            patch('src.app.calibration_session', self.mode),
            patch('src.app.maintenance', SimpleNamespace(requested=self.requested)),
            patch('src.app.frame_preview_limit', FramePreviewLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manager_patch = patch('src.app.get_camera_manager')
        self.manager = self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)
        self.manager.return_value.get_latest_frame.return_value = SimpleNamespace(image=np.zeros((60, 80, 3), np.uint8))

    def frame(self, role='primary', **kwargs):
        return self.client.get(f'/api/cameras/{role}/frame', headers=self.headers, **kwargs)

    def test_unauthenticated_bad_token_http_and_wrong_network_never_read_camera(self):
        self.assertEqual(self.client.get('/api/cameras/primary/frame').status_code, 401)
        self.assertEqual(self.client.head('/api/cameras/primary/frame').status_code, 401)
        self.assertEqual(self.client.get('/api/cameras/secondary/frame', headers={'X-Admin-Token': 'wrong'}).status_code, 401)
        self.assertEqual(self.frame(base_url='http://localhost').status_code, 403)
        self.assertEqual(self.frame(environ_overrides={'REMOTE_ADDR': '192.168.1.80'}).status_code, 403)
        self.manager.assert_not_called()

    def test_both_maintenance_flags_required_and_haar_cannot_bypass(self):
        with patch('src.app.face_detection_preview.enable') as enable:
            for active, requested in ((False, True), (True, False), (False, False)):
                self.mode.active = active
                self.requested.set() if requested else self.requested.clear()
                for role in ('primary', 'secondary'):
                    response = self.frame(role, query_string={'haar': 1})
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
            enable.assert_not_called()
            self.manager.assert_not_called()

    def test_shared_limit_across_roles_and_query_strings(self):
        with patch('utils.api_security.time.monotonic', return_value=100), \
                patch('src.app.frame_preview_limit', FramePreviewLimiter()):
            for role in ('primary', 'secondary'):
                response = self.frame(role)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/jpeg')
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            for role in ('primary', 'secondary'):
                response = self.frame(role, query_string={'t': 'changed', 'haar': 1})
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers['Retry-After'], '1')
            self.assertEqual(self.manager.return_value.get_latest_frame.call_count, 2)

    def test_end_of_maintenance_immediately_blocks_next_frame(self):
        self.assertEqual(self.frame().status_code, 200)
        self.mode.active = False
        self.requested.clear()
        self.assertEqual(self.frame('secondary').status_code, 403)
        self.assertEqual(self.manager.return_value.get_latest_frame.call_count, 1)

    def test_budget_refills_and_parallel_calls_are_bounded(self):
        with patch('utils.api_security.time.monotonic', return_value=100):
            limiter = FramePreviewLimiter()
            results = []
            threads = [threading.Thread(target=lambda: results.append(limiter.retry_after())) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(results.count(0), 2)
        with patch('utils.api_security.time.monotonic', return_value=100.5):
            self.assertEqual(limiter.retry_after(), 0)
            self.assertGreater(limiter.retry_after(), 0)

    def test_busy_maintenance_does_not_queue_camera_read(self):
        entered = threading.Event()
        release = threading.Event()
        def occupy():
            with self.mode.lock:
                entered.set()
                release.wait(3)
        worker = threading.Thread(target=occupy)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.frame().status_code, 409)
            self.manager.assert_not_called()
        finally:
            release.set()
            worker.join()

    def test_status_reports_availability_without_opening_cameras(self):
        with patch('src.app.get_public_camera_status', return_value={}):
            self.assertTrue(self.client.get('/api/cameras/status', headers=self.headers).json['preview_available'])
            self.mode.active = False
            self.assertFalse(self.client.get('/api/cameras/status', headers=self.headers).json['preview_available'])
        self.manager.assert_not_called()


if __name__ == '__main__':
    unittest.main()
