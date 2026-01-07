import functools
import http.server
import socketserver
import threading
import time
import unittest
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from media.models import MediaItem


class MediaTestServer(threading.Thread):
    """Lightweight HTTP server to serve files for E2E tests."""

    def __init__(self, directory: Path):
        super().__init__(daemon=True)
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(directory)
        )
        self.httpd = socketserver.TCPServer(
            ("127.0.0.1", 0), handler, bind_and_activate=False
        )
        self.httpd.allow_reuse_address = True
        self.httpd.server_bind()
        self.httpd.server_activate()
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@override_settings(STASHCAST_SUMMARY_SENTENCES=0)
class EndToEndSmokeTest(TestCase):
    """
    Happy-path E2E: stash a media URL from the test server and ensure it lands in the audio feed.
    Relies on demo_data/pecha-kucha-aud/aud.mp3 shipped with the repo.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_dir = Path(settings.BASE_DIR) / "demo_data" / "pecha-kucha-aud"
        test_file = demo_dir / "aud.mp3"
        if not test_file.exists():
            raise unittest.SkipTest("Demo media file not found for E2E test.")

        cls.server = MediaTestServer(demo_dir)
        cls.server.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.port}"
        cls.test_file = test_file

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.stop()
        super().tearDownClass()

    def test_stash_and_feed_ready(self):
        url = f"{self.base_url}/{self.test_file.name}"
        response = self.client.get(
            "/stash/",
            {
                "apikey": settings.STASHCAST_API_KEY,
                "url": url,
                "type": "auto",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        guid = payload.get("guid")
        self.assertTrue(guid)

        # Wait for processing to reach READY (Huey runs immediate in tests)
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, "Media item not found after stashing")
        self.assertEqual(item.status, MediaItem.STATUS_READY, f"Status: {item.status}")
        self.assertTrue(item.content_path)

        # Fetch feed and ensure slug/content appear
        feed_resp = self.client.get("/feeds/audio.xml")
        self.assertEqual(feed_resp.status_code, 200)
        feed_xml = feed_resp.content.decode()
        self.assertIn(item.slug, feed_xml)
        self.assertIn(item.content_path, feed_xml)
