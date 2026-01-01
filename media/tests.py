from django.test import TestCase, Client
from django.conf import settings
from media.models import MediaItem
from media.utils import generate_slug, ensure_unique_slug


class MediaItemModelTest(TestCase):
    def test_create_media_item(self):
        """Test creating a MediaItem"""
        item = MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug="test-video"
        )
        self.assertIsNotNone(item.guid)
        self.assertEqual(item.status, MediaItem.STATUS_PREFETCHING)
        self.assertEqual(item.slug, "test-video")

    def test_nanoid_generation(self):
        """Test that GUID is generated with NanoID"""
        item = MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug="test"
        )
        # NanoID should be 21 characters
        self.assertEqual(len(item.guid), 21)
        # Should only contain A-Z a-z 0-9
        self.assertTrue(item.guid.isalnum())


class SlugUtilsTest(TestCase):
    def test_generate_slug_basic(self):
        """Test basic slug generation"""
        slug = generate_slug("This is a Test Title")
        self.assertEqual(slug, "this-is-a-test-title")

    def test_generate_slug_max_words(self):
        """Test slug truncation by max words"""
        slug = generate_slug("One Two Three Four Five Six Seven Eight", max_words=4)
        self.assertEqual(slug, "one-two-three-four")

    def test_generate_slug_max_chars(self):
        """Test slug truncation by max characters"""
        slug = generate_slug("This is a very long title that should be truncated", max_chars=20)
        self.assertTrue(len(slug) <= 20)

    def test_generate_slug_special_chars(self):
        """Test slug with special characters"""
        slug = generate_slug("Hello! This & That (2024)")
        self.assertEqual(slug, "hello-this-that-2024")

    def test_ensure_unique_slug_new(self):
        """Test unique slug for new item"""
        slug = ensure_unique_slug("test-slug", "https://example.com/1")
        self.assertEqual(slug, "test-slug")

    def test_ensure_unique_slug_same_url(self):
        """Test slug reuse for same URL"""
        item = MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug="existing-slug"
        )
        slug = ensure_unique_slug("new-slug", "https://example.com/video", item)
        self.assertEqual(slug, "existing-slug")

    def test_ensure_unique_slug_collision(self):
        """Test slug uniqueness with collision"""
        MediaItem.objects.create(
            source_url="https://example.com/video1",
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug="test-slug"
        )
        slug = ensure_unique_slug("test-slug", "https://example.com/video2")
        # Should have a suffix added
        self.assertTrue(slug.startswith("test-slug-"))
        self.assertNotEqual(slug, "test-slug")


class StashViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_key = settings.STASHCAST_API_KEY

    def test_stash_missing_api_key(self):
        """Test stash endpoint without API key"""
        response = self.client.get('/stash/', {
            'url': 'https://example.com/video',
            'type': 'auto'
        })
        self.assertEqual(response.status_code, 403)

    def test_stash_invalid_api_key(self):
        """Test stash endpoint with invalid API key"""
        response = self.client.get('/stash/', {
            'apikey': 'wrong-key',
            'url': 'https://example.com/video',
            'type': 'auto'
        })
        self.assertEqual(response.status_code, 403)

    def test_stash_missing_url(self):
        """Test stash endpoint without URL"""
        response = self.client.get('/stash/', {
            'apikey': self.api_key,
            'type': 'auto'
        })
        self.assertEqual(response.status_code, 400)

    def test_stash_invalid_type(self):
        """Test stash endpoint with invalid type"""
        response = self.client.get('/stash/', {
            'apikey': self.api_key,
            'url': 'https://example.com/video',
            'type': 'invalid'
        })
        self.assertEqual(response.status_code, 400)

    def test_stash_success(self):
        """Test successful stash request"""
        response = self.client.get('/stash/', {
            'apikey': self.api_key,
            'url': 'https://example.com/video.mp4',
            'type': 'auto'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('guid', data)

    def test_stash_duplicate_url(self):
        """Test stashing the same URL twice"""
        url = 'https://example.com/video.mp4'

        # First request
        response1 = self.client.get('/stash/', {
            'apikey': self.api_key,
            'url': url,
            'type': 'auto'
        })
        guid1 = response1.json()['guid']

        # Second request with same URL
        response2 = self.client.get('/stash/', {
            'apikey': self.api_key,
            'url': url,
            'type': 'video'
        })
        guid2 = response2.json()['guid']

        # Should reuse the same GUID
        self.assertEqual(guid1, guid2)


class ItemDetailViewTest(TestCase):
    def test_item_detail_not_found(self):
        """Test item detail page for non-existent item"""
        response = self.client.get('/items/nonexistent/')
        self.assertEqual(response.status_code, 404)

    def test_item_detail_exists(self):
        """Test item detail page for existing item"""
        item = MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug="test-video",
            title="Test Video",
            status=MediaItem.STATUS_READY
        )
        response = self.client.get(f'/items/{item.guid}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Video")


class FeedTest(TestCase):
    def test_audio_feed(self):
        """Test audio feed generation"""
        MediaItem.objects.create(
            source_url="https://example.com/audio",
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug="test-audio",
            title="Test Audio",
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY
        )
        response = self.client.get('/feeds/audio.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/rss+xml; charset=utf-8')
        self.assertContains(response, "Test Audio")

    def test_video_feed(self):
        """Test video feed generation"""
        MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug="test-video",
            title="Test Video",
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY
        )
        response = self.client.get('/feeds/video.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/rss+xml; charset=utf-8')
        self.assertContains(response, "Test Video")


class FeedViewXMLTest(TestCase):
    """Test the XML viewing endpoints for feeds"""

    def setUp(self):
        """Create test items"""
        self.client = Client()

    def test_audio_feed_view_xml(self):
        """Test that audio-view.xml returns XML with correct content type"""
        # Create a ready audio item
        MediaItem.objects.create(
            source_url="https://example.com/audio",
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug="test-audio",
            title="Test Audio",
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY
        )

        response = self.client.get('/feeds/audio-view.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/xml; charset=utf-8')
        self.assertContains(response, 'Test Audio')
        self.assertContains(response, '<?xml')

    def test_video_feed_view_xml(self):
        """Test that video-view.xml returns XML with correct content type"""
        # Create a ready video item
        MediaItem.objects.create(
            source_url="https://example.com/video",
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug="test-video",
            title="Test Video",
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY
        )

        response = self.client.get('/feeds/video-view.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/xml; charset=utf-8')
        self.assertContains(response, 'Test Video')
        self.assertContains(response, '<?xml')


class HTMLMediaExtractorTest(TestCase):
    """Test the HTML media extractor fallback"""

    def test_extract_audio_tag_with_src(self):
        """Test extracting <audio src='...'> tag"""
        from media.tasks import extract_media_from_html
        from unittest.mock import patch, Mock
        from media.models import MediaItem

        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <audio src="/media/audio.mp3" controls></audio>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()

        with patch('media.tasks.requests.get', return_value=mock_response):
            media_url, media_type = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://example.com/media/audio.mp3')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_AUDIO)

    def test_extract_video_tag_with_src(self):
        """Test extracting <video src='...'> tag"""
        from media.tasks import extract_media_from_html
        from unittest.mock import patch, Mock
        from media.models import MediaItem

        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <video src="/media/video.mp4" controls></video>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()

        with patch('media.tasks.requests.get', return_value=mock_response):
            media_url, media_type = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://example.com/media/video.mp4')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_VIDEO)

    def test_extract_source_tag_inside_audio(self):
        """Test extracting <source> tag inside <audio>"""
        from media.tasks import extract_media_from_html
        from unittest.mock import patch, Mock
        from media.models import MediaItem

        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <audio controls>
                <source src="https://cdn.example.com/audio.mp3" type="audio/mpeg">
            </audio>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()

        with patch('media.tasks.requests.get', return_value=mock_response):
            media_url, media_type = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://cdn.example.com/audio.mp3')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_AUDIO)

    def test_no_media_found(self):
        """Test when no media is found in HTML"""
        from media.tasks import extract_media_from_html
        from unittest.mock import patch, Mock

        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <p>Just some text, no media here</p>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()

        with patch('media.tasks.requests.get', return_value=mock_response):
            media_url, media_type = extract_media_from_html('https://example.com/page.html')

        self.assertIsNone(media_url)
        self.assertIsNone(media_type)
