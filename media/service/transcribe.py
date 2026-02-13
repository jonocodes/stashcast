"""
Speech-to-text transcription service using faster-whisper.

Transcribes audio/video files to VTT subtitle format for media items
that don't already have subtitles. Runs entirely offline.

The model is loaded per-transcription and explicitly unloaded after,
so memory (potentially 10GB for large-v3) is freed between runs.
"""

import gc
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    vtt_path: Path
    language: str
    duration_seconds: float


def transcribe(
    media_path,
    output_path,
    model_size='base',
    language=None,
    device='auto',
    compute_type='auto',
    logger=None,
):
    """
    Transcribe an audio/video file to VTT format using faster-whisper.

    The model is loaded, used, and then explicitly freed so that memory
    is not held between transcription jobs.

    Args:
        media_path: Path to the audio or video file.
        output_path: Path where the VTT file will be written.
        model_size: Whisper model size (tiny, base, small, medium, large-v3).
        language: ISO language code (e.g. 'en', 'es', 'pt') or None for auto-detect.
        device: 'auto', 'cpu', or 'cuda'.
        compute_type: 'auto', 'int8', 'float16', or 'float32'.
        logger: Optional callable(str) for logging.

    Returns:
        TranscriptionResult with the VTT path, detected language, and elapsed time.
    """

    def log(message):
        if logger:
            logger(message)

    media_path = Path(media_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not media_path.exists():
        raise FileNotFoundError(f'Media file not found: {media_path}')

    log(f'Transcribing: {media_path.name}')
    log(f'Model: {model_size}, language: {language or "auto-detect"}, device: {device}')

    start_time = time.monotonic()
    model = None

    try:
        from faster_whisper import WhisperModel

        # Resolve device/compute_type defaults
        resolved_device = device
        resolved_compute = compute_type
        if device == 'auto':
            resolved_device, resolved_compute = _pick_device_and_compute(compute_type)

        log(f'Loading model (device={resolved_device}, compute={resolved_compute})...')
        model_load_start = time.monotonic()

        model = WhisperModel(
            model_size,
            device=resolved_device,
            compute_type=resolved_compute,
        )

        model_load_elapsed = time.monotonic() - model_load_start
        log(f'Model loaded in {model_load_elapsed:.1f}s')

        # Transcribe
        transcribe_start = time.monotonic()
        segments, info = model.transcribe(
            str(media_path),
            language=language,
            vad_filter=True,
            word_timestamps=False,
        )

        detected_language = info.language
        log(f'Detected language: {detected_language} (probability {info.language_probability:.2f})')

        # Write VTT
        _write_vtt(segments, output_path, log)

        transcribe_elapsed = time.monotonic() - transcribe_start
        total_elapsed = time.monotonic() - start_time
        log(
            f'Transcription completed in {transcribe_elapsed:.1f}s (total with model load: {total_elapsed:.1f}s)'
        )

        return TranscriptionResult(
            vtt_path=output_path,
            language=detected_language,
            duration_seconds=total_elapsed,
        )

    finally:
        # Explicitly free model memory
        del model
        gc.collect()

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def _pick_device_and_compute(compute_type):
    """
    Auto-detect the best device and compute type.

    Returns:
        (device, compute_type) tuple
    """
    try:
        import torch

        if torch.cuda.is_available():
            if compute_type == 'auto':
                return 'cuda', 'float16'
            return 'cuda', compute_type
    except ImportError:
        pass

    if compute_type == 'auto':
        return 'cpu', 'int8'
    return 'cpu', compute_type


def _write_vtt(segments, output_path, log):
    """
    Write transcription segments to a VTT file.

    Args:
        segments: Iterator of faster-whisper Segment objects.
        output_path: Path for the output VTT file.
        log: Logging callable.
    """
    segment_count = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('WEBVTT\n\n')

        for segment in segments:
            segment_count += 1
            start = _format_timestamp(segment.start)
            end = _format_timestamp(segment.end)
            text = segment.text.strip()

            if text:
                f.write(f'{start} --> {end}\n')
                f.write(f'{text}\n\n')

    log(f'Wrote {segment_count} segments to {output_path.name}')


def _format_timestamp(seconds):
    """
    Format seconds as VTT timestamp (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds (float).

    Returns:
        str: Formatted timestamp.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f'{hours:02d}:{minutes:02d}:{secs:06.3f}'
