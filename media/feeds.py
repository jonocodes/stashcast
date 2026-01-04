from django.conf import settings
from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Rss201rev2Feed

from media.models import MediaItem


class AudioFeed(Feed):
    """Podcast feed for audio items"""
    feed_type = Rss201rev2Feed
    title = "StashCast Audio Feed"
    link = "/feeds/audio.xml"
    description = "Downloaded audio content"

    def items(self):
        return MediaItem.objects.filter(
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY
        ).order_by('-publish_date', '-downloaded_at')[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        if item.summary:
            return f"{item.summary}\n\n{item.description}"
        return item.description

    def item_link(self, item):
        return f"/items/{item.guid}/"

    def item_guid(self, item):
        return item.guid

    def item_pubdate(self, item):
        return item.publish_date or item.downloaded_at

    def item_author_name(self, item):
        return item.author

    def item_enclosure_url(self, item):
        if settings.STASHCAST_MEDIA_BASE_URL and item.content_path:
            rel_path = f'audio/{item.slug}/{item.content_path}'
            return f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path}"
        elif item.content_path:
            # Use Django static files - build relative path from slug and filename
            rel_path = f'audio/{item.slug}/{item.content_path}'
            return f"/media/files/{rel_path}"
        return ""

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        return item.mime_type or 'audio/mp4'


class VideoFeed(Feed):
    """Podcast feed for video items"""
    feed_type = Rss201rev2Feed
    title = "StashCast Video Feed"
    link = "/feeds/video.xml"
    description = "Downloaded video content"

    def items(self):
        return MediaItem.objects.filter(
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY
        ).order_by('-publish_date', '-downloaded_at')[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        if item.summary:
            return f"{item.summary}\n\n{item.description}"
        return item.description

    def item_link(self, item):
        return f"/items/{item.guid}/"

    def item_guid(self, item):
        return item.guid

    def item_pubdate(self, item):
        return item.publish_date or item.downloaded_at

    def item_author_name(self, item):
        return item.author

    def item_enclosure_url(self, item):
        if settings.STASHCAST_MEDIA_BASE_URL and item.content_path:
            rel_path = f'video/{item.slug}/{item.content_path}'
            return f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path}"
        elif item.content_path:
            # Use Django static files - build relative path from slug and filename
            rel_path = f'video/{item.slug}/{item.content_path}'
            return f"/media/files/{rel_path}"
        return ""

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        return item.mime_type or 'video/mp4'
