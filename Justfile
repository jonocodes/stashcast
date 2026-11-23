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
