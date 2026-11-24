"""
Tests for the seed_showcase command and the static marketing site it feeds.
"""

import re
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from media.management.commands.seed_showcase import FIXTURE_DIR, load_fixture
from media.models import MediaItem

SITE_DIR = Path(settings.BASE_DIR) / 'site' / 'public'


class SeedShowcaseTest(TestCase):
    def setUp(self):
        self.media_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        media_settings = override_settings(
            STASHCAST_MEDIA_DIR=self.media_dir, MEDIA_ROOT=self.media_dir
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def seed(self, *args):
        call_command('seed_showcase', *args, stdout=StringIO())

    def test_creates_every_fixture_item_ready_with_files(self):
        self.seed()

        fixture = load_fixture()
        self.assertEqual(MediaItem.objects.count(), len(fixture['items']))
        for item in MediaItem.objects.all():
            self.assertEqual(item.status, MediaItem.STATUS_READY)
            self.assertTrue(item.get_absolute_content_path().exists(), item.slug)
            self.assertTrue(item.get_absolute_thumbnail_path().exists(), item.slug)

    def test_has_both_media_types_newest_first(self):
        self.seed()

        types = set(MediaItem.objects.values_list('media_type', flat=True))
        self.assertEqual(types, {MediaItem.MEDIA_TYPE_AUDIO, MediaItem.MEDIA_TYPE_VIDEO})
        newest = MediaItem.objects.order_by('-created_at').first()
        self.assertEqual(newest.slug, 'compilers')

    def test_refuses_when_library_not_empty(self):
        MediaItem.objects.create(source_url='https://example.com/a', slug='keep-me')

        with self.assertRaises(CommandError):
            self.seed()
        self.assertTrue(MediaItem.objects.filter(slug='keep-me').exists())

    def test_replace_removes_existing_items_and_files(self):
        old_dir = self.media_dir / 'old-item'
        old_dir.mkdir()
        (old_dir / 'content.mp3').write_bytes(b'x')
        MediaItem.objects.create(source_url='https://example.com/a', slug='old-item')

        self.seed('--replace')

        self.assertFalse(MediaItem.objects.filter(slug='old-item').exists())
        self.assertFalse(old_dir.exists())

    def test_rerun_with_replace_is_idempotent(self):
        self.seed()
        self.seed('--replace')

        self.assertEqual(MediaItem.objects.count(), len(load_fixture()['items']))

    def test_every_fixture_item_has_a_cover(self):
        for entry in load_fixture()['items']:
            self.assertTrue((FIXTURE_DIR / 'covers' / f'{entry["slug"]}.webp').exists())


class MarketingSiteLinksTest(TestCase):
    """Every local src/href/srcset in the static site must point at a file that exists."""

    def test_local_references_resolve(self):
        html = (SITE_DIR / 'index.html').read_text()
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        for srcset in re.findall(r'srcset="([^"]+)"', html):
            refs += [candidate.split()[0] for candidate in srcset.split(',')]
        local = [r for r in refs if not re.match(r'^(https?:|mailto:|#|data:)', r)]

        self.assertTrue(local, 'expected some local assets')
        missing = [r for r in local if not (SITE_DIR / r).exists()]
        self.assertEqual(missing, [])
