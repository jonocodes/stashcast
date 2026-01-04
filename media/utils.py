import re
from django.conf import settings
from nanoid import generate


def generate_slug(title, max_words=None, max_chars=None):
    """
    Generate a slug from a title.

    Args:
        title: The title to slugify
        max_words: Maximum number of words (default from settings)
        max_chars: Maximum number of characters (default from settings)

    Returns:
        A slugified string
    """
    if max_words is None:
        max_words = settings.STASHCAST_SLUG_MAX_WORDS
    if max_chars is None:
        max_chars = settings.STASHCAST_SLUG_MAX_CHARS

    # Convert to lowercase
    slug = title.lower()

    # Replace non-alphanumeric characters with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', slug)

    # Remove leading/trailing hyphens
    slug = slug.strip('-')

    # Split into words
    words = slug.split('-')

    # Limit by max words
    words = words[:max_words]

    # Join and truncate by max chars
    slug = '-'.join(words)[:max_chars]

    # Remove trailing hyphen if truncation created one
    slug = slug.rstrip('-')

    return slug or 'untitled'


def ensure_unique_slug(slug, source_url, existing_item=None, media_type=None):
    """
    Ensure slug is unique for the given media_type, handling same URL reuse and conflicts.

    Uniqueness is enforced on (slug, media_type) combination, not slug alone.
    This allows the same slug to be used for both audio and video versions,
    with files stored in separate directories (audio/{slug}/ vs video/{slug}/).

    Args:
        slug: The proposed slug
        source_url: The source URL for this item
        existing_item: Optional existing MediaItem if reusing same URL+type
        media_type: The media type (audio/video) to differentiate same URL downloads

    Returns:
        A unique slug for this media_type
    """
    from media.models import MediaItem

    # If this is for an existing item with the same URL and type, reuse its slug
    if existing_item:
        return existing_item.slug

    # Check if this slug + media_type combination already exists
    if media_type:
        existing = MediaItem.objects.filter(slug=slug, media_type=media_type).first()
    else:
        existing = MediaItem.objects.filter(slug=slug).first()

    if not existing:
        # Slug is unique for this media_type
        return slug

    if existing.source_url == source_url and existing.media_type == media_type:
        # Same URL and same type, reuse the slug
        return slug

    # Different URL but same slug+type conflict, append NanoID
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    nano_suffix = generate(alphabet, size=8)
    return f"{slug}-{nano_suffix}"
