"""
Tamil text chunker.

Strategy:
1. Normalize Unicode (NFC).
2. Split by paragraph (double newline).
3. If paragraph > CHUNK_TARGET_MAX, split by sentence boundary.
4. Merge small chunks up to CHUNK_TARGET_MIN.
5. Protect: decimal numbers, emails, URLs, parenthesized spans.
"""

import re
import unicodedata
from typing import List
from app.config import settings

# Sentence boundary pattern for Tamil + English
# Tamil sentence-ending characters: । (U+0964), ॥ (U+0965), . (period followed by space/end)
SENTENCE_SPLIT_RE = re.compile(
    r'(?<=[।॥])\s+'               # After Tamil danda
    r'|(?<=\.)\s+(?=[^\d])'        # After period not followed by digit (protect decimals)
    r'|(?<=[?!])\s+'               # After ? or !
)

# Patterns to protect from splitting
PROTECT_DECIMAL = re.compile(r'\d+\.\d+')
PROTECT_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}')
PROTECT_URL = re.compile(r'https?://\S+|www\.\S+')


def normalize_text(text: str) -> str:
    """Normalize unicode and clean whitespace."""
    text = unicodedata.normalize("NFC", text)
    # Normalize newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ newlines to double
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip trailing whitespace per line
    lines = [l.rstrip() for l in text.split('\n')]
    return '\n'.join(lines).strip()


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences, protecting special patterns."""
    # Temporarily replace protected patterns
    placeholders = {}
    counter = [0]

    def protect(m):
        key = f"\x00PROT{counter[0]}\x00"
        placeholders[key] = m.group(0)
        counter[0] += 1
        return key

    protected = PROTECT_DECIMAL.sub(protect, text)
    protected = PROTECT_EMAIL.sub(protect, protected)
    protected = PROTECT_URL.sub(protect, protected)

    parts = SENTENCE_SPLIT_RE.split(protected)

    # Restore
    restored = []
    for part in parts:
        for key, val in placeholders.items():
            part = part.replace(key, val)
        part = part.strip()
        if part:
            restored.append(part)

    return restored if restored else [text.strip()]


def make_chunks(text: str) -> List[str]:
    """
    Returns list of text chunks, each within configured size bounds.
    """
    min_size = settings.CHUNK_TARGET_MIN
    max_size = settings.CHUNK_TARGET_MAX

    text = normalize_text(text)
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

    raw_chunks: List[str] = []

    for para in paragraphs:
        if len(para) <= max_size:
            raw_chunks.append(para)
        else:
            # Split paragraph by sentences
            sentences = split_into_sentences(para)
            current = ""
            for sent in sentences:
                candidate = (current + " " + sent).strip() if current else sent
                if len(candidate) <= max_size:
                    current = candidate
                else:
                    if current:
                        raw_chunks.append(current)
                    # If single sentence too long, hard-split at max_size
                    if len(sent) > max_size:
                        for i in range(0, len(sent), max_size):
                            raw_chunks.append(sent[i:i + max_size])
                        current = ""
                    else:
                        current = sent
            if current:
                raw_chunks.append(current)

    # Merge small chunks
    merged: List[str] = []
    buffer = ""
    for chunk in raw_chunks:
        candidate = (buffer + "\n\n" + chunk).strip() if buffer else chunk
        if len(candidate) <= max_size:
            buffer = candidate
        else:
            if buffer:
                merged.append(buffer)
            buffer = chunk
    if buffer:
        merged.append(buffer)

    return [c for c in merged if c.strip()]
