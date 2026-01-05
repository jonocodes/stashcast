"""
Tests for service/process.py
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from media.service.process import (
    needs_transcode,
    transcode_to_playable,
    process_thumbnail,
    process_subtitle,
    ProcessedFileInfo
)


class ProcessServiceTest(TestCase):
    """Tests for media processing and transcoding"""

    def test_processed_file_info_dataclass(self):
        """Test ProcessedFileInfo dataclass"""
        info = ProcessedFileInfo(
            path=Path('/tmp/test.mp4'),
            file_size=2048,
            extension='.mp4',
            was_transcoded=True
        )
        self.assertEqual(info.path, Path('/tmp/test.mp4'))
        self.assertEqual(info.file_size, 2048)
        self.assertTrue(info.was_transcoded)

    def test_needs_transcode_audio_mp3_false(self):
        """Test that MP3 audio doesn't need transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.mp3') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertFalse(needs)

    def test_needs_transcode_audio_m4a_false(self):
        """Test that M4A audio doesn't need transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.m4a') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertFalse(needs)

    def test_needs_transcode_audio_ogg_true(self):
        """Test that OGG audio needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.ogg') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertTrue(needs)

    def test_needs_transcode_audio_opus_true(self):
        """Test that Opus audio needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.opus') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertTrue(needs)

    def test_needs_transcode_audio_flac_true(self):
        """Test that FLAC audio needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.flac') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertTrue(needs)

    def test_needs_transcode_audio_wav_true(self):
        """Test that WAV audio needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertTrue(needs)

    def test_needs_transcode_video_mp4_false(self):
        """Test that MP4 video doesn't need transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
            needs = needs_transcode(f.name, 'video')
            self.assertFalse(needs)

    def test_needs_transcode_video_webm_true(self):
        """Test that WebM video needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.webm') as f:
            needs = needs_transcode(f.name, 'video')
            self.assertTrue(needs)

    def test_needs_transcode_video_mkv_true(self):
        """Test that MKV video needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.mkv') as f:
            needs = needs_transcode(f.name, 'video')
            self.assertTrue(needs)

    def test_needs_transcode_video_avi_true(self):
        """Test that AVI video needs transcoding"""
        with tempfile.NamedTemporaryFile(suffix='.avi') as f:
            needs = needs_transcode(f.name, 'video')
            self.assertTrue(needs)

    def test_needs_transcode_case_insensitive(self):
        """Test that extension checking is case-insensitive"""
        with tempfile.NamedTemporaryFile(suffix='.MP3') as f:
            needs = needs_transcode(f.name, 'audio')
            self.assertFalse(needs)

    @patch('media.service.process.subprocess.run')
    def test_transcode_to_playable_success(self, mock_run):
        """Test successful transcoding"""
        def mock_ffmpeg(cmd, **kwargs):
            # Extract output file from command and create it
            if '-i' in cmd:
                output_idx = len(cmd) - 1
                output_path = Path(cmd[output_idx])
                output_path.write_bytes(b'transcoded data')
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = mock_ffmpeg

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create input file
            input_file = temp_dir / 'input.ogg'
            input_file.write_bytes(b'fake ogg data')

            output_file = temp_dir / 'output.m4a'

            result = transcode_to_playable(input_file, 'audio', output_file)

            # Verify subprocess.run was called twice (ffprobe for metadata, then ffmpeg for transcode)
            self.assertEqual(mock_run.call_count, 2)

            # First call should be ffprobe
            first_call_args = mock_run.call_args_list[0][0][0]
            self.assertIn('ffprobe', first_call_args[0])

            # Second call should be ffmpeg
            second_call_args = mock_run.call_args_list[1][0][0]
            self.assertIn('ffmpeg', second_call_args[0])
            self.assertIn(str(input_file), second_call_args)
            self.assertIn(str(output_file), second_call_args)

            # Verify result
            self.assertTrue(result.was_transcoded)

    @patch('media.service.process.subprocess.run')
    def test_transcode_to_playable_with_logger(self, mock_run):
        """Test transcoding with logger callback"""
        def mock_ffmpeg(cmd, **kwargs):
            output_path = Path(cmd[-1])
            output_path.write_bytes(b'transcoded data')
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = mock_ffmpeg

        logs = []
        logger = lambda msg: logs.append(msg)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_file = temp_dir / 'input.ogg'
            input_file.write_bytes(b'data')
            output_file = temp_dir / 'output.m4a'

            transcode_to_playable(input_file, 'audio', output_file, logger=logger)

            self.assertTrue(len(logs) > 0)
            self.assertTrue(any('Transcoding' in log for log in logs))

    @patch('media.service.process.subprocess.run')
    def test_transcode_to_playable_ffmpeg_error(self, mock_run):
        """Test that ffmpeg errors are raised"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = 'ffmpeg error message'
        mock_run.return_value = mock_result

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_file = temp_dir / 'input.ogg'
            input_file.write_bytes(b'data')
            output_file = temp_dir / 'output.m4a'

            with self.assertRaises(Exception) as ctx:
                transcode_to_playable(input_file, 'audio', output_file)

            self.assertIn('ffmpeg failed', str(ctx.exception))

    @patch('media.service.process.subprocess.run')
    def test_transcode_to_playable_creates_parent_dir(self, mock_run):
        """Test that transcoding creates parent directory"""
        def mock_ffmpeg(cmd, **kwargs):
            output_path = Path(cmd[-1])
            output_path.write_bytes(b'transcoded data')
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = mock_ffmpeg

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_file = temp_dir / 'input.ogg'
            input_file.write_bytes(b'data')

            output_file = temp_dir / 'subdir' / 'nested' / 'output.m4a'

            transcode_to_playable(input_file, 'audio', output_file)

            self.assertTrue(output_file.parent.exists())

    @patch('media.service.process.subprocess.run')
    def test_transcode_audio_uses_audio_settings(self, mock_run):
        """Test that audio transcoding uses audio ffmpeg settings"""
        def mock_ffmpeg(cmd, **kwargs):
            output_path = Path(cmd[-1])
            output_path.write_bytes(b'transcoded data')
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = mock_ffmpeg

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_file = temp_dir / 'input.ogg'
            input_file.write_bytes(b'data')
            output_file = temp_dir / 'output.m4a'

            transcode_to_playable(input_file, 'audio', output_file)

            call_args = mock_run.call_args[0][0]
            # Should contain AAC codec for audio
            self.assertTrue(any('aac' in str(arg).lower() for arg in call_args))

    @patch('media.service.process.subprocess.run')
    def test_transcode_video_uses_video_settings(self, mock_run):
        """Test that video transcoding uses video ffmpeg settings"""
        def mock_ffmpeg(cmd, **kwargs):
            output_path = Path(cmd[-1])
            output_path.write_bytes(b'transcoded data')
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = mock_ffmpeg

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_file = temp_dir / 'input.mkv'
            input_file.write_bytes(b'data')
            output_file = temp_dir / 'output.mp4'

            transcode_to_playable(input_file, 'video', output_file)

            call_args = mock_run.call_args[0][0]
            # Should contain x264 codec for video
            self.assertTrue(any('x264' in str(arg).lower() for arg in call_args))

    @patch('PIL.Image.open')
    def test_process_thumbnail_success(self, mock_image_open):
        """Test successful thumbnail processing"""
        mock_img = MagicMock()
        mock_image_open.return_value = mock_img

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            # Create input thumbnail
            input_thumb = temp_dir / 'thumb.jpg'
            input_thumb.write_bytes(b'fake jpg')

            output_thumb = temp_dir / 'thumb.png'

            result = process_thumbnail(input_thumb, output_thumb)

            # Verify Image was used
            mock_image_open.assert_called_once_with(input_thumb)
            mock_img.save.assert_called_once()

            # Verify PNG format was specified
            save_call_args = mock_img.save.call_args
            self.assertEqual(save_call_args[0][0], output_thumb)
            self.assertEqual(save_call_args[0][1], 'PNG')

            self.assertEqual(result, output_thumb)

    def test_process_thumbnail_none_input(self):
        """Test that None thumbnail returns None"""
        result = process_thumbnail(None, Path('/tmp/out.png'))
        self.assertIsNone(result)

    def test_process_thumbnail_missing_file(self):
        """Test that missing thumbnail returns None"""
        result = process_thumbnail(Path('/nonexistent/thumb.jpg'), Path('/tmp/out.png'))
        self.assertIsNone(result)

    @patch('PIL.Image.open')
    def test_process_thumbnail_with_logger(self, mock_image_open):
        """Test thumbnail processing with logger"""
        mock_img = MagicMock()
        mock_image_open.return_value = mock_img

        logs = []
        logger = lambda msg: logs.append(msg)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_thumb = temp_dir / 'thumb.jpg'
            input_thumb.write_bytes(b'data')
            output_thumb = temp_dir / 'thumb.png'

            process_thumbnail(input_thumb, output_thumb, logger=logger)

            self.assertTrue(len(logs) > 0)
            self.assertTrue(any('thumbnail' in log.lower() for log in logs))

    @patch('PIL.Image.open')
    @patch('media.service.process.shutil.copy2')
    def test_process_thumbnail_fallback_on_error(self, mock_copy, mock_image_open):
        """Test that thumbnail processing falls back to copy on error"""
        mock_image_open.side_effect = Exception("PIL error")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_thumb = temp_dir / 'thumb.jpg'
            input_thumb.write_bytes(b'data')
            output_thumb = temp_dir / 'thumb.png'

            result = process_thumbnail(input_thumb, output_thumb)

            # Should have fallen back to copy
            mock_copy.assert_called_once_with(input_thumb, output_thumb)
            self.assertEqual(result, output_thumb)

    def test_process_subtitle_vtt_copy(self):
        """Test that VTT subtitles are just copied"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            input_sub = temp_dir / 'sub.vtt'
            input_sub.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest')

            output_sub = temp_dir / 'output.vtt'

            result = process_subtitle(input_sub, output_sub)

            self.assertTrue(output_sub.exists())
            self.assertEqual(result, output_sub)
            # Content should be copied
            self.assertIn('WEBVTT', output_sub.read_text())

    @patch('media.service.process.subprocess.run')
    def test_process_subtitle_srt_conversion(self, mock_run):
        """Test that SRT subtitles are converted to VTT"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            input_sub = temp_dir / 'sub.srt'
            input_sub.write_text('1\n00:00:00,000 --> 00:00:01,000\nTest')

            output_sub = temp_dir / 'output.vtt'

            result = process_subtitle(input_sub, output_sub)

            # Verify ffmpeg was called for conversion
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            self.assertIn('ffmpeg', call_args[0])
            self.assertIn(str(input_sub), call_args)
            self.assertIn(str(output_sub), call_args)

    def test_process_subtitle_none_input(self):
        """Test that None subtitle returns None"""
        result = process_subtitle(None, Path('/tmp/out.vtt'))
        self.assertIsNone(result)

    def test_process_subtitle_missing_file(self):
        """Test that missing subtitle returns None"""
        result = process_subtitle(Path('/nonexistent/sub.vtt'), Path('/tmp/out.vtt'))
        self.assertIsNone(result)

    @patch('media.service.process.subprocess.run')
    def test_process_subtitle_with_logger(self, mock_run):
        """Test subtitle processing with logger"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        logs = []
        logger = lambda msg: logs.append(msg)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_sub = temp_dir / 'sub.srt'
            input_sub.write_text('subtitle data')
            output_sub = temp_dir / 'out.vtt'

            process_subtitle(input_sub, output_sub, logger=logger)

            self.assertTrue(len(logs) > 0)
            self.assertTrue(any('subtitle' in log.lower() for log in logs))

    @patch('media.service.process.subprocess.run')
    @patch('media.service.process.shutil.copy2')
    def test_process_subtitle_fallback_on_conversion_error(self, mock_copy, mock_run):
        """Test that subtitle processing falls back to copy on conversion error"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_sub = temp_dir / 'sub.srt'
            input_sub.write_text('subtitle')
            output_sub = temp_dir / 'out.vtt'

            result = process_subtitle(input_sub, output_sub)

            # Should have fallen back to copy
            mock_copy.assert_called()
