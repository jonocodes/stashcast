set shell := ["bash", "-c"]

# compose files for running a locally built image
dev_compose := "docker compose -f docker-compose.yml -f docker-compose.dev.yml"

# set dotenv-load

# setenv := '. ".envrc"'

# show list of commands
help:
    just --list

# setup the db etc
setup:
    ./setup.sh

# install python dependencies and then the db
setup-with-packages:
    ./setup.sh --with-packages

# install the locked python dependencies (including dev tools) into the active venv
install:
    pip install -r requirements-dev.txt

# re-lock after editing dependencies in pyproject.toml (keeps current versions where possible)
lock:
    uv lock
    scripts/export-requirements.sh

# upgrade every dependency to the newest allowed version, then test
upgrade:
    uv lock --upgrade
    scripts/export-requirements.sh
    just install
    just test
    just docker-smoke
    git diff --stat uv.lock requirements.txt requirements-dev.txt

# clean up dev dependencies
clean:
    rm -rf __pycache__

# remove all the data
clean-data:
    # rm -rf data
    rm -rf data_docker
    just setup

# lint, test, chcek translations
pre-commit:
    just lint
    just test
    ./scripts/check_translations.py

# run the django server
dev-web:
    honcho start web

# run the server, the worker, and demo data server
dev:
    exec honcho start

# run the dev services in docker, built from this checkout
dev-docker *args:
    {{ dev_compose }} up --build {{ args }}

# kill the local dev process by port in case it's running detached
kill:
    lsof -i tcp:8000 -t | xargs kill

# run linting and auto-fixing
lint:
    ruff format
    ruff check --fix --unsafe-fixes

# create a superuser with username 'admin' and password 'admin' for testing/dev
create-admin-dummy:
    DJANGO_SUPERUSER_PASSWORD=admin ./manage.py createsuperuser --username admin --email "" --noinput

# create or update a test superuser (idempotent, safe to re-run)
create-test-user username="test" password="test":
    ./manage.py create_test_user {{ username }} {{ password }}

# run tests
test *args:
    pytest {{ args }}

# alias for django manage command
manage *args:
    ./manage.py {{ args }}

# alias to manage
m *args:
    ./manage.py {{ args }}

# alias to run commands in docker
docker-run *args:
    {{ dev_compose }} run web {{ args }}

# build the image from git-tracked files (like CI) and smoke test it
docker-smoke tag="stashcast:smoke":
    scripts/docker-build-clean.sh {{ tag }}
    scripts/docker-smoke-test.sh {{ tag }}

# bump the version, commit and tag a release (e.g. just release 0.2.0)
release version:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "{{ version }}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "version must look like 1.2.3"; exit 1; }
    [[ "$(git rev-parse --abbrev-ref HEAD)" == main ]] || { echo "release from main"; exit 1; }
    git diff --quiet && git diff --cached --quiet || { echo "commit or stash your changes first"; exit 1; }
    sed -i 's/^version = ".*"/version = "{{ version }}"/' pyproject.toml
    git commit -am "Release v{{ version }}"
    git tag -a "v{{ version }}" -m "v{{ version }}"
    echo "Tagged v{{ version }}. Publish it with: git push origin main v{{ version }}"

# serve the marketing site (site/public) at http://localhost:8090
site port="8090":
    python3 -m http.server {{ port }} -d site/public

# install the marketing-site tooling (Playwright); set CHROME to use an existing Chromium
site-deps:
    cd site && npm ci --silent

# re-render the invented showcase cover art into media/fixtures/showcase/covers
site-covers: site-deps
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    node site/scripts/covers.mjs "$tmp"
    for f in "$tmp"/*.png; do
        ffmpeg -loglevel error -y -i "$f" -quality 82 "media/fixtures/showcase/covers/$(basename "$f" .png).webp"
    done

# regenerate the site + README screenshots from a throwaway instance seeded with showcase data
site-screenshots port="8777": site-deps
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    export STASHCAST_DATA_DIR="$tmp" NLTK_DATA="$tmp" DEBUG=True SECRET_KEY=screenshots \
        STASHCAST_USER_TOKEN=screenshots ALLOWED_HOSTS=127.0.0.1,localhost
    ./manage.py migrate -v 0
    DJANGO_SUPERUSER_PASSWORD=admin ./manage.py createsuperuser --username admin --email "" --noinput
    ./manage.py seed_showcase
    ./manage.py runserver 127.0.0.1:{{ port }} --noreload >"$tmp/server.log" 2>&1 &
    server=$!
    trap 'kill $server 2>/dev/null || true; rm -rf "$tmp"' EXIT
    for _ in $(seq 60); do curl -sf -o /dev/null http://127.0.0.1:{{ port }}/ && break; sleep 0.5; done
    out=site/public/assets
    # hero covers first: the OG card below is rendered from the site itself
    for f in media/fixtures/showcase/covers/*.webp; do
        ffmpeg -loglevel error -y -i "$f" -vf scale=320:-1 -quality 80 "$out/covers/$(basename "$f")"
    done
    mkdir "$tmp/shots"
    node site/scripts/screenshots.mjs http://127.0.0.1:{{ port }} "$tmp/shots"
    for f in "$tmp"/shots/*.png; do
        n=$(basename "$f" .png)
        [ "$n" = og ] || ffmpeg -loglevel error -y -i "$f" -quality 82 "$out/app/$n.webp"
    done
    cp "$tmp/shots/og.png" "$out/og.png"
    ffmpeg -loglevel error -y -i "$tmp/shots/grid-dark.png" -vf scale=1280:-1 docs/screenshot-grid-view.png
    echo "Updated $out/app, $out/covers, $out/og.png and docs/screenshot-grid-view.png"
