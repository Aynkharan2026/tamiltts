"""
Unicode Sanitizer Service
Tamil TTS Studio — VoxTN
Runs BEFORE any TTS engine receives text.
Deterministic: same input always produces same output.
"""
import unicodedata
import re
import logging

logger = logging.getLogger(__name__)

# Zero-width characters to strip
ZW_CHARS = [
    "\u200B",  # Zero Width Space
    "\u200C",  # Zero Width Non-Joiner (ZWNJ) - strip unless Tamil context
    "\u200D",  # Zero Width Joiner (ZWJ)
    "\uFEFF",  # Byte Order Mark
    "\u00AD",  # Soft Hyphen
]

# Tamil Unicode block range
TAMIL_START = 0x0B80
TAMIL_END   = 0x0BFF

def _is_tamil_char(ch: str) -> bool:
    return TAMIL_START <= ord(ch) <= TAMIL_END

def _has_tamil(text: str) -> bool:
    return any(_is_tamil_char(c) for c in text)


def sanitize(text: str, source: str = "unknown") -> str:
    """
    Main entry point. Call this before passing text to any TTS engine.

    Args:
        text:   Raw input text
        source: Label for logging (e.g. 'standard_job', 'cms_webhook',
                'pdf_extract', 'conversation_segment')

    Returns:
        Cleaned, NFC-normalized text string.
    """
    if not text or not isinstance(text, str):
        return ""

    original_len = len(text)

    # Step 1: NFC normalization
    # Ensures Tamil characters are in composed form (standard for web/TTS)
    text = unicodedata.normalize("NFC", text)

    # Step 2: Strip zero-width junk characters
    # ZWNJ (\u200C) is stripped globally — Tamil text does not require it
    # for standard TTS rendering with Edge-TTS or ElevenLabs
    for zw in ZW_CHARS:
        text = text.replace(zw, "")

    # Step 3: Normalize smart quotes and typographic punctuation
    text = text.replace("\u2018", "'")   # left single quote
    text = text.replace("\u2019", "'")   # right single quote / apostrophe
    text = text.replace("\u201C", '"')   # left double quote
    text = text.replace("\u201D", '"')   # right double quote
    text = text.replace("\u2014", " - ") # em dash
    text = text.replace("\u2013", " - ") # en dash
    text = text.replace("\u2026", "...")  # ellipsis character

    # Step 4: Normalize line breaks
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Step 5: Collapse repeated whitespace (preserve single newlines)
    # Replace 3+ newlines with double newline (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces/tabs to single space (within a line)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Step 6: Normalize repeated punctuation
    # "!!!" -> "!"  "???" -> "?"  "..." preserved (ellipsis)
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\?{2,}", "?", text)
    # Collapse repeated commas or semicolons
    text = re.sub(r",{2,}", ",", text)
    text = re.sub(r";{2,}", ";", text)

    # Step 7: Strip leading/trailing whitespace per line
    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)

    # Step 8: Final strip
    text = text.strip()

    sanitized_len = len(text)

    # Log length delta only (never log content — privacy)
    logger.debug(
        "sanitizer source=%s original_len=%d sanitized_len=%d delta=%d",
        source,
        original_len,
        sanitized_len,
        original_len - sanitized_len,
    )

    return text


def sanitize_chunks(chunks: list[str], source: str = "unknown") -> list[str]:
    """Sanitize a list of text chunks (used for chunked TTS jobs)."""
    return [sanitize(chunk, source=source) for chunk in chunks]
