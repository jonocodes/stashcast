from django.db.models.signals import pre_delete
from django.dispatch import receiver

from media.models import MediaItem
from media.storage import delete_item_files


@receiver(pre_delete, sender=MediaItem)
def cleanup_media_files(sender, instance, **kwargs):
    """
    Delete associated files (local directory and published copy) when a MediaItem is
    deleted. This handles both single and bulk deletions.
    """
    delete_item_files(instance)
