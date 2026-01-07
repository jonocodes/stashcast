import json
import time

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from media.models import MediaItem
from media.tasks import process_media
from media.utils import build_media_url


def _build_media_url(item, filename, request=None):
    """Build absolute or relative URL for a media file."""
    return build_media_url(item, filename, request=request)


def home_view(request):
    """Landing page with quick access to add URLs."""
    return render(request, 'media/home.html')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def stash_view(request):
    """
    Public endpoint to stash a URL for download.

    Params:
        apikey (required): API key for authentication
        url (required): URL to download
        type (required): auto|audio|video
        redirect (optional): If 'progress', redirect to progress page instead of returning JSON

    Returns:
        JSON response with item details, or redirect to progress page
    """
    # Check API key
    api_key = request.GET.get('apikey') or request.POST.get('apikey')
    if not api_key or api_key != settings.STASHCAST_API_KEY:
        return JsonResponse({'error': 'Invalid or missing API key'}, status=403)

    # Get parameters
    url = request.GET.get('url') or request.POST.get('url')
    requested_type = request.GET.get('type') or request.POST.get('type')
    redirect_param = request.GET.get('redirect') or request.POST.get('redirect')
    close_tab_after = request.GET.get('closeTabAfter') or request.POST.get('closeTabAfter')

    if not url:
        return JsonResponse({'error': 'Missing required parameter: url'}, status=400)

    if not requested_type or requested_type not in ['auto', 'audio', 'video']:
        return JsonResponse(
            {'error': 'Invalid type parameter. Must be: auto, audio, or video'},
            status=400,
        )

    # Check if item already exists for this URL and requested type combination
    # For 'auto', match with other 'auto' requests
    # For 'audio'/'video', match with items that have that media_type
    existing_item = None

    if requested_type == 'auto':
        # Match with existing 'auto' requests
        existing_item = MediaItem.objects.filter(source_url=url, requested_type='auto').first()
    else:
        # Match with items that have the same media_type as requested
        existing_item = MediaItem.objects.filter(source_url=url, media_type=requested_type).first()

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
            write_log(log_path, '=== OVERWRITE REQUEST ===')
            write_log(log_path, f'Re-fetching URL with type: {requested_type}')
    else:
        # Create new item
        item = MediaItem.objects.create(
            source_url=url,
            requested_type=requested_type,
            slug='pending',  # Will be set during processing
        )

    # Enqueue processing task
    process_media(item.guid)

    # Check if redirect to progress page is requested
    if redirect_param == 'progress':
        progress_url = request.build_absolute_uri(f'/stash/{item.guid}/progress/')
        if close_tab_after:
            progress_url = f'{progress_url}?closeTabAfter={close_tab_after}'
        return redirect(progress_url)

    # Return JSON response (default behavior for API compatibility)
    return JsonResponse(
        {
            'success': True,
            'guid': item.guid,
            'url': url,
            'type': requested_type,
            'status': item.status,
            'detail_url': request.build_absolute_uri(f'/admin/tools/item/{item.guid}/'),
        }
    )


@staff_member_required
def item_detail_view(request, guid):
    """
    Admin episode page.

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
        **admin.site.each_context(request),
        'item': item,
        'media_url': media_url,
        'thumbnail_url': thumbnail_url,
        'subtitle_url': subtitle_url,
    }

    return render(request, 'admin/item_detail.html', context)


@staff_member_required
def bookmarklet_view(request):
    """
    Admin tool page for bookmarklet configuration.

    Allows configuring and generating bookmarklets for one-click stashing.
    """
    from media.admin import is_demo_readonly

    # Use a bogus API key for demo users so their bookmarklet won't work
    api_key = (
        'demo-user-no-access' if is_demo_readonly(request.user) else settings.STASHCAST_API_KEY
    )

    context = {
        **admin.site.each_context(request),
        'base_url': request.build_absolute_uri('/').rstrip('/'),
        'api_key': api_key,
        'title': 'Bookmarklet',
    }

    return render(request, 'admin/bookmarklet.html', context)


@staff_member_required
def admin_stash_form_view(request):
    """
    Admin form for stashing URLs.

    Simple form interface in the admin to add URLs for download.
    """
    from django.contrib import messages

    from media.admin import is_demo_readonly

    if request.method == 'POST':
        # Block demo users from submitting
        if is_demo_readonly(request.user):
            messages.error(request, 'Demo users are not allowed to add URLs.')
            return redirect(request.path)

        url = request.POST.get('url', '').strip()
        media_type = request.POST.get('type', 'auto')

        if url:
            # Check if item already exists for this URL and requested type combination
            existing_item = None

            if media_type == 'auto':
                # Match with existing 'auto' requests
                existing_item = MediaItem.objects.filter(
                    source_url=url, requested_type='auto'
                ).first()
            else:
                # Match with items that have the same media_type as requested
                existing_item = MediaItem.objects.filter(
                    source_url=url, media_type=media_type
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
                    source_url=url, requested_type=media_type, slug='pending'
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
        **admin.site.each_context(request),
        'recent_items': recent_items,
        'title': 'Add URL to StashCast',
    }

    return render(request, 'admin/admin_stash_form.html', context)


@staff_member_required
def grid_view(request):
    """
    Grid view of all media items (YouTube-style).

    Shows thumbnails in a responsive grid with filtering options.
    """
    import os
    from pathlib import Path

    # Get filter parameters
    media_type = request.GET.get('type', 'all')

    # Build queryset - only show READY items
    items = MediaItem.objects.filter(status=MediaItem.STATUS_READY).order_by('-created_at')

    if media_type != 'all':
        items = items.filter(media_type=media_type)

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

        items_with_urls.append(
            {
                'item': item,
                'thumbnail_url': thumbnail_url,
            }
        )

    context = {
        **admin.site.each_context(request),
        'items': items_with_urls,
        'media_type_filter': media_type,
        'title': 'Media Grid',
        'total_storage_bytes': total_storage_bytes,
    }

    return render(request, 'admin/grid_view.html', context)


@staff_member_required
def list_view(request):
    """
    List view of all media items.

    Shows items in a list format with thumbnails, descriptions, and metadata.
    """
    import os
    from pathlib import Path

    # Get filter parameters
    media_type = request.GET.get('type', 'all')

    # Build queryset - only show READY items
    items = MediaItem.objects.filter(status=MediaItem.STATUS_READY).order_by('-created_at')

    if media_type != 'all':
        items = items.filter(media_type=media_type)

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

        items_with_urls.append(
            {
                'item': item,
                'thumbnail_url': thumbnail_url,
            }
        )

    context = {
        **admin.site.each_context(request),
        'items': items_with_urls,
        'media_type_filter': media_type,
        'title': 'Media List',
        'total_storage_bytes': total_storage_bytes,
    }

    return render(request, 'admin/list_view.html', context)


def stash_progress_view(request, guid):
    """
    Progress page for a stash operation using SSE for live updates.

    Displays real-time status updates for a media item being processed.
    """
    item = get_object_or_404(MediaItem, guid=guid)

    context = {
        'item': item,
        'guid': guid,
    }
    return render(request, 'media/stash_progress.html', context)


def stash_status_stream(request, guid):
    """
    SSE endpoint that streams status updates for a media item.

    Returns Server-Sent Events with the current status of the item.
    """

    def event_stream():
        last_status = None

        while True:
            try:
                # Refresh the item from database
                item = MediaItem.objects.get(guid=guid)

                # Only send event if status changed
                if item.status != last_status:
                    data = {
                        'status': item.status,
                        'title': item.title or 'Loading...',
                        'error_message': item.error_message,
                        'media_type': item.media_type,
                        'is_ready': item.status == MediaItem.STATUS_READY,
                        'has_error': item.status == MediaItem.STATUS_ERROR,
                        'detail_url': request.build_absolute_uri(f'/admin/tools/item/{guid}/'),
                    }

                    yield f'data: {json.dumps(data)}\n\n'
                    last_status = item.status

                    # If processing is complete or failed, stop streaming
                    if item.status in [MediaItem.STATUS_READY, MediaItem.STATUS_ERROR]:
                        yield 'event: complete\ndata: {}\n\n'
                        break

                # Wait before next check
                time.sleep(1)

            except MediaItem.DoesNotExist:
                # Item was deleted
                yield 'event: error\ndata: {"error": "Item not found"}\n\n'
                break
            except Exception as e:
                # Log error but continue
                yield f'event: error\ndata: {{"error": "{str(e)}"}}\n\n'
                break

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
