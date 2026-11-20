"""
Long-term media storage.

Downloading and transcoding always happen on local disk (yt-dlp and ffmpeg need real
files). Once an item is finalized, ``publish_item`` copies its directory to the remote
storage configured under ``settings.STORAGES[STASHCAST_MEDIA_STORAGE_ALIAS]`` (an
S3-compatible bucket via django-storages). When no remote storage is configured, every
function here falls back to today's local-only behaviour.

Remote layout mirrors the local one: ``<prefix>/<slug>/<filename>``, so
``STASHCAST_MEDIA_BASE_URL`` + ``<slug>/<filename>`` is the public URL.
"""

import logging
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages

logger = logging.getLogger(__name__)

# Files that stay on local disk and are never published (they can contain local paths)
LOCAL_ONLY_SUFFIXES = {'.log'}


def get_remote_storage():
    """Return the configured remote storage, or None when media is local-only."""
    alias = settings.STASHCAST_MEDIA_STORAGE_ALIAS
    if alias not in settings.STORAGES:
        return None
    return storages[alias]


def remote_enabled():
    return get_remote_storage() is not None


def _object_key(storage, rel=''):
    """Full object key for a path relative to the storage location (STASHCAST_S3_PREFIX)."""
    location = (storage.location or '').strip('/')
    return f'{location}/{rel}' if location else rel


def _delete_remote_dir(storage, slug):
    # Trailing slash so deleting 'talk' never touches 'talk-part-2'
    storage.bucket.objects.filter(Prefix=_object_key(storage, f'{slug}/')).delete()


class PublishError(Exception):
    pass


def publish_item(item, log=None):
    """
    Upload an item's local directory to remote storage.

    Replaces anything previously published for the slug, so re-fetches don't leave stale
    files behind. Unless STASHCAST_S3_KEEP_LOCAL is set, the local content file is removed
    afterwards; logs and subtitles stay local (admin log view and summaries read them).

    No-op when remote storage isn't configured.
    """
    storage = get_remote_storage()
    if storage is None:
        return False

    def _log(message):
        if log:
            log(message)

    base_dir = item.get_base_dir()
    content_file = item.get_absolute_content_path()
    # Guard: never wipe the remote copy unless we have a full local copy to replace it.
    if not content_file or not content_file.exists():
        raise PublishError(f'Local content file missing for {item.slug}; refusing to publish')

    _delete_remote_dir(storage, item.slug)

    for path in sorted(p for p in base_dir.rglob('*') if p.is_file()):
        if path.suffix in LOCAL_ONLY_SUFFIXES:
            continue
        name = path.relative_to(base_dir.parent).as_posix()  # <slug>/<file>
        with path.open('rb') as fh:
            storage.save(name, File(fh, name=path.name))
        _log(f'Published: {name}')

    if not settings.STASHCAST_S3_KEEP_LOCAL:
        content_file.unlink()
        _log(f'Removed local content file: {content_file.name}')

    return True


def delete_item_files(item):
    """Delete an item's local directory and its published copy (if any)."""
    base_dir = item.get_base_dir()
    if base_dir and base_dir.exists():
        try:
            shutil.rmtree(base_dir)
        except Exception as e:
            logger.error('Error deleting directory %s: %s', base_dir, e)

    storage = get_remote_storage()
    if storage is not None and item.slug and item.slug != 'pending':
        try:
            _delete_remote_dir(storage, item.slug)
        except Exception as e:
            logger.error('Error deleting remote files for %s: %s', item.slug, e)


def is_published(item):
    """True if the item's content file exists in remote storage."""
    storage = get_remote_storage()
    rel = item.get_relative_path(item.content_path)
    return bool(storage is not None and rel and storage.exists(rel))


def storage_usage_bytes():
    """Total bytes used by media: the bucket when remote is enabled, else local disk."""
    storage = get_remote_storage()
    if storage is not None:
        objects = storage.bucket.objects.filter(Prefix=_object_key(storage))
        return sum(obj.size for obj in objects)

    total = 0
    media_root = Path(settings.MEDIA_ROOT)
    if media_root.exists():
        for dirpath, _dirnames, filenames in os.walk(media_root):
            for filename in filenames:
                try:
                    total += (Path(dirpath) / filename).stat().st_size
                except OSError:
                    pass
    return total


def check_remote_storage_config(app_configs=None, **kwargs):
    """Django system check: a bucket needs a public base URL for feeds to link to."""
    from django.core.checks import Error

    if remote_enabled() and not settings.STASHCAST_MEDIA_BASE_URL:
        return [
            Error(
                'STASHCAST_S3_BUCKET is set but STASHCAST_MEDIA_BASE_URL is not.',
                hint=(
                    "Set STASHCAST_MEDIA_BASE_URL to the bucket's public URL (e.g. an R2 "
                    'custom domain), including STASHCAST_S3_PREFIX if you use one.'
                ),
                id='stashcast.E001',
            )
        ]
    return []
