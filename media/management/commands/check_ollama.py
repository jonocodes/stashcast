"""
Django management command to check Ollama configuration and status.

Usage:
    ./manage.py check_ollama
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from media.service.ollama import get_ollama_status, get_summarizer_status


class Command(BaseCommand):
    help = 'Check Ollama configuration and availability for summarization'

    def handle(self, *args, **options):
        self.stdout.write('\n=== Summarization Configuration ===\n')

        # Show current settings
        summarizer = settings.STASHCAST_SUMMARIZER
        sentences = settings.STASHCAST_SUMMARY_SENTENCES
        ollama_host = settings.STASHCAST_OLLAMA_HOST
        ollama_model = settings.STASHCAST_OLLAMA_MODEL

        self.stdout.write(f'STASHCAST_SUMMARIZER: {summarizer}')
        self.stdout.write(f'STASHCAST_SUMMARY_SENTENCES: {sentences}')
        self.stdout.write(f'STASHCAST_OLLAMA_HOST: {ollama_host}')
        self.stdout.write(f'STASHCAST_OLLAMA_MODEL: {ollama_model}')

        self.stdout.write('\n=== Status ===\n')

        # Get overall status
        status = get_summarizer_status()
        self.stdout.write(f"Mode: {status['mode']}")
        self.stdout.write(f"Status: {status['status']}")
        self.stdout.write(f"Message: {status['message']}")

        if summarizer == 'ollama':
            self.stdout.write('\n=== Ollama Details ===\n')

            ollama_status = get_ollama_status()

            if ollama_status.available:
                self.stdout.write(self.style.SUCCESS('Ollama service: Running'))
            else:
                self.stdout.write(self.style.ERROR('Ollama service: Not reachable'))
                self.stdout.write(f'  Error: {ollama_status.error}')
                self.stdout.write('\n  To start Ollama, run: ollama serve')

            if ollama_status.model_loaded:
                self.stdout.write(self.style.SUCCESS(f'Model {ollama_model}: Available'))
            elif ollama_status.available:
                self.stdout.write(self.style.WARNING(f'Model {ollama_model}: Not found'))
                self.stdout.write(f'\n  To pull the model, run: ollama pull {ollama_model}')

            if ollama_status.ready:
                self.stdout.write(
                    self.style.SUCCESS('\nOllama is ready for summarization!')
                )
            else:
                self.stdout.write(
                    self.style.ERROR('\nOllama is NOT ready for summarization.')
                )

        elif summarizer == 'extractive':
            self.stdout.write(
                self.style.SUCCESS(
                    '\nExtractive summarizer (LexRank) is ready. No external service required.'
                )
            )

        if sentences <= 0:
            self.stdout.write(
                self.style.WARNING(
                    '\nNote: Summarization is DISABLED (STASHCAST_SUMMARY_SENTENCES=0)'
                )
            )

        self.stdout.write('')
