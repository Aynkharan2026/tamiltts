import re
import unicodedata
from typing import List
from app.config import settings

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def make_chunks(text: str) -> List[str]:
    max_size = settings.CHUNK_TARGET_MAX
    text = normalize_text(text)

    # Priority 1: split by paragraph
    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

    raw = []
    for para in paragraphs:
        if len(para) <= max_size:
            raw.append(para)
        else:
            # Priority 2: split by full stop (. or Tamil danda ।)
            # Find all full stop positions
            segments = re.split(r'(?<=[.।])\s+', para)
            current = ""
            for seg in segments:
                candidate = (current + " " + seg).strip() if current else seg
                if len(candidate) <= max_size:
                    current = candidate
                else:
                    if current.strip():
                        raw.append(current.strip())
                    # seg itself too long - Priority 3: split by ? or !
                    if len(seg) > max_size:
                        subsegments = re.split(r'(?<=[?!])\s+', seg)
                        subcurrent = ""
                        for sub in subsegments:
                            subcandidate = (subcurrent + " " + sub).strip() if subcurrent else sub
                            if len(subcandidate) <= max_size:
                                subcurrent = subcandidate
                            else:
                                if subcurrent.strip():
                                    raw.append(subcurrent.strip())
                                # Last resort: split at whitespace only
                                if len(sub) > max_size:
                                    words = sub.split()
                                    wordcurrent = ""
                                    for word in words:
                                        wordcandidate = (wordcurrent + " " + word).strip() if wordcurrent else word
                                        if len(wordcandidate) <= max_size:
                                            wordcurrent = wordcandidate
                                        else:
                                            if wordcurrent:
                                                raw.append(wordcurrent)
                                            wordcurrent = word
                                    if wordcurrent:
                                        raw.append(wordcurrent)
                                else:
                                    subcurrent = sub
                        if subcurrent.strip():
                            raw.append(subcurrent.strip())
                    else:
                        current = seg
            if current.strip():
                raw.append(current.strip())

    return [c for c in raw if c.strip()]
