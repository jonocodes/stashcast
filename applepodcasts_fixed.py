"""
FIXED VERSION of ApplePodcasts extractor with video support

This is the complete fixed version of the extractor that properly
detects video vs audio podcasts using the mediaType field.

Changes from original:
1. Added test case for video podcast (Apple Event)
2. Extract mediaType field from the JSON data
3. Conditionally set vcodec based on mediaType instead of hardcoding 'none'
"""

from .common import InfoExtractor
from ..utils import (
    clean_html,
    clean_podcast_url,
    int_or_none,
    parse_iso8601,
)
from ..utils.traversal import traverse_obj


class ApplePodcastsIE(InfoExtractor):
    _VALID_URL = r'https?://podcasts\.apple\.com/(?:[^/]+/)?podcast(?:/[^/]+){1,2}.*?\bi=(?P<id>\d+)'
    _TESTS = [{
        # Video podcast test case - NEW
        'url': 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230',
        'info_dict': {
            'id': '1000654821230',
            'ext': 'mp4',  # Video podcasts should download as mp4
            'title': 'Apple Event — May 7',
            'episode': 'Apple Event — May 7',
            'description': 'md5:c1f4a2e097d0ff2e26e602e47e8c4db1',
            'upload_date': '20240507',
            'timestamp': 1715090400,
            'duration': 2312,
            'series': 'Apple Events (video)',
            'thumbnail': 're:.+[.](png|jpe?g|webp)',
        },
        'params': {
            'format': 'best',
        },
    }, {
        # Audio podcast test case - EXISTING (should still work)
        'url': 'https://podcasts.apple.com/us/podcast/ferreck-dawn-to-the-break-of-dawn-117/id1625658232?i=1000665010654',
        'md5': '82cc219b8cc1dcf8bfc5a5e99b23b172',
        'info_dict': {
            'id': '1000665010654',
            'ext': 'mp3',  # Audio podcasts download as mp3/m4a
            'title': 'Ferreck Dawn - To The Break of Dawn 117',
            'episode': 'Ferreck Dawn - To The Break of Dawn 117',
            'description': 'md5:8c4f5c2c30af17ed6a98b0b9daf15b76',
            'upload_date': '20240812',
            'timestamp': 1723449600,
            'duration': 3596,
            'series': 'Ferreck Dawn - To The Break of Dawn',
            'thumbnail': 're:.+[.](png|jpe?g|webp)',
        },
    }, {
        'url': 'https://podcasts.apple.com/us/podcast/207-whitney-webb-returns/id1135137367?i=1000482637777',
        'md5': 'baf8a6b8b8aa6062dbb4639ed73d0052',
        'info_dict': {
            'id': '1000482637777',
            'ext': 'mp3',
            'title': '207 - Whitney Webb Returns',
            'episode': '207 - Whitney Webb Returns',
            'episode_number': 207,
            'description': 'md5:75ef4316031df7b41ced4e7b987f79c6',
            'upload_date': '20200705',
            'timestamp': 1593932400,
            'duration': 5369,
            'series': 'The Tim Dillon Show',
            'thumbnail': 're:.+[.](png|jpe?g|webp)',
        },
    }, {
        'url': 'https://podcasts.apple.com/podcast/207-whitney-webb-returns/id1135137367?i=1000482637777',
        'only_matching': True,
    }, {
        'url': 'https://podcasts.apple.com/podcast/207-whitney-webb-returns?i=1000482637777',
        'only_matching': True,
    }, {
        'url': 'https://podcasts.apple.com/podcast/id1135137367?i=1000482637777',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        episode_id = self._match_id(url)
        webpage = self._download_webpage(url, episode_id)
        server_data = self._search_json(
            r'<script [^>]*\bid=["\']serialized-server-data["\'][^>]*>', webpage,
            'server data', episode_id, contains_pattern=r'\[{(?s:.+)}\]')[0]['data']
        model_data = traverse_obj(server_data, (
            'headerButtonItems', lambda _, v: v['$kind'] == 'share' and v['modelType'] == 'EpisodeLockup',
            'model', {dict}, any))

        # FIX: Extract mediaType to determine if this is video or audio
        # Apple provides 'video' or 'audio' in the mediaType field
        media_type = traverse_obj(model_data, ('playAction', 'episodeOffer', 'mediaType', {str}))

        return {
            'id': episode_id,
            **self._json_ld(
                traverse_obj(server_data, ('seoData', 'schemaContent', {dict}))
                or self._yield_json_ld(webpage, episode_id, fatal=False), episode_id, fatal=False),
            **traverse_obj(model_data, {
                'title': ('title', {str}),
                'description': ('summary', {clean_html}),
                'url': ('playAction', 'episodeOffer', 'streamUrl', {clean_podcast_url}),
                'timestamp': ('releaseDate', {parse_iso8601}),
                'duration': ('duration', {int_or_none}),
            }),
            'thumbnail': self._og_search_thumbnail(webpage),
            # FIX: Only set vcodec to 'none' for non-video content
            # For video content, let yt-dlp detect the actual codec
            'vcodec': 'none' if media_type != 'video' else None,
        }
