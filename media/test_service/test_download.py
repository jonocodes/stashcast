"""
Tests for service/download.py
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from media.service.download import download_direct, download_ytdlp, DownloadedFileInfo


class DownloadServiceTest(TestCase):
    """Tests for download service"""

    def test_downloaded_file_info_dataclass(self):
        """Test DownloadedFileInfo dataclass"""
        info = DownloadedFileInfo(path=Path('/tmp/test.mp3'), file_size=1024, extension='.mp3')
        self.assertEqual(info.path, Path('/tmp/test.mp3'))
        self.assertEqual(info.file_size, 1024)
        self.assertEqual(info.extension, '.mp3')
        self.assertIsNone(info.mime_type)

    @patch('media.service.download.requests.get')
    def test_download_direct_success(self, mock_get):
        """Test successful direct download"""
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.headers = {'content-type': 'audio/mpeg'}
        mock_response.iter_content.return_value = [b'test', b'data']
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / 'test.mp3'
            result = download_direct('https://example.com/audio.mp3', out_path)

            self.assertEqual(result.path, out_path)
            self.assertTrue(out_path.exists())
            self.assertEqual(result.extension, '.mp3')
            self.assertEqual(result.mime_type, 'audio/mpeg')

    @patch('media.service.download.requests.get')
    def test_download_direct_creates_directory(self, mock_get):
        """Test that download_direct creates parent directory"""
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.iter_content.return_value = [b'data']
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / 'subdir' / 'nested' / 'test.mp3'
            download_direct('https://example.com/audio.mp3', out_path)

            self.assertTrue(out_path.exists())
            self.assertTrue(out_path.parent.exists())

    @patch('media.service.download.requests.get')
    def test_download_direct_with_logger(self, mock_get):
        """Test direct download with logger callback"""
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.iter_content.return_value = [b'data']
        mock_get.return_value = mock_response

        logs = []

        def logger(msg):
            return logs.append(msg)

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / 'test.mp3'
            download_direct('https://example.com/audio.mp3', out_path, logger=logger)

            self.assertTrue(len(logs) > 0)
            self.assertTrue(any('Downloading' in log for log in logs))

    @patch('media.service.download.requests.get')
    def test_download_direct_raises_on_http_error(self, mock_get):
        """Test that HTTP errors are raised"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception('404 Not Found')
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / 'test.mp3'
            with self.assertRaises(Exception):
                download_direct('https://example.com/notfound.mp3', out_path)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_audio(self, mock_ytdlp_class):
        """Test yt-dlp download for audio"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create fake downloaded file
            downloaded_file = temp_dir / 'download.m4a'
            downloaded_file.write_bytes(b'fake audio data')

            result = download_ytdlp('https://youtube.com/watch?v=abc123', 'audio', temp_dir)

            # Verify yt-dlp was called
            mock_ydl.download.assert_called_once()

            # Verify result
            self.assertEqual(result.extension, '.m4a')
            self.assertTrue(result.file_size > 0)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_video(self, mock_ytdlp_class):
        """Test yt-dlp download for video"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create fake downloaded file
            downloaded_file = temp_dir / 'download.mp4'
            downloaded_file.write_bytes(b'fake video data')

            result = download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            self.assertEqual(result.extension, '.mp4')

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_with_thumbnail(self, mock_ytdlp_class):
        """Test yt-dlp download with thumbnail"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create fake files
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')

            thumb_file = temp_dir / 'download.jpg'
            thumb_file.write_bytes(b'thumbnail')

            result = download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            self.assertIsNotNone(result.thumbnail_path)
            self.assertTrue(result.thumbnail_path.exists())

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_with_subtitles(self, mock_ytdlp_class):
        """Test yt-dlp download with subtitles"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create fake files
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')

            subtitle_file = temp_dir / 'download.en.vtt'
            subtitle_file.write_bytes(b'WEBVTT')

            result = download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            self.assertIsNotNone(result.subtitle_path)
            self.assertTrue(result.subtitle_path.exists())

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_selects_largest_file(self, mock_ytdlp_class):
        """Test that yt-dlp selects the largest content file"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create multiple files with different sizes
            small_file = temp_dir / 'download.f137.mp4'
            small_file.write_bytes(b'small')

            large_file = temp_dir / 'download.mp4'
            large_file.write_bytes(b'large file content')

            result = download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            # Should select the larger file
            self.assertEqual(result.file_size, large_file.stat().st_size)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_with_logger(self, mock_ytdlp_class):
        """Test yt-dlp download with logger"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        logs = []

        def logger(msg):
            return logs.append(msg)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')

            download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir, logger=logger)

            self.assertTrue(len(logs) > 0)
            self.assertTrue(any('Downloading' in log for log in logs))

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_no_media_file_raises(self, mock_ytdlp_class):
        """Test that missing media file raises exception"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Don't create any media files

            with self.assertRaises(Exception) as ctx:
                download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            self.assertIn('No media file found', str(ctx.exception))

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_format_spec_audio(self, mock_ytdlp_class):
        """Test that correct format spec is used for audio"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            content_file = temp_dir / 'download.m4a'
            content_file.write_bytes(b'audio')

            download_ytdlp('https://youtube.com/watch?v=abc123', 'audio', temp_dir)

            # Check that yt-dlp was called with correct options
            call_args = mock_ytdlp_class.call_args[0][0]
            self.assertIn('format', call_args)
            self.assertEqual(call_args['format'], 'bestaudio/best')

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_ytdlp_format_spec_video(self, mock_ytdlp_class):
        """Test that correct format spec is used for video"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')

            download_ytdlp('https://youtube.com/watch?v=abc123', 'video', temp_dir)

            # Check format spec
            call_args = mock_ytdlp_class.call_args[0][0]
            self.assertIn('mp4', call_args['format'])
