"""Быстрый поиск не должен уменьшать разрешение уточнения углов"""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from utils.stereo.stereo_calibration import find_board


class FastBoardDetectionTests(unittest.TestCase):
    def test_scaled_coordinates_and_original_refinement(self):
        image = np.zeros((721, 1280, 3), dtype=np.uint8)
        candidates = np.full((49, 1, 2), [100, 100], dtype=np.float32)
        durations = {}
        with patch('utils.stereo.stereo_calibration.cv2.findChessboardCorners', return_value=(True, candidates)) as search, \
                patch('utils.stereo.stereo_calibration.cv2.cornerSubPix', side_effect=lambda gray, points, *args: points) as refine:
            result = find_board(image, max_search_width=640, durations=durations)
        self.assertEqual(search.call_args.args[0].shape, (360, 640))
        self.assertEqual(refine.call_args.args[0].shape, (721, 1280))
        np.testing.assert_allclose(result[0, 0], [200, 100 * 721 / 360])
        self.assertEqual(set(durations), {'board_search_reduced', 'board_refine_full'})

    def test_fallback_and_rotation(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        candidates = np.arange(98, dtype=np.float32).reshape(49, 1, 2)
        durations = {}
        with patch('utils.stereo.stereo_calibration.cv2.findChessboardCorners', side_effect=[(False, None), (True, candidates)]) as search, \
                patch('utils.stereo.stereo_calibration.cv2.cornerSubPix', side_effect=lambda gray, points, *args: points):
            result = find_board(image, 1, max_search_width=640, durations=durations)
        self.assertEqual([call.args[0].shape for call in search.call_args_list], [(360, 640), (720, 1280)])
        np.testing.assert_array_equal(result, np.rot90(candidates.reshape(7, 7, 2), 1).reshape(49, 1, 2))
        self.assertEqual(set(durations), {'board_search_reduced', 'board_search_full', 'board_refine_full'})

    def test_missing_board_and_small_image(self):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        with patch('utils.stereo.stereo_calibration.cv2.findChessboardCorners', return_value=(False, None)) as search, \
                patch('utils.stereo.stereo_calibration.cv2.cornerSubPix') as refine:
            self.assertIsNone(find_board(image, max_search_width=640))
        self.assertEqual(search.call_count, 1)
        refine.assert_not_called()

    def test_disabled_fast_path_keeps_full_search(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch('utils.stereo.stereo_calibration.cv2.findChessboardCorners', return_value=(False, None)) as search:
            self.assertIsNone(find_board(image))
        self.assertEqual(search.call_count, 1)
        self.assertEqual(search.call_args.args[0].shape, (720, 1280))

    def test_real_opencv_coordinates_on_perspective_board(self):
        image = np.full((720, 1280, 3), 255, dtype=np.uint8)
        for row in range(8):
            for column in range(8):
                if (row + column) % 2 == 0:
                    x, y = 400 + column * 60, 120 + row * 60
                    image[y:y + 60, x:x + 60] = 0
        source = np.float32([[400, 120], [880, 120], [880, 600], [400, 600]])
        target = np.float32([[380, 130], [900, 150], [850, 620], [410, 580]])
        transform = cv2.getPerspectiveTransform(source, target)
        image = cv2.warpPerspective(image, transform, (1280, 720), borderValue=(255, 255, 255))
        full = find_board(image)
        fast = find_board(image, max_search_width=640)
        self.assertIsNotNone(full)
        self.assertIsNotNone(fast)
        # У симметричной доски допустим разворот нумерации на 180 градусов
        error = min(np.max(np.linalg.norm(full - fast, axis=2)),
                    np.max(np.linalg.norm(full - fast[::-1], axis=2)))
        self.assertLess(error, .1)


if __name__ == '__main__':
    unittest.main()
