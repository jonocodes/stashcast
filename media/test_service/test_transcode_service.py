"""
Tests for service/transcode_service.py

Integration tests for the main transcode service entrypoint.
"""

from django.test import TestCase
from unittest.mock import patch
from pathlib import Path
import tempfile
import io

from media.service.transcode_service import transcode_url_to_dir, TranscodeResult
from media.service.resolve import PlaylistNotSupported


class TranscodeServiceTest(TestCase):
    """Integration tests for transcode service"""

    def _suppress_stdout(self):
        """Context manager to suppress stdout during tests"""
        return patch('sys.stdout', new_callable=io.StringIO)

    def test_transcode_result_dataclass(self):
        """Test TranscodeResult dataclass"""
        result = TranscodeResult(
            url='https://example.com/video.mp4',
            strategy='direct',
            requested_type='auto',
            resolved_type='video',
            title='test video',
            slug='test-video',
            downloaded_path=Path('/tmp/download.mp4'),
            output_path=Path('/tmp/content.mp4'),
            transcoded=False,
            file_size=1024,
        )
        self.assertEqual(result.url, 'https://example.com/video.mp4')
        self.assertEqual(result.strategy, 'direct')
        self.assertFalse(result.transcoded)

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.download_direct')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_direct_mp3_no_transcoding(
        self, mock_strategy, mock_prefetch, mock_download, mock_needs_transcode
    ):
        """Test direct MP3 download without transcoding"""
        # Setup mocks
        mock_strategy.return_value = 'direct'
        mock_needs_transcode.return_value = False  # MP3 doesn't need transcoding

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test audio'
        prefetch_result.has_audio_streams = True
        prefetch_result.has_video_streams = False
        mock_prefetch.return_value = prefetch_result

        # Mock download to create a fake file
        def mock_download_func(url, out_path, logger=None):
            out_path = Path(out_path)
            out_path.write_bytes(b'fake mp3 data')
            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(
                path=out_path,
                file_size=len(b'fake mp3 data'),
                extension='.mp3',
                mime_type='audio/mpeg',
            )

        mock_download.side_effect = mock_download_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(
                url='https://example.com/audio.mp3', outdir=temp_dir, requested_type='auto'
            )

            # Verify result
            self.assertEqual(result.strategy, 'direct')
            self.assertEqual(result.resolved_type, 'audio')
            self.assertFalse(result.transcoded)
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.name, 'test-audio.mp3')

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.download_direct')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_download_only(
        self, mock_strategy, mock_prefetch, mock_download, mock_needs_transcode
    ):
        """Test download_only flag skips transcoding"""
        mock_strategy.return_value = 'direct'
        mock_needs_transcode.return_value = (
            True  # Would need transcoding but download_only prevents it
        )

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test'
        prefetch_result.has_audio_streams = True
        prefetch_result.file_extension = '.ogg'
        mock_prefetch.return_value = prefetch_result

        def mock_download_func(url, out_path, logger=None):
            out_path = Path(out_path)
            out_path.write_bytes(b'ogg data')
            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(path=out_path, file_size=8, extension='.ogg')

        mock_download.side_effect = mock_download_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(
                url='https://example.com/audio.ogg', outdir=temp_dir, download_only=True
            )

            # Should keep OGG format (no transcoding)
            self.assertFalse(result.transcoded)
            self.assertEqual(result.output_path.suffix, '.ogg')

    @patch('media.service.transcode_service.transcode_to_playable')
    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.download_direct')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_ogg_to_m4a(
        self, mock_strategy, mock_prefetch, mock_download, mock_needs_transcode, mock_transcode
    ):
        """Test OGG audio transcoding to M4A"""
        mock_strategy.return_value = 'direct'

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test'
        prefetch_result.has_audio_streams = True
        mock_prefetch.return_value = prefetch_result

        def mock_download_func(url, out_path, logger=None):
            out_path = Path(out_path)
            out_path.write_bytes(b'ogg data')
            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(path=out_path, file_size=8, extension='.ogg')

        mock_download.side_effect = mock_download_func

        mock_needs_transcode.return_value = True

        def mock_transcode_func(input_path, resolved_type, output_path, **kwargs):
            output_path = Path(output_path)
            output_path.write_bytes(b'transcoded m4a data')
            from media.service.process import ProcessedFileInfo

            return ProcessedFileInfo(
                path=output_path, file_size=19, extension='.m4a', was_transcoded=True
            )

        mock_transcode.side_effect = mock_transcode_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(url='https://example.com/audio.ogg', outdir=temp_dir)

            # Should be transcoded to M4A
            self.assertTrue(result.transcoded)
            self.assertEqual(result.output_path.suffix, '.m4a')
            self.assertTrue(result.output_path.exists())

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.download_ytdlp')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_ytdlp_strategy(
        self, mock_strategy, mock_prefetch, mock_download_ytdlp, mock_needs_transcode
    ):
        """Test yt-dlp download strategy"""
        mock_strategy.return_value = 'ytdlp'
        mock_needs_transcode.return_value = False  # MP4 doesn't need transcoding

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'YouTube Video'
        prefetch_result.has_video_streams = True
        mock_prefetch.return_value = prefetch_result

        def mock_ytdlp_download_func(url, resolved_type, temp_dir, **kwargs):
            # Create a fake downloaded file in the temp_dir
            temp_dir = Path(temp_dir)
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'youtube video data')

            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(path=content_file, file_size=18, extension='.mp4')

        mock_download_ytdlp.side_effect = mock_ytdlp_download_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(url='https://youtube.com/watch?v=abc123', outdir=temp_dir)

            # Verify yt-dlp was used
            self.assertEqual(result.strategy, 'ytdlp')
            mock_download_ytdlp.assert_called_once()

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.process_thumbnail')
    @patch('media.service.transcode_service.download_ytdlp')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_with_thumbnail(
        self,
        mock_strategy,
        mock_prefetch,
        mock_download_ytdlp,
        mock_process_thumb,
        mock_needs_transcode,
    ):
        """Test that thumbnails are processed"""
        mock_strategy.return_value = 'ytdlp'
        mock_needs_transcode.return_value = False

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test'
        prefetch_result.has_video_streams = True
        mock_prefetch.return_value = prefetch_result

        def mock_ytdlp_download_func(url, resolved_type, temp_dir, **kwargs):
            temp_dir = Path(temp_dir)
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')
            thumb_file = temp_dir / 'thumbnail.jpg'
            thumb_file.write_bytes(b'thumbnail')

            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(
                path=content_file, file_size=5, extension='.mp4', thumbnail_path=thumb_file
            )

        mock_download_ytdlp.side_effect = mock_ytdlp_download_func

        def mock_process_thumb_func(thumb_path, output_path, **kwargs):
            output_path = Path(output_path)
            output_path.write_bytes(b'png')
            return output_path

        mock_process_thumb.side_effect = mock_process_thumb_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(url='https://youtube.com/watch?v=abc123', outdir=temp_dir)

            # Verify thumbnail was processed
            mock_process_thumb.assert_called_once()
            self.assertIsNotNone(result.thumbnail_path)

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.process_subtitle')
    @patch('media.service.transcode_service.download_ytdlp')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_with_subtitle(
        self,
        mock_strategy,
        mock_prefetch,
        mock_download_ytdlp,
        mock_process_sub,
        mock_needs_transcode,
    ):
        """Test that subtitles are processed"""
        mock_strategy.return_value = 'ytdlp'
        mock_needs_transcode.return_value = False

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test'
        prefetch_result.has_video_streams = True
        mock_prefetch.return_value = prefetch_result

        def mock_ytdlp_download_func(url, resolved_type, temp_dir, **kwargs):
            temp_dir = Path(temp_dir)
            content_file = temp_dir / 'download.mp4'
            content_file.write_bytes(b'video')
            sub_file = temp_dir / 'subtitle.vtt'
            sub_file.write_bytes(b'WEBVTT')

            from media.service.download import DownloadedFileInfo

            return DownloadedFileInfo(
                path=content_file, file_size=5, extension='.mp4', subtitle_path=sub_file
            )

        mock_download_ytdlp.side_effect = mock_ytdlp_download_func

        def mock_process_sub_func(sub_path, output_path, **kwargs):
            output_path = Path(output_path)
            output_path.write_bytes(b'WEBVTT')
            return output_path

        mock_process_sub.side_effect = mock_process_sub_func

        with tempfile.TemporaryDirectory() as temp_dir:
            result = transcode_url_to_dir(url='https://youtube.com/watch?v=abc123', outdir=temp_dir)

            # Verify subtitle was processed
            mock_process_sub.assert_called_once()
            self.assertIsNotNone(result.subtitle_path)

    @patch('media.service.transcode_service.add_metadata_without_transcode')
    @patch('media.service.transcode_service.needs_transcode')
    def test_transcode_verbose_logging(self, mock_needs_transcode, mock_add_metadata):
        """Test that verbose mode produces logs"""
        mock_needs_transcode.return_value = False

        with patch('media.service.transcode_service.choose_download_strategy') as mock_strategy:
            mock_strategy.return_value = 'direct'

            with patch('media.service.transcode_service.prefetch') as mock_prefetch:
                from media.service.resolve import PrefetchResult

                prefetch_result = PrefetchResult()
                prefetch_result.title = 'test'
                prefetch_result.has_audio_streams = True
                mock_prefetch.return_value = prefetch_result

                with patch('media.service.transcode_service.download_direct') as mock_download:

                    def mock_download_func(url, out_path, logger=None):
                        # Verify logger is passed
                        self.assertIsNotNone(logger)
                        logger('Test log message')

                        out_path = Path(out_path)
                        out_path.write_bytes(b'data')
                        from media.service.download import DownloadedFileInfo

                        return DownloadedFileInfo(path=out_path, file_size=4, extension='.mp3')

                    mock_download.side_effect = mock_download_func

                    def mock_metadata_func(input_path, output_path, metadata=None, logger=None):
                        # Just copy the file
                        output_path = Path(output_path)
                        output_path.write_bytes(input_path.read_bytes())

                    mock_add_metadata.side_effect = mock_metadata_func

                    with tempfile.TemporaryDirectory() as temp_dir:
                        # Suppress stdout to prevent leaked output during tests
                        with self._suppress_stdout():
                            # This should pass logger to download functions
                            transcode_url_to_dir(
                                url='https://example.com/audio.mp3', outdir=temp_dir, verbose=True
                            )

    @patch('media.service.transcode_service.needs_transcode')
    @patch('media.service.transcode_service.prefetch')
    @patch('media.service.transcode_service.choose_download_strategy')
    def test_transcode_explicit_audio_type(
        self, mock_strategy, mock_prefetch, mock_needs_transcode
    ):
        """Test explicit audio type request"""
        mock_strategy.return_value = 'direct'
        mock_needs_transcode.return_value = False

        from media.service.resolve import PrefetchResult

        prefetch_result = PrefetchResult()
        prefetch_result.title = 'test'
        prefetch_result.has_video_streams = True  # Has video but user wants audio
        prefetch_result.has_audio_streams = True
        mock_prefetch.return_value = prefetch_result

        with patch('media.service.transcode_service.download_direct') as mock_download:

            def mock_download_func(url, out_path, logger=None):
                out_path = Path(out_path)
                out_path.write_bytes(b'data')
                from media.service.download import DownloadedFileInfo

                return DownloadedFileInfo(path=out_path, file_size=4, extension='.mp3')

            mock_download.side_effect = mock_download_func

            with tempfile.TemporaryDirectory() as temp_dir:
                result = transcode_url_to_dir(
                    url='https://example.com/video.mp4',
                    outdir=temp_dir,
                    requested_type='audio',  # Explicit audio
                )

                # Should resolve to audio even though has video
                self.assertEqual(result.resolved_type, 'audio')

    @patch('media.service.transcode_service.prefetch')
    def test_transcode_playlist_raises_error(self, mock_prefetch):
        """Test that playlists raise PlaylistNotSupported"""
        mock_prefetch.side_effect = PlaylistNotSupported('Playlist detected')

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(PlaylistNotSupported):
                transcode_url_to_dir(
                    url='https://youtube.com/playlist?list=abc123', outdir=temp_dir
                )
