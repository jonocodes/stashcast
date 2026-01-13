#!/usr/bin/env bash

set -e

echo "Running quality checks..."

# Install dependencies if needed
./setup.sh --with-packages || { echo "Setup failed" >&2; exit 2; }

# Run linter
just lint || { echo "Justfile linting failed" >&2; exit 2; }

# Run tests
just test || { echo "Tests failed" >&2; exit 2; }

echo "✓ All quality checks passed"
