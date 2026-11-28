"""Сквозной регрессионный тест логики допуска с подменой оборудования."""
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from utils.capture import video_capture
from utils.capture.frame_pairing import CameraFrame
from utils.face.face_observations import FaceObservationSource, ObservationRejected
from utils.face.recognition import recognize_face_from_camera
from utils.access.authentication import AuthenticationEngine, AuthenticationState, CheckResult, CheckStatus
from utils.access.decision import AccessPolicy
from utils.common.maintenance import MaintenanceMode


class P8PipelineTests(unittest.TestCase):
    def run_attempt(self, backend, stereo=CheckStatus.PASS, challenge=CheckStatus.PASS,
                    lose_face=False, identity=True):
        now = [100.0]
        stop = threading.Event()
        maintenance = MaintenanceMode()
        lock = Mock()
        lock.unlock.return_value = True
        manager = Mock(dual_mode=False)
        image = np.zeros((120, 160, 3), np.uint8)
        box = (30, 30, 60, 60)
        # Последний кадр должен принадлежать тому же треку.
        second = CameraFrame('primary', 2, 100_100_000_000, image)
        manager.get_frame.side_effect = [CameraFrame('primary', 1, 100_000_000_000, image), second]
        detections = [[box], [] if lose_face else [box]]
        detector = Mock(side_effect=detections)
        fake_yunet = Mock()
        fake_yunet.detect = detector
        worker = Mock()
        worker.compute.return_value = [[1.0]]
        engine = AuthenticationEngine(
            lock, maintenance, stop, clock=lambda: now[0],
            policy=AccessPolicy(stereo_mode='required', challenge_mode='always'),
            stereo_check=lambda session: CheckResult(stereo, 'stereo_failed' if stereo != CheckStatus.PASS else ''),
            challenge_check=lambda session: CheckResult(challenge, 'challenge_failed' if challenge != CheckStatus.PASS else ''),
        )
        with patch.object(video_capture, '_detector_settings', {'backend': backend}), \
                patch.object(video_capture, 'detect_faces_haar', detector), \
                patch.object(video_capture, '_yunet', fake_yunet), \
                patch('utils.face.recognition.get_recognition_mode', return_value='fixed'), \
                patch('utils.face.recognition.get_multi_frame_recognition_config', return_value=(1, 1, 0, .05)), \
                patch('utils.face.recognition.recognize_face_from_embeddings_series',
                      return_value=(True, 7, .1) if identity else (False, None, None)):
            source = FaceObservationSource(manager, stop, maintenance.requested, clock=lambda: now[0])
            first = source.next()
            self.assertEqual(first.face_box, box)
            session = engine.begin(first.track_id)
            now[0] = 100.1

            def recognize():
                try:
                    return recognize_face_from_camera(source, engine.session.deadline, embedding_worker=worker)
                except ObservationRejected as error:
                    engine.cancel(str(error))
                    return False, None, None

            engine.evaluate(session, recognize)
        worker.compute.assert_called_once()
        self.assertEqual(worker.compute.call_args.args[1], box)
        detector.assert_called()
        return engine, lock

    def test_both_backends_grant_only_after_all_checks(self):
        for backend in ('haar', 'yunet'):
            with self.subTest(backend=backend):
                engine, lock = self.run_attempt(backend)
                self.assertEqual(engine.state, AuthenticationState.GRANTED)
                lock.unlock.assert_called_once()
                self.assertEqual(set(engine.session.checks), {'recognition', 'stereo', 'challenge'})

    def test_both_backends_reject_failures(self):
        for backend in ('haar', 'yunet'):
            for options in ({'stereo': CheckStatus.FAIL}, {'challenge': CheckStatus.FAIL},
                            {'lose_face': True}, {'identity': False}):
                with self.subTest(backend=backend, options=options):
                    engine, lock = self.run_attempt(backend, **options)
                    self.assertEqual(engine.state, AuthenticationState.DENIED)
                    lock.unlock.assert_not_called()
