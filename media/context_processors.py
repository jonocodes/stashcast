"""Context processors for media app."""
from django.conf import settings


def stashcast_settings(request):
    """Make StashCast settings available to all templates."""
    return {
        'api_key': settings.STASHCAST_API_KEY,
        'require_api_key_for_feeds': settings.REQUIRE_API_KEY_FOR_FEEDS,
    }
