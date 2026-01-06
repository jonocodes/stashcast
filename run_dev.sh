#!/usr/bin/env bash
# Development runner - uses honcho to manage all services

set -e

echo "========================================="
echo "STASHCAST Development Environment"
echo "========================================="
echo ""
echo "Starting all services with honcho..."
echo ""
echo "Services:"
echo "  - Django (http://localhost:8000)"
echo "  - Huey worker (auto-reload enabled)"
echo "  - Test server (http://localhost:8001)"
echo ""
echo "Press Ctrl+C to stop all services"
echo "========================================="
echo ""

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate
fi

# Run honcho
exec honcho start
