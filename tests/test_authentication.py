"""Проверки автомата без камер, БД и физических приводов."""

import threading
import unittest
from unittest.mock import Mock

from utils.authentication import (
    AuthenticationEngine, AuthenticationState as State, CheckResult, CheckStatus,
)
from utils.maintenance import MaintenanceMode


class AuthenticationEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.mode = MaintenanceMode()
        self.stop = threading.Event()
        self.lock = Mock()
        self.lock.unlock.return_value = True
        self.lock.lock.return_value = True
        self.states = []
        self.engine = AuthenticationEngine(
            self.lock, self.mode, self.stop, clock=lambda: self.now,
            session_timeout=10, cooldown_seconds=2, door_open_seconds=5,
            on_state=self.states.append,
        )

    def evaluate(self, result=(True, 7, 0.1)):
        session_id = self.engine.begin('track-1')
        self.engine.evaluate(session_id, lambda: result)
        return session_id

    def test_success_closes_door_and_enters_cooldown(self):
        session_id = self.evaluate()
        self.assertEqual(self.states, [State.TRACKING, State.EVALUATING, State.GRANTED])
        self.assertEqual(self.engine.session.tracked_face_id, 'track-1')
        self.assertEqual(self.engine.session.user_id, 7)
        self.assertTrue(self.mode.door_open.is_set())
        self.engine.evaluate(session_id, lambda: (True, 7, 0.1))
        self.lock.unlock.assert_called_once()
        self.assertIsNone(self.engine.begin())
        self.now += 5
        self.engine.tick()
        self.lock.lock.assert_called_once()
        self.assertFalse(self.mode.door_open.is_set())
        self.assertEqual(self.engine.state, State.COOLDOWN)
        self.now += 2
        self.engine.tick()
        self.assertEqual(self.engine.state, State.IDLE)
        self.assertNotEqual(self.engine.begin(), session_id)

    def test_unknown_and_invalid_identity_never_unlock(self):
        for result in ((False, None, None), (True, None, 0.1),
                       (True, 7, float('nan')), (True, 7, -1)):
            with self.subTest(result=result):
                self.setUp()
                self.evaluate(result)
                self.assertEqual(self.engine.state, State.DENIED)
                self.lock.unlock.assert_not_called()

    def test_late_result_after_stop_maintenance_timeout_or_face_loss(self):
        for action, reason in (
            (self.stop.set, 'stopped'),
            (self.mode.requested.set, 'maintenance'),
            (lambda: setattr(self, 'now', 110), 'timeout'),
            (lambda: self.engine.face_lost(self.engine.session.session_id), 'face_lost'),
            (self.engine.cancel, 'cancelled'),
        ):
            with self.subTest(reason=reason):
                self.stop.clear()
                self.mode.requested.clear()
                self.now = 100
                self.engine.state = State.IDLE
                session_id = self.engine.begin()
                def recognize():
                    action()
                    return True, 7, 0.1
                self.engine.evaluate(session_id, recognize)
                self.assertEqual(self.engine.state, State.DENIED)
                self.assertEqual(self.engine.session.reason, reason)
                self.lock.unlock.assert_not_called()

    def test_adapter_fail_or_unavailable_denies(self):
        for status in (CheckStatus.FAIL, CheckStatus.NOT_AVAILABLE):
            with self.subTest(status=status):
                self.setUp()
                self.engine.stereo_check = lambda session: CheckResult(status, 'no_data')
                self.engine.challenge_check = Mock()
                self.evaluate()
                self.assertEqual(self.engine.session.reason, 'no_data')
                self.engine.challenge_check.assert_not_called()
                self.lock.unlock.assert_not_called()

    def test_challenge_interface_and_session_binding(self):
        seen = []
        def challenge(session):
            self.assertEqual(self.engine.state, State.CHALLENGE)
            seen.append(session.session_id)
            return CheckResult(CheckStatus.PASS)
        self.engine.challenge_check = challenge
        session_id = self.evaluate()
        self.assertEqual(seen, [session_id])
        self.assertEqual(self.engine.state, State.GRANTED)

    def test_error_and_failed_unlock_are_safe(self):
        self.evaluate_error = Mock(side_effect=RuntimeError('camera'))
        self.engine.evaluate(self.engine.begin(), self.evaluate_error)
        self.assertEqual(self.engine.state, State.ERROR)
        self.lock.unlock.assert_not_called()
        self.engine.state = State.IDLE
        self.lock.unlock.return_value = False
        self.evaluate()
        self.assertEqual(self.engine.state, State.ERROR)
        self.assertTrue(self.engine.close())
        self.lock.lock.assert_called_once()
        self.assertIsNone(self.engine.begin())

    def test_close_failure_keeps_door_open_flag(self):
        self.evaluate()
        self.lock.lock.return_value = False
        self.assertFalse(self.engine.close())
        self.assertEqual(self.engine.state, State.ERROR)
        self.assertTrue(self.mode.door_open.is_set())

    def test_cancel_from_other_thread_ignores_inflight_result(self):
        entered = threading.Event()
        release = threading.Event()
        def recognize():
            entered.set()
            release.wait(2)
            return True, 7, 0.1
        session_id = self.engine.begin()
        worker = threading.Thread(target=self.engine.evaluate, args=(session_id, recognize))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.engine.cancel()
            self.engine.tick()
            self.now += 2
            self.engine.tick()
            self.assertIsNone(self.engine.begin())
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.lock.unlock.assert_not_called()

    def test_lock_exception_is_reported_without_clearing_open_flag(self):
        self.evaluate()
        self.lock.lock.side_effect = RuntimeError('device unavailable')
        self.assertFalse(self.engine.close())
        self.assertEqual(self.engine.session.reason, 'lock_failed')
        self.assertTrue(self.mode.door_open.is_set())

    def test_stale_session_cannot_affect_new_attempt(self):
        old_id = self.engine.begin()
        self.engine.cancel()
        self.engine.tick()
        self.now += 2
        self.engine.tick()
        new_id = self.engine.begin()
        self.engine.face_lost(old_id)
        recognize = Mock()
        self.engine.evaluate(old_id, recognize)
        recognize.assert_not_called()
        self.assertEqual(self.engine.session.session_id, new_id)
        self.assertEqual(self.engine.state, State.TRACKING)

    def test_idle_and_tracking_timeout(self):
        self.engine.tick()
        self.assertEqual(self.engine.state, State.IDLE)
        self.engine.begin()
        self.now += 10
        self.engine.tick()
        self.assertEqual(self.engine.session.reason, 'timeout')
        self.assertIn(State.DENIED, self.states)
        self.lock.unlock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
