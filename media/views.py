from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from media.models import MediaItem
from media.tasks import process_media


def _build_media_url(item, filename, request=None):
    """Build absolute or relative URL for a media file."""
    rel_path = item.get_relative_path(filename)
    if not rel_path:
        return None

    if settings.STASHCAST_MEDIA_BASE_URL:
        return f"{settings.STASHCAST_MEDIA_BASE_URL.rstrip('/')}/{rel_path}"

    if request:
        return request.build_absolute_uri(f'/media/files/{rel_path}')

    return f'/media/files/{rel_path}'


def home_view(request):
    """Landing page with quick access to add URLs."""
    return render(request, 'media/home.html')


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

    # Check if item already exists for this URL and requested type combination
    # For 'auto', match with other 'auto' requests
    # For 'audio'/'video', match with items that have that media_type
    existing_item = None

    if requested_type == 'auto':
        # Match with existing 'auto' requests
        existing_item = MediaItem.objects.filter(
            source_url=url,
            requested_type='auto'
        ).first()
    else:
        # Match with items that have the same media_type as requested
        existing_item = MediaItem.objects.filter(
            source_url=url,
            media_type=requested_type
        ).first()

    if existing_item:
        # Reuse existing item - overwrite behavior
        item = existing_item
        item.requested_type = requested_type
        item.status = MediaItem.STATUS_PREFETCHING
        item.error_message = ''
        item.save()

        # Log the overwrite
        from media.tasks import write_log
        log_path = item.get_absolute_log_path()
        if log_path:
            write_log(log_path, f"=== OVERWRITE REQUEST ===")
            write_log(log_path, f"Re-fetching URL with type: {requested_type}")
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
    media_url = _build_media_url(item, item.content_path, request)

    # Build thumbnail URL
    thumbnail_url = _build_media_url(item, item.thumbnail_path, request)

    # Build subtitle URL
    subtitle_url = _build_media_url(item, item.subtitle_path, request)

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
            # Check if item already exists for this URL and requested type combination
            existing_item = None

            if media_type == 'auto':
                # Match with existing 'auto' requests
                existing_item = MediaItem.objects.filter(
                    source_url=url,
                    requested_type='auto'
                ).first()
            else:
                # Match with items that have the same media_type as requested
                existing_item = MediaItem.objects.filter(
                    source_url=url,
                    media_type=media_type
                ).first()

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
        'title': 'Add URL to StashCast',
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


def view_combined_feed_xml(request):
    """View combined feed XML inline in browser"""
    from media.feeds import CombinedFeed
    feed = CombinedFeed()
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
    import os

    # Get filter parameters
    media_type = request.GET.get('type', 'all')
    status = request.GET.get('status', 'all')

    # Build queryset
    items = MediaItem.objects.all().order_by('-created_at')

    if media_type != 'all':
        items = items.filter(media_type=media_type)

    if status != 'all':
        items = items.filter(status=status)

    # Calculate total storage used by checking media directories
    total_storage_bytes = 0
    media_root = Path(settings.MEDIA_ROOT)

    if media_root.exists():
        for dirpath, dirnames, filenames in os.walk(media_root):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                try:
                    total_storage_bytes += filepath.stat().st_size
                except (OSError, FileNotFoundError):
                    pass

    # Build thumbnail URLs for each item
    items_with_urls = []
    for item in items:
        thumbnail_url = None
        if item.thumbnail_path:
            thumbnail_url = _build_media_url(item, item.thumbnail_path, request)

        items_with_urls.append({
            'item': item,
            'thumbnail_url': thumbnail_url,
        })

    context = {
        'items': items_with_urls,
        'media_type_filter': media_type,
        'status_filter': status,
        'title': 'Media Grid',
        'total_storage_bytes': total_storage_bytes,
    }

    return render(request, 'media/grid_view.html', context)


@staff_member_required
def list_view(request):
    """
    List view of all media items.

    Shows items in a list format with thumbnails, descriptions, and metadata.
    """
    from pathlib import Path
    import os

    # Get filter parameters
    media_type = request.GET.get('type', 'all')
    status = request.GET.get('status', 'all')

    # Build queryset
    items = MediaItem.objects.all().order_by('-created_at')

    if media_type != 'all':
        items = items.filter(media_type=media_type)

    if status != 'all':
        items = items.filter(status=status)

    # Calculate total storage used by checking media directories
    total_storage_bytes = 0
    media_root = Path(settings.MEDIA_ROOT)

    if media_root.exists():
        for dirpath, dirnames, filenames in os.walk(media_root):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                try:
                    total_storage_bytes += filepath.stat().st_size
                except (OSError, FileNotFoundError):
                    pass

    # Build thumbnail URLs for each item
    items_with_urls = []
    for item in items:
        thumbnail_url = None
        if item.thumbnail_path:
            thumbnail_url = _build_media_url(item, item.thumbnail_path, request)

        items_with_urls.append({
            'item': item,
            'thumbnail_url': thumbnail_url,
        })

    context = {
        'items': items_with_urls,
        'media_type_filter': media_type,
        'status_filter': status,
        'title': 'Media List',
        'total_storage_bytes': total_storage_bytes,
    }

    return render(request, 'media/list_view.html', context)
