import unittest
from unittest.mock import patch, Mock

import numpy as np

from utils.capture.yunet_detector import YuNetDetector
from utils.capture import video_capture


class DetectorTests(unittest.TestCase):
    def test_scaling_clipping_and_multiple_faces(self):
        detector = YuNetDetector({'input_width': 320})
        detector._model = Mock()
        detector._model.detect.return_value = (1, np.array([
            [-5, 10, 55, 60] + [0]*10 + [.99],
            [100, 30, 40, 50] + [0]*10 + [.95],
        ]))
        frame = np.zeros((720, 1280, 3), np.uint8)
        self.assertEqual(detector.detect(frame), [(0, 40, 200, 240), (400, 120, 160, 200)])
        detector._model.setInputSize.assert_called_once_with((320, 180))

    def test_no_faces(self):
        detector = YuNetDetector({})
        detector._model = Mock()
        detector._model.detect.return_value = (1, None)
        self.assertEqual(detector.detect(np.zeros((120, 160, 3), np.uint8)), [])

    def test_switch_haar(self):
        with patch.object(video_capture, '_detector_settings', {'backend': 'haar'}), \
                patch.object(video_capture, 'detect_faces_haar', return_value=[]) as haar:
            self.assertEqual(video_capture.detect_faces(None), [])
            haar.assert_called_once()

    def test_unknown_backend(self):
        with patch.object(video_capture, '_detector_settings', {'backend': 'invalid'}):
            with self.assertRaises(ValueError):
                video_capture.detect_faces(None)
