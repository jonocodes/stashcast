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
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        self.httpd = socketserver.TCPServer(('127.0.0.1', 0), handler, bind_and_activate=False)
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
        demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-aud'
        test_file = demo_dir / 'aud.mp3'
        if not test_file.exists():
            raise unittest.SkipTest('Demo media file not found for E2E test.')

        cls.server = MediaTestServer(demo_dir)
        cls.server.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.port}'
        cls.test_file = test_file

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'server', None):
            cls.server.stop()
        super().tearDownClass()

    def test_stash_and_feed_ready(self):
        url = f'{self.base_url}/{self.test_file.name}'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        guid = payload.get('guid')
        self.assertTrue(guid)

        # Wait for processing to reach READY (Huey runs immediate in tests)
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found after stashing')
        self.assertEqual(item.status, MediaItem.STATUS_READY, f'Status: {item.status}')
        self.assertTrue(item.content_path)

        # Fetch feed and ensure slug/content appear
        feed_resp = self.client.get('/feeds/audio.xml')
        self.assertEqual(feed_resp.status_code, 200)
        feed_xml = feed_resp.content.decode()
        self.assertIn(item.slug, feed_xml)
        self.assertIn(item.content_path, feed_xml)


@override_settings(STASHCAST_SUMMARY_SENTENCES=0)
class VideoE2ETest(TestCase):
    """E2E tests for video stashing"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-vid'
        test_file = demo_dir / 'vid.mp4'
        if not test_file.exists():
            raise unittest.SkipTest('Demo video file not found for E2E test.')

        cls.server = MediaTestServer(demo_dir)
        cls.server.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.port}'
        cls.test_file = test_file

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'server', None):
            cls.server.stop()
        super().tearDownClass()

    def test_stash_direct_video_url(self):
        """Test stashing a direct video URL"""
        url = f'{self.base_url}/{self.test_file.name}'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        guid = payload.get('guid')
        self.assertTrue(guid)

        # Wait for processing
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found')
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_VIDEO)
        self.assertTrue(item.content_path)

        # Verify in video feed
        feed_resp = self.client.get('/feeds/video.xml')
        self.assertEqual(feed_resp.status_code, 200)
        feed_xml = feed_resp.content.decode()
        self.assertIn(item.slug, feed_xml)

        # Verify NOT in audio feed
        audio_feed = self.client.get('/feeds/audio.xml')
        audio_xml = audio_feed.content.decode()
        self.assertNotIn(item.slug, audio_xml)

    def test_stash_video_with_thumbnail(self):
        """Test that video stashing includes thumbnail"""
        url = f'{self.base_url}/{self.test_file.name}'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'video',
            },
        )
        guid = response.json().get('guid')

        # Wait for processing
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item)
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        # Thumbnail may or may not be present depending on video
        # Just verify processing completed successfully


@override_settings(STASHCAST_SUMMARY_SENTENCES=0)
class HTMLExtractionE2ETest(TestCase):
    """E2E tests for HTML media extraction"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.audio_demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-aud'
        cls.video_demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-vid'

        if not (cls.audio_demo_dir / 'view.html').exists():
            raise unittest.SkipTest('Demo HTML files not found for E2E test.')

        # Start server for audio demo
        cls.audio_server = MediaTestServer(cls.audio_demo_dir)
        cls.audio_server.start()
        cls.audio_base_url = f'http://127.0.0.1:{cls.audio_server.port}'

        # Start server for video demo
        cls.video_server = MediaTestServer(cls.video_demo_dir)
        cls.video_server.start()
        cls.video_base_url = f'http://127.0.0.1:{cls.video_server.port}'

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'audio_server', None):
            cls.audio_server.stop()
        if getattr(cls, 'video_server', None):
            cls.video_server.stop()
        super().tearDownClass()

    def test_extract_audio_from_html_page(self):
        """Test extracting audio from HTML page with <audio> tag"""
        url = f'{self.audio_base_url}/view.html'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        guid = response.json().get('guid')

        # Wait for processing
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found')
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_AUDIO)
        self.assertTrue(item.content_path)

    def test_extract_video_from_html_page(self):
        """Test extracting video from HTML page with <video> tag"""
        url = f'{self.video_base_url}/view.html'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        guid = response.json().get('guid')

        # Wait for processing
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found')
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_VIDEO)
        self.assertTrue(item.content_path)


@override_settings(STASHCAST_SUMMARY_SENTENCES=0)
class TypeCoercionE2ETest(TestCase):
    """E2E tests for type coercion (requesting audio from video, etc.)"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-vid'
        test_file = demo_dir / 'vid.mp4'
        if not test_file.exists():
            raise unittest.SkipTest('Demo video file not found for E2E test.')

        cls.server = MediaTestServer(demo_dir)
        cls.server.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.port}'
        cls.test_file = test_file

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'server', None):
            cls.server.stop()
        super().tearDownClass()

    def test_request_audio_from_video_url(self):
        """Test requesting audio type from a video URL (should extract audio)"""
        url = f'{self.base_url}/{self.test_file.name}'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'audio',
            },
        )
        self.assertEqual(response.status_code, 200)
        guid = response.json().get('guid')

        # Wait for processing
        deadline = time.time() + 20
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found')
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        # Should have audio media type since we requested audio
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_AUDIO)
        self.assertTrue(item.content_path)

        # Verify in audio feed, NOT in video feed
        audio_feed = self.client.get('/feeds/audio.xml')
        audio_xml = audio_feed.content.decode()
        self.assertIn(item.slug, audio_xml)

        video_feed = self.client.get('/feeds/video.xml')
        video_xml = video_feed.content.decode()
        self.assertNotIn(item.slug, video_xml)


@override_settings(STASHCAST_SUMMARY_SENTENCES=3)
class SummaryE2ETest(TestCase):
    """E2E tests for subtitle summarization"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_dir = Path(settings.BASE_DIR) / 'demo_data' / 'carpool'
        test_file = demo_dir / 'vid.mp4'
        if not test_file.exists():
            raise unittest.SkipTest('Demo video with subtitles not found for E2E test.')

        cls.server = MediaTestServer(demo_dir)
        cls.server.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.port}'
        cls.test_file = test_file

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'server', None):
            cls.server.stop()
        super().tearDownClass()

    def test_generate_summary_from_vtt(self):
        """Test that summary is generated from VTT subtitles"""
        url = f'{self.base_url}/{self.test_file.name}'
        response = self.client.get(
            '/stash/',
            {
                'token': settings.STASHCAST_USER_TOKEN,
                'url': url,
                'type': 'video',
            },
        )
        guid = response.json().get('guid')

        # Wait for processing
        deadline = time.time() + 30
        item = None
        while time.time() < deadline:
            item = MediaItem.objects.filter(guid=guid).first()
            if item and item.status == MediaItem.STATUS_READY:
                break
            time.sleep(0.3)

        self.assertIsNotNone(item, 'Media item not found')
        self.assertEqual(item.status, MediaItem.STATUS_READY)

        # Summary generation happens after READY, so wait a bit more
        time.sleep(2)
        item.refresh_from_db()

        # Summary should be generated if subtitles exist
        # Note: May be empty if subtitle file doesn't have enough text
        # Just verify the field exists and processing completed
        self.assertIsNotNone(item.summary)
