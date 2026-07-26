"""
List recent uploads from a YouTube channel.

Used by the periodic channel-sync feature: given a channel URL configured on a
MediaGroup, return the most recent video URLs so new ones can be stashed as audio.

Uses yt-dlp's flat extraction (metadata only, no download) so a check is cheap
even for channels with a large back-catalogue.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import yt_dlp
from django.conf import settings

# Channel roots that expose several tabs (videos / shorts / streams). We target
# the plain uploads tab so `playlistend` yields the newest videos, newest first.
_CHANNEL_ROOT_RE = re.compile(r'youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)/?$')
_TAB_SUFFIXES = ('/videos', '/streams', '/shorts', '/playlists', '/featured', '/community')


@dataclass
class ChannelVideo:
    """A single upload discovered on a channel."""

    url: str
    title: Optional[str] = None
    external_id: Optional[str] = None


def normalize_channel_url(url: str) -> str:
    """Point a bare channel URL at its uploads tab for stable newest-first listing.

    URLs that already name a tab (``/videos``, ``/streams``, ...) or are playlists
    are returned unchanged.
    """
    stripped = url.strip()
    lowered = stripped.lower()
    if any(suffix in lowered for suffix in _TAB_SUFFIXES) or 'list=' in lowered:
        return stripped
    if _CHANNEL_ROOT_RE.search(stripped):
        return stripped.rstrip('/') + '/videos'
    return stripped


def _entry_to_video(entry: dict) -> Optional[ChannelVideo]:
    """Build a ChannelVideo from a flat playlist entry, or None if unusable."""
    if not entry:
        return None
    url = entry.get('url') or entry.get('webpage_url')
    external_id = entry.get('id')
    if url and not url.startswith('http'):
        # Flat entries sometimes carry only the bare video id.
        external_id = external_id or url
        url = f'https://www.youtube.com/watch?v={url}'
    if not url:
        if not external_id:
            return None
        url = f'https://www.youtube.com/watch?v={external_id}'
    return ChannelVideo(url=url, title=entry.get('title'), external_id=external_id)


def list_channel_videos(channel_url: str, max_videos: int = 5, logger=None) -> List[ChannelVideo]:
    """Return the most recent uploads for a channel (newest first).

    Args:
        channel_url: A YouTube channel URL (handle, /channel/, /c/, /user/, or a
            specific tab / playlist URL).
        max_videos: Cap on how many recent entries to return. ``0`` means no cap.
        logger: Optional callable(str) for progress logging.

    Returns:
        A list of ChannelVideo, newest first (empty if nothing is found).
    """

    def log(message):
        if logger:
            logger(message)

    target = normalize_channel_url(channel_url)
    log(f'Listing channel uploads: {target}')

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,  # metadata only, no per-video network cost
        'ignoreerrors': True,
    }
    if max_videos and max_videos > 0:
        ydl_opts['playlistend'] = max_videos
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target, download=False)

    if not info:
        log('No channel info returned')
        return []

    entries = info.get('entries')
    if entries is None:
        # A single video URL rather than a channel/playlist.
        video = _entry_to_video(info)
        return [video] if video else []

    videos: List[ChannelVideo] = []
    for entry in entries:
        # Some channel tabs nest a further level of playlists; flatten one level.
        if entry and entry.get('entries') is not None:
            for nested in entry['entries']:
                video = _entry_to_video(nested)
                if video:
                    videos.append(video)
        else:
            video = _entry_to_video(entry)
            if video:
                videos.append(video)
        if max_videos and len(videos) >= max_videos:
            break

    log(f'Found {len(videos)} recent upload(s)')
    return videos
