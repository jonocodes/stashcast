#!/bin/sh
# Default command for the web container: migrate, refresh static files, serve.
set -e
cd /app
./setup.sh
# The static volume outlives image upgrades, so refresh it on every start
python manage.py collectstatic --noinput --clear
exec gunicorn stashcast.wsgi
