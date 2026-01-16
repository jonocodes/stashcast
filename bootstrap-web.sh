#!/usr/bin/env bash

# This script bootstraps the development environment
# It auto-detects the environment type and runs the appropriate setup

set -e

# Detect environment and run appropriate setup
if [[ "$CLAUDE_CODE_REMOTE" == "true" ]]; then
    # Claude Code Web environment (Ubuntu 22.04 LTS container)
    echo "Claude Code Web detected, bootstrapping environment..."

    export DEBIAN_FRONTEND=noninteractive

    # Install system dependencies
    apt update -y
    apt install -y software-properties-common ffmpeg yt-dlp curl ruff

    # Install just command runner
    if ! command -v just &> /dev/null; then
        curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
    fi

    # Install Python packages and run migrations
    ./setup.sh --with-packages

    echo "Claude Code Web bootstrap complete"

elif command -v flox &> /dev/null || [[ -d ".flox" ]]; then
    # Flox environment (local machine)
    echo "Flox detected, activating environment..."

    flox activate
    just setup

    echo "Flox bootstrap complete"

else
    echo "Environment type unknown"
    exit 1
fi

