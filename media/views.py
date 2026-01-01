from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

from media.models import MediaItem
from media.tasks import process_media


@csrf_exempt
@require_http_methods(["GET", "POST"])
def stash_view(request):
    """
    Public endpoint to stash a URL for download.

    Params:
        apikey (required): API key for authentication
        url (required): URL to download
        type (required): auto|audio|video

    Returns:
        JSON response with item details
    """
    # Check API key
    api_key = request.GET.get('apikey') or request.POST.get('apikey')
    if not api_key or api_key != settings.STASHCAST_API_KEY:
        return JsonResponse({'error': 'Invalid or missing API key'}, status=403)

    # Get parameters
    url = request.GET.get('url') or request.POST.get('url')
    requested_type = request.GET.get('type') or request.POST.get('type')

    if not url:
        return JsonResponse({'error': 'Missing required parameter: url'}, status=400)

    if not requested_type or requested_type not in ['auto', 'audio', 'video']:
        return JsonResponse({'error': 'Invalid type parameter. Must be: auto, audio, or video'}, status=400)

    # Check if item already exists for this URL
    existing_item = MediaItem.objects.filter(source_url=url).first()

    if existing_item:
        # Reuse existing item - overwrite behavior
        item = existing_item
        item.requested_type = requested_type
        item.status = MediaItem.STATUS_PREFETCHING
        item.error_message = ''
        item.save()

        # Log the overwrite
        from media.tasks import write_log
        if item.log_path:
            write_log(item.log_path, f"=== OVERWRITE REQUEST ===")
            write_log(item.log_path, f"Re-fetching URL with type: {requested_type}")
    else:
        # Create new item
        item = MediaItem.objects.create(
            source_url=url,
            requested_type=requested_type,
            slug='pending'  # Will be set during processing
        )

    # Enqueue processing task
    process_media(item.guid)

    return JsonResponse({
        'success': True,
        'guid': item.guid,
        'url': url,
        'type': requested_type,
        'status': item.status,
        'detail_url': request.build_absolute_uri(f'/items/{item.guid}/'),
    })


def item_detail_view(request, guid):
    """
    Public episode page.

    Displays:
    - Title, thumbnail, description
    - Summary (if available)
    - Embedded audio/video player
    - Download links
    """
    item = get_object_or_404(MediaItem, guid=guid)

    # Build media URL
    if settings.STASHCAST_MEDIA_BASE_URL and item.content_path:
        # Use external CDN URL
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            rel_path = item.content_path.replace(str(settings.STASHCAST_AUDIO_DIR), 'audio')
        else:
            rel_path = item.content_path.replace(str(settings.STASHCAST_VIDEO_DIR), 'video')
        media_url = f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path.lstrip('/')}"
    elif item.content_path:
        # Use Django static files - convert absolute path to relative from MEDIA_ROOT
        from pathlib import Path
        rel_path = Path(item.content_path).relative_to(settings.MEDIA_ROOT)
        media_url = request.build_absolute_uri(f'/media/files/{rel_path}')
    else:
        media_url = None

    # Build thumbnail URL
    if settings.STASHCAST_MEDIA_BASE_URL and item.thumbnail_path:
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            rel_path = item.thumbnail_path.replace(str(settings.STASHCAST_AUDIO_DIR), 'audio')
        else:
            rel_path = item.thumbnail_path.replace(str(settings.STASHCAST_VIDEO_DIR), 'video')
        thumbnail_url = f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path.lstrip('/')}"
    elif item.thumbnail_path:
        # Use Django static files - convert absolute path to relative from MEDIA_ROOT
        from pathlib import Path
        rel_path = Path(item.thumbnail_path).relative_to(settings.MEDIA_ROOT)
        thumbnail_url = request.build_absolute_uri(f'/media/files/{rel_path}')
    else:
        thumbnail_url = None

    # Build subtitle URL
    if settings.STASHCAST_MEDIA_BASE_URL and item.subtitle_path:
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            rel_path = item.subtitle_path.replace(str(settings.STASHCAST_AUDIO_DIR), 'audio')
        else:
            rel_path = item.subtitle_path.replace(str(settings.STASHCAST_VIDEO_DIR), 'video')
        subtitle_url = f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path.lstrip('/')}"
    elif item.subtitle_path:
        # Use Django static files - convert absolute path to relative from MEDIA_ROOT
        from pathlib import Path
        rel_path = Path(item.subtitle_path).relative_to(settings.MEDIA_ROOT)
        subtitle_url = request.build_absolute_uri(f'/media/files/{rel_path}')
    else:
        subtitle_url = None

    context = {
        'item': item,
        'media_url': media_url,
        'thumbnail_url': thumbnail_url,
        'subtitle_url': subtitle_url,
    }

    return render(request, 'media/item_detail.html', context)


@staff_member_required
def bookmarklet_view(request):
    """
    Admin tool page for bookmarklet configuration.

    Allows configuring and generating bookmarklets for one-click stashing.
    """
    base_url = request.build_absolute_uri('/').rstrip('/')
    api_key = settings.STASHCAST_API_KEY

    context = {
        'base_url': base_url,
        'api_key': api_key,
    }

    return render(request, 'media/bookmarklet.html', context)


@staff_member_required
def admin_stash_form_view(request):
    """
    Admin form for stashing URLs.

    Simple form interface in the admin to add URLs for download.
    """
    from django.contrib import messages

    if request.method == 'POST':
        url = request.POST.get('url', '').strip()
        media_type = request.POST.get('type', 'auto')

        if url:
            # Create or get existing item
            existing_item = MediaItem.objects.filter(source_url=url).first()

            if existing_item:
                item = existing_item
                item.requested_type = media_type
                item.status = MediaItem.STATUS_PREFETCHING
                item.error_message = ''
                item.save()
                messages.info(request, f'Re-fetching existing item: {item.guid}')
            else:
                item = MediaItem.objects.create(
                    source_url=url,
                    requested_type=media_type,
                    slug='pending'
                )
                messages.success(request, f'Created new item: {item.guid}')

            # Enqueue processing
            process_media(item.guid)

            # Redirect to Huey monitor to see task progress
            return redirect('/admin/huey_monitor/taskmodel/')
        else:
            messages.error(request, 'Please provide a URL')

    # Get recent items
    recent_items = MediaItem.objects.all().order_by('-created_at')[:10]

    context = {
        'recent_items': recent_items,
        'title': 'Add URL to Stashcast',
    }

    return render(request, 'media/admin_stash_form.html', context)


def view_audio_feed_xml(request):
    """View audio feed XML inline in browser"""
    from media.feeds import AudioFeed
    feed = AudioFeed()
    response = feed(request)
    response['Content-Type'] = 'text/xml; charset=utf-8'
    return response


def view_video_feed_xml(request):
    """View video feed XML inline in browser"""
    from media.feeds import VideoFeed
    feed = VideoFeed()
    response = feed(request)
    response['Content-Type'] = 'text/xml; charset=utf-8'
    return response


@staff_member_required
def grid_view(request):
    """
    Grid view of all media items (YouTube-style).

    Shows thumbnails in a responsive grid with filtering options.
    """
    from pathlib import Path

    # Get filter parameters
    media_type = request.GET.get('type', 'all')
    status = request.GET.get('status', 'all')

    # Build queryset
    items = MediaItem.objects.all().order_by('-created_at')

    if media_type != 'all':
        items = items.filter(media_type=media_type)

    if status != 'all':
        items = items.filter(status=status)

    # Build thumbnail URLs for each item
    items_with_urls = []
    for item in items:
        thumbnail_url = None
        if item.thumbnail_path:
            if settings.STASHCAST_MEDIA_BASE_URL:
                if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                    rel_path = item.thumbnail_path.replace(str(settings.STASHCAST_AUDIO_DIR), 'audio')
                else:
                    rel_path = item.thumbnail_path.replace(str(settings.STASHCAST_VIDEO_DIR), 'video')
                thumbnail_url = f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path.lstrip('/')}"
            else:
                rel_path = Path(item.thumbnail_path).relative_to(settings.MEDIA_ROOT)
                thumbnail_url = f'/media/files/{rel_path}'

        items_with_urls.append({
            'item': item,
            'thumbnail_url': thumbnail_url,
        })

    context = {
        'items': items_with_urls,
        'media_type_filter': media_type,
        'status_filter': status,
        'title': 'Media Grid',
    }

    return render(request, 'media/grid_view.html', context)
