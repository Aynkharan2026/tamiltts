"""
Google Cloud Text-to-Speech integration.

Mixed-language handling approach:
- Tamil text often contains English words (product names, technical terms, etc.)
- We use SSML with <lang xml:lang="en-US"> tags around detected English "islands"
- The ta-IN voice will attempt to pronounce wrapped English spans using en-US phonology
- Limitation: Google TTS may not perfectly switch phonology mid-utterance; results
  vary by voice and content. This is the best available approach without a multilingual voice.
- English detection: sequences of ASCII letters (A-Z, a-z), possibly with digits,
  hyphens, apostrophes — but excluding common single-letter Tamil transliterations.
  Emails and URLs are also wrapped.
"""

import re
import time
import logging
from google.cloud import texttospeech
from app.models import VoiceMode, VOICE_MAP
from app.config import settings

logger = logging.getLogger(__name__)

# Detect English words: 2+ ASCII letters (avoid false positives on single chars)
ENGLISH_ISLAND_RE = re.compile(
    r'(?:'
    r'https?://\S+'                          # URLs
    r'|[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}'       # Emails
    r'|[A-Za-z][A-Za-z0-9\'-]*[A-Za-z0-9]' # Words 2+ chars
    r'|[A-Z]{1}'                             # Single uppercase (abbreviation initials)
    r')'
)


def _escape_xml(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def build_ssml(text: str) -> str:
    """
    Build SSML wrapping English spans with <lang xml:lang="en-US">.
    """
    result = []
    last = 0
    for m in ENGLISH_ISLAND_RE.finditer(text):
        start, end = m.start(), m.end()
        # Tamil portion before this English span
        tamil_part = text[last:start]
        if tamil_part:
            result.append(_escape_xml(tamil_part))
        eng_word = m.group(0)
        result.append(f'<lang xml:lang="en-US">{_escape_xml(eng_word)}</lang>')
        last = end
    # Remaining Tamil text
    remaining = text[last:]
    if remaining:
        result.append(_escape_xml(remaining))

    ssml_body = "".join(result)
    return f'<speak>{ssml_body}</speak>'


def synthesize_chunk(
    text: str,
    voice_mode: VoiceMode,
    speed: float,
    max_retries: int = 2,
) -> bytes:
    """
    Synthesize a single text chunk to MP3 bytes.
    Retries on transient errors.
    Returns raw MP3 bytes.
    Raises on persistent failure.
    """
    client = texttospeech.TextToSpeechClient()
    voice_name = VOICE_MAP[voice_mode]
    ssml = build_ssml(text)

    synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="ta-IN",
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=max(0.25, min(4.0, speed)),  # GCP limits: 0.25–4.0
    )

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )
            audio = response.audio_content
            if not audio or len(audio) < 100:
                raise ValueError(f"Empty or suspiciously small audio response ({len(audio)} bytes)")
            return audio
        except Exception as e:
            last_exc = e
            logger.warning(
                "TTS synthesis attempt %d/%d failed: %s",
                attempt, max_retries, str(e)
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"TTS synthesis failed after {max_retries} attempts: {last_exc}")
