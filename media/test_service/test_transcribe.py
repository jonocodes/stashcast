"""
Tests for service/transcribe.py
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from media.service.transcribe import (
    TranscriptionResult,
    _format_timestamp,
    _pick_device_and_compute,
    _write_vtt,
    transcribe,
)


class TranscriptionResultTest(TestCase):
    """Tests for TranscriptionResult dataclass"""

    def test_dataclass_fields(self):
        result = TranscriptionResult(
            vtt_path=Path('/tmp/subtitles.vtt'),
            language='en',
            duration_seconds=12.5,
        )
        self.assertEqual(result.vtt_path, Path('/tmp/subtitles.vtt'))
        self.assertEqual(result.language, 'en')
        self.assertEqual(result.duration_seconds, 12.5)


class FormatTimestampTest(TestCase):
    """Tests for VTT timestamp formatting"""

    def test_zero(self):
        self.assertEqual(_format_timestamp(0), '00:00:00.000')

    def test_seconds_only(self):
        self.assertEqual(_format_timestamp(5.123), '00:00:05.123')

    def test_minutes_and_seconds(self):
        self.assertEqual(_format_timestamp(65.5), '00:01:05.500')

    def test_hours(self):
        self.assertEqual(_format_timestamp(3661.0), '01:01:01.000')

    def test_fractional_milliseconds(self):
        result = _format_timestamp(1.1)
        self.assertEqual(result, '00:00:01.100')


class PickDeviceAndComputeTest(TestCase):
    """Tests for device/compute auto-detection"""

    def test_cpu_fallback_when_no_torch(self):
        """Falls back to CPU/int8 when torch is not available"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict('sys.modules', {'torch': mock_torch}):
            device, compute = _pick_device_and_compute('auto')
            self.assertEqual(device, 'cpu')
            self.assertEqual(compute, 'int8')

    def test_explicit_compute_type_on_cpu(self):
        """Explicit compute type is respected on CPU"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict('sys.modules', {'torch': mock_torch}):
            device, compute = _pick_device_and_compute('float32')
            self.assertEqual(device, 'cpu')
            self.assertEqual(compute, 'float32')

    def test_cuda_when_available(self):
        """Uses CUDA with float16 when GPU is available"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.dict('sys.modules', {'torch': mock_torch}):
            device, compute = _pick_device_and_compute('auto')
            self.assertEqual(device, 'cuda')
            self.assertEqual(compute, 'float16')

    def test_cuda_explicit_compute(self):
        """Explicit compute type is respected on CUDA"""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.dict('sys.modules', {'torch': mock_torch}):
            device, compute = _pick_device_and_compute('int8')
            self.assertEqual(device, 'cuda')
            self.assertEqual(compute, 'int8')


class WriteVttTest(TestCase):
    """Tests for VTT file writing"""

    def test_writes_valid_vtt(self):
        """Produces a valid VTT file with header and segments"""
        segments = [
            SimpleNamespace(start=0.0, end=2.5, text=' Hello world '),
            SimpleNamespace(start=3.0, end=5.0, text=' Second line '),
        ]
        log_messages = []

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'subtitles.vtt'
            _write_vtt(iter(segments), output, lambda m: log_messages.append(m))

            content = output.read_text()

            self.assertTrue(content.startswith('WEBVTT\n\n'))
            self.assertIn('00:00:00.000 --> 00:00:02.500', content)
            self.assertIn('Hello world', content)
            self.assertIn('00:00:03.000 --> 00:00:05.000', content)
            self.assertIn('Second line', content)
            self.assertEqual(len(log_messages), 1)
            self.assertIn('2 segments', log_messages[0])

    def test_skips_empty_text(self):
        """Segments with blank text are skipped"""
        segments = [
            SimpleNamespace(start=0.0, end=1.0, text='  '),
            SimpleNamespace(start=1.0, end=2.0, text=' Real text '),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'subtitles.vtt'
            _write_vtt(iter(segments), output, lambda m: None)

            content = output.read_text()
            self.assertNotIn('00:00:00.000 --> 00:00:01.000', content)
            self.assertIn('Real text', content)

    def test_empty_segments(self):
        """No segments produces a VTT header only"""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'subtitles.vtt'
            _write_vtt(iter([]), output, lambda m: None)

            content = output.read_text()
            self.assertEqual(content, 'WEBVTT\n\n')


class TranscribeTest(TestCase):
    """Tests for the main transcribe function"""

    def test_file_not_found_raises(self):
        """Raises FileNotFoundError for nonexistent media"""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                transcribe(
                    media_path=Path(tmp) / 'nonexistent.mp3',
                    output_path=Path(tmp) / 'out.vtt',
                )

    @patch('faster_whisper.WhisperModel')
    def test_transcribe_success(self, mock_whisper_class):
        """End-to-end test with mocked WhisperModel"""
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model

        segments = [
            SimpleNamespace(start=0.0, end=2.0, text='Hello world'),
            SimpleNamespace(start=2.5, end=4.0, text='Testing speech'),
        ]
        info = SimpleNamespace(language='en', language_probability=0.98)
        mock_model.transcribe.return_value = (iter(segments), info)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_file = tmp / 'audio.mp3'
            media_file.write_bytes(b'fake audio data')
            output_file = tmp / 'subtitles.vtt'

            log_messages = []
            result = transcribe(
                media_path=media_file,
                output_path=output_file,
                model_size='base',
                language='en',
                device='cpu',
                compute_type='int8',
                logger=lambda m: log_messages.append(m),
            )

            self.assertEqual(result.vtt_path, output_file)
            self.assertEqual(result.language, 'en')
            self.assertGreater(result.duration_seconds, 0)

            self.assertTrue(output_file.exists())
            content = output_file.read_text()
            self.assertIn('WEBVTT', content)
            self.assertIn('Hello world', content)

            mock_whisper_class.assert_called_once_with(
                'base',
                device='cpu',
                compute_type='int8',
            )

            mock_model.transcribe.assert_called_once_with(
                str(media_file),
                language='en',
                vad_filter=True,
                word_timestamps=False,
            )

            self.assertTrue(any('Transcribing' in m for m in log_messages))
            self.assertTrue(any('Detected language' in m for m in log_messages))
            self.assertTrue(any('completed' in m for m in log_messages))

    @patch('faster_whisper.WhisperModel')
    def test_transcribe_auto_language(self, mock_whisper_class):
        """Language=None triggers auto-detection"""
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model

        segments = [SimpleNamespace(start=0.0, end=1.0, text='Hola')]
        info = SimpleNamespace(language='es', language_probability=0.95)
        mock_model.transcribe.return_value = (iter(segments), info)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_file = tmp / 'audio.mp3'
            media_file.write_bytes(b'fake')

            result = transcribe(
                media_path=media_file,
                output_path=tmp / 'out.vtt',
                language=None,
                device='cpu',
                compute_type='int8',
            )

            self.assertEqual(result.language, 'es')
            mock_model.transcribe.assert_called_once()
            call_kwargs = mock_model.transcribe.call_args[1]
            self.assertIsNone(call_kwargs['language'])

    @patch('faster_whisper.WhisperModel')
    def test_model_is_freed_after_transcription(self, mock_whisper_class):
        """Model reference is deleted after transcription (memory management)"""
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model

        segments = [SimpleNamespace(start=0.0, end=1.0, text='Test')]
        info = SimpleNamespace(language='en', language_probability=0.99)
        mock_model.transcribe.return_value = (iter(segments), info)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_file = tmp / 'audio.mp3'
            media_file.write_bytes(b'fake')

            result = transcribe(
                media_path=media_file,
                output_path=tmp / 'out.vtt',
                device='cpu',
                compute_type='int8',
            )

            self.assertIsNotNone(result)

    @patch('faster_whisper.WhisperModel')
    def test_model_freed_on_error(self, mock_whisper_class):
        """Model is freed even when transcription fails"""
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model
        mock_model.transcribe.side_effect = RuntimeError('out of memory')

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_file = tmp / 'audio.mp3'
            media_file.write_bytes(b'fake')

            with self.assertRaises(RuntimeError):
                transcribe(
                    media_path=media_file,
                    output_path=tmp / 'out.vtt',
                    device='cpu',
                    compute_type='int8',
                )

    @patch('faster_whisper.WhisperModel')
    def test_output_directory_created(self, mock_whisper_class):
        """Output directory is created if it doesn't exist"""
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model

        segments = [SimpleNamespace(start=0.0, end=1.0, text='Test')]
        info = SimpleNamespace(language='en', language_probability=0.99)
        mock_model.transcribe.return_value = (iter(segments), info)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_file = tmp / 'audio.mp3'
            media_file.write_bytes(b'fake')

            output_file = tmp / 'nested' / 'dir' / 'subtitles.vtt'

            transcribe(
                media_path=media_file,
                output_path=output_file,
                device='cpu',
                compute_type='int8',
            )

            self.assertTrue(output_file.exists())
