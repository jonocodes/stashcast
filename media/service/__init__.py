"""
Service layer for media processing.

This module contains reusable functions for downloading and transcoding media,
independent of the database/Django models. These functions are used by:
- The web API + Huey background tasks (media/tasks.py)
- The CLI management command (management/commands/fetch.py)
"""
