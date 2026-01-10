"""
Tests for service/download.py
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from media.service.download import (
    download_direct,
    download_ytdlp,
    DownloadedFileInfo,
    prefetch_ytdlp_batch,
    download_ytdlp_batch,
    VideoInfo,
    BatchPrefetchResult,
    BatchDownloadResult,
)


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


class BatchPrefetchTest(TestCase):
    """Tests for batch prefetch functionality"""

    def test_video_info_dataclass(self):
        """Test VideoInfo dataclass"""
        info = VideoInfo(
            url='https://youtube.com/watch?v=abc',
            title='Test Video',
            source_url='https://youtube.com/watch?v=abc',
        )
        self.assertEqual(info.url, 'https://youtube.com/watch?v=abc')
        self.assertEqual(info.title, 'Test Video')
        self.assertIsNone(info.playlist_title)

    def test_batch_prefetch_result_dataclass(self):
        """Test BatchPrefetchResult dataclass"""
        result = BatchPrefetchResult(videos=[], errors={})
        self.assertEqual(result.videos, [])
        self.assertEqual(result.errors, {})

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_prefetch_single_video(self, mock_ytdlp_class):
        """Test prefetching a single video URL"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        # Mock extract_info for single video
        mock_ydl.extract_info.return_value = {
            'title': 'Test Video',
            'description': 'A test video',
            'uploader': 'Test Channel',
            'duration': 120,
            'webpage_url': 'https://youtube.com/watch?v=abc123',
            'extractor': 'youtube',
            'id': 'abc123',
            'formats': [{'vcodec': 'avc1', 'acodec': 'mp4a'}],
        }

        result = prefetch_ytdlp_batch(['https://youtube.com/watch?v=abc123'])

        self.assertEqual(len(result.videos), 1)
        self.assertEqual(result.videos[0].title, 'Test Video')
        self.assertEqual(result.videos[0].author, 'Test Channel')
        self.assertEqual(result.videos[0].duration_seconds, 120)
        self.assertIsNone(result.videos[0].playlist_title)
        self.assertEqual(len(result.errors), 0)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_prefetch_playlist_expands(self, mock_ytdlp_class):
        """Test that playlists are expanded to individual videos"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        # Mock extract_info for playlist
        mock_ydl.extract_info.return_value = {
            'title': 'My Playlist',
            'entries': [
                {
                    'title': 'Video 1',
                    'webpage_url': 'https://youtube.com/watch?v=vid1',
                    'id': 'vid1',
                    'duration': 60,
                    'formats': [{'vcodec': 'avc1', 'acodec': 'mp4a'}],
                },
                {
                    'title': 'Video 2',
                    'webpage_url': 'https://youtube.com/watch?v=vid2',
                    'id': 'vid2',
                    'duration': 90,
                    'formats': [{'vcodec': 'avc1', 'acodec': 'mp4a'}],
                },
                {
                    'title': 'Video 3',
                    'webpage_url': 'https://youtube.com/watch?v=vid3',
                    'id': 'vid3',
                    'duration': 120,
                    'formats': [{'vcodec': 'avc1', 'acodec': 'mp4a'}],
                },
            ],
        }

        result = prefetch_ytdlp_batch(['https://youtube.com/playlist?list=PL123'])

        self.assertEqual(len(result.videos), 3)
        self.assertEqual(result.videos[0].title, 'Video 1')
        self.assertEqual(result.videos[1].title, 'Video 2')
        self.assertEqual(result.videos[2].title, 'Video 3')
        # All videos should reference the playlist
        for video in result.videos:
            self.assertEqual(video.playlist_title, 'My Playlist')
            self.assertEqual(video.source_url, 'https://youtube.com/playlist?list=PL123')

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_prefetch_mixed_urls(self, mock_ytdlp_class):
        """Test prefetching mixed single videos and playlists"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        # Return different results based on URL
        def mock_extract(url, download=False):
            if 'playlist' in url:
                return {
                    'title': 'My Playlist',
                    'entries': [
                        {
                            'title': 'PL Video 1',
                            'webpage_url': 'https://youtube.com/watch?v=pl1',
                            'id': 'pl1',
                            'formats': [],
                        },
                        {
                            'title': 'PL Video 2',
                            'webpage_url': 'https://youtube.com/watch?v=pl2',
                            'id': 'pl2',
                            'formats': [],
                        },
                    ],
                }
            else:
                return {
                    'title': 'Single Video',
                    'webpage_url': url,
                    'id': 'single1',
                    'formats': [{'vcodec': 'avc1', 'acodec': 'mp4a'}],
                }

        mock_ydl.extract_info.side_effect = mock_extract

        result = prefetch_ytdlp_batch(
            [
                'https://youtube.com/watch?v=single',
                'https://youtube.com/playlist?list=PL123',
            ]
        )

        # Should have 3 videos total (1 single + 2 from playlist)
        self.assertEqual(len(result.videos), 3)
        # First should be single video
        self.assertEqual(result.videos[0].title, 'Single Video')
        self.assertIsNone(result.videos[0].playlist_title)
        # Rest from playlist
        self.assertEqual(result.videos[1].playlist_title, 'My Playlist')
        self.assertEqual(result.videos[2].playlist_title, 'My Playlist')

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_prefetch_handles_errors(self, mock_ytdlp_class):
        """Test that prefetch errors are captured per-URL"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        def mock_extract(url, download=False):
            if 'bad' in url:
                raise Exception('Video unavailable')
            return {
                'title': 'Good Video',
                'webpage_url': url,
                'id': 'good1',
                'formats': [],
            }

        mock_ydl.extract_info.side_effect = mock_extract

        result = prefetch_ytdlp_batch(
            [
                'https://youtube.com/watch?v=good',
                'https://youtube.com/watch?v=bad',
            ]
        )

        self.assertEqual(len(result.videos), 1)
        self.assertEqual(result.videos[0].title, 'Good Video')
        self.assertEqual(len(result.errors), 1)
        self.assertIn('bad', list(result.errors.keys())[0])


class BatchDownloadTest(TestCase):
    """Tests for batch download functionality"""

    def test_batch_download_result_dataclass(self):
        """Test BatchDownloadResult dataclass"""
        result = BatchDownloadResult(downloads={}, errors={})
        self.assertEqual(result.downloads, {})
        self.assertEqual(result.errors, {})

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_batch_single_call(self, mock_ytdlp_class):
        """Test that batch download uses single ydl.download() call"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        urls = [
            'https://youtube.com/watch?v=vid1',
            'https://youtube.com/watch?v=vid2',
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Simulate progress hook capturing URL->ID mapping
            def capture_hook(hooks):
                for url, vid_id in [
                    ('https://youtube.com/watch?v=vid1', 'vid1'),
                    ('https://youtube.com/watch?v=vid2', 'vid2'),
                ]:
                    for hook in hooks:
                        hook(
                            {'status': 'finished', 'info_dict': {'id': vid_id, 'webpage_url': url}}
                        )

            def mock_download(url_list):
                # Create output folders and files
                for vid_id in ['vid1', 'vid2']:
                    folder = temp_dir / vid_id
                    folder.mkdir(exist_ok=True)
                    (folder / 'download.mp4').write_bytes(b'video content')
                # Trigger progress hooks
                capture_hook(mock_ydl.params.get('progress_hooks', []))

            mock_ydl.download.side_effect = mock_download
            mock_ydl.params = {}

            # Capture the options to check progress_hooks
            def capture_opts(opts):
                mock_ydl.params = opts
                return mock_ydl

            mock_ytdlp_class.return_value.__enter__.side_effect = lambda: capture_opts(
                mock_ytdlp_class.call_args[0][0] if mock_ytdlp_class.call_args else {}
            )

            download_ytdlp_batch(urls, 'video', temp_dir)

            # Verify download was called once with all URLs
            mock_ydl.download.assert_called_once_with(urls)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_batch_creates_separate_folders(self, mock_ytdlp_class):
        """Test that each video gets its own folder by ID"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create folders as yt-dlp would
            (temp_dir / 'abc123').mkdir()
            (temp_dir / 'abc123' / 'download.mp4').write_bytes(b'video 1')
            (temp_dir / 'def456').mkdir()
            (temp_dir / 'def456' / 'download.mp4').write_bytes(b'video 2')

            # Mock progress hooks to map URLs to IDs
            url_id_map = {
                'https://youtube.com/watch?v=abc123': 'abc123',
                'https://youtube.com/watch?v=def456': 'def456',
            }

            def mock_download(urls):
                hooks = mock_ytdlp_class.call_args[0][0].get('progress_hooks', [])
                for url, vid_id in url_id_map.items():
                    for hook in hooks:
                        hook(
                            {'status': 'finished', 'info_dict': {'id': vid_id, 'webpage_url': url}}
                        )

            mock_ydl.download.side_effect = mock_download

            result = download_ytdlp_batch(list(url_id_map.keys()), 'video', temp_dir)

            self.assertEqual(len(result.downloads), 2)
            self.assertIn('https://youtube.com/watch?v=abc123', result.downloads)
            self.assertIn('https://youtube.com/watch?v=def456', result.downloads)

    @patch('media.service.download.yt_dlp.YoutubeDL')
    def test_download_batch_captures_errors(self, mock_ytdlp_class):
        """Test that failed downloads are captured in errors dict"""
        mock_ydl = MagicMock()
        mock_ytdlp_class.return_value.__enter__.return_value = mock_ydl

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Only create folder for successful download
            (temp_dir / 'good123').mkdir()
            (temp_dir / 'good123' / 'download.mp4').write_bytes(b'video')

            # Progress hook only reports good video
            def mock_download(urls):
                hooks = mock_ytdlp_class.call_args[0][0].get('progress_hooks', [])
                for hook in hooks:
                    hook(
                        {
                            'status': 'finished',
                            'info_dict': {
                                'id': 'good123',
                                'webpage_url': 'https://youtube.com/watch?v=good',
                            },
                        }
                    )
                # bad URL not reported - simulates failure

            mock_ydl.download.side_effect = mock_download

            result = download_ytdlp_batch(
                ['https://youtube.com/watch?v=good', 'https://youtube.com/watch?v=bad'],
                'video',
                temp_dir,
            )

            self.assertEqual(len(result.downloads), 1)
            self.assertEqual(len(result.errors), 1)
            self.assertIn('bad', list(result.errors.keys())[0])
