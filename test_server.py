#!/usr/bin/env python
"""
Simple HTTP server for testing media downloads.
Serves files from demo_data directory.
"""

import os
import http.server
import socketserver
from pathlib import Path

PORT = 8001
DIRECTORY = 'demo_data'


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Add CORS headers for cross-origin requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def log_message(self, format, *args):
        # Custom log format
        print(f'[TEST SERVER] {self.address_string()} - {format % args}')


if __name__ == '__main__':
    # Verify demo_data directory exists
    if not os.path.exists(DIRECTORY):
        print(f'Error: {DIRECTORY} directory not found!')
        print(f'Please create it with: mkdir {DIRECTORY}')
        exit(1)

    # List available files
    print(f'\n{"=" * 60}')
    print(f'TEST SERVER - Serving files from {DIRECTORY}/')
    print(f'{"=" * 60}')
    print(f'\nServer running on: http://localhost:{PORT}/')
    print(f'\nAvailable test URLs:')

    demo_path = Path(DIRECTORY)
    for file in sorted(demo_path.iterdir()):
        if file.is_file():
            file_size = file.stat().st_size
            size_mb = file_size / (1024 * 1024)
            url = f'http://localhost:{PORT}/{file.name}'
            print(f'  - {url}')
            print(f'    ({size_mb:.2f} MB)')

    print(f'\n{"=" * 60}')
    print('Press Ctrl+C to stop the server\n')

    # Start server
    with socketserver.TCPServer(('', PORT), CustomHTTPRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n\nShutting down test server...')
            httpd.shutdown()
