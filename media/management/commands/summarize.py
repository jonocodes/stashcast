"""
Django management command to summarize VTT subtitle files.

Usage:
    python manage.py summarize /path/to/file.vtt
    python manage.py summarize http://example.com/subtitles.vtt
"""
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer


class Command(BaseCommand):
    help = 'Generate a summary from a VTT subtitle file (local file or URL)'

    def add_arguments(self, parser):
        parser.add_argument(
            'source',
            type=str,
            help='Path to VTT file or URL'
        )
        parser.add_argument(
            '--sentences',
            type=int,
            default=settings.STASHCAST_SUMMARY_SENTENCES,
            help=f'Number of sentences in summary (default: {settings.STASHCAST_SUMMARY_SENTENCES})'
        )
        parser.add_argument(
            '--algorithm',
            type=str,
            choices=['lexrank', 'textrank', 'luhn'],
            default='lexrank',
            help='Summarization algorithm to use (default: lexrank)'
        )

    def handle(self, *args, **options):
        source = options['source']
        num_sentences = options['sentences']
        algorithm = options['algorithm']

        # Determine if source is URL or file path
        if source.startswith('http://') or source.startswith('https://'):
            self.stdout.write(f"Fetching VTT from URL: {source}")
            vtt_content = self.fetch_vtt_from_url(source)
        else:
            self.stdout.write(f"Reading VTT from file: {source}")
            vtt_content = self.read_vtt_from_file(source)

        # Extract text from VTT
        self.stdout.write("Extracting text from VTT...")
        text = self.extract_text_from_vtt(vtt_content)

        if not text or len(text.strip()) < 50:
            raise CommandError("Not enough text content to summarize")

        self.stdout.write(f"Extracted {len(text)} characters")
        self.stdout.write(f"Generating {num_sentences}-sentence summary using {algorithm}...")
        self.stdout.write("")

        # Generate summary
        summary = self.generate_summary(text, num_sentences, algorithm)

        # Output summary
        self.stdout.write(self.style.SUCCESS("="*60))
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write(self.style.SUCCESS("="*60))
        self.stdout.write("")
        self.stdout.write(summary)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("="*60))

    def fetch_vtt_from_url(self, url):
        """Fetch VTT content from a URL"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise CommandError(f"Failed to fetch URL: {e}")

    def read_vtt_from_file(self, file_path):
        """Read VTT content from a local file"""
        path = Path(file_path)
        if not path.exists():
            raise CommandError(f"File not found: {file_path}")

        if not path.is_file():
            raise CommandError(f"Not a file: {file_path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except IOError as e:
            raise CommandError(f"Failed to read file: {e}")

    def extract_text_from_vtt(self, vtt_content):
        """Extract plain text from VTT content"""
        lines = vtt_content.split('\n')
        text_lines = []

        for line in lines:
            # Skip VTT headers, timestamps, cue IDs, and blank lines
            if (not line.startswith('WEBVTT') and
                not line.startswith('Kind:') and
                not line.startswith('Language:') and
                not '-->' in line and
                not re.match(r'^\d+$', line.strip()) and
                not 'align:' in line and
                not 'position:' in line and
                line.strip()):
                # Remove timing tags like <00:00:00.400> and <c>
                clean_line = re.sub(r'<[^>]+>', '', line)
                if clean_line.strip():
                    text_lines.append(clean_line.strip())

        return ' '.join(text_lines)

    def generate_summary(self, text, num_sentences, algorithm):
        """Generate summary using specified algorithm"""
        try:
            parser = PlaintextParser.from_string(text, Tokenizer("english"))

            # Select summarizer based on algorithm
            if algorithm == 'lexrank':
                from sumy.summarizers.lex_rank import LexRankSummarizer
                summarizer = LexRankSummarizer()
            elif algorithm == 'textrank':
                from sumy.summarizers.text_rank import TextRankSummarizer
                summarizer = TextRankSummarizer()
            elif algorithm == 'luhn':
                from sumy.summarizers.luhn import LuhnSummarizer
                summarizer = LuhnSummarizer()
            else:
                raise CommandError(f"Unknown algorithm: {algorithm}")

            # Generate summary
            summary_sentences = summarizer(parser.document, num_sentences)
            summary = ' '.join(str(sentence) for sentence in summary_sentences)

            return summary

        except Exception as e:
            raise CommandError(f"Failed to generate summary: {e}")
