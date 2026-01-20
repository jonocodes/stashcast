"""
URL configuration for stashcast project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import RedirectView

from media.feeds import ArchiveFeed, AudioFeed, CombinedFeed, VideoFeed
from media.views import (
    admin_spotify_confirm_view,
    admin_stash_confirm_multiple_view,
    admin_stash_form_view,
    admin_stash_progress_view,
    bookmarklet_view,
    feed_links_view,
    grid_view,
    home_view,
    item_archive_view,
    item_detail_view,
    item_unarchive_view,
    list_view,
    stash_progress_view,
    stash_status_stream,
    stash_view,
)

admin.site.site_header = 'StashCast Administration'  # default: "Django Administration"
# admin.site.index_title = "Features area"  # default: "Site administration"
admin.site.site_title = 'StashCast site admin'  # default: "Django site admin"


urlpatterns = [
    # Favicon
    path(
        'favicon.ico',
        RedirectView.as_view(url='/static/media/favicon.ico', permanent=True),
        name='favicon',
    ),
    # Landing page
    path('', home_view, name='home'),
    # Custom admin tools (must come before admin.site.urls)
    path('admin/tools/bookmarklet/', bookmarklet_view, name='bookmarklet'),
    path('admin/tools/feeds/', feed_links_view, name='feed_links'),
    path('admin/tools/add-url/', admin_stash_form_view, name='admin_stash_form'),
    path(
        'admin/tools/add-url/confirm-multiple/',
        admin_stash_confirm_multiple_view,
        name='admin_stash_confirm_multiple',
    ),
    path(
        'admin/tools/add-url/spotify/',
        admin_spotify_confirm_view,
        name='admin_spotify_confirm',
    ),
    path(
        'admin/tools/add-url/progress/<str:guid>/',
        admin_stash_progress_view,
        name='admin_stash_progress',
    ),
    path('admin/tools/grid/', grid_view, name='grid_view'),
    path('admin/tools/list/', list_view, name='list_view'),
    path('admin/tools/item/<str:guid>/', item_detail_view, name='item_detail'),
    path('admin/tools/item/<str:guid>/archive/', item_archive_view, name='item_archive'),
    path('admin/tools/item/<str:guid>/unarchive/', item_unarchive_view, name='item_unarchive'),
    # Redirect admin index to grid view (must come before admin.site.urls)
    re_path(r'^admin/$', RedirectView.as_view(url='/admin/tools/grid/', permanent=False)),
    # Standard admin (includes django-huey-monitor integration)
    path('admin/', admin.site.urls),
    # Public endpoints
    path('stash/', stash_view, name='stash'),
    path('stash/<str:guid>/progress/', stash_progress_view, name='stash_progress'),
    path('stash/<str:guid>/stream/', stash_status_stream, name='stash_status_stream'),
    path('feeds/audio.xml', AudioFeed(), name='audio_feed'),
    path('feeds/video.xml', VideoFeed(), name='video_feed'),
    path('feeds/combined.xml', CombinedFeed(), name='combined_feed'),
    path('feeds/archive.xml', ArchiveFeed(), name='archive_feed'),
]

# Serve media files in development
if not settings.STASHCAST_MEDIA_BASE_URL:
    urlpatterns += static('/media/files/', document_root=settings.MEDIA_ROOT)
