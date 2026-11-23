"""Политика заданий, привязка к сессии и выполнение без камер"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from utils.access.authentication import AuthenticationSession, CheckResult, CheckStatus
from utils.access.decision import AccessPolicy
from utils.challenge.challenge_check import (
    ChallengeCheck, UnavailableChallengeCheck, build_challenge_check,
)
from utils.challenge.challenge_response import (
    COMMANDS, FaceObservation, challenge_settings, observe_face,
)
from utils.device.display import NullDisplay
from utils.face.face_observations import ObservationRejected
from utils.stereo.stereo_liveness import LIVE, UNKNOWN


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeImage:
    def __init__(self, yaw):
        self.yaw = yaw


class FakeSource:
    """Выдаёт кадры с заданной последовательностью yaw"""

    def __init__(self, clock, yaws, step=0.1, error=None, track_id='track-1'):
        self.clock = clock
        self.yaws = list(yaws)
        self.step = step
        self.error = error
        self.track_id = track_id

    def next(self, deadline=None):
        if self.error is not None:
            raise self.error
        if not self.yaws:
            raise ObservationRejected('face_lost')
        self.clock.value += self.step
        timestamp = self.clock.value
        return SimpleNamespace(
            primary=SimpleNamespace(
                image=FakeImage(self.yaws.pop(0)),
                timestamp_ns=int(timestamp * 1e9),
            ),
            face_box=(10, 10, 40, 40),
            track_id=self.track_id,
            pair=Mock(),
        )


def fake_observe(image, timestamp, durations=None, *, verify_identity=True, face_box=None):
    return FaceObservation(timestamp, 0.3, 0.3, image.yaw, None)


def flow_settings(count=1):
    settings = challenge_settings({})
    settings['count'] = count
    return settings


def make_session(distance=0.10, session_id='session-1', deadline=100.0, user_id=7):
    return AuthenticationSession(
        session_id, 0.0, 0.0, deadline,
        distance=distance, tracked_face_id='track-1', user_id=user_id,
    )


def make_check(policy='always', display=None, clock=None):
    return ChallengeCheck(
        flow_settings(), AccessPolicy(challenge_mode=policy, challenge_count=1),
        display if display is not None else Mock(),
        clock=clock if clock is not None else FakeClock(),
    )


class ChallengeExecutionTests(unittest.TestCase):
    def setUp(self):
        # Реальные кадры, dlib и база в этих проверках не нужны
        patchers = (
            patch('utils.challenge.challenge_check.observe_face', side_effect=fake_observe),
            patch('utils.challenge.challenge_check.get_embeddings_from_frame',
                  return_value=[np.zeros(128)]),
            patch('utils.challenge.challenge_check.match_embedding', return_value=(7, 0.1)),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_to_result(self, command, sign):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 8 + [0.4 * sign] * 4 + [0.0] * 2)
        display = Mock()
        check = make_check(clock=clock, display=display)
        check.bind(source)
        with patch('utils.challenge.challenge_response.secrets.choice', return_value=command):
            result = check(make_session())
        return result, display

    def test_both_turn_directions_pass_and_show_command(self):
        for command, sign in (('TURN_LEFT', 1), ('TURN_RIGHT', -1)):
            with self.subTest(command=command):
                result, display = self.run_to_result(command, sign)
                self.assertEqual(result.status, CheckStatus.PASS)
                self.assertEqual(result.reason, 'challenge_passed')
                shown = [call.args[1] for call in display.show_state.call_args_list]
                self.assertIn(COMMANDS[command], shown)

    def test_action_before_command_is_not_accepted(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.4] * 20, step=1.0)
        check = make_check(clock=clock)
        check.bind(source)
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'baseline_timeout')
        shown = [call.args[1] for call in check.display.show_state.call_args_list]
        for command in COMMANDS.values():
            self.assertNotIn(command, shown)

    def test_challenge_fails_when_identity_changed(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 8 + [0.4] * 4 + [0.0] * 2)
        check = make_check(clock=clock)
        check.bind(source)
        with patch('utils.challenge.challenge_response.secrets.choice',
                   return_value='TURN_LEFT'), \
                patch('utils.challenge.challenge_check.match_embedding',
                      return_value=(8, 0.1)):
            result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'identity_changed')

    def test_missing_final_embedding_fails_closed(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 8 + [0.4] * 4 + [0.0] * 2)
        check = make_check(clock=clock)
        check.bind(source)
        with patch('utils.challenge.challenge_response.secrets.choice',
                   return_value='TURN_LEFT'), \
                patch('utils.challenge.challenge_check.get_embeddings_from_frame',
                      return_value=None):
            result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'identity_not_measured')

    def test_face_loss_cancels_attempt(self):
        clock = FakeClock()
        source = FakeSource(clock, [], error=ObservationRejected('face_lost'))
        check = make_check(clock=clock)
        check.bind(source)
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'face_lost')

    def test_track_change_cancels_attempt(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 8, track_id='other')
        check = make_check(clock=clock)
        check.bind(source)
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'track_changed')

    def test_session_deadline_limits_challenge(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 10, step=5.0)
        check = make_check(clock=clock)
        check.bind(source)
        result = check(make_session(deadline=1.0))
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'timeout')

    def test_result_cannot_be_reused_for_same_session(self):
        clock = FakeClock()
        source = FakeSource(clock, [0.0] * 8 + [0.4] * 4 + [0.0] * 2)
        check = make_check(clock=clock)
        check.bind(source)
        session = make_session()
        with patch('utils.challenge.challenge_response.secrets.choice', return_value='TURN_LEFT'):
            self.assertEqual(check(session).status, CheckStatus.PASS)
            second = check(session)
        self.assertEqual(second.status, CheckStatus.FAIL)
        self.assertEqual(second.reason, 'challenge_reused')

    def test_prior_failure_blocks_challenge(self):
        clock = FakeClock()
        check = make_check(clock=clock)
        check.bind(FakeSource(clock, [0.0] * 8))
        session = make_session()
        session.checks['stereo'] = CheckResult(CheckStatus.FAIL, 'spoof')
        result = check(session)
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'prior_check_failed')

    def test_missing_source_and_display_are_not_available(self):
        result = make_check()(make_session())
        self.assertEqual(result.status, CheckStatus.NOT_AVAILABLE)
        self.assertEqual(result.reason, 'source_missing')

        clock = FakeClock()
        check = ChallengeCheck(
            flow_settings(),
            {'policy': 'always', 'adaptive_max_distance': 0.12},
            NullDisplay(), clock=clock,
        )
        check.bind(FakeSource(clock, [0.0] * 8))
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.NOT_AVAILABLE)
        self.assertEqual(result.reason, 'display_unavailable')

    def test_display_error_fails_closed(self):
        clock = FakeClock()
        display = Mock()
        display.show_state.side_effect = RuntimeError('tft')
        check = make_check(clock=clock, display=display)
        check.bind(FakeSource(clock, [0.0] * 8))
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(result.reason, 'display_error')


class ChallengePolicyTests(unittest.TestCase):
    def test_disabled_and_always(self):
        self.assertFalse(make_check('disabled').should_run(make_session()))
        self.assertTrue(make_check('always').should_run(make_session()))

    def test_adaptive_depends_on_stereo_verdict(self):
        for verdict, expected in ((LIVE, False), (UNKNOWN, True), (None, True)):
            with self.subTest(verdict=verdict):
                session = make_session()
                if verdict is not None:
                    session.diagnostics['stereo'] = {'decision': verdict}
                self.assertEqual(make_check('adaptive').should_run(session), expected)

    def test_build_returns_none_for_disabled_policy(self):
        self.assertIsNone(build_challenge_check({}, Mock(), AccessPolicy()))
        check = build_challenge_check(
            {'challenge_response': {'count': 3}},
            Mock(), AccessPolicy(challenge_mode='always', challenge_count=1),
        )
        self.assertIsInstance(check, ChallengeCheck)
        self.assertEqual(check.settings['count'], 1)

    def test_config_error_does_not_disable_mandatory_check(self):
        check = build_challenge_check(
            {'challenge_response': {'count': 0}},
            Mock(), AccessPolicy(challenge_mode='always'),
        )
        self.assertIsInstance(check, UnavailableChallengeCheck)
        self.assertTrue(check.should_run(make_session()))
        result = check(make_session())
        self.assertEqual(result.status, CheckStatus.NOT_AVAILABLE)


class KnownFaceBoxTests(unittest.TestCase):
    def face(self):
        return {
            'left_eye': [(10, 10), (11, 9), (12, 9), (13, 10), (12, 11), (11, 11)],
            'right_eye': [(20, 10), (21, 9), (22, 9), (23, 10), (22, 11), (21, 11)],
            'nose_tip': [(15, 15), (16, 16), (17, 17), (16, 18), (15, 19)],
        }

    def test_known_box_skips_repeated_detection(self):
        image = np.zeros((120, 160, 3), np.uint8)
        with patch('face_recognition.face_locations') as detect, \
                patch('face_recognition.face_landmarks',
                      return_value=[self.face()]) as landmarks, \
                patch('face_recognition.face_encodings',
                      return_value=[np.zeros(128)]), \
                patch('utils.challenge.challenge_response.estimate_head_pose',
                      return_value={'status': 'failed'}):
            result = observe_face(image, 1.0, face_box=(10, 20, 40, 50))

        detect.assert_not_called()
        self.assertEqual(landmarks.call_args.kwargs['face_locations'], [(20, 50, 70, 10)])
        self.assertAlmostEqual(result.yaw, 0.05)

    def test_box_outside_image_is_rejected(self):
        image = np.zeros((120, 160, 3), np.uint8)
        with self.assertRaisesRegex(ValueError, 'landmarks_not_detected'):
            observe_face(image, 1.0, face_box=(200, 200, 10, 10))


if __name__ == '__main__':
    unittest.main()
