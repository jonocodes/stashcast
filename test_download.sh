#!/bin/bash
# Test script to demonstrate downloading from the test server

set -e

API_KEY="dev-api-key-change-in-production"
BASE_URL="http://localhost:8000"
TEST_SERVER="http://localhost:8001"

echo "========================================="
echo "STASHCAST Download Test"
echo "========================================="
echo ""

# Check if servers are running
echo "Checking if servers are running..."

if ! curl -s "$BASE_URL" > /dev/null 2>&1; then
    echo "❌ Django server not running on $BASE_URL"
    echo "   Start it with: python manage.py runserver"
    exit 1
fi

if ! curl -s "$TEST_SERVER" > /dev/null 2>&1; then
    echo "❌ Test server not running on $TEST_SERVER"
    echo "   Start it with: python test_server.py"
    exit 1
fi

echo "✅ All servers running"
echo ""

# Test 1: Download audio file
echo "Test 1: Downloading audio file..."
echo "URL: $TEST_SERVER/01_Eragon_001_of_115.mp3"
echo ""

RESPONSE=$(curl -s "$BASE_URL/stash/?apikey=$API_KEY&url=$TEST_SERVER/01_Eragon_001_of_115.mp3&type=auto")
echo "Response: $RESPONSE"

GUID=$(echo $RESPONSE | grep -o '"guid":"[^"]*"' | cut -d'"' -f4)
echo "Item GUID: $GUID"
echo ""

# Wait for processing
echo "Waiting for download to complete (10 seconds)..."
sleep 10

echo ""
echo "========================================="

# Test 2: Download video file
echo "Test 2: Downloading video file..."
echo "URL: $TEST_SERVER/dji_fly_20250723_094842_13_1753459195176_quickshot.mp4"
echo ""

RESPONSE=$(curl -s "$BASE_URL/stash/?apikey=$API_KEY&url=$TEST_SERVER/dji_fly_20250723_094842_13_1753459195176_quickshot.mp4&type=auto")
echo "Response: $RESPONSE"

GUID=$(echo $RESPONSE | grep -o '"guid":"[^"]*"' | cut -d'"' -f4)
echo "Item GUID: $GUID"
echo ""

echo "Waiting for download to complete (10 seconds)..."
sleep 10

echo ""
echo "========================================="
echo "Test complete!"
echo "========================================="
echo ""
echo "Check results:"
echo "  Admin: $BASE_URL/admin/media/mediaitem/"
echo "  Audio feed: $BASE_URL/feeds/audio.xml"
echo "  Video feed: $BASE_URL/feeds/video.xml"
echo ""
echo "Downloaded files should be in:"
echo "  Audio: media_files/audio/"
echo "  Video: media_files/video/"
echo ""
