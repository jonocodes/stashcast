import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
            # File has been moved/renamed to content.mp3
            self.assertEqual(item.file_size, (tmp_dir / 'content.mp3').stat().st_size)
            self.assertTrue((tmp_dir / 'thumbnail_temp.jpg').exists())
            self.assertTrue((tmp_dir / 'subtitles_temp.vtt').exists())

    @patch('media.processing.resolve_title_from_metadata', return_value='Real Title')
    def test_process_files_updates_title_and_slug(self, _mock_title):
        """Test that process_files updates title and slug from metadata.

        Note: yt-dlp now handles metadata embedding with --embed-metadata flag,
        so we no longer need to mock add_metadata_without_transcode.
        """
        from pathlib import Path

        from media.processing import process_files

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

    @patch('media.processing.process_thumbnail')
    def test_process_files_converts_webp_thumbnail_to_png(self, mock_process_thumbnail):
        """Test that process_files converts webp thumbnails to PNG.

        This tests the fix for the yt-dlp race condition where --convert-thumbnails
        would fail with FileNotFoundError. Now we convert thumbnails manually after
        download completes using PIL.
        """
        from pathlib import Path

        from media.processing import process_files

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            # Create content file
            content_path = tmp_dir / 'content.mp3'
            content_path.write_bytes(b'audio data')

            # Create a webp thumbnail (simulating what yt-dlp downloads)
            thumb_path = tmp_dir / 'download.webp'
            thumb_path.write_bytes(b'webp thumbnail data')

            # Mock process_thumbnail to simulate successful conversion
            output_png = tmp_dir / 'thumbnail.png'
            mock_process_thumbnail.return_value = output_png

            # Create the output file (simulating what process_thumbnail does)
            output_png.write_bytes(b'png thumbnail data')

            item = MediaItem.objects.create(
                source_url='https://example.com/audio.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                title='Test Audio',
                slug='test-audio',
                content_path='content.mp3',
            )

            process_files(item, tmp_dir, None)

            # Verify process_thumbnail was called with the webp file
            mock_process_thumbnail.assert_called_once()
            call_args = mock_process_thumbnail.call_args
            self.assertEqual(call_args[0][0], thumb_path)  # Input path
            self.assertEqual(call_args[0][1], tmp_dir / 'thumbnail.png')  # Output path

            # Verify item has thumbnail_path set
            item.refresh_from_db()
            self.assertEqual(item.thumbnail_path, 'thumbnail.png')

    def test_process_files_handles_missing_thumbnail(self):
        """Test that process_files handles case where no thumbnail exists."""
        from pathlib import Path

        from media.processing import process_files

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            # Create content file only, no thumbnail
            content_path = tmp_dir / 'content.mp3'
            content_path.write_bytes(b'audio data')

            item = MediaItem.objects.create(
                source_url='https://example.com/audio.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                title='Test Audio',
                slug='test-audio',
                content_path='content.mp3',
            )

            # Should not raise an error
            process_files(item, tmp_dir, None)

            # Verify item has no thumbnail_path (empty string or None)
            item.refresh_from_db()
            self.assertFalse(item.thumbnail_path)

    def test_extract_metadata_updates_title_and_slug(self):
        """Test that extract_metadata_with_ffprobe updates both title and slug.

        This is a regression test for a bug where title was updated from embedded
        metadata but slug was not, causing title/slug mismatch.
        """
        import subprocess
        import tempfile
        from pathlib import Path

        from media.processing import extract_metadata_with_ffprobe

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            audio_file = tmp_dir / 'test.mp3'

            # Create a minimal MP3 with embedded metadata using ffmpeg
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'libmp3lame',
                    '-metadata',
                    'title=Open Source Talk',
                    '-metadata',
                    'artist=Test Artist',
                    '-t',
                    '1',
                    str(audio_file),
                ],
                capture_output=True,
                check=True,
            )

            # Create item with generic filename title/slug
            item = MediaItem.objects.create(
                source_url='http://example.com/aud.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                title='aud',
                slug='aud',
            )

            # Extract metadata - should update both title and slug
            extract_metadata_with_ffprobe(item, audio_file, None)

            item.refresh_from_db()
            self.assertEqual(item.title, 'Open Source Talk')
            self.assertEqual(item.slug, 'open-source-talk')
            self.assertEqual(item.author, 'Test Artist')

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
        self.user_token = settings.STASHCAST_USER_TOKEN
        # Mock the process_media task to prevent actual downloads during tests
        self.process_media_patcher = patch('media.views.process_media')
        self.mock_process_media = self.process_media_patcher.start()

    def tearDown(self):
        self.process_media_patcher.stop()

    def test_stash_missing_user_token(self):
        """Test stash endpoint without user token"""
        response = self.client.get('/stash/', {'url': 'https://example.com/video', 'type': 'auto'})
        self.assertEqual(response.status_code, 403)

    def test_stash_invalid_user_token(self):
        """Test stash endpoint with invalid user token"""
        response = self.client.get(
            '/stash/',
            {'token': 'wrong-token', 'url': 'https://example.com/video', 'type': 'auto'},
        )
        self.assertEqual(response.status_code, 403)

    def test_stash_missing_url(self):
        """Test stash endpoint without URL"""
        response = self.client.get('/stash/', {'token': self.user_token, 'type': 'auto'})
        self.assertEqual(response.status_code, 400)

    def test_stash_invalid_type(self):
        """Test stash endpoint with invalid type"""
        response = self.client.get(
            '/stash/',
            {
                'token': self.user_token,
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
                'token': self.user_token,
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
        response1 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'auto'}
        )
        guid1 = response1.json()['guid']

        # Second request with same URL and same type
        response2 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'auto'}
        )
        guid2 = response2.json()['guid']

        # Should reuse the same GUID for same URL+type
        self.assertEqual(guid1, guid2)
        self.assertEqual(MediaItem.objects.count(), 1)

    def test_stash_same_url_different_types(self):
        """Test stashing the same URL as both audio and video - should create separate items"""
        url = 'https://example.com/content.mp4'  # Use .mp4 to avoid ytdlp prefetch

        # First request - video
        response1 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'video'}
        )
        guid1 = response1.json()['guid']
        item1 = MediaItem.objects.get(guid=guid1)
        item1.media_type = 'video'  # Simulate what would happen after processing
        item1.slug = 'test-content'
        item1.save()

        # Second request - audio from same URL
        response2 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'audio'}
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
        url = 'https://example.com/content.mp4'  # Use .mp4 to avoid ytdlp prefetch

        # First request - auto
        response1 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'auto'}
        )
        guid1 = response1.json()['guid']
        item1 = MediaItem.objects.get(guid=guid1)
        item1.media_type = 'video'  # Simulate auto detection resulting in video
        item1.slug = 'test-content'
        item1.save()

        # Second request - explicit audio
        response2 = self.client.get(
            '/stash/', {'token': self.user_token, 'url': url, 'type': 'audio'}
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
class FeedTranscriptTest(TestCase):
    """Ensure transcripts are included in RSS feeds via podcast:transcript."""

    def setUp(self):
        self.client = Client()

    def test_feed_includes_transcript(self):
        """Test that items with subtitles include podcast:transcript in the feed."""
        MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='video-with-subs',
            title='Video With Subtitles',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp4',
            subtitle_path='subtitles.vtt',
        )

        response = self.client.get('/feeds/video.xml')
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('xmlns:podcast="https://podcastindex.org/namespace/1.0"', xml)
        self.assertIn('<podcast:transcript', xml)
        self.assertIn('type="text/vtt"', xml)
        self.assertIn('language="en"', xml)
        self.assertIn('url="http://testserver/media/files/video-with-subs/subtitles.vtt"', xml)

    def test_feed_no_transcript_when_missing(self):
        """Test that items without subtitles don't include podcast:transcript."""
        MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='video-no-subs',
            title='Video Without Subtitles',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp4',
            subtitle_path='',
        )

        response = self.client.get('/feeds/video.xml')
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<podcast:transcript', xml)


@override_settings(STASHCAST_MEDIA_BASE_URL='')
class FeedAuthenticationTest(TestCase):
    """Test feed user token authentication"""

    def setUp(self):
        self.client = Client()
        self.user_token = settings.STASHCAST_USER_TOKEN
        # Create test items
        MediaItem.objects.create(
            source_url='https://example.com/audio',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=False)
    def test_feeds_public_by_default(self):
        """Test that feeds are accessible without user token when setting is False"""
        response = self.client.get('/feeds/audio.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Audio')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_feeds_require_user_token_when_enabled(self):
        """Test that feeds require user token when setting is True"""
        response = self.client.get('/feeds/audio.xml')
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'User token required', response.content)

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_feeds_work_with_valid_user_token(self):
        """Test that feeds work with valid user token"""
        response = self.client.get(f'/feeds/audio.xml?token={self.user_token}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Audio')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_feeds_reject_invalid_user_token(self):
        """Test that feeds reject invalid user token"""
        response = self.client.get('/feeds/audio.xml?token=invalid-token')
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'User token required', response.content)

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_all_feed_types_require_user_token(self):
        """Test that all feed types require user token when enabled"""
        MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Test Video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )

        # Test all three feed types
        for feed_url in ['/feeds/audio.xml', '/feeds/video.xml', '/feeds/combined.xml']:
            # Without user token - should fail
            response = self.client.get(feed_url)
            self.assertEqual(response.status_code, 403, f'{feed_url} should require user token')

            # With valid user token - should work
            response = self.client.get(f'{feed_url}?token={self.user_token}')
            self.assertEqual(response.status_code, 200, f'{feed_url} should work with valid token')


class FeedProtectionUITest(TestCase):
    """Test visual indicators for feed protection status"""

    def setUp(self):
        self.client = Client()
        # Create a staff user for admin pages
        from django.contrib.auth.models import User

        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.user.is_staff = True
        self.user.save()

    def test_home_page_does_not_expose_feed_urls(self):
        """Test that home page does not show feed URLs with tokens"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Home page should not contain feed URLs or tokens
        self.assertNotIn('/feeds/audio.xml?token=', content)
        self.assertNotIn('/feeds/video.xml?token=', content)
        self.assertNotIn('/feeds/combined.xml?token=', content)
        # Should link to admin feed links page instead
        self.assertIn('/admin/tools/feeds/', content)
        self.assertIn('Subscribe to feeds', content)

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_feed_links_page_shows_protected_banner(self):
        """Test that feed links page shows protected banner when setting is enabled"""
        self.client.login(username='testuser', password='password')
        response = self.client.get('/admin/tools/feeds/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Feed Protection Enabled')
        self.assertContains(response, 'Keep these URLs private')
        self.assertContains(response, '🔒')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=False)
    def test_feed_links_page_shows_public_banner(self):
        """Test that feed links page shows public banner when setting is disabled"""
        self.client.login(username='testuser', password='password')
        response = self.client.get('/admin/tools/feeds/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Feeds')
        self.assertContains(response, 'publicly accessible')
        self.assertContains(response, 'REQUIRE_USER_TOKEN_FOR_FEEDS=true')
        self.assertContains(response, '🌐')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_feed_links_page_includes_token_in_urls(self):
        """Test that feed links page includes user token when protection is enabled"""
        self.client.login(username='testuser', password='password')
        response = self.client.get('/admin/tools/feeds/')
        self.assertEqual(response.status_code, 200)
        # Check that feed URLs contain the token parameter
        self.assertContains(response, f'/feeds/audio.xml?token={settings.STASHCAST_USER_TOKEN}')
        self.assertContains(response, f'/feeds/video.xml?token={settings.STASHCAST_USER_TOKEN}')
        self.assertContains(response, f'/feeds/combined.xml?token={settings.STASHCAST_USER_TOKEN}')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=False)
    def test_feed_links_page_excludes_token_from_urls(self):
        """Test that feed links page excludes token when protection is disabled"""
        self.client.login(username='testuser', password='password')
        response = self.client.get('/admin/tools/feeds/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Feed URLs should not have token when protection is disabled
        self.assertIn('/feeds/audio.xml"', content)
        self.assertIn('/feeds/video.xml"', content)
        self.assertIn('/feeds/combined.xml"', content)
        self.assertNotIn(f'token={settings.STASHCAST_USER_TOKEN}', content)

    def test_feed_links_page_requires_login(self):
        """Test that feed links page requires staff login"""
        response = self.client.get('/admin/tools/feeds/')
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=True)
    def test_bookmarklet_page_shows_protected_banner(self):
        """Test that bookmarklet page shows protected banner when setting is enabled"""
        self.client.login(username='testuser', password='password')

        response = self.client.get('/admin/tools/bookmarklet/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Feed Protection Enabled')
        self.assertContains(response, 'RSS feeds require a user token')
        self.assertContains(response, '🔒')

    @override_settings(REQUIRE_USER_TOKEN_FOR_FEEDS=False)
    def test_bookmarklet_page_shows_public_banner(self):
        """Test that bookmarklet page shows public banner when setting is disabled"""
        self.client.login(username='testuser', password='password')

        response = self.client.get('/admin/tools/bookmarklet/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Feeds Notice')
        self.assertContains(response, 'RSS feeds are currently publicly accessible')
        self.assertContains(response, 'REQUIRE_USER_TOKEN_FOR_FEEDS=true')
        self.assertContains(response, '🌐')


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
        self.assertIn('http://testserver/static/media/feed-audio.png', xml)
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
        self.assertIn('http://testserver/static/media/feed-video.png', xml)
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
        self.assertIn('http://testserver/static/media/feed-combined.png', xml)
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
        mock_document = MagicMock()
        mock_parser.from_string.return_value = SimpleNamespace(document=mock_document)
        # LexRankSummarizer() returns an instance, and calling that instance returns sentences
        mock_summarizer_instance = MagicMock()
        mock_summarizer_instance.return_value = ['First sentence.', 'Second sentence.']
        mock_summarizer.return_value = mock_summarizer_instance

        # Call generate_summary
        generate_summary(item.guid)

        # Refresh from DB
        item.refresh_from_db()

        # Summary should be generated
        self.assertIsNotNone(item.summary)
        self.assertTrue(len(item.summary) > 0)
        self.assertIn('First sentence.', item.summary)


class MetadataEmbeddingTest(TestCase):
    """Tests for metadata embedding without transcoding.

    Note: These functions are still used by transcode_service.py for direct/file downloads
    (non-yt-dlp strategies) where yt-dlp postprocessors don't run.
    """

    def test_add_metadata_embedded_in_file(self):
        """Test that add_metadata_without_transcode embeds metadata in media files"""
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.process import add_metadata_without_transcode

        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create a minimal valid MP4 file
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

    def test_add_metadata_no_quality_loss(self):
        """Test that add_metadata_without_transcode doesn't re-encode the file"""
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


class ResolveTitleFromMetadataTest(TestCase):
    """Tests for resolve_title_from_metadata function"""

    def test_resolve_generic_title(self):
        """Test that generic titles are replaced with embedded metadata"""
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.media_info import resolve_title_from_metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            audio_file = temp_dir / 'test.mp3'

            # Create MP3 with embedded title
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'libmp3lame',
                    '-metadata',
                    'title=Real Title',
                    '-t',
                    '1',
                    str(audio_file),
                ],
                capture_output=True,
                check=True,
            )

            # Test generic titles are replaced
            self.assertEqual(resolve_title_from_metadata('content', audio_file), 'Real Title')
            self.assertEqual(resolve_title_from_metadata('untitled', audio_file), 'Real Title')
            self.assertEqual(
                resolve_title_from_metadata('downloaded-media', audio_file), 'Real Title'
            )
            self.assertEqual(resolve_title_from_metadata(None, audio_file), 'Real Title')

    def test_resolve_filename_like_title(self):
        """Test that filename-like titles are replaced with embedded metadata"""
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.media_info import resolve_title_from_metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            audio_file = temp_dir / 'test.mp3'

            # Create MP3 with embedded title
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'libmp3lame',
                    '-metadata',
                    'title=Open Source Talk',
                    '-t',
                    '1',
                    str(audio_file),
                ],
                capture_output=True,
                check=True,
            )

            # Short filename-like titles (< 30 chars, no spaces) should be replaced
            # when metadata is more descriptive (has spaces or longer)
            self.assertEqual(resolve_title_from_metadata('aud', audio_file), 'Open Source Talk')
            self.assertEqual(resolve_title_from_metadata('vid', audio_file), 'Open Source Talk')
            self.assertEqual(resolve_title_from_metadata('podcast', audio_file), 'Open Source Talk')

    def test_resolve_keeps_descriptive_title(self):
        """Test that descriptive titles are NOT replaced"""
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.media_info import resolve_title_from_metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            audio_file = temp_dir / 'test.mp3'

            # Create MP3 with embedded title
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'libmp3lame',
                    '-metadata',
                    'title=Embedded Title',
                    '-t',
                    '1',
                    str(audio_file),
                ],
                capture_output=True,
                check=True,
            )

            # Long or descriptive titles should NOT be replaced
            descriptive_title = 'My Descriptive Podcast Title'
            self.assertEqual(
                resolve_title_from_metadata(descriptive_title, audio_file), descriptive_title
            )

    def test_resolve_no_metadata_returns_original(self):
        """Test that when there's no metadata, original title is returned"""
        import subprocess
        import tempfile
        from pathlib import Path

        from media.service.media_info import resolve_title_from_metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            audio_file = temp_dir / 'test.mp3'

            # Create MP3 WITHOUT embedded title
            subprocess.run(
                [
                    'ffmpeg',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=duration=1',
                    '-c:a',
                    'libmp3lame',
                    '-t',
                    '1',
                    str(audio_file),
                ],
                capture_output=True,
                check=True,
            )

            # Should return original title when no metadata exists
            self.assertEqual(resolve_title_from_metadata('original', audio_file), 'original')
            self.assertEqual(resolve_title_from_metadata('content', audio_file), 'content')


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
