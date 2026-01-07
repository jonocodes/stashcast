"""
Tests for service/resolve.py
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from media.service.resolve import (
    PlaylistNotSupported,
    PrefetchResult,
    prefetch,
    resolve_media_type,
)


class ResolveServiceTest(TestCase):
    """Tests for metadata extraction and type resolution"""

    def test_prefetch_result_dataclass(self):
        """Test PrefetchResult dataclass creation"""
        result = PrefetchResult()
        self.assertIsNone(result.title)
        self.assertIsNone(result.description)
        self.assertFalse(result.has_video_streams)
        self.assertFalse(result.has_audio_streams)

    def test_prefetch_direct_mp3(self):
        """Test prefetch for direct MP3 URL"""
        url = 'https://example.com/audio.mp3'
        result = prefetch(url, 'direct')

        self.assertEqual(result.title, 'audio')
        self.assertEqual(result.file_extension, '.mp3')
        self.assertTrue(result.has_audio_streams)
        self.assertFalse(result.has_video_streams)

    def test_prefetch_direct_mp4(self):
        """Test prefetch for direct MP4 URL"""
        url = 'https://example.com/video.mp4'
        result = prefetch(url, 'direct')

        self.assertEqual(result.title, 'video')
        self.assertEqual(result.file_extension, '.mp4')
        self.assertTrue(result.has_video_streams)
        self.assertTrue(result.has_audio_streams)  # Videos usually have audio

    def test_prefetch_direct_complex_path(self):
        """Test prefetch with complex URL path"""
        url = 'https://cdn.example.com/media/2024/01/my-audio-file.mp3'
        result = prefetch(url, 'direct')

        self.assertEqual(result.title, 'my-audio-file')
        self.assertEqual(result.file_extension, '.mp3')

    def test_prefetch_direct_m4a(self):
        """Test prefetch for M4A file"""
        url = 'https://example.com/audio.m4a'
        result = prefetch(url, 'direct')

        self.assertTrue(result.has_audio_streams)
        self.assertFalse(result.has_video_streams)

    def test_prefetch_direct_webm(self):
        """Test prefetch for WebM file (video)"""
        url = 'https://example.com/video.webm'
        result = prefetch(url, 'direct')

        self.assertTrue(result.has_video_streams)

    def test_prefetch_direct_ogg(self):
        """Test prefetch for OGG file (audio)"""
        url = 'https://example.com/audio.ogg'
        result = prefetch(url, 'direct')

        self.assertTrue(result.has_audio_streams)
        self.assertFalse(result.has_video_streams)

    def test_prefetch_direct_with_logger(self):
        """Test prefetch with logger callback"""
        logs = []
        logger = lambda msg: logs.append(msg)

        url = 'https://example.com/audio.mp3'
        result = prefetch(url, 'direct', logger=logger)

        self.assertTrue(len(logs) > 0)
        self.assertTrue(any('Direct URL' in log for log in logs))

    @patch('media.service.resolve.yt_dlp.YoutubeDL')
    def test_prefetch_ytdlp_success(self, mock_ytdlp_class):
        """Test successful yt-dlp metadata extraction"""
        # Mock the yt-dlp info extraction
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            'title': 'Test Video',
            'description': 'Test description',
            'uploader': 'Test Channel',
            'duration': 120,
            'extractor': 'youtube',
            'id': 'abc123',
            'webpage_url': 'https://youtube.com/watch?v=abc123',
            'formats': [
                {'vcodec': 'h264', 'acodec': 'aac'},
                {'vcodec': 'none', 'acodec': 'opus'},
            ],
        }

        url = 'https://youtube.com/watch?v=abc123'
        result = prefetch(url, 'ytdlp')

        self.assertEqual(result.title, 'Test Video')
        self.assertEqual(result.description, 'Test description')
        self.assertEqual(result.author, 'Test Channel')
        self.assertEqual(result.duration_seconds, 120)
        self.assertEqual(result.extractor, 'youtube')
        self.assertTrue(result.has_video_streams)
        self.assertTrue(result.has_audio_streams)

    @patch('media.service.resolve.yt_dlp.YoutubeDL')
    def test_prefetch_ytdlp_audio_only(self, mock_ytdlp_class):
        """Test yt-dlp extraction for audio-only content"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            'title': 'Test Audio',
            'formats': [
                {'vcodec': 'none', 'acodec': 'opus'},
            ],
        }

        url = 'https://example.com/audio'
        result = prefetch(url, 'ytdlp')

        self.assertFalse(result.has_video_streams)
        self.assertTrue(result.has_audio_streams)

    @patch('media.service.resolve.yt_dlp.YoutubeDL')
    def test_prefetch_ytdlp_playlist_error(self, mock_ytdlp_class):
        """Test that playlists raise PlaylistNotSupported"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            'entries': [
                {'title': 'Video 1'},
                {'title': 'Video 2'},
            ]
        }

        url = 'https://youtube.com/playlist?list=abc123'

        with self.assertRaises(PlaylistNotSupported):
            prefetch(url, 'ytdlp')

    def test_prefetch_ytdlp_fallback_to_html(self):
        """Test HTML extraction fallback when yt-dlp fails"""
        # Make yt-dlp fail with DownloadError
        import yt_dlp

        # Use context managers to ensure proper cleanup
        with (
            patch('bs4.BeautifulSoup') as mock_bs,
            patch('media.service.resolve.yt_dlp.YoutubeDL') as mock_ytdlp_class,
            patch('media.service.resolve.requests.get') as mock_requests,
        ):
            mock_ydl = MagicMock()
            mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl
            mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError('yt-dlp failed')

            # Mock HTML response with video tag
            mock_response = MagicMock()
            mock_response.text = '<html><video src="video.mp4"></video></html>'
            mock_response.raise_for_status = MagicMock()
            mock_requests.return_value = mock_response

            mock_soup = MagicMock()

            # Mock find to return video tag when called with 'video'
            def find_side_effect(tag, **kwargs):
                if tag == 'video':
                    return {'src': 'video.mp4'}
                return None

            mock_soup.find.side_effect = find_side_effect
            mock_bs.return_value = mock_soup

            url = 'https://example.com/page.html'
            result = prefetch(url, 'ytdlp')

            self.assertTrue(result.has_video_streams)
            self.assertEqual(result.webpage_url, url)

    def test_resolve_media_type_explicit_audio(self):
        """Test explicit audio type request"""
        result = PrefetchResult()
        result.has_video_streams = True
        result.has_audio_streams = True

        media_type = resolve_media_type('audio', result)
        self.assertEqual(media_type, 'audio')

    def test_resolve_media_type_explicit_video(self):
        """Test explicit video type request"""
        result = PrefetchResult()
        result.has_video_streams = False
        result.has_audio_streams = True

        media_type = resolve_media_type('video', result)
        self.assertEqual(media_type, 'video')

    def test_resolve_media_type_auto_video(self):
        """Test auto detection chooses video when available"""
        result = PrefetchResult()
        result.has_video_streams = True
        result.has_audio_streams = True

        media_type = resolve_media_type('auto', result)
        self.assertEqual(media_type, 'video')

    def test_resolve_media_type_auto_audio_only(self):
        """Test auto detection chooses audio when no video"""
        result = PrefetchResult()
        result.has_video_streams = False
        result.has_audio_streams = True

        media_type = resolve_media_type('auto', result)
        self.assertEqual(media_type, 'audio')

    def test_resolve_media_type_auto_default_video(self):
        """Test auto detection defaults to video when ambiguous"""
        result = PrefetchResult()
        result.has_video_streams = False
        result.has_audio_streams = False

        media_type = resolve_media_type('auto', result)
        self.assertEqual(media_type, 'video')

    def test_resolve_media_type_invalid_defaults_to_video(self):
        """Test invalid type defaults to video with video streams"""
        result = PrefetchResult()
        result.has_video_streams = True

        media_type = resolve_media_type('invalid', result)
        self.assertEqual(media_type, 'video')

    def test_resolve_media_type_invalid_defaults_to_audio(self):
        """Test invalid type defaults to audio without video streams"""
        result = PrefetchResult()
        result.has_video_streams = False
        result.has_audio_streams = True

        media_type = resolve_media_type('invalid', result)
        self.assertEqual(media_type, 'audio')

    def test_prefetch_invalid_strategy(self):
        """Test that invalid strategy raises ValueError"""
        with self.assertRaises(ValueError):
            prefetch('https://example.com', 'invalid_strategy')
