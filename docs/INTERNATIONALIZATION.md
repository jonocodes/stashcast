# Internationalization (i18n) Guide

StashCast now supports multiple languages! The UI language and video subtitle language are configured via the `LANGUAGE_CODE` environment variable.

## Quick Start

### Set Your Language

Add to your `.env` file:

```bash
# Set language code ('en' for English, 'es' for Spanish)
LANGUAGE_CODE=es
```

### Supported Languages

**Currently supported with full translations:**
- `en` / `en-us` - English (default)
- `es` - Español (Spanish)

**Adding more languages:**
Additional languages can be added by creating translation files (`.po`) and compiling them. See the "Creating Translations" section below for instructions on how to contribute translations for other languages.

## How It Works

### UI Translation

The `LANGUAGE_CODE` setting controls:
- All text in the web interface (buttons, labels, messages)
- Admin interface language
- RSS feed titles and descriptions
- Status messages and error messages

### Subtitle/Transcript Language

The same `LANGUAGE_CODE` setting also controls:
- **Video subtitle download language** - yt-dlp will download subtitles/transcripts in your specified language
- Automatic subtitle generation (if available)

When you set `LANGUAGE_CODE=es`, for example:
- The UI will display in Spanish
- Videos will download Spanish subtitles (if available)
- Summaries will be generated from Spanish transcripts

## Creating Translations

### For Developers: Adding a New Language

1. **Generate message files** for the language you want to add (e.g., Spanish):

```bash
python manage.py makemessages -l es
```

This creates `locale/es/LC_MESSAGES/django.po`

2. **Translate the strings** in the `.po` file:

```po
msgid "Add URL"
msgstr "Añadir URL"

msgid "Download media from any URL"
msgstr "Descargar medios desde cualquier URL"
```

3. **Compile the translations**:

```bash
python manage.py compilemessages
```

This creates `locale/es/LC_MESSAGES/django.mo`

4. **Test your translations**:

```bash
export LANGUAGE_CODE=es
python manage.py runserver
```

### Updating Existing Translations

When new strings are added to the codebase:

```bash
# Update all translation files with new strings
python manage.py makemessages -a

# Compile after translating
python manage.py compilemessages
```

## Translation File Structure

```
stashcast/
├── locale/
│   ├── en/
│   │   └── LC_MESSAGES/
│   │       ├── django.po   # English strings (reference)
│   │       └── django.mo   # Compiled (generated)
│   ├── es/
│   │   └── LC_MESSAGES/
│   │       ├── django.po   # Spanish translations
│   │       └── django.mo   # Compiled (generated)
│   └── fr/
│       └── LC_MESSAGES/
│           ├── django.po   # French translations
│           └── django.mo   # Compiled (generated)
```

## Language Code Format

Django uses standard language codes:
- Two-letter codes: `en`, `es`, `fr`, `de`
- Regional variants: `en-us`, `en-gb`, `pt-br`, `zh-hans`

StashCast automatically extracts the primary language code for subtitle downloads:
- `en-us` → subtitles in `en`
- `zh-hans` → subtitles in `zh-hans`
- `pt-br` → subtitles in `pt`

## What Gets Translated

### Templates (HTML)
- All user-facing text wrapped in `{% trans %}` or `{% blocktrans %}` tags
- Page titles, buttons, labels, descriptions, messages

### Python Code
- Model field choices (status messages, media types)
- Form labels and help text
- View messages and notifications
- Error messages

### What Doesn't Get Translated
- Media content (titles, descriptions from sources)
- User-entered data
- URLs and technical identifiers
- Code and configuration

## Accessibility Note

When combined with proper subtitle support, i18n makes StashCast accessible to:
- **Non-English speakers** - full UI in their language
- **Deaf/hard-of-hearing users** - subtitles in their language
- **Learning users** - content with transcripts for comprehension

## Contributing Translations

We welcome translation contributions! To add a new language:

1. Fork the repository
2. Generate the message file: `python manage.py makemessages -l <lang_code>`
3. Translate strings in `locale/<lang_code>/LC_MESSAGES/django.po`
4. Compile: `python manage.py compilemessages`
5. Test your translations
6. Submit a pull request

Please ensure translations are:
- Accurate and natural in the target language
- Consistent in terminology
- Properly formatted (maintain placeholders like `%(name)s`)
- Culturally appropriate

## Troubleshooting

### Translations not showing up?

1. **Compile messages**: `python manage.py compilemessages`
2. **Restart the server**: Changes require a restart
3. **Check LANGUAGE_CODE**: Verify it's set correctly in your `.env`
4. **Clear browser cache**: Sometimes needed for static content

### Subtitles not in the right language?

1. **Check LANGUAGE_CODE**: Should match your preferred subtitle language
2. **Not all videos have subtitles**: Some sources don't provide subtitles in all languages
3. **Automatic subtitles**: yt-dlp will fallback to auto-generated subtitles if available

### Mixed language UI?

- Some strings may not be translated yet
- Contribute translations to help complete the language pack!

## Technical Details

### Settings Configuration

In `stashcast/settings.py`:

```python
# Language code from environment variable
LANGUAGE_CODE = os.environ.get('LANGUAGE_CODE', 'en-us')

# Supported languages
LANGUAGES = [
    ('en', 'English'),
    ('es', 'Español'),
    # ... more languages
]

# Translation files location
LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Subtitle language for yt-dlp (derived from LANGUAGE_CODE)
STASHCAST_SUBTITLE_LANGUAGE = LANGUAGE_CODE.split('-')[0]
```

### yt-dlp Integration

In `media/service/download.py`:

```python
ydl_opts = {
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitleslangs': [settings.STASHCAST_SUBTITLE_LANGUAGE],
    # ... other options
}
```

## References

- [Django i18n Documentation](https://docs.djangoproject.com/en/stable/topics/i18n/)
- [yt-dlp Subtitle Options](https://github.com/yt-dlp/yt-dlp#subtitle-options)
- [Language Codes (ISO 639-1)](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)
