import unittest
from unittest.mock import Mock, patch

from utils.face.embedding_worker import EmbeddingWorker


class WorkerPreparationTests(unittest.TestCase):
    def test_completed_previous_result_is_discarded(self):
        worker = EmbeddingWorker()
        worker.pending_since = 1
        worker.connection = Mock()
        worker.connection.poll.return_value = True
        with patch.object(worker, 'start') as start:
            worker.prepare_for_session()
        worker.connection.recv.assert_called_once()
        self.assertIsNone(worker.pending_since)
        start.assert_called_once()

    def test_unfinished_previous_job_is_restarted(self):
        worker = EmbeddingWorker()
        worker.pending_since = 1
        worker.connection = Mock()
        worker.connection.poll.return_value = False
        with patch.object(worker, 'close') as close, patch.object(worker, 'start') as start:
            worker.prepare_for_session()
        close.assert_called_once()
        start.assert_called_once()

class WorkerRoiTests(unittest.TestCase):
    def test_job_preserves_rgb_pixels_and_location(self):
        import numpy as np
        from utils.face.embedding_worker import prepare_job
        from utils.face.recognition import prepare_face_roi
        frame = np.random.default_rng(42).integers(0, 256, (720,1280,3), dtype=np.uint8)
        box = (100, 90, 160, 180)
        with patch('utils.face.recognition.config',
                   {'recognition_optimization': {'roi_enabled': True, 'roi_padding': .3}}):
            mode, roi, location = prepare_job(frame, box)
            expected, expected_location = prepare_face_roi(frame, box, .3)
        self.assertEqual(mode, 'roi')
        self.assertEqual(location, expected_location)
        np.testing.assert_array_equal(roi, expected)
        self.assertLess(roi.nbytes, frame.nbytes)

    def test_disabled_roi_keeps_full_frame(self):
        import numpy as np
        from utils.face.embedding_worker import prepare_job
        frame = np.zeros((120, 160, 3), np.uint8)
        with patch('utils.face.recognition.config', {'recognition_optimization': {'roi_enabled': False}}):
            mode, data, box = prepare_job(frame, (1, 2, 30, 40))
        self.assertEqual(mode, 'frame')
        self.assertIs(data, frame)
        self.assertEqual(box, (1,2,30,40))
