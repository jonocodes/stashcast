"""Gunicorn settings used by the Docker image.

Override any of these with the GUNICORN_CMD_ARGS environment variable,
e.g. GUNICORN_CMD_ARGS="--workers 4".
"""

bind = '0.0.0.0:8000'
# Threads rather than more processes: the stash progress page holds a
# server-sent events connection open for the whole download.
worker_class = 'gthread'
workers = 2
threads = 8
accesslog = '-'
