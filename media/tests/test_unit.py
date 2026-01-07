import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from media.models import MediaItem
from media.service.resolve import PrefetchResult
from media.utils import ensure_unique_slug, generate_slug


class MediaItemModelTest(TestCase):
    def test_create_media_item(self):
        """Test creating a MediaItem"""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='test-video',
        )
        self.assertIsNotNone(item.guid)
        self.assertEqual(item.status, MediaItem.STATUS_PREFETCHING)
        self.assertEqual(item.slug, 'test-video')

    def test_nanoid_generation(self):
        """Test that GUID is generated with NanoID"""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='test',
        )
        # NanoID should be 21 characters
        self.assertEqual(len(item.guid), 21)
        # Should only contain A-Z a-z 0-9
        self.assertTrue(item.guid.isalnum())


class PrefetchProcessingTest(TestCase):
    def _prefetch_result(self):
        result = PrefetchResult()
        result.title = 'Test Title'
        result.description = 'Test description'
        result.author = 'Test Author'
        result.duration_seconds = 42
        result.has_audio_streams = True
        result.has_video_streams = False
        result.extractor = 'unit-test'
        result.external_id = 'abc123'
        return result

    @patch('media.processing.service_prefetch')
    def test_prefetch_file_uses_file_strategy(self, mock_prefetch):
        from media.processing import prefetch_file

        mock_prefetch.return_value = self._prefetch_result()
        item = MediaItem.objects.create(
            source_url='file:///tmp/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending',
        )

        prefetch_file(item, None, None)

        self.assertEqual(mock_prefetch.call_args[0][1], 'file')
        item.refresh_from_db()
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_AUDIO)
        self.assertEqual(item.slug, 'test-title')

    @patch('media.processing.service_prefetch')
    def test_prefetch_direct_uses_direct_strategy(self, mock_prefetch):
        from media.processing import prefetch_direct

        mock_prefetch.return_value = self._prefetch_result()
        item = MediaItem.objects.create(
            source_url='https://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending',
        )

        prefetch_direct(item, None, None)

        self.assertEqual(mock_prefetch.call_args[0][1], 'direct')
        item.refresh_from_db()
        self.assertEqual(item.media_type, MediaItem.MEDIA_TYPE_AUDIO)
        self.assertEqual(item.slug, 'test-title')


class DownloadProcessingTest(TestCase):
    @patch('media.processing.extract_metadata_with_ffprobe')
    @patch('media.processing.service_download_direct')
    def test_download_direct_updates_fields(self, mock_download, mock_extract):
        from pathlib import Path

        from media.processing import download_direct
        from media.service.download import DownloadedFileInfo

        mock_download.return_value = DownloadedFileInfo(
            path=Path('/tmp/content.mp3'),
            file_size=1234,
            extension='.mp3',
            mime_type='audio/mpeg',
        )

        item = MediaItem.objects.create(
            source_url='https://example.com/audio.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            slug='pending',
        )
        tmp_dir = Path('/tmp')

        download_direct(item, tmp_dir, None)

        item.refresh_from_db()
        self.assertEqual(item.content_path, 'content.mp3')
        self.assertEqual(item.file_size, 1234)
        self.assertEqual(item.mime_type, 'audio/mpeg')
        mock_extract.assert_called_once()

    @patch('media.processing.service_download_ytdlp')
    def test_download_ytdlp_updates_fields(self, mock_download):
        from pathlib import Path

        from media.processing import download_ytdlp
        from media.service.download import DownloadedFileInfo

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            content_path = tmp_dir / 'download.mp3'
            thumb_path = tmp_dir / 'thumb.jpg'
            sub_path = tmp_dir / 'subs.vtt'
            content_path.write_bytes(b'data')
            thumb_path.write_bytes(b'thumb')
            sub_path.write_bytes(b'subs')

            mock_download.return_value = DownloadedFileInfo(
                path=content_path,
                file_size=4,  # Size of 'data' bytes
                extension='.mp3',
                thumbnail_path=thumb_path,
                subtitle_path=sub_path,
            )

            item = MediaItem.objects.create(
                source_url='https://example.com/audio',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                slug='pending',
            )

            download_ytdlp(item, tmp_dir, None)

            item.refresh_from_db()
            self.assertEqual(item.content_path, 'content.mp3')
            self.assertEqual(item.file_size, content_path.stat().st_size)
            self.assertTrue((tmp_dir / 'thumbnail_temp.jpg').exists())
            self.assertTrue((tmp_dir / 'subtitles_temp.vtt').exists())

    @patch('media.processing.get_title_from_metadata', return_value='Real Title')
    @patch('media.processing.add_metadata_without_transcode')
    def test_process_files_updates_title_and_slug(self, mock_add_metadata, _mock_title):
        from pathlib import Path

        from media.processing import process_files

        def mock_add_metadata_func(input_path, output_path, metadata=None, logger=None):
            output_path = Path(output_path)
            output_path.write_bytes(b'output data')

        mock_add_metadata.side_effect = mock_add_metadata_func

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            content_path = tmp_dir / 'content.mp3'
            content_path.write_bytes(b'data')

            item = MediaItem.objects.create(
                source_url='https://example.com/audio.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                title='content',
                slug='content',
                content_path='content.mp3',
            )

            process_files(item, tmp_dir, None)

            item.refresh_from_db()
            self.assertEqual(item.title, 'Real Title')
            self.assertEqual(item.slug, 'real-title')

    def test_same_slug_different_media_type_suffixes(self):
        """Test that same slug across media types gets a unique suffix"""
        MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='my-content',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )

        new_slug = ensure_unique_slug(
            'my-content',
            'https://example.com/content',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
        )

        self.assertNotEqual(new_slug, 'my-content')
        self.assertTrue(new_slug.startswith('my-content-'))

    def test_get_base_dir(self):
        """Test get_base_dir for items"""
        item = MediaItem.objects.create(
            source_url='https://example.com/audio',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
        )
        base_dir = item.get_base_dir()
        self.assertIsNotNone(base_dir)
        self.assertTrue(str(base_dir).endswith('media/test-audio'))

    def test_get_base_dir_pending_slug(self):
        """Test get_base_dir returns None for pending slug"""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending',
        )
        base_dir = item.get_base_dir()
        self.assertIsNone(base_dir)

    def test_get_absolute_paths(self):
        """Test absolute path helper methods"""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            content_path='content.mp4',
            thumbnail_path='thumbnail.png',
            subtitle_path='subtitles.vtt',
            log_path='download.log',
        )

        content_path = item.get_absolute_content_path()
        self.assertIsNotNone(content_path)
        self.assertTrue(str(content_path).endswith('test-video/content.mp4'))

        thumbnail_path = item.get_absolute_thumbnail_path()
        self.assertIsNotNone(thumbnail_path)
        self.assertTrue(str(thumbnail_path).endswith('test-video/thumbnail.png'))

        subtitle_path = item.get_absolute_subtitle_path()
        self.assertIsNotNone(subtitle_path)
        self.assertTrue(str(subtitle_path).endswith('test-video/subtitles.vtt'))

        log_path = item.get_absolute_log_path()
        self.assertIsNotNone(log_path)
        self.assertTrue(str(log_path).endswith('test-video/download.log'))


class SlugUtilsTest(TestCase):
    def test_generate_slug_basic(self):
        """Test basic slug generation"""
        slug = generate_slug('This is a Test Title')
        self.assertEqual(slug, 'this-is-a-test-title')

    def test_generate_slug_max_words(self):
        """Test slug truncation by max words"""
        slug = generate_slug('One Two Three Four Five Six Seven Eight', max_words=4)
        self.assertEqual(slug, 'one-two-three-four')

    def test_generate_slug_max_chars(self):
        """Test slug truncation by max characters"""
        slug = generate_slug('This is a very long title that should be truncated', max_chars=20)
        self.assertTrue(len(slug) <= 20)

    def test_generate_slug_special_chars(self):
        """Test slug with special characters"""
        slug = generate_slug('Hello! This & That (2024)')
        self.assertEqual(slug, 'hello-this-that-2024')

    def test_generate_slug_empty_string(self):
        """Test slug generation with empty string"""
        slug = generate_slug('')
        self.assertEqual(slug, 'untitled')

    def test_generate_slug_only_special_chars(self):
        """Test slug with only special characters"""
        slug = generate_slug('!@#$%^&*()')
        self.assertEqual(slug, 'untitled')

    def test_generate_slug_unicode(self):
        """Test slug with unicode characters"""
        slug = generate_slug('Hello 世界 Мир')
        # Non-ASCII characters are stripped, leaving "hello"
        self.assertEqual(slug, 'hello')

    def test_generate_slug_very_long(self):
        """Test slug truncation with very long title"""
        long_title = ' '.join([f'word{i}' for i in range(100)])
        slug = generate_slug(long_title, max_words=6, max_chars=40)
        # Should be truncated
        self.assertTrue(len(slug) <= 40)
        # Should have max 6 words
        self.assertTrue(len(slug.split('-')) <= 6)

    def test_ensure_unique_slug_same_url(self):
        """Test slug reuse for same URL"""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='existing-slug',
        )
        slug = ensure_unique_slug('new-slug', 'https://example.com/video', item)
        self.assertEqual(slug, 'existing-slug')

    def test_ensure_unique_slug_collision(self):
        """Test slug uniqueness with collision"""
        MediaItem.objects.create(
            source_url='https://example.com/video1',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='test-slug',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )
        slug = ensure_unique_slug(
            'test-slug',
            'https://example.com/video2',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )
        # Should have a suffix added
        self.assertTrue(slug.startswith('test-slug-'))
        self.assertNotEqual(slug, 'test-slug')

    def test_ensure_unique_slug_same_url_different_type(self):
        """Test slug generation for same URL but different media type"""
        # Create video item
        MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='my-content',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )

        # Request audio from same URL - should create unique slug
        slug = ensure_unique_slug(
            'my-content',
            'https://example.com/content',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
        )
        self.assertNotEqual(slug, 'my-content')
        self.assertTrue(slug.startswith('my-content-'))

    def test_ensure_unique_slug_same_url_video_after_audio(self):
        """Test slug generation when video is requested after audio"""
        # Create audio item
        MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='my-content',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
        )

        # Request video from same URL - should create unique slug
        slug = ensure_unique_slug(
            'my-content',
            'https://example.com/content',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )
        self.assertNotEqual(slug, 'my-content')
        self.assertTrue(slug.startswith('my-content-'))

    def test_ensure_unique_slug_reuse_same_type(self):
        """Test slug reuse when same URL and type already exists"""
        # Create video item
        item = MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='my-content',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )

        # Request same URL and type - should reuse slug
        slug = ensure_unique_slug(
            'my-content',
            'https://example.com/content',
            existing_item=item,
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
        )
        self.assertEqual(slug, 'my-content')


class StashViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_key = settings.STASHCAST_API_KEY
        # Mock the process_media task to prevent actual downloads during tests
        self.process_media_patcher = patch('media.views.process_media')
        self.mock_process_media = self.process_media_patcher.start()

    def tearDown(self):
        self.process_media_patcher.stop()

    def test_stash_missing_api_key(self):
        """Test stash endpoint without API key"""
        response = self.client.get('/stash/', {'url': 'https://example.com/video', 'type': 'auto'})
        self.assertEqual(response.status_code, 403)

    def test_stash_invalid_api_key(self):
        """Test stash endpoint with invalid API key"""
        response = self.client.get(
            '/stash/',
            {'apikey': 'wrong-key', 'url': 'https://example.com/video', 'type': 'auto'},
        )
        self.assertEqual(response.status_code, 403)

    def test_stash_missing_url(self):
        """Test stash endpoint without URL"""
        response = self.client.get('/stash/', {'apikey': self.api_key, 'type': 'auto'})
        self.assertEqual(response.status_code, 400)

    def test_stash_invalid_type(self):
        """Test stash endpoint with invalid type"""
        response = self.client.get(
            '/stash/',
            {
                'apikey': self.api_key,
                'url': 'https://example.com/video',
                'type': 'invalid',
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_stash_success(self):
        """Test successful stash request"""
        response = self.client.get(
            '/stash/',
            {
                'apikey': self.api_key,
                'url': 'https://example.com/video.mp4',
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('guid', data)

    def test_stash_duplicate_url_same_type(self):
        """Test stashing the same URL twice with same type - should reuse"""
        url = 'https://example.com/video.mp4'

        # First request
        response1 = self.client.get('/stash/', {'apikey': self.api_key, 'url': url, 'type': 'auto'})
        guid1 = response1.json()['guid']

        # Second request with same URL and same type
        response2 = self.client.get('/stash/', {'apikey': self.api_key, 'url': url, 'type': 'auto'})
        guid2 = response2.json()['guid']

        # Should reuse the same GUID for same URL+type
        self.assertEqual(guid1, guid2)
        self.assertEqual(MediaItem.objects.count(), 1)

    def test_stash_same_url_different_types(self):
        """Test stashing the same URL as both audio and video - should create separate items"""
        url = 'https://example.com/content'

        # First request - video
        response1 = self.client.get(
            '/stash/', {'apikey': self.api_key, 'url': url, 'type': 'video'}
        )
        guid1 = response1.json()['guid']
        item1 = MediaItem.objects.get(guid=guid1)
        item1.media_type = 'video'  # Simulate what would happen after processing
        item1.slug = 'test-content'
        item1.save()

        # Second request - audio from same URL
        response2 = self.client.get(
            '/stash/', {'apikey': self.api_key, 'url': url, 'type': 'audio'}
        )
        guid2 = response2.json()['guid']

        # Should create a different GUID for different type
        self.assertNotEqual(guid1, guid2)

        # Should have two separate database entries
        self.assertEqual(MediaItem.objects.count(), 2)

        # Verify both items exist with different types
        item1 = MediaItem.objects.get(guid=guid1)
        item2 = MediaItem.objects.get(guid=guid2)
        self.assertEqual(item1.source_url, url)
        self.assertEqual(item2.source_url, url)
        self.assertEqual(item1.requested_type, 'video')
        self.assertEqual(item2.requested_type, 'audio')

    def test_stash_auto_then_explicit_type(self):
        """Test stashing with auto, then explicitly requesting different type"""
        url = 'https://example.com/content'

        # First request - auto
        response1 = self.client.get('/stash/', {'apikey': self.api_key, 'url': url, 'type': 'auto'})
        guid1 = response1.json()['guid']
        item1 = MediaItem.objects.get(guid=guid1)
        item1.media_type = 'video'  # Simulate auto detection resulting in video
        item1.slug = 'test-content'
        item1.save()

        # Second request - explicit audio
        response2 = self.client.get(
            '/stash/', {'apikey': self.api_key, 'url': url, 'type': 'audio'}
        )
        guid2 = response2.json()['guid']

        # Should create a new item for explicit audio type
        self.assertNotEqual(guid1, guid2)
        self.assertEqual(MediaItem.objects.count(), 2)


class FeedTest(TestCase):
    def test_audio_feed(self):
        """Test audio feed generation"""
        MediaItem.objects.create(
            source_url='https://example.com/audio',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        response = self.client.get('/feeds/audio.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/rss+xml; charset=utf-8')
        self.assertContains(response, 'Test Audio')

    def test_video_feed(self):
        """Test video feed generation"""
        MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Test Video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )
        response = self.client.get('/feeds/video.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/rss+xml; charset=utf-8')
        self.assertContains(response, 'Test Video')

    def test_feeds_separate_media_types(self):
        """Test that audio and video feeds contain only their media types"""
        MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='my-content-audio',
            title='My Content (Audio)',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            content_path='content.m4a',
        )
        MediaItem.objects.create(
            source_url='https://example.com/content',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='my-content-video',
            title='My Content (Video)',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp4',
        )

        # Check audio feed only contains audio item
        audio_response = self.client.get('/feeds/audio.xml')
        self.assertEqual(audio_response.status_code, 200)
        self.assertContains(audio_response, 'My Content (Audio)')
        self.assertNotContains(audio_response, 'My Content (Video)')
        self.assertContains(audio_response, 'my-content-audio/content.m4a')
        self.assertNotContains(audio_response, 'my-content-video/content.mp4')

        # Check video feed only contains video item
        video_response = self.client.get('/feeds/video.xml')
        self.assertEqual(video_response.status_code, 200)
        self.assertContains(video_response, 'My Content (Video)')
        self.assertNotContains(video_response, 'My Content (Audio)')
        self.assertContains(video_response, 'my-content-video/content.mp4')
        self.assertNotContains(video_response, 'my-content-audio/content.m4a')


@override_settings(STASHCAST_MEDIA_BASE_URL='')
class FeedAbsoluteUrlTest(TestCase):
    """Ensure feed channel images and item links are absolute URLs."""

    def setUp(self):
        self.client = Client()

    def test_audio_feed_absolute_urls(self):
        item = MediaItem.objects.create(
            source_url='https://example.com/audio',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='audio-item',
            title='Audio Item',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            content_path='audio.m4a',
            thumbnail_path='thumbnail.jpg',
        )

        response = self.client.get('/feeds/audio.xml')
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('xmlns:media="http://search.yahoo.com/mrss/"', xml)
        self.assertIn('http://testserver/feeds/audio.xml', xml)
        self.assertIn('http://testserver/static/media/feed-logo-audio.png', xml)
        self.assertIn(f'http://testserver/admin/tools/item/{item.guid}/', xml)
        self.assertIn('http://testserver/media/files/audio-item/audio.m4a', xml)
        self.assertIn(
            'media:thumbnail url="http://testserver/media/files/audio-item/thumbnail.jpg"',
            xml,
        )

    def test_video_feed_absolute_urls(self):
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='video-item',
            title='Video Item',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='video.mp4',
            thumbnail_path='thumb.png',
        )

        response = self.client.get('/feeds/video.xml')
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('xmlns:media="http://search.yahoo.com/mrss/"', xml)
        self.assertIn('http://testserver/feeds/video.xml', xml)
        self.assertIn('http://testserver/static/media/feed-logo-video.png', xml)
        self.assertIn(f'http://testserver/admin/tools/item/{item.guid}/', xml)
        self.assertIn('http://testserver/media/files/video-item/video.mp4', xml)
        self.assertIn(
            'media:thumbnail url="http://testserver/media/files/video-item/thumb.png"',
            xml,
        )
        # Check that media:content element exists with correct attributes (order may vary)
        self.assertIn('<media:content', xml)
        self.assertIn('url="http://testserver/media/files/video-item/video.mp4"', xml)
        self.assertIn('type="video/mp4"', xml)
        self.assertIn('medium="video"', xml)

    def test_combined_feed_absolute_urls(self):
        audio_item = MediaItem.objects.create(
            source_url='https://example.com/audio',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='audio-combined',
            title='Audio Combined',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            content_path='track.m4a',
            thumbnail_path='a-thumb.jpg',
        )
        video_item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='video-combined',
            title='Video Combined',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='clip.mp4',
            thumbnail_path='v-thumb.png',
        )

        response = self.client.get('/feeds/combined.xml')
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('http://testserver/feeds/combined.xml', xml)
        self.assertIn('http://testserver/static/media/feed-logo-combined.png', xml)
        self.assertIn(f'http://testserver/admin/tools/item/{audio_item.guid}/', xml)
        self.assertIn(f'http://testserver/admin/tools/item/{video_item.guid}/', xml)
        self.assertIn('http://testserver/media/files/audio-combined/track.m4a', xml)
        self.assertIn('http://testserver/media/files/video-combined/clip.mp4', xml)
        self.assertIn(
            'media:thumbnail url="http://testserver/media/files/audio-combined/a-thumb.jpg"',
            xml,
        )
        self.assertIn(
            'media:thumbnail url="http://testserver/media/files/video-combined/v-thumb.png"',
            xml,
        )
        # Check that media:content element exists with correct attributes (order may vary)
        self.assertIn('<media:content', xml)
        self.assertIn('url="http://testserver/media/files/video-combined/clip.mp4"', xml)
        self.assertIn('type="video/mp4"', xml)
        self.assertIn('medium="video"', xml)


class HTMLMediaExtractorTest(TestCase):
    """Test the HTML media extractor fallback"""

    def test_extract_audio_tag_with_src(self):
        """Test extracting <audio src='...'> tag"""
        from unittest.mock import Mock, patch

        from media.models import MediaItem
        from media.processing import extract_media_from_html

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

        with patch('media.html_extractor.requests.get', return_value=mock_response):
            media_url, media_type, title = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://example.com/media/audio.mp3')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_AUDIO)

    def test_extract_video_tag_with_src(self):
        """Test extracting <video src='...'> tag"""
        from unittest.mock import Mock, patch

        from media.models import MediaItem
        from media.processing import extract_media_from_html

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

        with patch('media.html_extractor.requests.get', return_value=mock_response):
            media_url, media_type, title = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://example.com/media/video.mp4')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_VIDEO)

    def test_extract_source_tag_inside_audio(self):
        """Test extracting <source> tag inside <audio>"""
        from unittest.mock import Mock, patch

        from media.models import MediaItem
        from media.processing import extract_media_from_html

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

        with patch('media.html_extractor.requests.get', return_value=mock_response):
            media_url, media_type, title = extract_media_from_html('https://example.com/page.html')

        self.assertEqual(media_url, 'https://cdn.example.com/audio.mp3')
        self.assertEqual(media_type, MediaItem.MEDIA_TYPE_AUDIO)

    def test_no_media_found(self):
        """Test when no media is found in HTML"""
        from unittest.mock import Mock, patch

        from media.processing import extract_media_from_html

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

        with patch('media.html_extractor.requests.get', return_value=mock_response):
            media_url, media_type, title = extract_media_from_html('https://example.com/page.html')

        self.assertIsNone(media_url)
        self.assertIsNone(media_type)
        self.assertIsNone(title)


class WorkerTimeoutTest(TestCase):
    """Tests for worker timeout detection"""

    def test_worker_timeout_detection(self):
        """Test that items stuck in PREFETCHING for >30s get timeout error"""
        from datetime import timedelta

        from media.tasks import process_media

        # Create item with old timestamp (simulating stuck item)
        old_time = timezone.now() - timedelta(seconds=35)
        item = MediaItem.objects.create(
            source_url='https://example.com/video.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending',
            status=MediaItem.STATUS_PREFETCHING,
        )

        # Force old timestamp by updating with raw SQL to bypass auto_now
        MediaItem.objects.filter(guid=item.guid).update(updated_at=old_time)

        # Refresh to get the updated timestamp
        item.refresh_from_db()

        # Call process_media directly (not as async task)
        # The timeout check happens before any actual processing
        process_media.call_local(item.guid)

        item.refresh_from_db()
        self.assertEqual(item.status, MediaItem.STATUS_ERROR)
        self.assertIn('Worker timeout', item.error_message)
        self.assertIn('run_huey', item.error_message)

    def test_worker_timeout_not_triggered_for_recent_items(self):
        """Test that recently created items don't trigger timeout"""
        from unittest.mock import patch

        from media.tasks import process_media

        # Create item that's been PREFETCHING for only 5 seconds (recent)
        item = MediaItem.objects.create(
            source_url='https://example.com/video.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending',
            status=MediaItem.STATUS_PREFETCHING,
        )

        # Mock the actual processing to prevent real download
        with (
            patch('media.tasks.prefetch_direct') as mock_prefetch,
            patch('media.tasks.prefetch_file') as mock_prefetch_file,
        ):
            # Make it fail quickly so we can test timeout didn't trigger
            mock_prefetch.side_effect = Exception('Test error')
            mock_prefetch_file.side_effect = Exception('Test error')

            try:
                process_media.call_local(item.guid)
            except Exception:
                pass  # Expected to fail

        item.refresh_from_db()
        # Should have error from the mock exception, not timeout
        self.assertEqual(item.status, MediaItem.STATUS_ERROR)
        self.assertNotIn('Worker timeout', item.error_message)
        self.assertIn('Test error', item.error_message)


class SummaryGenerationTest(TestCase):
    """Tests for summary generation settings"""

    @override_settings(STASHCAST_SUMMARY_SENTENCES=0)
    def test_summary_generation_skipped_when_zero(self):
        """Test that summary generation is skipped when STASHCAST_SUMMARY_SENTENCES is 0"""

        from media.models import MediaItem
        from media.tasks import generate_summary

        # Create a test item with subtitles
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='test-video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            subtitle_path='subtitles.vtt',
        )

        # Create a fake subtitle file
        base_dir = item.get_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        subtitle_file = base_dir / 'subtitles.vtt'
        subtitle_file.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest subtitle')

        # Call generate_summary - it should return early without processing
        generate_summary(item.guid)

        # Refresh from DB
        item.refresh_from_db()

        # Summary should still be empty since generation was skipped
        self.assertEqual(item.summary, '')

    @override_settings(STASHCAST_SUMMARY_SENTENCES=3)
    @patch('sumy.nlp.tokenizers.Tokenizer')
    @patch('sumy.parsers.plaintext.PlaintextParser')
    @patch('sumy.summarizers.lex_rank.LexRankSummarizer')
    def test_summary_generation_runs_when_positive(
        self, mock_summarizer, mock_parser, mock_tokenizer
    ):
        """Test that summary generation runs when STASHCAST_SUMMARY_SENTENCES > 0"""

        from media.models import MediaItem
        from media.tasks import generate_summary

        # Create a test item with subtitles
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='test-video-summary',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            subtitle_path='subtitles.vtt',
        )

        # Create a fake subtitle file with enough content
        base_dir = item.get_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        subtitle_file = base_dir / 'subtitles.vtt'
        subtitle_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
This is the first sentence about an important topic.

00:00:05.000 --> 00:00:10.000
Here is another sentence with more details.

00:00:10.000 --> 00:00:15.000
And this is a third sentence to provide context.

00:00:15.000 --> 00:00:20.000
Finally we have a fourth sentence to conclude.
"""
        subtitle_file.write_text(subtitle_content)

        # Mock sumy components to avoid NLTK data dependency
        mock_parser.from_string.return_value = SimpleNamespace(document='doc')
        mock_summarizer.return_value.return_value = ['First half', 'Second half']

        # Call generate_summary
        generate_summary(item.guid)

        # Refresh from DB
        item.refresh_from_db()

        # Summary should be generated
        self.assertIsNotNone(item.summary)
        self.assertTrue(len(item.summary) > 0)


class MetadataEmbeddingTest(TestCase):
    """Tests for metadata embedding without transcoding"""

    def test_metadata_embedded_in_file(self):
        """Test that metadata is embedded in media files"""
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.process import add_metadata_without_transcode

        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create a minimal valid MP4 file (empty but valid structure)
            input_file = temp_dir / 'input.mp4'
            output_file = temp_dir / 'output.mp4'

            # Create a minimal MP4 using ffmpeg
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'aac',
                    '-t',
                    '1',
                    str(input_file),
                ],
                capture_output=True,
                check=True,
            )

            # Add metadata
            metadata = {
                'title': 'Test Title',
                'author': 'Test Author',
                'description': 'Test Description',
            }

            add_metadata_without_transcode(input_file, output_file, metadata=metadata)

            # Verify metadata was embedded using ffprobe
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v',
                    'quiet',
                    '-show_format',
                    '-of',
                    'json',
                    str(output_file),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            probe_data = json.loads(result.stdout)
            tags = probe_data.get('format', {}).get('tags', {})

            # Check metadata is present (ffprobe returns lowercase keys)
            self.assertEqual(tags.get('title'), 'Test Title')
            self.assertEqual(tags.get('artist'), 'Test Author')
            self.assertEqual(tags.get('comment'), 'Test Description')

    def test_metadata_without_transcode_no_quality_loss(self):
        """Test that metadata embedding doesn't re-encode the file"""
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.process import add_metadata_without_transcode

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            input_file = temp_dir / 'input.mp4'
            output_file = temp_dir / 'output.mp4'

            # Create a test file
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'aac',
                    '-t',
                    '1',
                    str(input_file),
                ],
                capture_output=True,
                check=True,
            )

            input_size = input_file.stat().st_size

            # Add metadata
            metadata = {'title': 'Test'}
            add_metadata_without_transcode(input_file, output_file, metadata=metadata)

            output_size = output_file.stat().st_size

            # File sizes should be very similar (within 5% due to metadata overhead)
            size_diff_percent = abs(output_size - input_size) / input_size * 100
            self.assertLess(size_diff_percent, 5)


class SlugPathSecurityTest(TestCase):
    """Tests for path traversal security in slugs"""

    def test_slug_path_traversal_protection(self):
        """Test that slugs with path traversal attempts are sanitized"""
        from media.utils import generate_slug

        # Test various path traversal attempts
        malicious_inputs = [
            '../../../etc/passwd',
            '..\\..\\windows\\system32',
            'test/../../../sensitive',
            'normal-name/../../etc',
        ]

        for malicious in malicious_inputs:
            slug = generate_slug(malicious)
            # Slug should not contain .. or /
            self.assertNotIn('..', slug)
            self.assertNotIn('/', slug)
            self.assertNotIn('\\', slug)

    def test_get_base_dir_no_traversal(self):
        """Test that get_base_dir doesn't allow path traversal"""
        from pathlib import Path

        # Try to create an item with a malicious slug
        item = MediaItem.objects.create(
            source_url='https://example.com/test',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='../../../etc/passwd',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
        )

        base_dir = item.get_base_dir()

        # Verify the path is still within the media directory
        media_dir = Path(settings.STASHCAST_MEDIA_DIR)
        try:
            # This will raise ValueError if base_dir is not relative to media_dir
            base_dir.relative_to(media_dir)
        except ValueError:
            self.fail('get_base_dir allowed path traversal outside media directory')


class DownloadStrategyTest(TestCase):
    """Tests for download strategy selection"""

    def test_direct_url_strategy(self):
        """Test that direct media URLs use direct download strategy"""
        from media.service.strategy import choose_download_strategy

        direct_urls = [
            'https://example.com/video.mp4',
            'https://cdn.example.com/audio.mp3',
            'https://example.com/media/file.m4a',
        ]

        for url in direct_urls:
            strategy = choose_download_strategy(url)
            self.assertEqual(strategy, 'direct')

    def test_ytdlp_strategy_for_hosted_content(self):
        """Test that hosted video platforms use yt-dlp strategy"""
        from media.service.strategy import choose_download_strategy

        ytdlp_urls = [
            'https://youtube.com/watch?v=dQw4w9WgXcQ',
            'https://vimeo.com/123456789',
            'https://example.com/video-page',
        ]

        for url in ytdlp_urls:
            strategy = choose_download_strategy(url)
            self.assertEqual(strategy, 'ytdlp')

    def test_local_file_strategy(self):
        """Test that local file paths use file strategy"""
        import tempfile

        from media.service.strategy import choose_download_strategy

        with tempfile.NamedTemporaryFile(suffix='.mp4') as tmp:
            strategy = choose_download_strategy(tmp.name)
            self.assertEqual(strategy, 'file')

    def test_html_file_uses_ytdlp_strategy(self):
        """Test that local HTML files use yt-dlp strategy for extraction"""
        import tempfile

        from media.service.strategy import choose_download_strategy

        with tempfile.NamedTemporaryFile(suffix='.html') as tmp:
            strategy = choose_download_strategy(tmp.name)
            self.assertEqual(strategy, 'ytdlp')
