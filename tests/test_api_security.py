"""HTTPS, сетевые ограничения и сессия администратора без оборудования"""

import unittest
from datetime import timedelta
from unittest.mock import patch

from src.app import app
from utils.api_security import _failures


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.config = {'security': {'admin_networks': ['127.0.0.1/32', '::1/128']}}
        self.settings = patch('utils.api_security.load_config', side_effect=lambda: self.config)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.secret = patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'test-' + 'a' * 40})
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.client = app.test_client()
        self.headers = {'X-Admin-Token': 'test-' + 'a' * 40}
        _failures.clear()

    def login(self, **kwargs):
        return self.client.post('/api/admin/login', headers=self.headers, **kwargs)

    def test_plain_http_denied_even_with_forged_proxy_headers(self):
        for route in ('/api/admin/login', '/api/calibration/start', '/api/add_user', '/api/authenticate'):
            response = self.client.post(route, base_url='http://localhost',
                headers={**self.headers, 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '127.0.0.1'})
            self.assertEqual(response.status_code, 403)

    def test_remote_admin_denied_even_with_valid_token_or_cookie(self):
        self.assertEqual(self.login().status_code, 200)
        for headers in ({}, self.headers, {**self.headers, 'X-Forwarded-For': '127.0.0.1'}):
            response = self.client.get('/api/admin/session', headers=headers,
                                       environ_overrides={'REMOTE_ADDR': '192.168.1.77'})
            self.assertEqual(response.status_code, 403)
        self.config['security']['admin_networks'].append('192.168.1.77/32')
        self.assertEqual(self.client.get('/api/admin/session',
            environ_overrides={'REMOTE_ADDR': '192.168.1.77'}).status_code, 200)

    def test_private_routes_deny_without_token_before_side_effects(self):
        with patch('src.app.get_all_users') as users, patch('src.app.get_camera_manager') as cameras, \
                patch('src.app.create_embeddings_from_camera') as enroll, patch('src.app.delete_user_by_id') as delete:
            for method, route in (('get', '/api/get_users'), ('post', '/api/add_user'),
                                  ('delete', '/api/delete_user/1'), ('get', '/api/cameras/status'),
                                  ('get', '/api/cameras/primary/frame'), ('post', '/api/calibration/face')):
                self.assertEqual(getattr(self.client, method)(route).status_code, 401)
            for operation in (users, cameras, enroll, delete):
                operation.assert_not_called()

    def test_cookie_flags_login_logout_and_rotation(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['Set-Cookie']
        for attribute in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Expires='):
            self.assertIn(attribute, cookie)
        self.assertEqual(self.client.get('/api/admin/session').status_code, 200)
        with patch.dict('os.environ', {'CALIBRATION_ADMIN_TOKEN': 'rotated-' + 'b' * 40}):
            self.assertEqual(self.client.get('/api/admin/session').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/admin/session').status_code, 401)

    def test_foreign_origin_and_invalid_network_settings_fail_closed(self):
        response = self.client.post('/api/admin/login', headers={**self.headers, 'Origin': 'https://evil.test'})
        self.assertEqual(response.status_code, 403)
        self.config['security']['admin_networks'] = ['invalid']
        self.assertEqual(self.login().status_code, 403)

    def test_expired_session_is_denied(self):
        self.assertEqual(self.login().status_code, 200)
        with patch.dict(app.config, {'PERMANENT_SESSION_LIFETIME': timedelta(seconds=-1)}):
            self.assertEqual(self.client.get('/api/admin/session').status_code, 401)

    def test_login_throttled_and_api_responses_not_cached(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/api/admin/login', headers={'X-Admin-Token': 'wrong'}).status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        response = self.client.get('/api/admin/session')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
