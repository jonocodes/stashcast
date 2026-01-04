import os
import shutil
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from media.models import MediaItem


@receiver(pre_delete, sender=MediaItem)
def cleanup_media_files(sender, instance, **kwargs):
    """
    Delete associated files and directory when a MediaItem is deleted.
    This handles both single and bulk deletions.
    """
    base_dir = instance.get_base_dir()
    if base_dir and os.path.exists(base_dir):
        try:
            shutil.rmtree(base_dir)
        except Exception as e:
            # Log error but continue with deletion
            print(f"Error deleting directory {base_dir}: {e}")
