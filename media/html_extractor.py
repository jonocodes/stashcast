"""
HTML media extraction utilities.

Provides functions to extract embedded audio/video from HTML pages.
"""
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup

def extract_title_from_html(soup, media_url):
    """
    Extract title from HTML page or media filename.

    Args:
        soup: BeautifulSoup object of the HTML page
        media_url: URL of the media file

    Returns:
        str: Extracted title
    """
    # First try to get HTML page title
    title_tag = soup.find('title')
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    # Last resort
    return "content"


def extract_media_from_html_page(url):
    """
    Extract embedded media URL and metadata from an HTML page.

    This function looks for <audio>, <video>, and <source> tags in HTML.
    It tries to extract both the media URL and a meaningful title.

    Args:
        url: URL of the HTML page (http/https or file://)

    Returns:
        dict with keys:
            - media_url: URL of the media file (or None if not found)
            - media_type: 'audio' or 'video' (or None if not found)
            - title: Extracted title from HTML <title> or media filename
            - webpage_url: Original HTML page URL

    Raises:
        Exception: If fetching the HTML fails
    """
    # Fetch the HTML
    if url.startswith('file://'):
        # Read from local file
        file_path = Path(url.replace('file://', ''))
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        base_url = url
    else:
        # Fetch from HTTP
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        html_content = response.text
        base_url = url

    soup = BeautifulSoup(html_content, 'html.parser')

    # Look for <audio> tags with src
    audio_tag = soup.find('audio', src=True)
    if audio_tag:
        media_url = urljoin(base_url, audio_tag['src'])
        return {
            'media_url': media_url,
            'media_type': 'audio',
            'title': extract_title_from_html(soup, media_url),
            'webpage_url': base_url
        }

    # Look for <video> tags with src
    video_tag = soup.find('video', src=True)
    if video_tag:
        media_url = urljoin(base_url, video_tag['src'])
        return {
            'media_url': media_url,
            'media_type': 'video',
            'title': extract_title_from_html(soup, media_url),
            'webpage_url': base_url
        }

    # Look for <source> tags inside <audio>
    audio_with_source = soup.find('audio')
    if audio_with_source:
        source_tag = audio_with_source.find('source', src=True)
        if source_tag:
            media_url = urljoin(base_url, source_tag['src'])
            return {
                'media_url': media_url,
                'media_type': 'audio',
                'title': extract_title_from_html(soup, media_url),
                'webpage_url': base_url
            }

    # Look for <source> tags inside <video>
    video_with_source = soup.find('video')
    if video_with_source:
        source_tag = video_with_source.find('source', src=True)
        if source_tag:
            media_url = urljoin(base_url, source_tag['src'])
            return {
                'media_url': media_url,
                'media_type': 'video',
                'title': extract_title_from_html(soup, media_url),
                'webpage_url': base_url
            }

    # No media found
    return {
        'media_url': None,
        'media_type': None,
        'title': None,
        'webpage_url': base_url
    }
