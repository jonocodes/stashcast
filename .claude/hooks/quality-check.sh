#!/usr/bin/env bash

set -e

echo "Running quality checks..."

# Install dependencies if needed
./setup.sh --with-packages || { echo "Setup failed" >&2; exit 2; }

# Run linter
uv run ruff format || { echo "Ruff format failed" >&2; exit 2; }
uv run ruff check --fix --unsafe-fixes || { echo "Ruff check failed" >&2; exit 2; }

# Run tests
uv run pytest || { echo "Tests failed" >&2; exit 2; }

echo "✓ All quality checks passed"
