#!/bin/sh
# Container entrypoint. Starts as root only to make the data directories
# writable by the app user, then drops privileges for the real command.
# Set PUID/PGID to match the owner you want for files in bind mounts.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    for dir in "$STASHCAST_DATA_DIR" /app/staticfiles; do
        mkdir -p "$dir"
        # Only walk the tree when something is owned by someone else
        # (e.g. data written by older, root-running images).
        if [ -n "$(find "$dir" \( ! -user "$PUID" -o ! -group "$PGID" \) -print -quit)" ]; then
            echo "entrypoint: setting owner of $dir to $PUID:$PGID" >&2
            chown -R "$PUID:$PGID" "$dir"
        fi
    done
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
fi

exec "$@"
