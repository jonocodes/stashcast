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
from media.tasks import generate_summary, process_media, process_media_batch
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
        token (required): User token for authentication
        url (required): URL to download
        type (required): auto|audio|video
        allow_multiple (optional): If 'true', allow downloading multiple items
        redirect (optional): If 'progress', redirect to progress page instead of returning JSON

    Returns:
        JSON response with item details, or redirect to progress page
    """
    from media.service.strategy import choose_download_strategy
    from media.service.resolve import prefetch

    # Check user token
    user_token = request.GET.get('token') or request.POST.get('token')
    if not user_token or user_token != settings.STASHCAST_USER_TOKEN:
        return JsonResponse({'error': 'Invalid or missing user token'}, status=403)

    # Get parameters
    url = request.GET.get('url') or request.POST.get('url')
    requested_type = request.GET.get('type') or request.POST.get('type')
    redirect_param = request.GET.get('redirect') or request.POST.get('redirect')
    close_tab_after = request.GET.get('closeTabAfter') or request.POST.get('closeTabAfter')
    allow_multiple_param = request.GET.get('allow_multiple') or request.POST.get('allow_multiple')
    allow_multiple = allow_multiple_param in ['true', 'True', '1', 'yes']

    if not url:
        return JsonResponse({'error': 'Missing required parameter: url'}, status=400)

    if not requested_type or requested_type not in ['auto', 'audio', 'video']:
        return JsonResponse(
            {'error': 'Invalid type parameter. Must be: auto, audio, or video'},
            status=400,
        )

    # Check episode limit
    from media.tasks import check_episode_limit

    limit_error = check_episode_limit()
    if limit_error:
        if redirect_param == 'progress':
            item = MediaItem.objects.create(
                source_url=url,
                requested_type=requested_type,
                slug='pending',
                status=MediaItem.STATUS_ERROR,
                error_message=limit_error,
            )
            progress_url = request.build_absolute_uri(f'/stash/{item.guid}/progress/')
            if close_tab_after:
                progress_url = f'{progress_url}?closeTabAfter={close_tab_after}'
            return redirect(progress_url)
        return JsonResponse({'error': limit_error}, status=400)

    # Check for multiple items before processing
    strategy = choose_download_strategy(url)

    # Handle Spotify URLs - these require interactive YouTube selection
    if strategy == 'spotify':
        from media.service.spotify import resolve_spotify_url

        try:
            resolution = resolve_spotify_url(url, max_results=5)

            # Return YouTube search results for the client to choose from
            error_msg = (
                'Spotify content is DRM-protected and cannot be downloaded directly. '
                'Use the admin interface to select a YouTube source, or use one of the '
                'suggested YouTube URLs below.'
            )

            return JsonResponse(
                {
                    'error': error_msg,
                    'is_spotify': True,
                    'spotify_title': resolution.spotify_metadata.title,
                    'spotify_author': resolution.spotify_metadata.author,
                    'search_query': resolution.search_query,
                    'youtube_suggestions': [
                        {
                            'url': r.url,
                            'title': r.title,
                            'channel': r.channel,
                            'duration_seconds': r.duration_seconds,
                        }
                        for r in resolution.youtube_results
                    ],
                    'admin_url': request.build_absolute_uri('/admin/tools/add-url/'),
                },
                status=400,
            )
        except Exception as e:
            return JsonResponse(
                {'error': f'Failed to process Spotify URL: {str(e)}'},
                status=500,
            )

    if strategy == 'ytdlp':
        try:
            prefetch_result = prefetch(url, strategy, logger=None)
            if prefetch_result.is_multiple:
                count = len(prefetch_result.entries)

                if not allow_multiple:
                    error_msg = (
                        f'Found {count} items in this URL (playlist, channel, or page with '
                        f'multiple videos). Add allow_multiple=true parameter to proceed, '
                        f'or use the admin interface to confirm.'
                    )
                    # Handle redirect for progress page
                    if redirect_param == 'progress':
                        item = MediaItem.objects.create(
                            source_url=url,
                            requested_type=requested_type,
                            slug='pending',
                            status=MediaItem.STATUS_ERROR,
                            error_message=error_msg,
                        )
                        progress_url = request.build_absolute_uri(f'/stash/{item.guid}/progress/')
                        if close_tab_after:
                            progress_url = f'{progress_url}?closeTabAfter={close_tab_after}'
                        return redirect(progress_url)
                    # Return error with actionable message
                    return JsonResponse(
                        {
                            'error': error_msg,
                            'is_multiple': True,
                            'count': count,
                            'playlist_title': prefetch_result.playlist_title,
                            'entries': [
                                {'title': e.title, 'url': e.url}
                                for e in prefetch_result.entries[:10]  # Limit preview
                            ],
                        },
                        status=400,
                    )

                # allow_multiple is True - create items for each entry
                created_items = []
                created_guids = []
                for entry in prefetch_result.entries:
                    entry_url = entry.url
                    if not entry_url:
                        continue

                    # Check if item already exists
                    existing_item = None
                    if requested_type == 'auto':
                        existing_item = MediaItem.objects.filter(
                            source_url=entry_url, requested_type='auto'
                        ).first()
                    else:
                        existing_item = MediaItem.objects.filter(
                            source_url=entry_url, media_type=requested_type
                        ).first()

                    if existing_item:
                        item = existing_item
                        item.requested_type = requested_type
                        item.status = MediaItem.STATUS_PREFETCHING
                        item.error_message = ''
                        item.save()
                    else:
                        item = MediaItem.objects.create(
                            source_url=entry_url,
                            requested_type=requested_type,
                            slug='pending',
                        )

                    created_guids.append(item.guid)
                    created_items.append(
                        {
                            'guid': item.guid,
                            'url': entry_url,
                            'title': entry.title,
                        }
                    )

                # Use batch processing to avoid SQLite lock contention
                # This processes items sequentially with proper rate limiting
                if created_guids:
                    process_media_batch(created_guids)

                # Handle redirect for progress page (redirect to first item)
                if redirect_param == 'progress' and created_items:
                    first_guid = created_items[0]['guid']
                    progress_url = request.build_absolute_uri(f'/stash/{first_guid}/progress/')
                    # Build query params
                    params = []
                    if close_tab_after:
                        params.append(f'closeTabAfter={close_tab_after}')
                    params.append(f'multiCount={len(created_items)}')
                    if prefetch_result.playlist_title:
                        from urllib.parse import quote

                        params.append(f'playlistTitle={quote(prefetch_result.playlist_title)}')
                    if params:
                        progress_url = f'{progress_url}?{"&".join(params)}'
                    return redirect(progress_url)

                return JsonResponse(
                    {
                        'success': True,
                        'is_multiple': True,
                        'count': len(created_items),
                        'playlist_title': prefetch_result.playlist_title,
                        'items': created_items,
                    }
                )

        except Exception:
            # Prefetch failed (e.g. Apple Podcasts extractor broken).
            # Fall through to single-item flow — the download pipeline
            # has its own fallback extractors and error handling.
            pass

    # Single item flow
    # Check if item already exists for this URL and requested type combination
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

    # Use a bogus user token for demo users so their bookmarklet won't work
    user_token = (
        'demo-user-no-access' if is_demo_readonly(request.user) else settings.STASHCAST_USER_TOKEN
    )

    context = {
        **admin.site.each_context(request),
        'base_url': request.build_absolute_uri('/').rstrip('/'),
        'user_token': user_token,
        'require_user_token_for_feeds': settings.REQUIRE_USER_TOKEN_FOR_FEEDS,
        'title': 'Bookmarklet',
    }

    return render(request, 'admin/bookmarklet.html', context)


@staff_member_required
def feed_links_view(request):
    """
    Admin page showing RSS feed subscription links.

    Displays feed URLs with tokens for subscribing in podcast apps.
    """
    from media.admin import is_demo_readonly

    # Use a bogus user token for demo users
    user_token = (
        'demo-user-no-access' if is_demo_readonly(request.user) else settings.STASHCAST_USER_TOKEN
    )

    context = {
        **admin.site.each_context(request),
        'base_url': request.build_absolute_uri('/').rstrip('/'),
        'user_token': user_token,
        'require_user_token_for_feeds': settings.REQUIRE_USER_TOKEN_FOR_FEEDS,
        'title': 'Feed Links',
    }

    return render(request, 'admin/feed_links.html', context)


@staff_member_required
def admin_stash_form_view(request):
    """
    Admin form for stashing URLs.

    Simple form interface in the admin to add URLs for download.
    """
    from django.contrib import messages

    from media.admin import is_demo_readonly
    from media.service.strategy import choose_download_strategy
    from media.service.resolve import prefetch

    if request.method == 'POST':
        # Block demo users from submitting
        if is_demo_readonly(request.user):
            messages.error(request, 'Demo users are not allowed to add URLs.')
            return redirect(request.path)

        # Check episode limit
        from media.tasks import check_episode_limit

        limit_error = check_episode_limit()
        if limit_error:
            messages.error(request, limit_error)
            return redirect(request.path)

        url = request.POST.get('url', '').strip()
        media_type = request.POST.get('type', 'auto')
        bulk_urls_raw = request.POST.get('bulk_urls', '').strip()

        # Check if bulk URLs were provided
        if bulk_urls_raw:
            # Parse bulk URLs (one per line)
            bulk_urls = [u.strip() for u in bulk_urls_raw.split('\n') if u.strip()]

            if not bulk_urls:
                messages.error(request, 'No valid URLs found in bulk input')
                return redirect(request.path)

            # Create MediaItems for all valid URLs
            created_guids = []
            skipped_count = 0
            first_guid = None

            for bulk_url in bulk_urls:
                # Basic URL validation
                if not bulk_url.startswith(('http://', 'https://', '/')):
                    skipped_count += 1
                    continue

                # Check if item already exists
                existing_item = None
                if media_type == 'auto':
                    existing_item = MediaItem.objects.filter(
                        source_url=bulk_url, requested_type='auto'
                    ).first()
                else:
                    existing_item = MediaItem.objects.filter(
                        source_url=bulk_url, media_type=media_type
                    ).first()

                if existing_item:
                    item = existing_item
                    item.requested_type = media_type
                    item.status = MediaItem.STATUS_PREFETCHING
                    item.error_message = ''
                    item.save()
                else:
                    item = MediaItem.objects.create(
                        source_url=bulk_url, requested_type=media_type, slug='pending'
                    )

                created_guids.append(item.guid)

                if first_guid is None:
                    first_guid = item.guid

            if created_guids:
                # Enqueue batch processing task (single yt-dlp process for all URLs)
                process_media_batch(created_guids)

                msg = f'Queued {len(created_guids)} URLs for batch download'
                if skipped_count > 0:
                    msg += f' ({skipped_count} invalid URLs skipped)'
                messages.success(request, msg)

                # Redirect to progress page for first item
                return redirect('admin_stash_progress', guid=first_guid)
            else:
                messages.error(request, 'No valid URLs were processed')
                return redirect(request.path)

        # Single URL mode
        if url:
            # Check for multiple items first
            strategy = choose_download_strategy(url)

            # Handle Spotify URLs - redirect to YouTube search confirmation
            if strategy == 'spotify':
                from media.service.spotify import resolve_spotify_url

                try:
                    resolution = resolve_spotify_url(url, max_results=5)

                    # Store in session for confirmation page
                    request.session['spotify_url'] = url
                    request.session['spotify_media_type'] = media_type
                    request.session['spotify_title'] = resolution.spotify_metadata.title
                    request.session['spotify_author'] = resolution.spotify_metadata.author
                    request.session['spotify_thumbnail'] = resolution.spotify_metadata.thumbnail_url
                    request.session['spotify_search_query'] = resolution.search_query
                    request.session['spotify_youtube_results'] = [
                        {
                            'url': r.url,
                            'title': r.title,
                            'channel': r.channel,
                            'duration_seconds': r.duration_seconds,
                            'thumbnail_url': r.thumbnail_url,
                            'view_count': r.view_count,
                        }
                        for r in resolution.youtube_results
                    ]
                    # Store all platform results
                    request.session['spotify_all_results'] = [
                        {
                            'url': r.url,
                            'title': r.title,
                            'platform': r.platform,
                            'channel': r.channel,
                            'duration_seconds': r.duration_seconds,
                            'thumbnail_url': r.thumbnail_url,
                            'view_count': r.view_count,
                            'feed_url': r.feed_url,
                        }
                        for r in resolution.all_results
                    ]
                    return redirect('admin_spotify_confirm')
                except Exception as e:
                    messages.error(request, f'Error fetching Spotify metadata: {str(e)}')
                    return redirect(request.path)

            if strategy == 'ytdlp':
                try:
                    prefetch_result = prefetch(url, strategy, logger=None)
                    if prefetch_result.is_multiple:
                        # Redirect to confirmation page
                        request.session['multi_item_url'] = url
                        request.session['multi_item_type'] = media_type
                        request.session['multi_item_entries'] = [
                            {
                                'url': e.url,
                                'title': e.title,
                                'duration_seconds': e.duration_seconds,
                            }
                            for e in prefetch_result.entries
                        ]
                        request.session['multi_item_playlist_title'] = (
                            prefetch_result.playlist_title
                        )
                        return redirect('admin_stash_confirm_multiple')
                except Exception:
                    # Prefetch failed (e.g. Apple Podcasts extractor broken).
                    # Fall through to single-item flow — the download pipeline
                    # has its own fallback extractors and error handling.
                    pass

            # Single item - proceed as before
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

            # Redirect to admin progress page
            return redirect('admin_stash_progress', guid=item.guid)
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
def admin_stash_confirm_multiple_view(request):
    """
    Confirmation page for multi-item downloads.

    Shows list of items that will be downloaded and asks for confirmation.
    """
    from django.contrib import messages

    from media.admin import is_demo_readonly

    # Get data from session
    url = request.session.get('multi_item_url')
    media_type = request.session.get('multi_item_type', 'auto')
    entries = request.session.get('multi_item_entries', [])
    playlist_title = request.session.get('multi_item_playlist_title', 'Multiple Items')

    if not url or not entries:
        messages.error(request, 'No multi-item data found. Please try again.')
        return redirect('admin_stash_form')

    if request.method == 'POST':
        # Block demo users from submitting
        if is_demo_readonly(request.user):
            messages.error(request, 'Demo users are not allowed to add URLs.')
            return redirect('admin_stash_form')

        # Clear session data
        del request.session['multi_item_url']
        del request.session['multi_item_type']
        del request.session['multi_item_entries']
        del request.session['multi_item_playlist_title']

        # Create MediaItem for each entry and queue batch processing
        created_guids = []
        for entry in entries:
            entry_url = entry.get('url')
            if not entry_url:
                continue

            # Check if item already exists
            existing_item = None
            if media_type == 'auto':
                existing_item = MediaItem.objects.filter(
                    source_url=entry_url, requested_type='auto'
                ).first()
            else:
                existing_item = MediaItem.objects.filter(
                    source_url=entry_url, media_type=media_type
                ).first()

            if existing_item:
                item = existing_item
                item.requested_type = media_type
                item.status = MediaItem.STATUS_PREFETCHING
                item.error_message = ''
                item.save()
            else:
                item = MediaItem.objects.create(
                    source_url=entry_url, requested_type=media_type, slug='pending'
                )

            created_guids.append(item.guid)

        # Use batch processing to avoid SQLite lock contention
        if created_guids:
            process_media_batch(created_guids)

        messages.success(request, f'Queued {len(created_guids)} items for download')
        return redirect('admin_stash_form')

    context = {
        **admin.site.each_context(request),
        'url': url,
        'media_type': media_type,
        'entries': entries,
        'playlist_title': playlist_title,
        'count': len(entries),
        'title': f'Confirm Download - {len(entries)} Items',
    }

    return render(request, 'admin/admin_stash_confirm_multiple.html', context)


@staff_member_required
def admin_spotify_confirm_view(request):
    """
    Confirmation page for Spotify URLs.

    Shows YouTube search results and lets user select which one to download.
    """
    from django.contrib import messages

    from media.admin import is_demo_readonly

    # Get data from session
    spotify_url = request.session.get('spotify_url')
    media_type = request.session.get('spotify_media_type', 'audio')
    spotify_title = request.session.get('spotify_title', '')
    spotify_author = request.session.get('spotify_author')
    spotify_thumbnail = request.session.get('spotify_thumbnail')
    search_query = request.session.get('spotify_search_query', '')
    youtube_results = request.session.get('spotify_youtube_results', [])
    all_results = request.session.get('spotify_all_results', [])

    # Group results by platform for display
    results_by_platform = {}
    for result in all_results:
        platform = result.get('platform', 'unknown')
        if platform not in results_by_platform:
            results_by_platform[platform] = []
        results_by_platform[platform].append(result)

    if not spotify_url:
        messages.error(request, 'No Spotify URL found. Please try again.')
        return redirect('admin_stash_form')

    if request.method == 'POST':
        # Block demo users from submitting
        if is_demo_readonly(request.user):
            messages.error(request, 'Demo users are not allowed to add URLs.')
            return redirect('admin_stash_form')

        # Get selected YouTube URL
        youtube_url = request.POST.get('youtube_url', '').strip()
        custom_url = request.POST.get('custom_url', '').strip()

        # Prefer custom URL if provided
        if custom_url:
            youtube_url = custom_url

        if not youtube_url:
            messages.error(request, 'Please select a YouTube result or enter a custom URL.')
            return redirect('admin_spotify_confirm')

        # Clear session data
        for key in [
            'spotify_url',
            'spotify_media_type',
            'spotify_title',
            'spotify_author',
            'spotify_thumbnail',
            'spotify_search_query',
            'spotify_youtube_results',
            'spotify_all_results',
        ]:
            if key in request.session:
                del request.session[key]

        # Create MediaItem with the YouTube URL
        # Check if item already exists
        existing_item = None
        if media_type == 'auto':
            existing_item = MediaItem.objects.filter(
                source_url=youtube_url, requested_type='auto'
            ).first()
        else:
            existing_item = MediaItem.objects.filter(
                source_url=youtube_url, media_type=media_type
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
                source_url=youtube_url,
                requested_type=media_type,
                slug='pending',
            )
            messages.success(
                request,
                f'Downloading from YouTube (original: Spotify): {spotify_title or "Unknown"}',
            )

        # Store the original Spotify URL in the description for reference
        if spotify_url and not item.description:
            item.description = f'Originally from Spotify: {spotify_url}'
            item.save()

        # Enqueue processing
        process_media(item.guid)

        # Redirect to progress page
        return redirect('admin_stash_progress', guid=item.guid)

    context = {
        **admin.site.each_context(request),
        'spotify_url': spotify_url,
        'spotify_title': spotify_title,
        'spotify_author': spotify_author,
        'spotify_thumbnail': spotify_thumbnail,
        'search_query': search_query,
        'youtube_results': youtube_results,
        'all_results': all_results,
        'results_by_platform': results_by_platform,
        'media_type': media_type,
        'title': 'Select Source',
    }

    return render(request, 'admin/admin_spotify_confirm.html', context)


@staff_member_required
def admin_stash_progress_view(request, guid):
    """
    Admin progress page for monitoring media processing.

    Shows live progress updates within the admin interface.
    """
    context = {
        **admin.site.each_context(request),
        'guid': guid,
        'title': 'Processing Media',
    }

    return render(request, 'admin/admin_stash_progress.html', context)


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


@staff_member_required
def preferences_view(request):
    """
    Status/preferences page showing system info and current configuration.
    """
    import os
    from pathlib import Path

    # Episode counts
    ready_count = MediaItem.objects.filter(status=MediaItem.STATUS_READY).count()
    archived_count = MediaItem.objects.filter(status=MediaItem.STATUS_ARCHIVED).count()
    audio_count = MediaItem.objects.filter(
        status=MediaItem.STATUS_READY, media_type='audio'
    ).count()
    video_count = MediaItem.objects.filter(
        status=MediaItem.STATUS_READY, media_type='video'
    ).count()
    error_count = MediaItem.objects.filter(status=MediaItem.STATUS_ERROR).count()

    # Last download
    last_download = (
        MediaItem.objects.filter(status=MediaItem.STATUS_READY).order_by('-downloaded_at').first()
    )

    # Storage used (walk actual disk)
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

    # Episode limit
    max_episodes = settings.STASHCAST_MAX_EPISODES

    context = {
        **admin.site.each_context(request),
        'title': 'About',
        'ready_count': ready_count,
        'archived_count': archived_count,
        'audio_count': audio_count,
        'video_count': video_count,
        'error_count': error_count,
        'last_download': last_download,
        'total_storage_bytes': total_storage_bytes,
        'max_episodes': max_episodes,
    }

    return render(request, 'admin/preferences.html', context)


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


@staff_member_required
@require_http_methods(['POST'])
def item_archive_view(request, guid):
    """Archive a media item."""
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone

    from media.admin import is_demo_readonly

    if is_demo_readonly(request.user):
        raise PermissionDenied('Demo users are not allowed to archive items.')

    item = get_object_or_404(MediaItem, guid=guid)

    if item.status == MediaItem.STATUS_READY:
        item.status = MediaItem.STATUS_ARCHIVED
        item.archived_at = timezone.now()
        item.save()
        messages.success(request, f'Archived: {item.title or item.guid}')
    else:
        messages.error(request, 'Only ready items can be archived.')

    return redirect('item_detail', guid=guid)


@staff_member_required
@require_http_methods(['POST'])
def item_refetch_view(request, guid):
    """Re-fetch a media item (re-download and re-process)."""
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied

    from media.admin import is_demo_readonly

    if is_demo_readonly(request.user):
        raise PermissionDenied('Demo users are not allowed to refetch items.')

    item = get_object_or_404(MediaItem, guid=guid)

    item.status = MediaItem.STATUS_PREFETCHING
    item.error_message = ''
    item.save()
    process_media(item.guid)
    messages.success(request, f'Re-fetching: {item.title or item.guid}')

    return redirect('item_detail', guid=guid)


@staff_member_required
@require_http_methods(['POST'])
def item_regenerate_summary_view(request, guid):
    """Regenerate the summary for a media item."""
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied

    from media.admin import is_demo_readonly

    if is_demo_readonly(request.user):
        raise PermissionDenied('Demo users are not allowed to regenerate summaries.')

    item = get_object_or_404(MediaItem, guid=guid)

    if item.subtitle_path:
        generate_summary(item.guid)
        messages.success(request, f'Regenerating summary for: {item.title or item.guid}')
    else:
        messages.error(request, 'No subtitles available for summary generation.')

    return redirect('item_detail', guid=guid)


@staff_member_required
@require_http_methods(['POST'])
def item_unarchive_view(request, guid):
    """Unarchive a media item."""
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied

    from media.admin import is_demo_readonly

    if is_demo_readonly(request.user):
        raise PermissionDenied('Demo users are not allowed to unarchive items.')

    item = get_object_or_404(MediaItem, guid=guid)

    if item.status == MediaItem.STATUS_ARCHIVED:
        item.status = MediaItem.STATUS_READY
        item.archived_at = None
        item.save()
        messages.success(request, f'Unarchived: {item.title or item.guid}')
    else:
        messages.error(request, 'Only archived items can be unarchived.')

    return redirect('item_detail', guid=guid)
