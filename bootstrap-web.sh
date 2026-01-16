#!/usr/bin/env bash

# This script bootstraps the Claude Code Web environment (Ubuntu 22.04 LTS container)
# It auto-detects if running in Claude Code Web and exits gracefully if not

set -e

# Detect Claude Code Web environment
if [[ "$CLAUDE_CODE_REMOTE" != "true" ]]; then
    echo "Not running in Claude Code Web environment, skipping bootstrap"
    exit 0
fi

echo "Claude Code Web detected, bootstrapping environment..."

export DEBIAN_FRONTEND=noninteractive

# Install system dependencies
apt update -y
apt install -y software-properties-common ffmpeg yt-dlp curl ruff

# Install just command runner
if ! command -v just &> /dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
fi

echo "Bootstrap complete"

