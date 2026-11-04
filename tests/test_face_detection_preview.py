"""Разметка должна относиться к обработанному кадру, а не к новому превью"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from utils.face_detection_preview import FaceDetectionPreview
from src.app import app


class FaceDetectionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.preview = FaceDetectionPreview()
        self.frame = SimpleNamespace(image=np.full((120, 200, 3), 40, np.uint8), sequence=12)
        self.current = SimpleNamespace(image=np.full((120, 200, 3), 180, np.uint8), sequence=20)

    def test_disabled_does_not_store_images(self):
        self.preview.record(self.frame, [(30, 50, 40, 40)], 'SEARCH')
        self.assertIsNone(self.preview.latest)

    def test_positive_snapshot_is_exact_and_original_is_unchanged(self):
        original = self.frame.image.copy()
        self.preview.enable()
        self.preview.record(self.frame, [(30, 50, 40, 40)], 'SEARCH')
        self.preview.record(self.current, [], 'SERIES')
        image = self.preview.render(self.current)
        np.testing.assert_array_equal(image[110, 150], [40, 40, 40])
        np.testing.assert_array_equal(image[50, 30], [0, 0, 255])
        np.testing.assert_array_equal(self.frame.image, original)
        self.assertEqual(self.preview.last_positive['sequence'], 12)

    def test_expiration_and_empty_detections(self):
        with patch('utils.face_detection_preview.time.monotonic', return_value=100):
            self.preview.enable()
            self.preview.record(self.frame, [(30, 50, 40, 40)], 'SEARCH')
        with patch('utils.face_detection_preview.time.monotonic', return_value=111):
            image = self.preview.render(self.current)
            np.testing.assert_array_equal(image[110, 150], [180, 180, 180])
            self.preview.record(self.current, [], 'SERIES')
            self.assertIsNone(self.preview.last_positive)
        self.preview.enable()
        self.preview.record(self.current, [], 'SEARCH')
        self.assertEqual(self.preview.latest['faces'], ())

    def test_api_uses_cache_without_detection(self):
        self.preview.enable()
        self.preview.record(self.frame, [(30, 50, 40, 40)], 'SEARCH')
        with patch('src.app.face_detection_preview', self.preview), \
                patch('src.app.authorize_admin', return_value=None), \
                patch('src.app.calibration_session.active', True), \
                patch('src.app.maintenance.requested.is_set', return_value=True), \
                patch('src.app.frame_preview_limit.retry_after', return_value=0), \
                patch('src.app.get_camera_manager') as manager, \
                patch('utils.video_capture.detect_faces') as detect:
            manager.return_value.get_latest_frame.return_value = self.current
            client = app.test_client()
            result = client.get('/api/cameras/primary/frame?haar=1')
            self.assertEqual(result.status_code, 200)
            image = cv2.imdecode(np.frombuffer(result.data, np.uint8), cv2.IMREAD_COLOR)
            self.assertLess(int(image[110, 150, 0]), 60)
            result = client.get('/api/cameras/secondary/frame?haar=1')
            image = cv2.imdecode(np.frombuffer(result.data, np.uint8), cv2.IMREAD_COLOR)
            self.assertGreater(int(image[110, 150, 0]), 150)
            result = client.get('/api/cameras/primary/frame')
            image = cv2.imdecode(np.frombuffer(result.data, np.uint8), cv2.IMREAD_COLOR)
            self.assertGreater(int(image[110, 150, 0]), 150)
            detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
