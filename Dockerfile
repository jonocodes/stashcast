FROM python:3.13-slim

# Build info shown on the About page (passed as build args; no .git needed)
ARG GIT_COMMIT_SHA=""
ARG GIT_COMMIT_MSG=""
ARG GIT_BRANCH=""

# The app runs as an arbitrary uid (see docker/entrypoint.sh), so HOME and
# caches (yt-dlp keeps one) point somewhere that is always writable
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STASHCAST_DATA_DIR=/app/data_docker \
    NLTK_DATA=/usr/share/nltk_data \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache

# yt-dlp comes from pip (below), which is far newer than Debian's
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg just sqlite3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Exact, hashed versions exported from uv.lock
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# The one deliberate exception to the lock: sites like YouTube break old
# yt-dlp releases, so take the newest. Cached builds reuse this layer; the
# manual "Run workflow" rebuild skips the cache to pick up a new release.
RUN pip install --no-cache-dir --upgrade yt-dlp

# Summarizer data, baked in so containers don't download it on every start
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt_tab stopwords

COPY . /app/

# Outside /app so volume mounts don't hide it. Python builds the JSON so
# quotes in commit messages can't break it.
RUN GIT_COMMIT_SHA="$GIT_COMMIT_SHA" GIT_COMMIT_MSG="$GIT_COMMIT_MSG" GIT_BRANCH="$GIT_BRANCH" \
    python -c 'import json, os; json.dump({"commit_sha": os.environ["GIT_COMMIT_SHA"], "commit_message": os.environ["GIT_COMMIT_MSG"], "branch": os.environ["GIT_BRANCH"]}, open("/etc/git_info.json", "w"))'

RUN SECRET_KEY="dummy" ALLOWED_HOSTS="dummy" STASHCAST_USER_TOKEN="dummy" \
    python manage.py collectstatic --noinput

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# The worker uses the same image with: python manage.py run_huey
CMD ["/app/docker/start-web.sh"]
