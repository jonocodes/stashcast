

Below is the **final, consolidated implementation spec** for **STASHCAST**, incorporating *all* decisions made in this conversation.
This is written to be directly consumable by another model or by you as a build blueprint.

---

# STASHCAST – Final Implementation Specification

## 1. Overview

**STASHCAST** is a single-user Django application for downloading online media (audio/video) for offline consumption and exposing it via podcast feeds.

Key characteristics:

* Django + SQLite
* Async downloads via **Huey** (SQLite backend)
* Media downloads via **yt-dlp** and direct HTTP
* Optional transcoding via **ffmpeg**
* Files stored on local filesystem
* Podcast feeds generated **on the fly**
* Admin-first UX
* Public `/stash/` endpoint protected by a single API key
* Bookmarklet support for one-click ingestion from arbitrary pages
* Future-ready for transcript-based summaries

---

## 2. Core Concepts & Rules

### Media ingestion

* Accept **any URL** supported by yt-dlp.
* Accept **direct media URLs** (`.mp3`, `.m4a`, `.mp4`, etc.).
* If URL resolves to a playlist / multiple entries:

  * **Do not download anything**
  * Mark item as `ERROR` with message:
    `"fetching playlist not supported"`

### Media type resolution

* Request includes `type` parameter **always** (`auto|audio|video`)
* Resolution rules:

  1. If `type` is `audio` or `video`, obey it.
  2. If `type=auto`:

     * Interrogate extracted formats:

       * If video streams exist → video
       * Else → audio
     * If ambiguous → video

### Overwrite behavior

* Fetching the **same URL again**:

  * Reuse the **same DB row**
  * Reuse the **same slug and GUID**
  * Overwrite files on disk
  * Append a log entry noting overwrite
* Concurrent fetches for the same URL:

  * Allowed
  * Later run overwrites earlier output
  * No locking or cancellation logic required

---

## 3. Identifiers & Directory Layout

### GUID

* Primary key for media items
* Use **NanoID**

  * Alphabet: `A–Z a–z 0–9`
* Stable forever (used as feed GUID)

### Slug

* Derived from media title
* Lowercase, sanitized
* Truncated by:

  * max words (default: 6)
  * max chars (default: 40)
* If slug exists:

  * Same URL → reuse slug
  * Different URL → append `-<nanoid>`
* Slug never changes once assigned to a URL

### Filesystem layout

```
/media/<slug>/
  content.m4a OR content.mp3 OR content.mp4
  thumbnail.webp (if available)
  subtitles.vtt (if available)
```

Fixed filenames are mandatory.

---

## 4. Configuration (Environment Variables)

### Required

* `STASHCAST_DATA_DIR=/path/to/data` (media stored in `STASHCAST_DATA_DIR/media`, default `./data`)
* `STASHCAST_API_KEY=<random string>`

### Optional

* `STASHCAST_MEDIA_BASE_URL=https://cdn.example.com`

  * If set: media URLs in feeds/pages use this base
  * If not set: Django serves media
* `STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO="..."`
* `STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO="..."`
* `STASHCAST_DEFAULT_FFMPEG_ARGS_AUDIO="..."`
* `STASHCAST_DEFAULT_FFMPEG_ARGS_VIDEO="..."`
* `STASHCAST_SLUG_MAX_WORDS=6`
* `STASHCAST_SLUG_MAX_CHARS=40`

---

## 5. Database Model

### `MediaItem`

Primary key: `guid` (NanoID string)

Fields:

* `guid` (PK)
* `source_url`
* `slug`
* `media_type` (`audio|video`)
* `requested_type` (`auto|audio|video`)
* `status`:

  * `PREFETCHING`
  * `DOWNLOADING`
  * `PROCESSING`
  * `READY`
  * `ERROR`
* Metadata:

  * `title`
  * `description`
  * `author`
  * `publish_date`
  * `duration_seconds`
  * `extractor`
  * `external_id`
  * `webpage_url`
* Files:

  * `base_dir`
  * `content_path`
  * `thumbnail_path` (blank if none)
  * `subtitle_path` (blank if none)
  * `file_size` (nullable)
  * `mime_type`
* Logging:

  * `log_path`
  * `error_message`
* Processing args:

  * `ytdlp_args`
  * `ffmpeg_args`
* Summary:

  * `summary` (TextField, blank)
* Timestamps:

  * `downloaded_at`
  * `created_at`
  * `updated_at`

---

## 6. Download & Processing Pipeline (Huey)

### Task: `process_media(guid)`

1. **PREFETCHING**

   * Detect direct vs yt-dlp
   * Extract metadata (yt-dlp if applicable)
   * Abort if playlist
   * Resolve media type
   * Generate slug if first time

2. **DOWNLOADING**

   * Direct download:

     * HEAD request (size/type)
     * Stream to disk
   * yt-dlp:

     * Use default args + overrides
     * Enforce:

       * no playlist
       * output to temp → rename to fixed filenames
       * subtitle download
       * thumbnail download

3. **PROCESSING**

   * Audio:

     * Prefer **m4a**
     * Do NOT transcode mp3 → m4a
     * Transcode only if necessary
   * Video:

     * Transcode only if codec/container/dimensions unsuitable
   * Subtitles:

     * Always convert to **VTT**
   * Thumbnails:

     * Convert to `thumbnail.webp` when possible

4. **READY**

   * Populate paths, size, mime
   * Set `downloaded_at`

5. **ERROR**

   * Capture error + logs

All stdout/stderr written to per-item log file.

---

## 7. Summary Generation (Future-ready)

* Summary generated **only from downloaded subtitles**
* No transcript stored in DB
* Separate Huey task: `generate_summary(guid)`
* Default implementation:

  * Extractive summarizer (TextRank/LexRank)
  * CPU-only
  * Fast, deterministic
* DB field: `summary`
* Admin button: **“Regenerate summary”**
* Code comment placeholder for future audio-based transcription

---

## 8. Public Endpoints

### `/stash/`

* Method: GET or POST
* Params:

  * `apikey` (required)
  * `url` (required)
  * `type` (`auto|audio|video`, required)
* Behavior:

  * Create or reuse MediaItem
  * Enqueue processing task
* Response:

  * JSON only (for bookmarklet use)

---

## 9. Feeds (Django Syndication Framework)

### Endpoints

* `/feeds/audio.xml`
* `/feeds/video.xml`

### Rules

* Generated on-the-fly
* Include only `READY` items
* Enclosure URLs:

  * Use `STASHCAST_MEDIA_BASE_URL` if set
  * Else Django-served URLs
* `<guid>` = `guid`
* Ordered by publish_date (fallback: downloaded_at)

---

## 10. Public Episode Page

* URL: `/items/<guid>/`
* Displays:

  * Title
  * Thumbnail
  * Summary (if available)
  * Description
  * Embedded audio/video player
  * Download link
  * Subtitle link (if exists)

Admin preview uses same rendering.

---

## 11. Admin Interface

### MediaItem admin

* List + filters + search
* Detail view:

  * Metadata
  * Embedded preview
  * Logs link
  * Regenerate summary button
  * Re-fetch/overwrite action

### Logs view

* Raw log viewer
* Tail support

---

## 12. Bookmarklet (Admin Tool)

### Location

* Admin sidebar → **Tools → Bookmarklet**

### Page features

* Explainer text
* Config form:

  * Base URL (default inferred from request)
  * Media type (`auto|audio|video`)
  * Test URL
* Generated bookmarklet:

  * Draggable link
  * Copyable textarea
* Test button:

  * Opens stash URL with test URL

### Bookmarklet behavior

* Opens new tab
* Always includes `type` parameter
* Shows JSON response

---

## 13. Admin Sidebar Integration

* Minimal template override (`nav_sidebar.html`)
* Add **Tools** section
* Link to bookmarklet page
* Future utility pages fit here naturally

---

## 14. Testing Strategy

### A) Fixture HTTP server

* Serves static media for deterministic tests

### B) Mock yt-dlp

* Wrapper client for injection
* Fake metadata + downloads

### C) Manual dev environment

* Django dev server
* Huey worker
* Optional fixture server

Only **one real service**; others are ephemeral or mocked.

---

## 15. Definition of Done

* Bookmarklet works from arbitrary pages
* Media downloads correctly
* Overwrites behave as specified
* Feeds play in AntennaPod (audio + video)
* Admin fully controls lifecycle
* Architecture supports future ML summaries

---

If you want, next steps could be:

* turning this into a **directory/module layout**
* drafting **initial migrations**
* or writing the **admin bookmarklet template + JS** first to bootstrap UI quickly
