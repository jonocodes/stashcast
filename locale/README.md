# Translation Files

This directory contains translation files for internationalization (i18n).

## Structure

```
locale/
├── en/              # English (reference)
│   └── LC_MESSAGES/
│       ├── django.po   # Translation source
│       └── django.mo   # Compiled (generated)
├── es/              # Spanish
│   └── LC_MESSAGES/
│       ├── django.po
│       └── django.mo
└── ...              # Other languages
```

## Generating Translation Files

To create translation files for a new language:

```bash
python manage.py makemessages -l <language_code>
```

Examples:
```bash
python manage.py makemessages -l es  # Spanish
python manage.py makemessages -l fr  # French
python manage.py makemessages -l de  # German
python manage.py makemessages -l ja  # Japanese
```

## Updating Translations

After making code changes with new translatable strings:

```bash
# Update all existing translation files
python manage.py makemessages -a

# Or update specific language
python manage.py makemessages -l es
```

## Compiling Translations

After editing .po files, compile them:

```bash
python manage.py compilemessages
```

This generates .mo files that Django uses at runtime.

## Notes

- `.po` files are text files that translators edit
- `.mo` files are binary compiled versions (don't edit these)
- `.mo` files should be committed to git for deployment
- Translation keys are extracted from:
  - Python code: `_("text")` or `gettext_lazy("text")`
  - Templates: `{% trans "text" %}` or `{% blocktrans %}`

## See Also

- [Full i18n Documentation](../docs/INTERNATIONALIZATION.md)
- [Django i18n Guide](https://docs.djangoproject.com/en/stable/topics/i18n/)
