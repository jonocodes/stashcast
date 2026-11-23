"""Tests for the /healthz endpoint used by container healthchecks."""

from unittest.mock import patch

from django.test import Client, TestCase, override_settings


@override_settings(ALLOWED_HOSTS=['stashcast.example.com'])
class HealthCheckTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_ok_when_database_reachable(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    def test_ignores_allowed_hosts(self):
        """Healthchecks hit 127.0.0.1, which is rarely in ALLOWED_HOSTS."""
        response = self.client.get('/healthz', HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(response.status_code, 200)

    def test_other_paths_still_validate_host(self):
        response = self.client.get('/', HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(response.status_code, 400)

    def test_503_when_database_unreachable(self):
        with patch('stashcast.health.connection.ensure_connection', side_effect=Exception('down')):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
