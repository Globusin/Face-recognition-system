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
