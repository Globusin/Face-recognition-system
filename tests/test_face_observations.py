"""Свежесть, сопровождение и переиспользование кадров без оборудования"""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from utils.camera_manager import CameraManager, CameraReader, CameraUnavailableError
from utils.face_observations import FaceObservationSource, ObservationRejected
from utils.frame_pairing import CameraFrame, FramePair, FramePairer
from utils.recognition import recognize_face_from_camera


class FaceObservationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.manager = Mock(dual_mode=True)
        self.manager.pairer.max_delta_ns = 80_000_000
        self.detector = Mock(return_value=[(10, 10, 40, 40)])
        self.source = FaceObservationSource(
            self.manager, self.stop, self.cancel, detector=self.detector,
            clock=lambda: self.now,
        )
        self.source.started_at = 99.0

    def frame(self, sequence, timestamp=100.0, role='primary'):
        return CameraFrame(role, sequence, round(timestamp * 1e9),
                           np.zeros((80, 80, 3), dtype=np.uint8))

    def pair(self, number, primary_time=100.0, secondary_time=None):
        if secondary_time is None:
            secondary_time = primary_time
        return FramePair(number, self.frame(number, primary_time),
                         self.frame(number, secondary_time, 'secondary'),
                         abs(primary_time - secondary_time) * 1000)

    def test_roi_track_and_initial_frame_are_reused(self):
        first, second = self.pair(1), self.pair(2, 100.2)
        self.manager.get_pair.side_effect = [first, second]
        initial = self.source.wait_for_face()
        self.now = 100.2
        observations = list(self.source.observations(2, 0.15, 110))
        self.assertIs(observations[0], initial)
        self.assertEqual(observations[1].track_id, initial.track_id)
        self.assertIs(observations[1].pair, second)
        self.assertEqual(self.detector.call_count, 2)
        self.assertEqual(self.manager.get_pair.call_count, 2)
        self.assertTrue(self.manager.get_pair.call_args.kwargs['latest'])

    def test_stale_repeated_and_unsynchronized_pairs_are_skipped(self):
        self.manager.get_pair.side_effect = [
            self.pair(1, 98), self.pair(2, 100, 99.8), self.pair(3),
            self.pair(3), self.pair(4, 100.1),
        ]
        self.source.next()
        self.now = 100.1
        result = self.source.next()
        self.assertEqual(result.primary.sequence, 4)
        self.assertEqual(self.detector.call_count, 2)

    def test_loss_multiple_faces_and_track_jump_abort(self):
        for faces, reason in (([], 'face_lost'),
                              ([(10, 10, 40, 40)] * 2, 'multiple_faces'),
                              ([(60, 60, 10, 10)], 'track_changed')):
            with self.subTest(reason=reason):
                self.setUp()
                self.manager.get_pair.side_effect = [self.pair(1), self.pair(2, 100.1)]
                self.source.next()
                self.now = 100.1
                self.detector.return_value = faces
                with self.assertRaisesRegex(ObservationRejected, reason):
                    self.source.next()

    def test_track_gap_aborts(self):
        self.manager.get_pair.side_effect = [self.pair(1), self.pair(2, 103)]
        self.source.next()
        self.now = 103
        with self.assertRaisesRegex(ObservationRejected, 'track_gap'):
            self.source.next()

    def test_stop_maintenance_and_deadline_prevent_detection(self):
        for event, reason in ((self.stop, 'stopped'), (self.cancel, 'maintenance')):
            event.set()
            with self.assertRaisesRegex(ObservationRejected, reason):
                self.source.next()
            event.clear()
        with self.assertRaisesRegex(ObservationRejected, 'timeout'):
            self.source.next(deadline=100)
        self.detector.assert_not_called()

    def test_expired_during_detection_is_rejected(self):
        self.manager.get_pair.return_value = self.pair(1)
        def detect(image):
            self.now += 1
            return [(10, 10, 40, 40)]
        self.detector.side_effect = detect
        with self.assertRaisesRegex(ObservationRejected, 'observation_expired'):
            self.source.next()

    def test_camera_failure_does_not_reuse_previous_observation(self):
        self.manager.get_pair.side_effect = [self.pair(1), CameraUnavailableError('lost')]
        self.source.next()
        with self.assertRaises(CameraUnavailableError):
            self.source.next()
        self.assertEqual(self.detector.call_count, 1)

    def test_missing_pairs_stop_waiting_at_frame_timeout(self):
        self.manager.get_pair.return_value = None
        def advance(*args, **kwargs):
            self.now += kwargs.get('timeout', args[1] if len(args) > 1 else 0.1)
            return None
        self.manager.get_pair.side_effect = advance
        with self.assertRaises(CameraUnavailableError):
            self.source.next()
        self.detector.assert_not_called()

    def test_rejected_track_after_database_cannot_return_success(self):
        source = Mock()
        source.observations.return_value = iter([])
        source.next.side_effect = ObservationRejected('face_lost')
        with patch('utils.recognition.recognize_face_from_embeddings_series',
                   return_value=(True, 7, 0.1)):
            with self.assertRaisesRegex(ObservationRejected, 'face_lost'):
                recognize_face_from_camera(source, 110)

    def test_single_camera_mode_uses_same_manager(self):
        self.manager.dual_mode = False
        self.manager.get_frame.return_value = self.frame(1)
        observation = self.source.next()
        self.assertIsNone(observation.pair)
        self.manager.get_pair.assert_not_called()
        self.assertTrue(self.manager.get_frame.call_args.kwargs['latest'])

    def test_frames_before_source_started_are_skipped(self):
        self.source.started_at = 100
        self.manager.get_pair.side_effect = [self.pair(1, 99.9), self.pair(2)]
        self.assertEqual(self.source.next().primary.sequence, 2)
        self.detector.assert_called_once()

    def test_too_close_frames_are_skipped_before_detection(self):
        self.manager.get_pair.side_effect = [self.pair(1), self.pair(2, 100.05),
                                             self.pair(3, 100.2)]
        self.source.next()
        self.now = 100.2
        observations = list(self.source.observations(2, 0.15, 110))
        self.assertEqual([item.primary.sequence for item in observations], [1, 3])
        self.assertEqual(self.detector.call_count, 2)

    def test_recognition_uses_roi_and_checks_track_after_database(self):
        observation = SimpleNamespace(primary=self.frame(1), face_box=(10, 10, 40, 40))
        source = Mock()
        source.observations.return_value = iter([observation])
        with patch('utils.recognition.get_embeddings_from_frame', return_value=[[1]]) as embed, \
                patch('utils.recognition.recognize_face_from_embeddings_series',
                      return_value=(True, 7, 0.1)) as score:
            result = recognize_face_from_camera(source, 110)
        embed.assert_called_once_with(observation.primary.image, observation.face_box)
        score.assert_called_once_with([[1]])
        source.next.assert_called_once_with(110)
        self.assertTrue(result[0])


class BufferedCaptureTests(unittest.TestCase):
    def frame(self, sequence):
        return CameraFrame('primary', sequence, time.monotonic_ns(), None)

    def test_reader_selects_latest_without_consuming_buffer(self):
        reader = CameraReader('primary', 0, {}, buffer_size=2)
        reader.frames.extend([self.frame(1), self.frame(2), self.frame(3)])
        self.assertEqual(len(reader.frames), 2)
        self.assertEqual(reader.get_frame(latest=True).sequence, 3)
        self.assertEqual(reader.get_frame().sequence, 2)
        reader.error = 'lost'
        self.assertIsNone(reader.get_frame(latest=True))
        self.assertIsNone(reader.get_latest_frame())

    def test_both_readers_continue_during_slow_processing(self):
        class FakeCapture:
            def __init__(self, device):
                self.stopped = threading.Event()

            def isOpened(self):
                return True

            def set(self, *args):
                return True

            def get(self, key):
                return 0

            def read(self):
                self.stopped.wait(0.005)
                return not self.stopped.is_set(), np.zeros((80, 80, 3), np.uint8)

            def release(self):
                self.stopped.set()

        factory = Mock(side_effect=FakeCapture)
        manager = CameraManager(
            {'cameras': {'enabled': True, 'buffer_size': 2,
                         'primary': {'device': 0}, 'secondary': {'device': 1}}},
            capture_factory=factory, use_process_lock=False,
        )
        try:
            manager.start()
            first = manager.get_pair(timeout=1, latest=True)
            self.assertIsNotNone(first)
            # Имитируем потребителя, занятого вычислением и не читающего кадры
            deadline = time.monotonic() + 1
            while min(reader.sequence for reader in manager.readers.values()) < 10:
                self.assertLess(time.monotonic(), deadline)
                threading.Event().wait(0.01)
            latest = manager.get_pair(first.number, timeout=1, latest=True)
            self.assertGreater(latest.primary.sequence, first.primary.sequence + 1)
            self.assertGreater(latest.secondary.sequence, first.secondary.sequence + 1)
            for reader in manager.readers.values():
                self.assertLessEqual(len(reader.frames), 2)
            self.assertLessEqual(len(manager.pairer.pairs), 2)
            self.assertEqual(factory.call_count, 2)
        finally:
            manager.stop()

    def test_pairer_selects_latest_and_keeps_bounded_queue(self):
        pairer = FramePairer(buffer_size=2)
        for number in range(1, 5):
            for role in ('primary', 'secondary'):
                frame = self.frame(number)
                frame.role = role
                pairer.add_frame(frame)
        self.assertEqual(len(pairer.pairs), 2)
        self.assertEqual(pairer.wait_for_pair(latest=True).number, 4)
        self.assertEqual(pairer.wait_for_pair().number, 3)


if __name__ == '__main__':
    unittest.main()
