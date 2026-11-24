#!/usr/bin/env bash
# Write requirements.txt and requirements-dev.txt from uv.lock.
# pip users (Docker, CI, cPanel, bootstrap.sh) install these exact, hashed pins.
# Don't edit them by hand: change pyproject.toml and run `just lock`.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uv="${UV:-uv}"

"$uv" export --quiet --frozen --no-emit-project --no-dev -o requirements.txt
"$uv" export --quiet --frozen --no-emit-project -o requirements-dev.txt
