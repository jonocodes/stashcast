from django.conf import settings
from django.contrib.syndication.views import Feed
from django.http import HttpResponseForbidden
from django.templatetags.static import static
from django.utils import timezone
from django.utils.feedgenerator import Rss201rev2Feed

from media.models import MediaItem
from media.utils import build_media_url


class StashcastRSSFeed(Rss201rev2Feed):
    """
    RSS 2.0 feed generator that always emits an <image> tag when provided.
    Some podcast clients ignore relative URLs, so we ensure image URLs are absolute.
    """

    def rss_attributes(self):
        attrs = super().rss_attributes()
        attrs['xmlns:media'] = 'http://search.yahoo.com/mrss/'
        attrs['xmlns:itunes'] = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
        attrs['xmlns:podcast'] = 'https://podcastindex.org/namespace/1.0'
        return attrs

    def latest_post_date(self):
        """Override to always use current time for lastBuildDate."""
        # Check if we have an explicit lastBuildDate in feed dict
        last_build = self.feed.get('lastBuildDate')
        if last_build:
            return last_build
        # Otherwise call parent implementation
        return super().latest_post_date()

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
        image = self.feed.get('image')
        if image and image.get('url'):
            handler.startElement('image', {})
            handler.addQuickElement('url', image.get('url'))
            handler.addQuickElement('title', image.get('title', ''))
            handler.addQuickElement('link', image.get('link', ''))
            handler.endElement('image')

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        thumbnail = item.get('thumbnail')
        if thumbnail:
            handler.addQuickElement('media:thumbnail', '', {'url': thumbnail})
            # Add iTunes-specific image tag for Apple Podcasts
            handler.addQuickElement('itunes:image', '', {'href': thumbnail})
        media_content = item.get('media_content')
        if media_content:
            handler.addQuickElement(
                'media:content',
                '',
                {
                    'url': media_content.get('url', ''),
                    'type': media_content.get('type', ''),
                    'medium': media_content.get('medium', ''),
                },
            )
        transcript = item.get('transcript')
        if transcript:
            handler.addQuickElement(
                'podcast:transcript',
                '',
                {
                    'url': transcript,
                    'type': 'text/vtt',
                    'language': 'en',
                },
            )


class BaseFeed(Feed):
    """Shared feed helpers."""

    logo_filename = None
    feed_type = StashcastRSSFeed
    absolute_link = None

    def __call__(self, request, *args, **kwargs):
        # Check if API key is required for feeds
        if settings.REQUIRE_API_KEY_FOR_FEEDS:
            api_key = request.GET.get('apikey')
            if not api_key or api_key != settings.STASHCAST_API_KEY:
                return HttpResponseForbidden(
                    'API key required. Add ?apikey=YOUR_KEY to the feed URL.'
                )

        # Store request so we can build absolute URLs everywhere
        self.request = request
        # Precompute absolute link for the channel
        self.absolute_link = request.build_absolute_uri(self.link)
        response = super().__call__(request, *args, **kwargs)

        # If ?view=1 is present, force browser to display XML instead of downloading
        if request.GET.get('view') == '1':
            response['Content-Type'] = 'text/xml; charset=utf-8'

        return response

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

    def feed_pubdate(self):
        """Use current time for lastBuildDate/pubDate."""
        return timezone.now()

    def get_queryset(self):
        """Base queryset for feed items; subclasses can further filter."""
        return MediaItem.objects.filter(status=MediaItem.STATUS_READY)

    def feed_extra_kwargs(self, obj):
        extra = super().feed_extra_kwargs(obj) or {}
        if self.logo_filename:
            extra['image'] = self._build_feed_image()
        # Use the most recent updated_at from all items
        items = self.get_queryset()
        latest_item = items.order_by('-updated_at').first()
        if latest_item and latest_item.updated_at:
            extra['lastBuildDate'] = latest_item.updated_at
        else:
            extra['lastBuildDate'] = timezone.now()
        return extra

    def latest_post_date(self, items):
        """Override to use the most recent updated_at from items."""
        if items:
            # Find the most recent updated_at from the items list
            latest = max(
                (
                    item.updated_at
                    for item in items
                    if hasattr(item, 'updated_at') and item.updated_at
                ),
                default=None,
            )
            if latest:
                return latest
        return timezone.now()

    def _build_feed_image(self):
        """Return dict for RSS image element with absolute URL."""
        rel_url = static(f'media/{self.logo_filename}')
        return {
            'url': self.absolute_url(rel_url),
            'title': self.title,
            'link': self.feed_url(),
        }

    def item_extra_kwargs(self, item):
        extra = super().item_extra_kwargs(item) or {}
        thumb_url = self._thumbnail_url(item)
        if thumb_url:
            extra['thumbnail'] = thumb_url
        media_content = self._media_content(item)
        if media_content:
            extra['media_content'] = media_content
        transcript_url = self._transcript_url(item)
        if transcript_url:
            extra['transcript'] = transcript_url
        return extra

    def _media_content(self, item):
        """Return media:content dict with medium/type/url for podcast clients."""
        enclosure_url = self.item_enclosure_url(item)
        if not enclosure_url:
            return None
        return {
            'url': self.absolute_url(enclosure_url),
            'type': self.item_enclosure_mime_type(item),
            'medium': ('video' if item.media_type == MediaItem.MEDIA_TYPE_VIDEO else 'audio'),
        }

    def _thumbnail_url(self, item):
        """Return absolute thumbnail URL for an item, if available."""
        return build_media_url(item, item.thumbnail_path, absolute_builder=self.absolute_url)

    def _transcript_url(self, item):
        """Return absolute transcript/subtitle URL for an item, if available."""
        return build_media_url(item, item.subtitle_path, absolute_builder=self.absolute_url)

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        if item.summary:
            return f'{item.summary}\n\n{item.description}'
        return item.description

    def item_link(self, item):
        return self.absolute_url(f'/admin/tools/item/{item.guid}/')

    def item_guid(self, item):
        return item.guid

    def item_pubdate(self, item):
        return item.publish_date or item.downloaded_at

    def item_author_name(self, item):
        return item.author

    def item_enclosure_url(self, item):
        url = build_media_url(item, item.content_path, absolute_builder=self.absolute_url)
        return url or ''

    def item_enclosure_length(self, item):
        return item.file_size or 0

    def item_enclosure_mime_type(self, item):
        if item.mime_type:
            return item.mime_type
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            return 'audio/mp4'
        if item.media_type == MediaItem.MEDIA_TYPE_VIDEO:
            return 'video/mp4'
        return 'application/octet-stream'


class AudioFeed(BaseFeed):
    """Podcast feed for audio items"""

    title = 'StashCast Audio'
    link = '/feeds/audio.xml'
    description = 'Downloaded audio content'
    logo_filename = 'feed-logo-audio.png'

    def items(self):
        return self.get_queryset().order_by('-publish_date', '-downloaded_at')[:100]

    def get_queryset(self):
        return MediaItem.objects.filter(
            media_type=MediaItem.MEDIA_TYPE_AUDIO, status=MediaItem.STATUS_READY
        )


class VideoFeed(BaseFeed):
    """Podcast feed for video items"""

    title = 'StashCast Video'
    link = '/feeds/video.xml'
    description = 'Downloaded video content'
    logo_filename = 'feed-logo-video.png'

    def items(self):
        return self.get_queryset().order_by('-publish_date', '-downloaded_at')[:100]

    def get_queryset(self):
        return MediaItem.objects.filter(
            media_type=MediaItem.MEDIA_TYPE_VIDEO, status=MediaItem.STATUS_READY
        )


class CombinedFeed(BaseFeed):
    """Podcast feed for all media items (audio and video)"""

    title = 'StashCast'
    link = '/feeds/combined.xml'
    description = 'Downloaded audio and video content'
    logo_filename = 'feed-logo-combined.png'

    def items(self):
        return self.get_queryset().order_by('-publish_date', '-downloaded_at')[:100]
