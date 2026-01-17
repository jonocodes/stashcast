#!/usr/bin/env python

"""Check for missing translations in .po files (excluding 'en')."""

import sys
from pathlib import Path


def check_po_file(po_path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, msgid) for untranslated entries."""
    missing = []
    lines = po_path.read_text().splitlines()
    header_seen = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for msgid lines
        if line.startswith('msgid '):
            msgid_start = i
            # Collect full msgid (may span multiple lines)
            # Handle both 'msgid "text"' and 'msgid ""' followed by continuation
            if line == 'msgid ""':
                msgid_parts = []
            else:
                msgid_parts = [line[7:-1]]  # Extract content between quotes

            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid_parts.append(lines[i][1:-1])
                i += 1

            msgid = ''.join(msgid_parts)

            # Skip the header entry (first msgid "")
            if not msgid and not header_seen:
                header_seen = True
                # Skip past msgstr for header
                while i < len(lines) and (
                    lines[i].startswith('msgstr') or lines[i].startswith('"')
                ):
                    i += 1
                continue

            # Skip empty msgid (shouldn't happen except header)
            if not msgid:
                continue

            # Skip msgid_plural if present
            if i < len(lines) and lines[i].startswith('msgid_plural'):
                i += 1
                while i < len(lines) and lines[i].startswith('"'):
                    i += 1

            # Now check msgstr
            if i < len(lines) and lines[i].startswith('msgstr'):
                # Collect full msgstr
                msgstr_parts = []
                if lines[i].startswith('msgstr['):
                    # Plural form - check all msgstr[n] entries
                    while i < len(lines) and lines[i].startswith('msgstr['):
                        # Handle msgstr[n] "" with continuation or inline content
                        after_bracket = lines[i].split(']', 1)[1].strip()
                        if after_bracket == '""':
                            pass  # Empty, check continuations
                        elif after_bracket.startswith('"'):
                            msgstr_parts.append(after_bracket[1:-1])
                        i += 1
                        while i < len(lines) and lines[i].startswith('"'):
                            msgstr_parts.append(lines[i][1:-1])
                            i += 1
                    # Check if all plural forms are empty
                    if not any(msgstr_parts):
                        missing.append((msgid_start + 1, msgid))
                    continue
                else:
                    # Regular msgstr - extract content after 'msgstr '
                    msgstr_content = lines[i][7:]  # Everything after 'msgstr '
                    if msgstr_content == '""':
                        pass  # Empty on this line, check continuations
                    elif msgstr_content.startswith('"'):
                        msgstr_parts.append(msgstr_content[1:-1])

                    i += 1
                    while i < len(lines) and lines[i].startswith('"'):
                        msgstr_parts.append(lines[i][1:-1])
                        i += 1

                    msgstr = ''.join(msgstr_parts)
                    if not msgstr:
                        missing.append((msgid_start + 1, msgid))
        else:
            i += 1

    return missing


def main():
    locale_dir = Path(__file__).parent.parent / 'locale'

    if not locale_dir.exists():
        print(f'Error: locale directory not found at {locale_dir}', file=sys.stderr)
        sys.exit(1)

    total_missing = 0
    languages_checked = []

    for lang_dir in sorted(locale_dir.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name == 'en':
            continue

        po_file = lang_dir / 'LC_MESSAGES' / 'django.po'
        if not po_file.exists():
            continue

        languages_checked.append(lang_dir.name)
        missing = check_po_file(po_file)

        if missing:
            print(f'\n{lang_dir.name}: {len(missing)} missing translation(s)')
            print('-' * 40)
            for line_num, msgid in missing:
                # Truncate long msgids for display
                display_msgid = msgid if len(msgid) <= 60 else msgid[:57] + '...'
                print(f'  Line {line_num}: {display_msgid}')
            total_missing += len(missing)

    if not languages_checked:
        print('No non-English language directories found.')
        sys.exit(0)

    print(f'\n{"=" * 40}')
    print(f'Languages checked: {", ".join(languages_checked)}')
    print(f'Total missing translations: {total_missing}')

    if total_missing > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
