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
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from media.views import (
    stash_view, item_detail_view, bookmarklet_view, admin_stash_form_view,
    view_audio_feed_xml, view_video_feed_xml, grid_view, list_view
)
from media.feeds import AudioFeed, VideoFeed

urlpatterns = [
    # Custom admin tools (must come before admin.site.urls)
    path('admin/tools/bookmarklet/', bookmarklet_view, name='bookmarklet'),
    path('admin/tools/add-url/', admin_stash_form_view, name='admin_stash_form'),
    path('admin/tools/grid/', grid_view, name='grid_view'),
    path('admin/tools/list/', list_view, name='list_view'),

    # Standard admin (includes django-huey-monitor integration)
    path('admin/', admin.site.urls),

    # Public endpoints
    path('stash/', stash_view, name='stash'),
    path('items/<str:guid>/', item_detail_view, name='item_detail'),
    path('feeds/audio.xml', AudioFeed(), name='audio_feed'),
    path('feeds/video.xml', VideoFeed(), name='video_feed'),
    path('feeds/audio-view.xml', view_audio_feed_xml, name='audio_feed_view'),
    path('feeds/video-view.xml', view_video_feed_xml, name='video_feed_view'),
]

# Serve media files in development
if not settings.STASHCAST_MEDIA_BASE_URL:
    urlpatterns += static('/media/files/', document_root=settings.MEDIA_ROOT)
