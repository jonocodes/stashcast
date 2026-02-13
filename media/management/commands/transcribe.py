"""
Django management command to transcribe media files to VTT using faster-whisper.

Usage:
    ./manage.py transcribe /path/to/audio.mp3
    ./manage.py transcribe /path/to/video.mp4 --model large-v3 --language es
    ./manage.py transcribe /path/to/audio.m4a --output /tmp/subtitles.vtt
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Transcribe an audio/video file to VTT using faster-whisper (offline STT)'

    def add_arguments(self, parser):
        parser.add_argument('source', type=str, help='Path to audio or video file')
        parser.add_argument(
            '--output',
            '-o',
            type=str,
            default=None,
            help='Output VTT file path (default: <source>.vtt)',
        )
        parser.add_argument(
            '--model',
            type=str,
            default=settings.STASHCAST_STT_MODEL or 'base',
            help='Whisper model size: tiny, base, small, medium, large-v3 '
            f'(default: {settings.STASHCAST_STT_MODEL or "base"})',
        )
        parser.add_argument(
            '--language',
            type=str,
            default=None,
            help='Language code (e.g. en, es, pt) or omit for auto-detect',
        )
        parser.add_argument(
            '--device',
            type=str,
            default=settings.STASHCAST_STT_DEVICE,
            help=f'Device: auto, cpu, cuda (default: {settings.STASHCAST_STT_DEVICE})',
        )
        parser.add_argument(
            '--compute-type',
            type=str,
            default=settings.STASHCAST_STT_COMPUTE_TYPE,
            help=f'Compute type: auto, int8, float16, float32 '
            f'(default: {settings.STASHCAST_STT_COMPUTE_TYPE})',
        )

    def handle(self, *args, **options):
        source = Path(options['source'])
        if not source.exists():
            raise CommandError(f'File not found: {source}')
        if not source.is_file():
            raise CommandError(f'Not a file: {source}')

        output = options['output']
        if output:
            output_path = Path(output)
        else:
            output_path = source.with_suffix('.vtt')

        model = options['model']
        language = options['language']
        device = options['device']
        compute_type = options['compute_type']

        self.stdout.write(f'Source:  {source}')
        self.stdout.write(f'Output:  {output_path}')
        self.stdout.write(f'Model:   {model}')
        self.stdout.write(f'Language: {language or "auto-detect"}')
        self.stdout.write(f'Device:  {device}')
        self.stdout.write(f'Compute: {compute_type}')
        self.stdout.write('')

        try:
            from media.service.transcribe import transcribe

            result = transcribe(
                media_path=source,
                output_path=output_path,
                model_size=model,
                language=language,
                device=device,
                compute_type=compute_type,
                logger=lambda m: self.stdout.write(m),
            )

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Transcription complete'))
            self.stdout.write(self.style.SUCCESS(f'Language: {result.language}'))
            self.stdout.write(self.style.SUCCESS(f'Time:     {result.duration_seconds:.1f}s'))
            self.stdout.write(self.style.SUCCESS(f'Output:   {result.vtt_path}'))

        except ImportError:
            raise CommandError(
                'faster-whisper is not installed. Install it with:\n  pip install faster-whisper'
            )
        except Exception as e:
            raise CommandError(f'Transcription failed: {e}')
