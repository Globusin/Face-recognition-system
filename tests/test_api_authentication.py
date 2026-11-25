"""API состояния, журнала и политик без оборудования"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import app
from utils.access.audit import AuditLog
from utils.access.decision import AccessPolicy
from utils.access.status import authentication_service


class FakeEngine:
    def __init__(self):
        self.snapshot_data = None

    def snapshot(self):
        return self.snapshot_data


class ApiAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.policy_file = str(Path(self.folder.name) / 'policy.json')
        self.config = {
            'security': {'admin_networks': ['127.0.0.1/32', '::1/128']},
            'authentication': {'policy_file': self.policy_file},
            'stereo_liveness': {'mode': 'advisory'},
            'challenge_response': {'policy': 'disabled', 'pipeline_count': 1},
        }
        for target in ('src.app.load_config', 'utils.access.api_security.load_config'):
            patcher = patch(target, side_effect=lambda: self.config)
            patcher.start()
            self.addCleanup(patcher.stop)
        secret = patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'test-' + 'a' * 40})
        secret.start()
        self.addCleanup(secret.stop)
        self.client = app.test_client()
        self.headers = {'X-Admin-Token': 'test-' + 'a' * 40}
        self.engine = FakeEngine()
        authentication_service.attach(self.engine)
        authentication_service.configure_audit(
            AuditLog(Path(self.folder.name) / 'audit.jsonl'),
        )
        authentication_service.set_running_policy(AccessPolicy(
            stereo_mode='advisory', challenge_mode='disabled',
        ))
        self.addCleanup(authentication_service.attach, None)

    def snapshot(self, user_id=7):
        return {
            'state': 'GRANTED',
            'door_open': False,
            'session': {
                'session_id': 'session-1',
                'started_at': 1.0,
                'updated_at': 2.0,
                'finished_at': 2.0,
                'user_id': user_id,
                'distance': 0.1,
                'reason': '',
                'unlock_attempted': True,
                'checks': {'recognition': {'status': 'PASS', 'reason': ''}},
                'diagnostics': {},
            },
        }

    def test_state_is_public_and_has_no_identity(self):
        self.engine.snapshot_data = self.snapshot()
        response = self.client.get(
            '/api/authentication/state', base_url='https://localhost',
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['identity_matched'])
        self.assertEqual(data['decision'], 'GRANTED')
        self.assertNotIn('user_id', data)

    def test_history_requires_admin(self):
        response = self.client.get(
            '/api/authentication/history', base_url='https://localhost',
        )
        self.assertEqual(response.status_code, 401)
        response = self.client.get(
            '/api/authentication/history', base_url='https://localhost',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['items'], [])

    def test_policy_read_and_update(self):
        response = self.client.get(
            '/api/authentication/policy', base_url='https://localhost',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['policy']['stereo_mode'], 'advisory')
        self.assertFalse(data['restart_required'])

        response = self.client.put(
            '/api/authentication/policy', base_url='https://localhost',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'stereo_mode': 'required', 'challenge_mode': 'adaptive',
                  'challenge_count': 2},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['restart_required'])
        self.assertTrue(Path(self.policy_file).is_file())

        invalid = self.client.put(
            '/api/authentication/policy', base_url='https://localhost',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'stereo_mode': 'always', 'challenge_mode': 'disabled',
                  'challenge_count': 1},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_authenticate_endpoint_is_removed(self):
        # Маршрут удалён: аутентификацию выполняет только Monitor
        response = self.client.post(
            '/api/authenticate', base_url='https://localhost', headers=self.headers,
        )
        self.assertEqual(response.status_code, 405)
        anonymous = self.client.post(
            '/api/authenticate', base_url='https://localhost',
        )
        self.assertEqual(anonymous.status_code, 401)


if __name__ == '__main__':
    unittest.main()
