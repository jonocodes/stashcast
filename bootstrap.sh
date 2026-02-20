#!/usr/bin/env bash

# This script bootstraps the development environment
# It auto-detects the environment type and runs the appropriate setup
# This is primarily intended for Claude Code Web which runs in an Ubuntu container.

set -e

# Detect environment and run appropriate setup
if grep -q "Ubuntu 22" /etc/os-release || [[ "$CLAUDE_CODE_REMOTE" == "true" ]]; then
    # Claude Code Web environment (Ubuntu 22.04 LTS container)
    echo "Claude Code Web detected, bootstrapping environment..."

    export DEBIAN_FRONTEND=noninteractive
    apt update -y

    # Setup flox - unfortunately this does not work well in containers
    # apt install -y curl sudo

    # curl -sL "https://downloads.flox.dev/by-env/stable/deb/flox.deb" -o /tmp/flox.deb && apt install -y /tmp/flox.deb

    # flox init --auto-setup
    # flox install ffmpeg just python313Packages.pip python3 ruff yt-dlp

    apt install -y software-properties-common ffmpeg yt-dlp curl gettext python3.12 python3.12-venv python3.12-dev

    # Install just command runner
    if ! command -v just &> /dev/null; then
        curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
    fi

    # Create virtual environment with Python 3.12
    VENV_DIR="${PWD}/.venv"
    if [[ ! -d "$VENV_DIR" ]]; then
        echo "Creating Python 3.12 virtual environment..."
        python3.12 -m venv "$VENV_DIR"
    fi

    # Activate venv and upgrade pip
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip

    # Install Python packages first (before setup.sh needs them)
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    pip install ruff

    # Now run setup (NLTK download, migrations, etc.)
    ./setup.sh

    echo "Claude Code Web bootstrap complete"

elif command -v flox &> /dev/null || [[ -d ".flox" ]]; then

    echo "Flox detected"

    flox install ffmpeg just python313Packages.pip python3 ruff yt-dlp gettext

    # check if flox is activated
    if [[ -v FLOX_ENV_PROJECT ]]; then
        # just setup-with-packages
        ./setup.sh
        pip install -r requirements-dev.txt
    else
        # flox activate -- just setup-with-packages
        flox activate -- ./setup.sh
        flox activate -- pip install -r requirements-dev.txt
        echo " == Please activate flox to continue == "
        return 0
    fi

else
    echo "Environment type unknown"
    exit 1
fi

DEMO_USERNAME=demo DEMO_PASSWORD=omed ./manage.py create_demo_user
TEST_USERNAME=admin TEST_PASSWORD=admin ./manage.py create_test_user
