#!/usr/bin/env bash

set -e

echo "Running quality checks..."

# Run linter (ruff format + check)
ruff format || { echo "Ruff format failed" >&2; exit 2; }
ruff check --fix --unsafe-fixes || { echo "Ruff check failed" >&2; exit 2; }

# Run tests
pytest || { echo "Tests failed" >&2; exit 2; }

echo "All quality checks passed"
