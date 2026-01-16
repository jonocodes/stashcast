#!/usr/bin/env bash

set -e

echo "Running quality checks..."

# Run linter
just lint || { echo "Linting failed" >&2; exit 2; }

# Run tests
just test || { echo "Tests failed" >&2; exit 2; }

echo "All quality checks passed"
