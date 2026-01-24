"""
Spotify URL handling and cross-platform search fallback.

Spotify content is DRM-protected and cannot be downloaded directly.
This service extracts metadata from Spotify URLs and searches for
equivalent content on multiple platforms (YouTube, SoundCloud, Dailymotion,
and Podcast Index for podcasts).
"""

import hashlib
import re
import time
import urllib.request
import urllib.parse
import json
from dataclasses import dataclass, field
from typing import Optional, List
import yt_dlp
from django.conf import settings


# Spotify URL patterns
SPOTIFY_EPISODE_PATTERN = re.compile(r'https?://open\.spotify\.com/episode/([a-zA-Z0-9]+)')
SPOTIFY_SHOW_PATTERN = re.compile(r'https?://open\.spotify\.com/show/([a-zA-Z0-9]+)')
SPOTIFY_TRACK_PATTERN = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')
SPOTIFY_ALBUM_PATTERN = re.compile(r'https?://open\.spotify\.com/album/([a-zA-Z0-9]+)')


@dataclass
class SpotifyMetadata:
    """Metadata extracted from a Spotify URL."""

    title: str
    description: Optional[str] = None
    author: Optional[str] = None  # Show name for podcasts, artist for tracks
    thumbnail_url: Optional[str] = None
    spotify_url: str = ''
    spotify_type: str = ''  # 'episode', 'show', 'track', 'album'
    spotify_id: str = ''


@dataclass
class SearchResult:
    """A single search result from any platform."""

    url: str
    title: str
    platform: str  # 'youtube', 'soundcloud', 'dailymotion', 'podcast_index'
    channel: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    view_count: Optional[int] = None
    # For podcast index results
    feed_url: Optional[str] = None
    episode_url: Optional[str] = None


# Keep YouTubeSearchResult for backwards compatibility
@dataclass
class YouTubeSearchResult:
    """A single YouTube search result (backwards compatible)."""

    url: str
    title: str
    channel: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    view_count: Optional[int] = None


@dataclass
class SpotifyResolution:
    """Result of resolving a Spotify URL to alternatives on multiple platforms."""

    spotify_metadata: SpotifyMetadata
    youtube_results: List[YouTubeSearchResult]  # Backwards compatible
    search_query: str
    # New: results from all platforms
    all_results: List[SearchResult] = field(default_factory=list)
    podcast_index_results: List[SearchResult] = field(default_factory=list)


def is_spotify_url(url: str) -> bool:
    """Check if a URL is a Spotify URL."""
    return 'open.spotify.com' in url or 'spotify.com' in url


def get_spotify_type(url: str) -> Optional[str]:
    """
    Determine the type of Spotify content from a URL.

    Returns:
        'episode', 'show', 'track', 'album', or None if not recognized
    """
    if SPOTIFY_EPISODE_PATTERN.search(url):
        return 'episode'
    elif SPOTIFY_SHOW_PATTERN.search(url):
        return 'show'
    elif SPOTIFY_TRACK_PATTERN.search(url):
        return 'track'
    elif SPOTIFY_ALBUM_PATTERN.search(url):
        return 'album'
    return None


def get_spotify_id(url: str) -> Optional[str]:
    """Extract the Spotify ID from a URL."""
    for pattern in [
        SPOTIFY_EPISODE_PATTERN,
        SPOTIFY_SHOW_PATTERN,
        SPOTIFY_TRACK_PATTERN,
        SPOTIFY_ALBUM_PATTERN,
    ]:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def fetch_spotify_oembed(url: str) -> dict:
    """
    Fetch metadata from Spotify's oEmbed API.

    Args:
        url: A Spotify URL

    Returns:
        dict with oEmbed response data

    Raises:
        Exception if the request fails
    """
    oembed_url = f'https://open.spotify.com/oembed?url={urllib.parse.quote(url)}'

    req = urllib.request.Request(
        oembed_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def extract_spotify_metadata(url: str, logger=None) -> SpotifyMetadata:
    """
    Extract metadata from a Spotify URL using the oEmbed API.

    Args:
        url: A Spotify URL
        logger: Optional callable(str) for logging

    Returns:
        SpotifyMetadata with extracted information
    """

    def log(msg):
        if logger:
            logger(msg)

    log(f'Extracting Spotify metadata from: {url}')

    spotify_type = get_spotify_type(url)
    spotify_id = get_spotify_id(url)

    log(f'Spotify type: {spotify_type}, ID: {spotify_id}')

    # Fetch oEmbed data
    try:
        oembed_data = fetch_spotify_oembed(url)
        log(f'oEmbed response: {oembed_data.get("title", "No title")}')
    except Exception as e:
        log(f'oEmbed request failed: {e}')
        raise ValueError(f'Failed to fetch Spotify metadata: {e}')

    # Parse the title to extract show name and episode title
    # oEmbed title format is typically "Episode Title" for episodes
    # or "Show Name" for shows
    title = oembed_data.get('title', '')
    description = oembed_data.get('description', '')
    thumbnail_url = oembed_data.get('thumbnail_url', '')

    # The provider_name is typically "Spotify" but we want the show/artist name
    # For podcasts, we can try to extract from the HTML or use the title
    author = None

    # For episodes, the HTML often contains the show name
    html = oembed_data.get('html', '')
    if html and spotify_type == 'episode':
        # Try to extract show name from iframe title or other attributes
        # The oEmbed HTML is an iframe, metadata is limited
        pass

    return SpotifyMetadata(
        title=title,
        description=description,
        author=author,
        thumbnail_url=thumbnail_url,
        spotify_url=url,
        spotify_type=spotify_type or 'unknown',
        spotify_id=spotify_id or '',
    )


def search_platform(
    query: str,
    platform: str,
    max_results: int = 3,
    logger=None,
) -> List[SearchResult]:
    """
    Search a specific platform for content matching a query.

    Args:
        query: Search query string
        platform: Platform to search ('youtube', 'soundcloud', 'dailymotion')
        max_results: Maximum number of results to return
        logger: Optional callable(str) for logging

    Returns:
        List of SearchResult objects
    """

    def log(msg):
        if logger:
            logger(msg)

    # Map platform names to yt-dlp search prefixes
    search_prefixes = {
        'youtube': 'ytsearch',
        'soundcloud': 'scsearch',
        'dailymotion': 'dailymotion:search',
    }

    prefix = search_prefixes.get(platform)
    if not prefix:
        log(f'Unknown platform: {platform}')
        return []

    log(f'Searching {platform} for: {query}')

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }

    # Add proxy if configured
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    results = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_url = f'{prefix}{max_results}:{query}'
            info = ydl.extract_info(search_url, download=False)

            entries = info.get('entries', [])
            log(f'Found {len(entries)} {platform} results')

            for entry in entries:
                if entry is None:
                    continue

                # Build URL based on platform
                url = entry.get('url') or entry.get('webpage_url')
                if not url and entry.get('id'):
                    if platform == 'youtube':
                        url = f'https://www.youtube.com/watch?v={entry.get("id")}'
                    elif platform == 'soundcloud':
                        url = entry.get('webpage_url', '')
                    elif platform == 'dailymotion':
                        url = f'https://www.dailymotion.com/video/{entry.get("id")}'

                if not url:
                    continue

                result = SearchResult(
                    url=url,
                    title=entry.get('title', 'Untitled'),
                    platform=platform,
                    channel=entry.get('channel') or entry.get('uploader'),
                    duration_seconds=entry.get('duration'),
                    thumbnail_url=entry.get('thumbnail'),
                    view_count=entry.get('view_count'),
                )
                results.append(result)
    except Exception as e:
        log(f'Error searching {platform}: {e}')

    return results


def search_youtube(query: str, max_results: int = 5, logger=None) -> List[YouTubeSearchResult]:
    """
    Search YouTube for videos matching a query (backwards compatible).

    Args:
        query: Search query string
        max_results: Maximum number of results to return
        logger: Optional callable(str) for logging

    Returns:
        List of YouTubeSearchResult objects
    """
    results = search_platform(query, 'youtube', max_results, logger)

    # Convert to YouTubeSearchResult for backwards compatibility
    return [
        YouTubeSearchResult(
            url=r.url,
            title=r.title,
            channel=r.channel,
            duration_seconds=r.duration_seconds,
            thumbnail_url=r.thumbnail_url,
            view_count=r.view_count,
        )
        for r in results
    ]


def search_podcast_index(
    query: str,
    max_results: int = 3,
    logger=None,
) -> List[SearchResult]:
    """
    Search Podcast Index for episodes matching a query.

    Requires PODCAST_INDEX_API_KEY and PODCAST_INDEX_API_SECRET settings.

    Args:
        query: Search query string
        max_results: Maximum number of results to return
        logger: Optional callable(str) for logging

    Returns:
        List of SearchResult objects with feed_url and episode_url
    """

    def log(msg):
        if logger:
            logger(msg)

    # Check for API credentials
    api_key = getattr(settings, 'PODCAST_INDEX_API_KEY', None)
    api_secret = getattr(settings, 'PODCAST_INDEX_API_SECRET', None)

    if not api_key or not api_secret:
        log('Podcast Index API credentials not configured, skipping')
        return []

    log(f'Searching Podcast Index for: {query}')

    try:
        # Build authentication headers
        epoch_time = int(time.time())
        data_to_hash = api_key + api_secret + str(epoch_time)
        sha1_hash = hashlib.sha1(data_to_hash.encode('utf-8')).hexdigest()

        headers = {
            'X-Auth-Key': api_key,
            'X-Auth-Date': str(epoch_time),
            'Authorization': sha1_hash,
            'User-Agent': 'StashCast/1.0',
        }

        # Search for episodes
        search_url = (
            f'https://api.podcastindex.org/api/1.0/search/byterm'
            f'?q={urllib.parse.quote(query)}&max={max_results}'
        )

        req = urllib.request.Request(search_url, headers=headers)

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        results = []
        feeds = data.get('feeds', [])
        log(f'Found {len(feeds)} Podcast Index results')

        for feed in feeds[:max_results]:
            # Get the feed URL (original RSS)
            feed_url = feed.get('url') or feed.get('originalUrl')
            if not feed_url:
                continue

            result = SearchResult(
                url=feed_url,  # The RSS feed URL
                title=feed.get('title', 'Untitled'),
                platform='podcast_index',
                channel=feed.get('author') or feed.get('ownerName'),
                thumbnail_url=feed.get('image') or feed.get('artwork'),
                feed_url=feed_url,
            )
            results.append(result)

        return results

    except Exception as e:
        log(f'Error searching Podcast Index: {e}')
        return []


def search_all_platforms(
    query: str,
    platforms: List[str] = None,
    max_results_per_platform: int = 3,
    logger=None,
) -> List[SearchResult]:
    """
    Search multiple platforms for content matching a query.

    Args:
        query: Search query string
        platforms: List of platforms to search (default: youtube, soundcloud, dailymotion)
        max_results_per_platform: Maximum results per platform
        logger: Optional callable(str) for logging

    Returns:
        List of SearchResult objects from all platforms
    """
    if platforms is None:
        platforms = ['youtube', 'soundcloud', 'dailymotion']

    all_results = []

    for platform in platforms:
        if platform == 'podcast_index':
            results = search_podcast_index(query, max_results_per_platform, logger)
        else:
            results = search_platform(query, platform, max_results_per_platform, logger)
        all_results.extend(results)

    return all_results


def build_search_query(metadata: SpotifyMetadata) -> str:
    """
    Build a search query from Spotify metadata.

    Args:
        metadata: SpotifyMetadata object

    Returns:
        Search query string optimized for finding the content
    """
    parts = []

    # Add the title
    if metadata.title:
        parts.append(metadata.title)

    # Add author/show name if available
    if metadata.author:
        parts.append(metadata.author)

    # Add type hint for podcasts
    if metadata.spotify_type == 'episode':
        # Don't add "podcast" if title already contains it
        if 'podcast' not in metadata.title.lower():
            parts.append('podcast')

    query = ' '.join(parts)

    # Clean up the query - remove special characters that might interfere
    query = re.sub(r'[^\w\s\-]', ' ', query)
    query = re.sub(r'\s+', ' ', query).strip()

    return query


def resolve_spotify_url(
    url: str,
    max_results: int = 5,
    search_all: bool = True,
    logger=None,
) -> SpotifyResolution:
    """
    Resolve a Spotify URL to alternatives on multiple platforms.

    This is the main entry point for handling Spotify URLs.

    Args:
        url: A Spotify URL
        max_results: Maximum number of YouTube results (for backwards compatibility)
        search_all: If True, search all platforms; if False, only search YouTube
        logger: Optional callable(str) for logging

    Returns:
        SpotifyResolution with metadata and search results from all platforms
    """

    def log(msg):
        if logger:
            logger(msg)

    log(f'Resolving Spotify URL: {url}')

    # Extract Spotify metadata
    metadata = extract_spotify_metadata(url, logger=log)

    # Build search query
    search_query = build_search_query(metadata)
    log(f'Search query: {search_query}')

    # Search YouTube (always, for backwards compatibility)
    youtube_results = search_youtube(search_query, max_results=max_results, logger=log)

    # Initialize result lists
    all_results = []
    podcast_index_results = []

    # Convert YouTube results to SearchResult format
    for r in youtube_results:
        all_results.append(
            SearchResult(
                url=r.url,
                title=r.title,
                platform='youtube',
                channel=r.channel,
                duration_seconds=r.duration_seconds,
                thumbnail_url=r.thumbnail_url,
                view_count=r.view_count,
            )
        )

    if search_all:
        # Search SoundCloud
        soundcloud_results = search_platform(search_query, 'soundcloud', max_results=3, logger=log)
        all_results.extend(soundcloud_results)

        # Search Dailymotion
        dailymotion_results = search_platform(
            search_query, 'dailymotion', max_results=3, logger=log
        )
        all_results.extend(dailymotion_results)

        # For podcasts, also search Podcast Index
        if metadata.spotify_type in ('episode', 'show'):
            podcast_index_results = search_podcast_index(search_query, max_results=3, logger=log)
            all_results.extend(podcast_index_results)

    return SpotifyResolution(
        spotify_metadata=metadata,
        youtube_results=youtube_results,
        search_query=search_query,
        all_results=all_results,
        podcast_index_results=podcast_index_results,
    )


def select_spotify_alternative(url: str, logger=None) -> str:
    """
    Resolve a Spotify URL and select an alternative source.

    This consolidates the Spotify handling logic used by CLI commands.
    Shows available alternatives and either auto-selects the first one
    (if STASHCAST_ACCEPT_FIRST_MATCH is set) or prompts for user selection.

    Args:
        url: Spotify URL to resolve
        logger: Optional callable for logging messages

    Returns:
        URL of the selected alternative source

    Raises:
        ValueError: If no alternatives found or selection cancelled
    """

    def log(msg):
        if logger:
            logger(msg)
        else:
            print(msg)

    log('Spotify URL detected - searching alternatives...')
    resolution = resolve_spotify_url(url, max_results=5, search_all=True, logger=logger)

    if not resolution.all_results:
        raise ValueError('No alternative sources found for Spotify URL')

    # Show results
    for i, r in enumerate(resolution.all_results, 1):
        duration = ''
        if r.duration_seconds:
            mins = int(r.duration_seconds) // 60
            secs = int(r.duration_seconds) % 60
            duration = f' [{mins}:{secs:02d}]'
        log(f'  {i}. [{r.platform}] {r.title}{duration}')

    # Auto-select or prompt
    if settings.STASHCAST_ACCEPT_FIRST_MATCH:
        selected = resolution.all_results[0]
        log(f'Auto-selecting: {selected.title}')
        return selected.url

    # Interactive selection
    try:
        choice = int(input(f'Select (1-{len(resolution.all_results)}): ')) - 1
        if choice < 0 or choice >= len(resolution.all_results):
            raise ValueError('Invalid selection')
        return resolution.all_results[choice].url
    except (ValueError, EOFError) as e:
        raise ValueError(f'Selection cancelled: {e}')
