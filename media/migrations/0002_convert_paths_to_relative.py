# Generated manually for path conversion

from django.db import migrations
from pathlib import Path


def convert_paths_to_relative(apps, schema_editor):
    """Convert absolute paths to relative paths"""
    MediaItem = apps.get_model('media', 'MediaItem')

    for item in MediaItem.objects.all():
        changed = False

        # Convert content_path
        if item.content_path and '/' in item.content_path:
            # Extract just the filename from absolute path
            item.content_path = Path(item.content_path).name
            changed = True

        # Convert thumbnail_path
        if item.thumbnail_path and '/' in item.thumbnail_path:
            item.thumbnail_path = Path(item.thumbnail_path).name
            changed = True

        # Convert subtitle_path
        if item.subtitle_path and '/' in item.subtitle_path:
            item.subtitle_path = Path(item.subtitle_path).name
            changed = True

        # Convert log_path
        if item.log_path and '/' in item.log_path:
            item.log_path = Path(item.log_path).name
            changed = True

        if changed:
            item.save(update_fields=['content_path', 'thumbnail_path', 'subtitle_path', 'log_path'])


def reverse_conversion(apps, schema_editor):
    """This migration cannot be reversed automatically"""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('media', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(convert_paths_to_relative, reverse_conversion),
    ]
