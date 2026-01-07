from django import template

register = template.Library()


@register.filter
def duration(seconds):
    """
    Format duration in seconds to YouTube-style format.

    Examples:
        42 -> "0:42"
        125 -> "2:05"
        3825 -> "1:03:45"
    """
    if not seconds:
        return ''

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    else:
        return f'{minutes}:{secs:02d}'


@register.filter
def filesize(bytes_value):
    """
    Format bytes to human-readable file size.

    Examples:
        1024 -> "1.0 KB"
        1536 -> "1.5 KB"
        1048576 -> "1.0 MB"
        1073741824 -> "1.0 GB"
    """
    if not bytes_value:
        return '0 B'

    bytes_value = float(bytes_value)

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            if unit == 'B':
                return f'{int(bytes_value)} {unit}'
            else:
                return f'{bytes_value:.1f} {unit}'
        bytes_value /= 1024.0

    return f'{bytes_value:.1f} PB'
