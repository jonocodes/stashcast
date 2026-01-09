"""
Tests for service/resolve.py
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from media.service.resolve import (
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

        def logger(msg):
            return logs.append(msg)

        url = 'https://example.com/audio.mp3'
        prefetch(url, 'direct', logger=logger)

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
    def test_prefetch_ytdlp_playlist_returns_multiple(self, mock_ytdlp_class):
        """Test that playlists return is_multiple=True with entries"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            'title': 'Test Playlist',
            'entries': [
                {'title': 'Video 1', 'webpage_url': 'https://youtube.com/watch?v=abc1'},
                {'title': 'Video 2', 'webpage_url': 'https://youtube.com/watch?v=abc2'},
            ],
        }

        url = 'https://youtube.com/playlist?list=abc123'

        result = prefetch(url, 'ytdlp')
        self.assertTrue(result.is_multiple)
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.entries[0].title, 'Video 1')
        self.assertEqual(result.entries[1].title, 'Video 2')
        self.assertEqual(result.playlist_title, 'Test Playlist')

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
