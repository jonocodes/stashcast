#!/usr/bin/env bash

set -e

echo "Running quality checks..."

# Run linter if ruff is available
if command -v ruff &> /dev/null; then
    ruff format || { echo "Ruff format failed" >&2; exit 2; }
    ruff check --fix --unsafe-fixes || { echo "Ruff check failed" >&2; exit 2; }
else
    echo "Skipping lint (ruff not installed)"
fi

# Run tests only if Django is installed (indicates full setup)
if python -c "import django" &> /dev/null; then
    pytest || { echo "Tests failed" >&2; exit 2; }
else
    echo "Skipping tests (dependencies not installed - run ./setup.sh --with-packages)"
fi

echo "All quality checks passed"
