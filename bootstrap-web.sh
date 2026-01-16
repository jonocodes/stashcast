#!/usr/bin/env bash

# This script is for bootstrapping the bare vm/container that Claude Code Web runs in - which looks like Ubuntu 22.04 LTS

set -e

export DEBIAN_FRONTEND=noninteractive

apt update -y

apt install -y software-properties-common ffmpeg yt-dlp curl

add-apt-repository ppa:deadsnakes/ppa -y

apt install python3.12 python3.12-venv python3-pip3 -y

curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin

python3.12 -m venv .venv

source .venv/bin/activate

