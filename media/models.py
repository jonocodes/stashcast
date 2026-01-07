from pathlib import Path

from django.conf import settings
from django.db import models
from nanoid import generate


def generate_nanoid():
    """Generate NanoID with A-Z a-z 0-9 alphabet"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return generate(alphabet, size=21)


class MediaItem(models.Model):
    """Media item downloaded via yt-dlp or direct HTTP"""

    # Status choices
    STATUS_PREFETCHING = "PREFETCHING"
    STATUS_DOWNLOADING = "DOWNLOADING"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_READY = "READY"
    STATUS_ERROR = "ERROR"

    STATUS_CHOICES = [
        (STATUS_PREFETCHING, "Prefetching"),
        (STATUS_DOWNLOADING, "Downloading"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_ERROR, "Error"),
    ]

    # Media type choices
    MEDIA_TYPE_AUDIO = "audio"
    MEDIA_TYPE_VIDEO = "video"

    MEDIA_TYPE_CHOICES = [
        (MEDIA_TYPE_AUDIO, "Audio"),
        (MEDIA_TYPE_VIDEO, "Video"),
    ]

    # Requested type choices
    REQUESTED_TYPE_AUTO = "auto"
    REQUESTED_TYPE_AUDIO = "audio"
    REQUESTED_TYPE_VIDEO = "video"

    REQUESTED_TYPE_CHOICES = [
        (REQUESTED_TYPE_AUTO, "Auto"),
        (REQUESTED_TYPE_AUDIO, "Audio"),
        (REQUESTED_TYPE_VIDEO, "Video"),
    ]

    # Primary key
    guid = models.CharField(
        max_length=21, primary_key=True, default=generate_nanoid, editable=False
    )

    # Basic fields
    source_url = models.URLField(max_length=2048)
    slug = models.SlugField(max_length=100, db_index=True)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, blank=True)
    requested_type = models.CharField(max_length=10, choices=REQUESTED_TYPE_CHOICES)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PREFETCHING, db_index=True
    )

    # Metadata
    title = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    author = models.CharField(max_length=200, blank=True)
    publish_date = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)
    extractor = models.CharField(max_length=100, blank=True)
    external_id = models.CharField(max_length=200, blank=True)
    webpage_url = models.URLField(max_length=2048, blank=True)

    # File paths (relative to slug directory)
    content_path = models.CharField(max_length=500, blank=True)
    thumbnail_path = models.CharField(max_length=500, blank=True)
    subtitle_path = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)

    # Logging
    log_path = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)

    # Processing arguments
    ytdlp_args = models.TextField(blank=True, help_text="Additional yt-dlp arguments")
    ffmpeg_args = models.TextField(blank=True, help_text="Additional ffmpeg arguments")

    # Summary
    summary = models.TextField(blank=True)

    # Timestamps
    downloaded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-publish_date", "-downloaded_at"]
        indexes = [
            models.Index(fields=["source_url"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["status"]),
            models.Index(fields=["media_type"]),
        ]

    def __str__(self):
        return f"{self.title or self.source_url} ({self.guid})"

    @property
    def is_ready(self):
        return self.status == self.STATUS_READY

    @property
    def has_error(self):
        return self.status == self.STATUS_ERROR

    def get_base_dir(self):
        """Get absolute base directory path for this item's files"""
        if not self.slug or self.slug == "pending":
            return None
        return Path(settings.STASHCAST_MEDIA_DIR) / self.slug

    def get_relative_path(self, filename):
        """Build relative media path for the given filename"""
        if not filename or not self.slug or self.slug == "pending":
            return None
        return f"{self.slug}/{filename}"

    def get_absolute_content_path(self):
        """Get absolute path to content file"""
        if not self.content_path:
            return None
        base_dir = self.get_base_dir()
        if not base_dir:
            return None
        return base_dir / self.content_path

    def get_absolute_thumbnail_path(self):
        """Get absolute path to thumbnail file"""
        if not self.thumbnail_path:
            return None
        base_dir = self.get_base_dir()
        if not base_dir:
            return None
        return base_dir / self.thumbnail_path

    def get_absolute_subtitle_path(self):
        """Get absolute path to subtitle file"""
        if not self.subtitle_path:
            return None
        base_dir = self.get_base_dir()
        if not base_dir:
            return None
        return base_dir / self.subtitle_path

    def get_absolute_log_path(self):
        """Get absolute path to log file"""
        if not self.log_path:
            return None
        base_dir = self.get_base_dir()
        if not base_dir:
            return None
        return base_dir / self.log_path
