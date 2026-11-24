#!/usr/bin/env bash
# Boot a built StashCast image and check that it actually works.
#
# Usage: scripts/docker-smoke-test.sh IMAGE
# Set CONTAINER_ENGINE=podman to use podman instead of docker.
set -euo pipefail

image="${1:?usage: $0 IMAGE}"
engine="${CONTAINER_ENGINE:-docker}"
web="stashcast-smoke-web-$$"
worker="stashcast-smoke-worker-$$"
volume="stashcast-smoke-data-$$"

cleanup() {
    "$engine" rm -f "$web" "$worker" >/dev/null 2>&1 || true
    "$engine" volume rm -f "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    echo "--- web logs ---" >&2
    "$engine" logs "$web" >&2 || true
    echo "--- worker logs ---" >&2
    "$engine" logs "$worker" >&2 || true
    exit 1
}

# Run Python inside the web container as the app user
in_web() { "$engine" exec --user 1000:1000 "$web" python -c "$1"; }

env_args=(
    -e SECRET_KEY=smoke-test
    -e ALLOWED_HOSTS=localhost
    -e STASHCAST_USER_TOKEN=smoke-test
    -v "$volume:/app/data_docker"
)

echo "==> Starting web container from $image"
"$engine" run -d --name "$web" "${env_args[@]}" "$image" >/dev/null

echo "==> Waiting for /healthz"
healthy=""
for _ in $(seq 1 60); do
    if in_web "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" 2>/dev/null; then
        healthy=1
        break
    fi
    [ "$("$engine" inspect -f '{{.State.Running}}' "$web")" = "true" ] || fail "web container exited"
    sleep 2
done
[ -n "$healthy" ] || fail "/healthz never answered"

echo "==> Home page answers for an allowed host"
in_web "
import urllib.request
req = urllib.request.Request('http://127.0.0.1:8000/', headers={'Host': 'localhost'})
assert urllib.request.urlopen(req, timeout=5).status == 200
" || fail "home page did not return 200"

echo "==> Server runs as non-root"
uid=$("$engine" exec "$web" awk '/^Uid:/ {print $2}' /proc/1/status)
[ "$uid" = "1000" ] || fail "PID 1 runs as uid $uid, expected 1000"

echo "==> DEBUG is off by default"
"$engine" exec --user 1000:1000 -w /app "$web" python manage.py shell -c \
    "from django.conf import settings; assert not settings.DEBUG, 'DEBUG is on'" \
    || fail "DEBUG is on"

echo "==> Media tools are installed"
"$engine" exec "$web" ffmpeg -version >/dev/null || fail "ffmpeg missing"
ytdlp_version=$("$engine" exec "$web" yt-dlp --version) || fail "yt-dlp missing"
echo "    yt-dlp $ytdlp_version"

echo "==> Worker starts with the same image"
"$engine" run -d --name "$worker" "${env_args[@]}" "$image" python manage.py run_huey >/dev/null
sleep 5
[ "$("$engine" inspect -f '{{.State.Running}}' "$worker")" = "true" ] || fail "worker exited"

echo "PASS: $image"
