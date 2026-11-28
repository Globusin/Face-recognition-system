"""Правила допуска: обязательность проверок и итоговое решение"""

import unittest

from utils.access.authentication import AuthenticationSession, CheckResult, CheckStatus
from utils.access.decision import AccessPolicy, DENIED, GRANTED
from utils.stereo.stereo_liveness import LIVE, SPOOF, UNKNOWN


def make_session(**checks):
    session = AuthenticationSession(
        'session-1', 0.0, 0.0, 100.0, tracked_face_id='track-1', user_id=7,
    )
    for name, status in checks.items():
        session.checks[name] = CheckResult(status, f'{name}_reason')
    return session


class PolicyConfigTests(unittest.TestCase):
    def test_from_config_defaults(self):
        policy = AccessPolicy.from_config({})
        self.assertEqual(policy.stereo_mode, 'off')
        self.assertEqual(policy.challenge_mode, 'disabled')
        self.assertEqual(policy.challenge_count, 4)

    def test_from_config_reads_modes(self):
        policy = AccessPolicy.from_config({
            'stereo_liveness': {'mode': 'REQUIRED'},
            'challenge_response': {'policy': 'adaptive', 'pipeline_count': 2},
        })
        self.assertEqual(policy.stereo_mode, 'required')
        self.assertEqual(policy.challenge_mode, 'adaptive')
        self.assertEqual(policy.challenge_count, 2)

    def test_invalid_modes_are_rejected(self):
        invalid = (
            {'stereo_liveness': {'mode': 'always'}},
            {'challenge_response': {'policy': 'auto'}},
            {'challenge_response': {'pipeline_count': 0}},
        )
        for config in invalid:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    AccessPolicy.from_config(config)


class PolicyTests(unittest.TestCase):
    def test_challenge_required(self):
        self.assertFalse(
            AccessPolicy(challenge_mode='disabled').challenge_required(make_session()),
        )
        self.assertTrue(
            AccessPolicy(challenge_mode='always').challenge_required(make_session()),
        )
        adaptive = AccessPolicy(challenge_mode='adaptive')
        self.assertTrue(adaptive.challenge_required(make_session()))
        for verdict, expected in ((LIVE, False), (UNKNOWN, True), (SPOOF, False)):
            session = make_session()
            session.diagnostics['stereo'] = {'decision': verdict}
            with self.subTest(verdict=verdict):
                self.assertEqual(adaptive.challenge_required(session), expected)

    def test_config_error_denies_everything(self):
        policy = AccessPolicy(config_error='policy_config_error')
        result = policy.evaluate(make_session(recognition=CheckStatus.PASS))
        self.assertEqual(result.status, DENIED)
        self.assertEqual(result.reason, 'policy_config_error')

    def test_advisory_spoof_denies_without_challenge(self):
        policy = AccessPolicy(stereo_mode='advisory', challenge_mode='adaptive')
        session = make_session(recognition=CheckStatus.PASS)
        session.diagnostics['stereo'] = {'decision': SPOOF}
        self.assertFalse(policy.challenge_required(session))
        result = policy.evaluate(session)
        self.assertEqual(result.status, DENIED)
        self.assertEqual(result.reason, 'liveness_spoof')

    def test_advisory_unknown_does_not_gate(self):
        policy = AccessPolicy(stereo_mode='advisory', challenge_mode='disabled')
        session = make_session(recognition=CheckStatus.PASS)
        session.diagnostics['stereo'] = {'decision': UNKNOWN}
        self.assertEqual(policy.evaluate(session).status, GRANTED)

    def test_identity_is_required(self):
        policy = AccessPolicy()
        self.assertEqual(
            policy.evaluate(make_session()).reason, 'identity_not_confirmed',
        )
        self.assertEqual(
            policy.evaluate(make_session(recognition=CheckStatus.FAIL)).status, DENIED,
        )
        self.assertEqual(
            policy.evaluate(make_session(recognition=CheckStatus.PASS)).status, GRANTED,
        )

    def test_required_stereo_must_pass(self):
        policy = AccessPolicy(stereo_mode='required')
        self.assertEqual(
            policy.evaluate(make_session(recognition=CheckStatus.PASS)).reason,
            'stereo_required',
        )
        for status in (CheckStatus.FAIL, CheckStatus.NOT_AVAILABLE):
            result = policy.evaluate(
                make_session(recognition=CheckStatus.PASS, stereo=status),
            )
            self.assertEqual(result.status, DENIED)
            self.assertEqual(result.reason, 'stereo_reason')
        granted = policy.evaluate(
            make_session(recognition=CheckStatus.PASS, stereo=CheckStatus.PASS),
        )
        self.assertEqual(granted.status, GRANTED)

    def test_advisory_stereo_does_not_gate(self):
        policy = AccessPolicy(stereo_mode='advisory')
        result = policy.evaluate(
            make_session(recognition=CheckStatus.PASS, stereo=CheckStatus.SKIPPED),
        )
        self.assertEqual(result.status, GRANTED)

    def test_required_challenge_must_pass(self):
        policy = AccessPolicy(challenge_mode='always')
        self.assertEqual(
            policy.evaluate(make_session(recognition=CheckStatus.PASS)).reason,
            'challenge_required',
        )
        for status in (CheckStatus.FAIL, CheckStatus.NOT_AVAILABLE,
                       CheckStatus.SKIPPED):
            with self.subTest(status=status):
                result = policy.evaluate(
                    make_session(recognition=CheckStatus.PASS, challenge=status),
                )
                self.assertEqual(result.status, DENIED)
        granted = policy.evaluate(
            make_session(recognition=CheckStatus.PASS, challenge=CheckStatus.PASS),
        )
        self.assertEqual(granted.status, GRANTED)

    def test_adaptive_live_skips_challenge(self):
        policy = AccessPolicy(challenge_mode='adaptive')
        session = make_session(recognition=CheckStatus.PASS)
        session.diagnostics['stereo'] = {'decision': LIVE}
        self.assertEqual(policy.evaluate(session).status, GRANTED)

    def test_any_failed_check_denies(self):
        policy = AccessPolicy()
        result = policy.evaluate(
            make_session(recognition=CheckStatus.PASS, challenge=CheckStatus.FAIL),
        )
        self.assertEqual(result.status, DENIED)
        self.assertEqual(result.reason, 'challenge_reason')

    def test_skipped_challenge_not_required_is_neutral(self):
        policy = AccessPolicy()
        result = policy.evaluate(
            make_session(recognition=CheckStatus.PASS, challenge=CheckStatus.SKIPPED),
        )
        self.assertEqual(result.status, GRANTED)


if __name__ == '__main__':
    unittest.main()
