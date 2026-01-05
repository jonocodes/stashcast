from django.conf import settings
from django.contrib.syndication.views import Feed
from django.templatetags.static import static
from django.utils.feedgenerator import Rss201rev2Feed

from media.models import MediaItem


class StashcastRSSFeed(Rss201rev2Feed):
    """
    RSS 2.0 feed generator that always emits an <image> tag when provided.
    Some podcast clients ignore relative URLs, so we ensure image URLs are absolute.
    """

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
        image = self.feed.get('image')
        if image and image.get('url'):
            handler.startElement('image', {})
            handler.addQuickElement('url', image.get('url'))
            handler.addQuickElement('title', image.get('title', ''))
            handler.addQuickElement('link', image.get('link', ''))
            handler.endElement('image')


class BaseFeed(Feed):
    """Shared feed helpers."""
    logo_filename = None
    feed_type = StashcastRSSFeed
    absolute_link = None

    def __call__(self, request, *args, **kwargs):
        # Store request so we can build absolute URLs everywhere
        self.request = request
        # Precompute absolute link for the channel
        self.absolute_link = request.build_absolute_uri(self.link)
        return super().__call__(request, *args, **kwargs)

    def absolute_url(self, url):
        """Convert relative URLs to absolute using the current request."""
        if not url:
            return url
        if url.startswith('http://') or url.startswith('https://'):
            return url
        if getattr(self, 'request', None):
            return self.request.build_absolute_uri(url)
        return url

    def feed_url(self):
        """Ensure channel link is absolute."""
        if self.absolute_link:
            return self.absolute_link
        return self.absolute_url(self.link)

    def feed_extra_kwargs(self, obj):
        extra = super().feed_extra_kwargs(obj) or {}
        if self.logo_filename:
            extra['image'] = self._build_feed_image()
        return extra

    def _build_feed_image(self):
        """Return dict for RSS image element with absolute URL."""
        rel_url = static(f"media/{self.logo_filename}")
        return {
            'url': self.absolute_url(rel_url),
            'title': self.title,
            'link': self.feed_url(),
        }


class AudioFeed(BaseFeed):
    """Podcast feed for audio items"""
    title = "StashCast Audio Feed"
    link = "/feeds/audio.xml"
    description = "Downloaded audio content"
    logo_filename = "feed-logo-audio.png"

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
        return self.absolute_url(f"/items/{item.guid}/")

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
            return self.absolute_url(f"/media/files/{rel_path}")
        return ""

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        return item.mime_type or 'audio/mp4'


class VideoFeed(BaseFeed):
    """Podcast feed for video items"""
    title = "StashCast Video Feed"
    link = "/feeds/video.xml"
    description = "Downloaded video content"
    logo_filename = "feed-logo-video.png"

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
        return self.absolute_url(f"/items/{item.guid}/")

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
            return self.absolute_url(f"/media/files/{rel_path}")
        return ""

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        return item.mime_type or 'video/mp4'


class CombinedFeed(BaseFeed):
    """Podcast feed for all media items (audio and video)"""
    title = "StashCast Combined Feed"
    link = "/feeds/combined.xml"
    description = "Downloaded audio and video content"
    logo_filename = "feed-logo-combined.png"

    def items(self):
        return MediaItem.objects.filter(
            status=MediaItem.STATUS_READY
        ).order_by('-publish_date', '-downloaded_at')[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        if item.summary:
            return f"{item.summary}\n\n{item.description}"
        return item.description

    def item_link(self, item):
        return self.absolute_url(f"/items/{item.guid}/")

    def item_guid(self, item):
        return item.guid

    def item_pubdate(self, item):
        return item.publish_date or item.downloaded_at

    def item_author_name(self, item):
        return item.author

    def item_enclosure_url(self, item):
        if settings.STASHCAST_MEDIA_BASE_URL and item.content_path:
            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                rel_path = f'audio/{item.slug}/{item.content_path}'
            else:
                rel_path = f'video/{item.slug}/{item.content_path}'
            return f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path}"
        elif item.content_path:
            # Use Django static files - build relative path from slug and filename
            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                rel_path = f'audio/{item.slug}/{item.content_path}'
            else:
                rel_path = f'video/{item.slug}/{item.content_path}'
            return self.absolute_url(f"/media/files/{rel_path}")
        return ""

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            return item.mime_type or 'audio/mp4'
        else:
            return item.mime_type or 'video/mp4'
