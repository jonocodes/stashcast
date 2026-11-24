"""
Tests for long-term media storage in an S3-compatible bucket (media/storage.py).

S3 is emulated with moto; no network or real bucket needed.
"""

import shutil
import tempfile
from io import StringIO
from pathlib import Path

import boto3
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from moto import mock_aws

from media.models import MediaItem
from media.processing import finalize_item
from media.storage import (
    PublishError,
    check_remote_storage_config,
    delete_item_files,
    is_published,
    publish_item,
    storage_usage_bytes,
)

BUCKET = 'stashcast-test'
BASE_URL = 'https://media.example.com'
REGION = 'us-east-1'


def s3_storages(prefix=''):
    return {
        **settings.STORAGES,
        settings.STASHCAST_MEDIA_STORAGE_ALIAS: {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {
                'bucket_name': BUCKET,
                'location': prefix,
                'region_name': REGION,
                'access_key': 'testing',
                'secret_key': 'testing',
                'querystring_auth': False,
                'default_acl': None,
                'file_overwrite': True,
            },
        },
    }


def local_storages():
    return {
        k: v for k, v in settings.STORAGES.items() if k != settings.STASHCAST_MEDIA_STORAGE_ALIAS
    }


class MediaDirMixin:
    """Point the media directory at a fresh temp dir for each test."""

    def setUp(self):
        super().setUp()
        self.media_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        media_settings = override_settings(
            STASHCAST_MEDIA_DIR=self.media_dir, MEDIA_ROOT=self.media_dir
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def make_item(self, slug='my-talk', files=None, **fields):
        files = files or {
            'content.m4a': b'A' * 1000,
            'thumbnail.webp': b'T' * 100,
            'subtitles.vtt': b'WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n',
            'download.log': b'log line\n',
        }
        item_dir = self.media_dir / slug
        item_dir.mkdir(parents=True)
        for name, data in files.items():
            (item_dir / name).write_bytes(data)
        defaults = dict(
            source_url=f'https://example.com/{slug}',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            slug=slug,
            title=slug.replace('-', ' ').title(),
            status=MediaItem.STATUS_READY,
            content_path='content.m4a',
            thumbnail_path='thumbnail.webp',
            subtitle_path='subtitles.vtt',
            log_path='download.log',
        )
        defaults.update(fields)
        return MediaItem.objects.create(**defaults)


class S3Mixin(MediaDirMixin):
    prefix = ''
    keep_local = False

    def setUp(self):
        super().setUp()
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.s3 = boto3.client(
            's3', region_name=REGION, aws_access_key_id='x', aws_secret_access_key='x'
        )
        self.s3.create_bucket(Bucket=BUCKET)
        s3_settings = override_settings(
            STORAGES=s3_storages(self.prefix),
            STASHCAST_MEDIA_BASE_URL=BASE_URL,
            STASHCAST_S3_KEEP_LOCAL=self.keep_local,
        )
        s3_settings.enable()
        self.addCleanup(s3_settings.disable)

    def keys(self):
        resp = self.s3.list_objects_v2(Bucket=BUCKET)
        return sorted(o['Key'] for o in resp.get('Contents', []))

    def put(self, key, body=b'x'):
        self.s3.put_object(Bucket=BUCKET, Key=key, Body=body)


class PublishTest(S3Mixin, TestCase):
    def test_uploads_all_files_except_logs(self):
        item = self.make_item()
        self.assertTrue(publish_item(item))
        self.assertEqual(
            self.keys(),
            ['my-talk/content.m4a', 'my-talk/subtitles.vtt', 'my-talk/thumbnail.webp'],
        )

    def test_sets_content_types_for_players(self):
        item = self.make_item()
        publish_item(item)
        types = {
            key: self.s3.head_object(Bucket=BUCKET, Key=key)['ContentType'] for key in self.keys()
        }
        self.assertEqual(types['my-talk/content.m4a'], 'audio/mp4')
        self.assertEqual(types['my-talk/subtitles.vtt'], 'text/vtt')
        self.assertEqual(types['my-talk/thumbnail.webp'], 'image/webp')

    def test_removes_stale_remote_files_on_republish(self):
        self.put('my-talk/content.mp4')  # from an earlier fetch as video
        item = self.make_item()
        publish_item(item)
        self.assertNotIn('my-talk/content.mp4', self.keys())

    def test_does_not_touch_other_items_sharing_a_slug_prefix(self):
        self.put('my-talk-part-2/content.m4a')
        publish_item(self.make_item())
        self.assertIn('my-talk-part-2/content.m4a', self.keys())

    def test_removes_local_content_but_keeps_subtitles_and_log(self):
        item = self.make_item()
        publish_item(item)
        base = item.get_base_dir()
        self.assertFalse((base / 'content.m4a').exists())
        self.assertTrue((base / 'subtitles.vtt').exists())
        self.assertTrue((base / 'download.log').exists())

    def test_refuses_to_publish_without_local_content(self):
        """A missing local file must never wipe the published copy."""
        self.put('my-talk/content.m4a', b'published')
        item = self.make_item(files={'subtitles.vtt': b'WEBVTT\n'})
        with self.assertRaises(PublishError):
            publish_item(item)
        self.assertIn('my-talk/content.m4a', self.keys())

    def test_is_published(self):
        item = self.make_item()
        self.assertFalse(is_published(item))
        publish_item(item)
        self.assertTrue(is_published(item))


class PublishKeepLocalTest(S3Mixin, TestCase):
    keep_local = True

    def test_keeps_local_content_when_configured(self):
        item = self.make_item()
        publish_item(item)
        self.assertTrue(item.get_absolute_content_path().exists())
        self.assertIn('my-talk/content.m4a', self.keys())


class PublishWithPrefixTest(S3Mixin, TestCase):
    prefix = 'stashcast'

    def test_keys_live_under_prefix(self):
        publish_item(self.make_item())
        self.assertIn('stashcast/my-talk/content.m4a', self.keys())

    def test_delete_and_usage_respect_prefix(self):
        self.put('other-app/big.bin', b'x' * 5000)
        item = self.make_item()
        publish_item(item)
        self.assertEqual(
            storage_usage_bytes(), 1000 + 100 + len(b'WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n')
        )
        delete_item_files(item)
        self.assertEqual(self.keys(), ['other-app/big.bin'])


class DeleteTest(S3Mixin, TestCase):
    def test_model_delete_removes_local_and_remote_files(self):
        item = self.make_item()
        publish_item(item)
        base = item.get_base_dir()
        item.delete()
        self.assertFalse(base.exists())
        self.assertEqual(self.keys(), [])

    def test_bulk_queryset_delete_removes_remote_files(self):
        for slug in ['one', 'two']:
            publish_item(self.make_item(slug=slug))
        MediaItem.objects.all().delete()
        self.assertEqual(self.keys(), [])


class LocalOnlyTest(MediaDirMixin, TestCase):
    """Without a bucket configured, behaviour is unchanged."""

    def setUp(self):
        super().setUp()
        local = override_settings(STORAGES=local_storages())
        local.enable()
        self.addCleanup(local.disable)

    def test_publish_is_a_noop(self):
        item = self.make_item()
        self.assertFalse(publish_item(item))
        self.assertTrue(item.get_absolute_content_path().exists())

    def test_model_delete_removes_local_dir(self):
        """Regression: the pre_delete signal must be connected (see media/apps.py)."""
        item = self.make_item()
        base = item.get_base_dir()
        item.delete()
        self.assertFalse(base.exists())

    def test_usage_walks_local_disk(self):
        self.make_item(files={'content.m4a': b'A' * 1234})
        self.assertEqual(storage_usage_bytes(), 1234)

    def test_publish_media_command_requires_bucket(self):
        with self.assertRaises(CommandError):
            call_command('publish_media')

    def test_system_check_passes(self):
        self.assertEqual(check_remote_storage_config(), [])


class SystemCheckTest(S3Mixin, TestCase):
    def test_bucket_without_public_base_url_is_an_error(self):
        with override_settings(STASHCAST_MEDIA_BASE_URL=None):
            errors = check_remote_storage_config()
        self.assertEqual([e.id for e in errors], ['stashcast.E001'])

    def test_bucket_with_base_url_passes(self):
        self.assertEqual(check_remote_storage_config(), [])


class FinalizeItemTest(S3Mixin, TestCase):
    def make_tmp(self, item):
        tmp_dir = self.media_dir / f'tmp-{item.guid}'
        tmp_dir.mkdir()
        (tmp_dir / 'content.m4a').write_bytes(b'A' * 10)
        (tmp_dir / 'download.log').write_text('started\n')
        return tmp_dir

    def test_moves_publishes_and_marks_ready(self):
        item = MediaItem.objects.create(
            source_url='https://example.com/x',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='finalized',
            status=MediaItem.STATUS_PROCESSING,
            content_path='content.m4a',
        )
        tmp_dir = self.make_tmp(item)

        final_dir = finalize_item(item, tmp_dir)

        self.assertFalse(tmp_dir.exists())
        self.assertEqual(final_dir, self.media_dir / 'finalized')
        self.assertEqual(self.keys(), ['finalized/content.m4a'])
        item.refresh_from_db()
        self.assertEqual(item.status, MediaItem.STATUS_READY)
        self.assertIsNotNone(item.downloaded_at)
        log = (final_dir / 'download.log').read_text()
        self.assertIn('PUBLISHED TO REMOTE STORAGE', log)

    def test_publish_failure_is_logged_in_final_dir(self):
        item = MediaItem.objects.create(
            source_url='https://example.com/x',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='broken',
            status=MediaItem.STATUS_PROCESSING,
            content_path='content.m4a',
        )
        tmp_dir = self.make_tmp(item)
        self.s3.delete_bucket(Bucket=BUCKET)

        with self.assertRaises(Exception):
            finalize_item(item, tmp_dir)

        self.assertFalse(tmp_dir.exists())
        log = (self.media_dir / 'broken' / 'download.log').read_text()
        self.assertIn('Publishing to remote storage failed', log)
        item.refresh_from_db()
        self.assertNotEqual(item.status, MediaItem.STATUS_READY)


class PublishMediaCommandTest(S3Mixin, TestCase):
    keep_local = True

    def run_command(self, *args):
        out = StringIO()
        call_command('publish_media', *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_backfills_ready_and_archived_items(self):
        self.make_item(slug='ready-one')
        self.make_item(slug='archived-one', status=MediaItem.STATUS_ARCHIVED)
        self.make_item(slug='errored', status=MediaItem.STATUS_ERROR)

        output = self.run_command()

        self.assertIn('Published 2', output)
        self.assertIn('ready-one/content.m4a', self.keys())
        self.assertIn('archived-one/content.m4a', self.keys())
        self.assertNotIn('errored/content.m4a', self.keys())

    def test_dry_run_uploads_nothing(self):
        self.make_item()
        output = self.run_command('--dry-run')
        self.assertIn('Would publish: my-talk', output)
        self.assertEqual(self.keys(), [])

    def test_skips_items_without_local_content(self):
        self.make_item(files={'subtitles.vtt': b'WEBVTT\n'})
        output = self.run_command()
        self.assertIn('Published 0, skipped 1', output)

    def test_slug_filter(self):
        self.make_item(slug='first')
        self.make_item(slug='second')
        self.run_command('--slug', 'second')
        self.assertEqual(self.keys()[0].split('/')[0], 'second')


@override_settings(STASHCAST_SUMMARY_SENTENCES=0)
class EndToEndPublishTest(S3Mixin, TestCase):
    """Stash a real file through the full pipeline (ffmpeg included) into the bucket."""

    def test_stash_publishes_and_feed_links_to_bucket(self):
        from media.tasks import process_media

        source = Path(settings.BASE_DIR) / 'demo_data' / 'pecha-kucha-aud' / 'aud.mp3'
        local_copy = self.media_dir.parent / f'{self.media_dir.name}-src.mp3'
        shutil.copy(source, local_copy)
        self.addCleanup(local_copy.unlink, missing_ok=True)

        item = MediaItem.objects.create(
            source_url=str(local_copy),
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='pending',
        )
        process_media(item.guid)
        item.refresh_from_db()

        self.assertEqual(item.status, MediaItem.STATUS_READY, item.error_message)
        content_key = f'{item.slug}/{item.content_path}'
        self.assertIn(content_key, self.keys())
        self.assertFalse(any(k.endswith('.log') for k in self.keys()))
        self.assertFalse(item.get_absolute_content_path().exists())
        self.assertFalse((self.media_dir / f'tmp-{item.guid}').exists())

        feed = self.client.get('/feeds/audio.xml').content.decode()
        self.assertIn(f'url="{BASE_URL}/{content_key}"', feed)
