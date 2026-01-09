"""Context processors for media app."""
from django.conf import settings


def stashcast_settings(request):
    """Make StashCast settings available to all templates."""
    return {
        'user_token': settings.STASHCAST_USER_TOKEN,
        'require_user_token_for_feeds': settings.REQUIRE_USER_TOKEN_FOR_FEEDS,
    }
