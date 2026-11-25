"""Снимок для панели и обезличенный журнал без оборудования"""

import tempfile
import unittest
from pathlib import Path

from utils.access.authentication import CheckResult, CheckStatus
from utils.access.audit import AuditLog
from utils.access.status import AuthenticationService


class FakeEngine:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


def engine_snapshot(state='GRANTED', checks=None, diagnostics=None):
    return {
        'state': state,
        'door_open': False,
        'session': {
            'session_id': 'session-1',
            'started_at': 10.0,
            'updated_at': 12.0,
            'finished_at': 12.0,
            'user_id': 7,
            'distance': 0.09,
            'reason': 'identity_confirmed',
            'unlock_attempted': True,
            'checks': checks if checks is not None else {
                'recognition': {'status': 'PASS', 'reason': ''},
            },
            'diagnostics': diagnostics or {},
        },
    }


class ServiceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.service = AuthenticationService(clock=lambda: 15.0)

    def test_public_snapshot_hides_identity_and_metrics(self):
        self.service.attach(FakeEngine(engine_snapshot()))
        snapshot = self.service.public_snapshot()
        self.assertEqual(snapshot['state'], 'GRANTED')
        self.assertEqual(snapshot['decision'], 'GRANTED')
        self.assertTrue(snapshot['identity_matched'])
        self.assertEqual(snapshot['checks']['recognition']['status'], 'PASS')
        self.assertEqual(snapshot['elapsed_seconds'], 5.0)
        self.assertNotIn('user_id', snapshot)
        self.assertNotIn('distance', snapshot)

    def test_active_session_is_pending(self):
        self.service.attach(FakeEngine(engine_snapshot(state='EVALUATING')))
        self.assertEqual(self.service.public_snapshot()['decision'], 'PENDING')

    def test_stereo_verdict_is_visible(self):
        diagnostics = {'stereo': {'decision': 'UNKNOWN', 'reason': 'мало данных'}}
        self.service.attach(FakeEngine(engine_snapshot(diagnostics=diagnostics)))
        snapshot = self.service.public_snapshot()
        self.assertEqual(snapshot['stereo']['decision'], 'UNKNOWN')
        self.assertEqual(snapshot['stereo']['reason'], 'мало данных')

    def test_challenge_progress_is_bound_to_session(self):
        self.service.attach(FakeEngine(engine_snapshot(state='CHALLENGE')))
        self.service.publish_challenge_progress(
            'session-1', {'stage': 'action', 'command': 'TURN_LEFT'},
        )
        self.assertEqual(
            self.service.public_snapshot()['challenge']['command'], 'TURN_LEFT',
        )
        self.service.publish_challenge_progress(
            'other-session', {'stage': 'action', 'command': 'TURN_RIGHT'},
        )
        self.assertIsNone(self.service.public_snapshot()['challenge'])


class ServiceAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = AuthenticationService(clock=lambda: 20.0)
        self.service.configure_audit(
            AuditLog(Path(self.folder.name) / 'audit.jsonl'),
        )

    def session(self, state='DENIED'):
        from utils.access.authentication import AuthenticationSession

        result = AuthenticationSession('session-1', 10.0, 18.0, 30.0)
        result.state = state
        result.finished_at = 19.0
        result.reason = 'liveness_spoof'
        result.user_id = 7
        result.checks['recognition'] = CheckResult(CheckStatus.PASS)
        result.checks['stereo'] = CheckResult(CheckStatus.FAIL, 'liveness_spoof')
        result.diagnostics['stereo'] = {'decision': 'SPOOF', 'reason': 'плоско'}
        return result

    def test_record_session_has_no_biometric_payload(self):
        self.service.record_session(self.session())
        items = self.service.history()
        self.assertEqual(len(items), 1)
        record = items[0]
        self.assertEqual(record['decision'], 'DENIED')
        self.assertEqual(record['reason'], 'liveness_spoof')
        self.assertEqual(record['checks']['stereo']['status'], 'FAIL')
        self.assertEqual(record['stereo_decision'], 'SPOOF')
        self.assertNotIn('embedding', record)
        self.assertNotIn('image', record)

    def test_history_filters_and_policy_change(self):
        self.service.record_session(self.session())
        self.service.record_policy_change({'stereo_mode': 'required'}, '127.0.0.1')
        self.assertEqual(len(self.service.history(kind='session')), 1)
        self.assertEqual(len(self.service.history(kind='policy')), 1)


if __name__ == '__main__':
    unittest.main()
