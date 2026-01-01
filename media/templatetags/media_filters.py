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
        return ""

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
