"""Конфигурация HTTPS и единственного аппаратного worker без камер"""

import ssl
import unittest
from unittest.mock import patch

from src.run_app import server_options, start_monitor, tls_context


class HttpsServerTests(unittest.TestCase):
    def test_tls_and_single_worker_cannot_be_disabled_in_config(self):
        with patch('src.run_app.load_config', return_value={'server': {'workers': 8, 'tls': False}}), \
                patch('src.run_app.ssl.SSLContext'), patch('src.run_app.Path.is_file', return_value=True):
            options = server_options()
        self.assertEqual(options['workers'], 1)
        self.assertEqual(options['worker_class'], 'gthread')
        self.assertEqual(options['forwarded_allow_ips'], '')
        self.assertEqual(options['secure_scheme_headers'], {})
        self.assertIs(options['post_worker_init'], start_monitor)
        self.assertTrue(options['certfile'].endswith('server.crt'))

    def test_no_plaintext_fallback_without_certificate(self):
        with patch('src.run_app.load_config', return_value={'server': {'cert_file': '/nonexistent/face-test.crt'}}):
            with self.assertRaises(OSError):
                server_options()

    def test_minimum_tls_version(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.assertIs(tls_context(None, lambda: context), context)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


if __name__ == '__main__':
    unittest.main()
