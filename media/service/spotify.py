"""
Spotify URL handling and YouTube search fallback.

Spotify content is DRM-protected and cannot be downloaded directly.
This service extracts metadata from Spotify URLs and searches for
equivalent content on YouTube.
"""

import re
import urllib.request
import urllib.parse
import json
from dataclasses import dataclass
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
class YouTubeSearchResult:
    """A single YouTube search result."""

    url: str
    title: str
    channel: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    view_count: Optional[int] = None


@dataclass
class SpotifyResolution:
    """Result of resolving a Spotify URL to YouTube alternatives."""

    spotify_metadata: SpotifyMetadata
    youtube_results: List[YouTubeSearchResult]
    search_query: str


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


def search_youtube(query: str, max_results: int = 5, logger=None) -> List[YouTubeSearchResult]:
    """
    Search YouTube for videos matching a query.

    Args:
        query: Search query string
        max_results: Maximum number of results to return
        logger: Optional callable(str) for logging

    Returns:
        List of YouTubeSearchResult objects
    """

    def log(msg):
        if logger:
            logger(msg)

    log(f'Searching YouTube for: {query}')

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': 'ytsearch',
    }

    # Add proxy if configured
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    results = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # ytsearch returns multiple results
        search_url = f'ytsearch{max_results}:{query}'
        info = ydl.extract_info(search_url, download=False)

        entries = info.get('entries', [])
        log(f'Found {len(entries)} YouTube results')

        for entry in entries:
            if entry is None:
                continue

            result = YouTubeSearchResult(
                url=entry.get('url') or f'https://www.youtube.com/watch?v={entry.get("id")}',
                title=entry.get('title', 'Untitled'),
                channel=entry.get('channel') or entry.get('uploader'),
                duration_seconds=entry.get('duration'),
                thumbnail_url=entry.get('thumbnail'),
                view_count=entry.get('view_count'),
            )
            results.append(result)

    return results


def build_search_query(metadata: SpotifyMetadata) -> str:
    """
    Build a YouTube search query from Spotify metadata.

    Args:
        metadata: SpotifyMetadata object

    Returns:
        Search query string optimized for finding the content on YouTube
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


def resolve_spotify_url(url: str, max_results: int = 5, logger=None) -> SpotifyResolution:
    """
    Resolve a Spotify URL to YouTube alternatives.

    This is the main entry point for handling Spotify URLs.

    Args:
        url: A Spotify URL
        max_results: Maximum number of YouTube results to return
        logger: Optional callable(str) for logging

    Returns:
        SpotifyResolution with metadata and YouTube search results
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

    # Search YouTube
    youtube_results = search_youtube(search_query, max_results=max_results, logger=log)

    return SpotifyResolution(
        spotify_metadata=metadata,
        youtube_results=youtube_results,
        search_query=search_query,
    )
