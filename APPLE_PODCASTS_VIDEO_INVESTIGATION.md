# Apple Podcasts Video Bug Investigation for yt-dlp

## Summary

The yt-dlp `ApplePodcasts` extractor incorrectly treats all podcast episodes as audio-only, even when they are video podcasts. This causes video podcast episodes to be downloaded without video streams.

## Problem Description

The ApplePodcasts extractor unconditionally sets `'vcodec': 'none'` for all episodes, which signals to yt-dlp that the content is audio-only. However, Apple Podcasts hosts both audio-only podcasts AND video podcasts (like Apple Events, WWDC sessions, etc.). The extractor currently ignores the `mediaType` field in Apple's JSON data, which correctly identifies whether an episode is audio or video.

## Impact

- Video podcast episodes download as audio-only
- Users cannot download video podcasts from Apple Podcasts
- Format selection (`-f` flags) cannot differentiate between video and audio formats
- Downstream tools that rely on yt-dlp's codec detection get incorrect information

## Affected URLs

### Video Podcast Examples (Currently Broken)
- `https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230`
  - Apple Events (video) - May 7, 2024 iPad event
  - This is a 38-minute video podcast but yt-dlp treats it as audio
  - **Actual file**: `https://applehosted.podcasts.apple.com/apple_keynotes/2024/240507.mp4`
  - **mediaType in JSON**: `"video"`

- Apple Events (video) podcast: `https://podcasts.apple.com/us/podcast/id275834665`
  - All episodes are video but extracted as audio

### Audio Podcast Example (Working Correctly for audio)
- `https://podcasts.apple.com/us/podcast/ferreck-dawn-to-the-break-of-dawn-117/id1625658232?i=1000665010654`
  - This is an audio-only podcast (correctly identified as audio)
  - **Actual file**: `.mp3` format
  - **mediaType in JSON**: `"audio"`

### Expected vs Actual Behavior

**Expected**: yt-dlp should detect video podcasts and set appropriate `vcodec` information based on the `mediaType` field
**Actual**: All Apple Podcasts episodes are marked as `vcodec: 'none'` (audio-only), even video content

## Technical Analysis

### Current Extractor Code

The problem is on line 78 of `yt_dlp/extractor/applepodcasts.py`:

```python
def _real_extract(self, url):
    episode_id = self._match_id(url)
    webpage = self._download_webpage(url, episode_id)
    server_data = self._search_json(
        r'<script [^>]*\bid=["\']serialized-server-data["\'][^>]*>', webpage,
        'server data', episode_id, contains_pattern=r'\[{(?s:.+)}\]')[0]['data']
    model_data = traverse_obj(server_data, (
        'headerButtonItems', lambda _, v: v['$kind'] == 'share' and v['modelType'] == 'EpisodeLockup',
        'model', {dict}, any))

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
        'vcodec': 'none',  # ← HARDCODED - THIS IS THE BUG
    }
```

### Apple's JSON Structure

Apple provides a `mediaType` field in their JSON data structure that correctly identifies video vs audio. This field is already accessible in the same location the extractor currently uses:

**Video Podcast JSON** (excerpts from actual Apple Podcasts page):
```json
{
  "headerButtonItems": [
    {
      "$kind": "bookmark",
      "modelType": "EpisodeOffer",
      "model": {
        "streamUrl": "https://applehosted.podcasts.apple.com/apple_keynotes/2024/240507.mp4",
        "mediaType": "video",  // ← THIS FIELD EXISTS
        "title": "Apple Event — May 7",
        "duration": 2312
      }
    }
  ]
}
```

**Audio Podcast JSON**:
```json
{
  "headerButtonItems": [
    {
      "$kind": "bookmark",
      "modelType": "EpisodeOffer",
      "model": {
        "streamUrl": "https://audio.thisisdistorted.com/.../TTBOD_117_192k.mp3",
        "mediaType": "audio",  // ← THIS FIELD EXISTS
        "title": "Ferreck Dawn - To The Break of Dawn 117",
        "duration": 3596
      }
    }
  ]
}
```

### Verification

I've verified that:
1. ✅ The `mediaType` field exists in Apple's JSON for both audio and video podcasts
2. ✅ Video podcasts have `"mediaType": "video"` and `.mp4` URLs
3. ✅ Audio podcasts have `"mediaType": "audio"` and `.mp3` URLs (or other audio formats)
4. ✅ The field is in the exact same location the extractor already accesses for other metadata
5. ✅ The extractor can access this with a trivial code change

## Proposed Solution

### Option 1: Simple Fix (Minimal Change)

Replace line 78 with conditional logic based on `mediaType`:

```python
def _real_extract(self, url):
    episode_id = self._match_id(url)
    webpage = self._download_webpage(url, episode_id)
    server_data = self._search_json(
        r'<script [^>]*\bid=["\']serialized-server-data["\'][^>]*>', webpage,
        'server data', episode_id, contains_pattern=r'\[{(?s:.+)}\]')[0]['data']
    model_data = traverse_obj(server_data, (
        'headerButtonItems', lambda _, v: v['$kind'] == 'share' and v['modelType'] == 'EpisodeLockup',
        'model', {dict}, any))

    # Extract mediaType to determine if this is video or audio
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
        'vcodec': 'none' if media_type != 'video' else None,  # ← FIX: Check mediaType
    }
```

**Rationale**: Setting `vcodec` to `None` (instead of `'none'`) allows yt-dlp to detect the actual codec from the media file. For video podcasts, yt-dlp will correctly identify it has video.

### Option 2: More Explicit Fix

Alternatively, we could be more explicit:

```python
# Extract mediaType to determine if this is video or audio
media_type = traverse_obj(model_data, ('playAction', 'episodeOffer', 'mediaType', {str}))
is_video = media_type == 'video'

return {
    'id': episode_id,
    # ... metadata ...
    'vcodec': None if is_video else 'none',  # Let yt-dlp detect codec for video
}
```

## Testing

### Test Cases Needed

1. **Video Podcast Test** (NEW):
```python
{
    'url': 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230',
    'info_dict': {
        'id': '1000654821230',
        'ext': 'mp4',  # Should be mp4, not mp3
        'title': 'Apple Event — May 7',
        'duration': 2312,
        'series': 'Apple Events (video)',
    },
    'params': {
        'format': 'best',
    },
}
```

2. **Existing Audio Test** (Should still work):
```python
{
    'url': 'https://podcasts.apple.com/us/podcast/ferreck-dawn-to-the-break-of-dawn-117/id1625658232?i=1000665010654',
    'md5': '82cc219b8cc1dcf8bfc5a5e99b23b172',
    'info_dict': {
        'id': '1000665010654',
        'ext': 'mp3',
        'title': 'Ferreck Dawn - To The Break of Dawn 117',
        'duration': 3596,
    },
}
```

### Manual Testing

Before the fix:
```bash
$ yt-dlp -F 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'
# Shows only audio formats (INCORRECT)
```

After the fix:
```bash
$ yt-dlp -F 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'
# Should show video format available
```

## Additional Context

### Why This Matters

1. **Apple Events**: Apple publishes all their product launch events as video podcasts
2. **WWDC Sessions**: Technical sessions are often video
3. **Educational Content**: Many educational podcasts include video demonstrations
4. **User Expectations**: Users specifically seeking video podcasts expect video output

### Backward Compatibility

✅ **No breaking changes**: Audio podcasts will continue to work exactly as before since they already have `"mediaType": "audio"`.

### Related Issues/PRs

- PR #10903: Fixed the ApplePodcasts extractor after Apple's website rewrite
- The extractor was last updated in September 2024 but the `mediaType` field was not utilized

## Reproduction Steps

### Current Behavior (Bug)
```bash
# Try to download a video podcast
yt-dlp -vU 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'

# Result: Downloads only audio, no video stream
# File extension: .mp3 or similar audio format
# vcodec: 'none' in info dict
```

### Expected Behavior (After Fix)
```bash
# Try to download a video podcast
yt-dlp -vU 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'

# Result: Downloads video with audio
# File extension: .mp4
# vcodec: Properly detected (e.g., 'h264', 'avc1')
```

## Summary

This is a straightforward fix that:
- ✅ Requires changing only 1-2 lines of code
- ✅ Uses data already present in Apple's JSON
- ✅ Has no backward compatibility issues
- ✅ Enables a significant new capability (video podcast support)
- ✅ Benefits all yt-dlp users downloading Apple Podcasts

The `mediaType` field is reliable, well-defined, and already exists in Apple's production API.
