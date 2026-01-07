"""
Progress tracker for media processing tasks.

Provides thread-safe progress storage that can be updated by Huey tasks
and read by the SSE stream endpoint.
"""

import threading
from datetime import datetime

# Thread-safe progress storage
# Format: {guid: {'status': str, 'progress': int, 'updated_at': datetime}}
_progress_store = {}
_lock = threading.Lock()


def update_progress(guid, status, progress=None):
    """
    Update progress for a media item.

    Args:
        guid: Media item GUID
        status: Current status (PREFETCHING, DOWNLOADING, PROCESSING, READY, ERROR)
        progress: Optional progress percentage (0-100)
    """
    with _lock:
        _progress_store[guid] = {
            'status': status,
            'progress': progress,
            'updated_at': datetime.now(),
        }


def get_progress(guid):
    """
    Get current progress for a media item.

    Args:
        guid: Media item GUID

    Returns:
        dict with 'status', 'progress', and 'updated_at' or None if not found
    """
    with _lock:
        return _progress_store.get(guid)


def clear_progress(guid):
    """
    Clear progress for a media item (called when task completes).

    Args:
        guid: Media item GUID
    """
    with _lock:
        _progress_store.pop(guid, None)
