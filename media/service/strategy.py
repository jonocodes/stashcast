"""
Download strategy detection.

Determines whether to use direct HTTP download or yt-dlp for a given URL.
"""

from urllib.parse import urlparse
from pathlib import Path

from media.service.constants import MEDIA_EXTENSIONS
from media.service.spotify import is_spotify_url


def choose_download_strategy(url):
    """
    Determine the download strategy for a URL or file path.

    Args:
        url: The source URL or file path

    Returns:
        str: 'file' for local media files, 'direct' for direct media URLs,
             'ytdlp' for hosted content or HTML files,
             'spotify' for Spotify URLs (requires YouTube fallback)
    """
    # Check for Spotify URLs first (DRM-protected, need YouTube fallback)
    if is_spotify_url(url):
        return 'spotify'

    # Check if it's a local file path
    file_path = Path(url)
    if file_path.exists():
        # If it's an HTML file, treat it as content for yt-dlp to extract media from
        if file_path.suffix.lower() in ['.html', '.htm']:
            return 'ytdlp'
        # Otherwise, treat it as a direct media file
        return 'file'

    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check if URL path ends with a media extension
    if any(path.endswith(ext) for ext in MEDIA_EXTENSIONS):
        return 'direct'

    return 'ytdlp'
