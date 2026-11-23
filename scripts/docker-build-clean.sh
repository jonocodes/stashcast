#!/usr/bin/env bash
# Build the image from the files git knows about, the same context CI uses.
# This keeps local .env files and data directories out of the image.
#
# Usage: scripts/docker-build-clean.sh TAG [extra build args...]
set -euo pipefail

tag="${1:?usage: $0 TAG [build args...]}"
shift
engine="${CONTAINER_ENGINE:-docker}"
cd "$(git rev-parse --show-toplevel)"

git ls-files -z --cached --others --exclude-standard |
    tar --null --files-from=- --ignore-failed-read -c 2>/dev/null |
    "$engine" build -t "$tag" \
        --build-arg GIT_COMMIT_SHA="$(git rev-parse HEAD)" \
        --build-arg GIT_COMMIT_MSG="$(git log -1 --pretty=%s)" \
        --build-arg GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)" \
        "$@" -
