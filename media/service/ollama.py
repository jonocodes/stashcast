"""Ollama service for LLM-based summarization."""

import urllib.request
import urllib.error
import json
from dataclasses import dataclass
from typing import Optional

from django.conf import settings


@dataclass
class OllamaStatus:
    """Status of Ollama service and model availability."""

    available: bool
    model_loaded: bool
    error: Optional[str] = None

    @property
    def ready(self) -> bool:
        """Return True if Ollama is available and model is loaded."""
        return self.available and self.model_loaded


def get_ollama_status() -> OllamaStatus:
    """
    Check if Ollama is running and the configured model is available.

    Returns:
        OllamaStatus with availability information
    """
    host = settings.STASHCAST_OLLAMA_HOST
    model = settings.STASHCAST_OLLAMA_MODEL

    try:
        # Check if Ollama is running by listing models
        url = f"{host}/api/tags"
        req = urllib.request.Request(url, method='GET')
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        # Check if the configured model is available
        available_models = [m.get('name', '') for m in data.get('models', [])]

        # Model names in Ollama can be with or without :latest tag
        model_base = model.split(':')[0]
        model_found = any(
            m == model or m.startswith(f"{model_base}:") or m == f"{model}:latest"
            for m in available_models
        )

        if model_found:
            return OllamaStatus(available=True, model_loaded=True)
        else:
            return OllamaStatus(
                available=True,
                model_loaded=False,
                error=f"Model '{model}' not found. Run: ollama pull {model}",
            )

    except urllib.error.URLError as e:
        return OllamaStatus(
            available=False,
            model_loaded=False,
            error=f"Ollama not reachable at {host}: {e.reason}",
        )
    except Exception as e:
        return OllamaStatus(
            available=False, model_loaded=False, error=f"Error checking Ollama: {e}"
        )


def generate_summary_ollama(text: str, max_sentences: int = 8) -> Optional[str]:
    """
    Generate a summary using Ollama.

    Args:
        text: The full text to summarize (e.g., from subtitles)
        max_sentences: Target number of sentences for the summary

    Returns:
        The generated summary, or None if generation failed
    """
    host = settings.STASHCAST_OLLAMA_HOST
    model = settings.STASHCAST_OLLAMA_MODEL

    # Construct the prompt
    prompt = f"""Summarize the following transcript in approximately {max_sentences} sentences.
Focus on the main topics, key points, and any important conclusions discussed.
Write in a clear, informative style suitable for a podcast description.
Do not include phrases like "This transcript discusses" or "The speaker talks about".
Just provide the summary directly.

Transcript:
{text}

Summary:"""

    try:
        url = f"{host}/api/generate"
        payload = json.dumps({
            'model': model,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': 0.3,  # Lower temperature for more focused summaries
                'num_predict': 500,  # Limit output length
            },
        }).encode('utf-8')

        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode('utf-8'))

        summary = data.get('response', '').strip()
        return summary if summary else None

    except Exception as e:
        # Log the error but don't raise - summarization failure shouldn't block anything
        print(f"Ollama summarization failed: {e}")
        return None


def get_summarizer_status() -> dict:
    """
    Get the current summarizer configuration and status for display.

    Returns:
        Dict with 'mode', 'status', and 'message' keys
    """
    summarizer = settings.STASHCAST_SUMMARIZER
    sentences = settings.STASHCAST_SUMMARY_SENTENCES

    if sentences <= 0:
        return {
            'mode': 'disabled',
            'status': 'disabled',
            'message': 'Summarization disabled (STASHCAST_SUMMARY_SENTENCES=0)',
        }

    if summarizer == 'extractive':
        return {
            'mode': 'extractive',
            'status': 'ready',
            'message': f'Extractive (LexRank, {sentences} sentences)',
        }

    if summarizer == 'ollama':
        ollama_status = get_ollama_status()
        model = settings.STASHCAST_OLLAMA_MODEL

        if ollama_status.ready:
            return {
                'mode': 'ollama',
                'status': 'ready',
                'message': f'Ollama ({model})',
            }
        elif ollama_status.available:
            return {
                'mode': 'ollama',
                'status': 'model_missing',
                'message': f'Ollama: model not found ({model})',
            }
        else:
            return {
                'mode': 'ollama',
                'status': 'unavailable',
                'message': 'Ollama: service not running',
            }

    return {
        'mode': 'unknown',
        'status': 'error',
        'message': f"Unknown summarizer: {summarizer}",
    }
