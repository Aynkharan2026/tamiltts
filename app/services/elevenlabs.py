"""
ElevenLabs Service Layer
Tamil TTS Studio — VoxTN

Used ONLY for:
  - Premium voice cloning (upload sample, provision voice model)
  - Premium multi-speaker jobs where voice_model_id is set

All standard jobs, presets, and watermark audio use Edge-TTS.
API key loaded from environment variable ELEVENLABS_API_KEY.
"""
import os
import logging
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_TIMEOUT  = 60  # seconds


def _get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY not set. Add it to .env before using voice cloning."
        )
    return key


def _headers() -> dict:
    return {
        "xi-api-key": _get_api_key(),
        "Accept":     "application/json",
    }


async def upload_voice(
    display_name: str,
    sample_path: str,
    description: str = "Tamil TTS Studio voice model",
) -> dict:
    """
    Upload a normalized voice sample to ElevenLabs and provision a voice model.

    Returns:
        {"voice_id": str, "name": str}

    Raises:
        httpx.HTTPStatusError on API failure (caller must handle + fallback)
    """
    sample_file = Path(sample_path)
    if not sample_file.exists():
        raise FileNotFoundError(f"Voice sample not found: {sample_path}")

    url = f"{ELEVENLABS_API_BASE}/voices/add"

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as client:
        with open(sample_path, "rb") as f:
            response = await client.post(
                url,
                headers=_headers(),
                data={
                    "name":        display_name,
                    "description": description,
                    "labels":      '{"language": "ta"}',
                },
                files={"files": (sample_file.name, f, "audio/wav")},
            )
        response.raise_for_status()
        data = response.json()
        logger.info("ElevenLabs voice provisioned: voice_id=%s", data.get("voice_id"))
        return {"voice_id": data["voice_id"], "name": display_name}


async def generate_audio(
    voice_id: str,
    text: str,
    output_path: str,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    model_id: str = "eleven_multilingual_v2",
) -> dict:
    """
    Generate audio using a cloned ElevenLabs voice.

    Returns:
        {"output_path": str, "char_count": int, "provider": "elevenlabs"}

    On failure: raises exception — caller must catch and fallback to Edge-TTS.
    """
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"

    payload = {
        "text":           text,
        "model_id":       model_id,
        "voice_settings": {
            "stability":        stability,
            "similarity_boost": similarity_boost,
        },
    }

    headers = {**_headers(), "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    char_count = len(text)
    logger.info(
        "ElevenLabs audio generated: voice_id=%s chars=%d output=%s",
        voice_id, char_count, output_path,
    )
    return {
        "output_path": output_path,
        "char_count":  char_count,
        "provider":    "elevenlabs",
    }


async def delete_voice(voice_id: str) -> bool:
    """
    Delete a voice model from ElevenLabs.
    Called when user deletes their voice model.

    Returns True on success, False on failure (log and continue).
    """
    url = f"{ELEVENLABS_API_BASE}/voices/{voice_id}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(url, headers=_headers())
            response.raise_for_status()
        logger.info("ElevenLabs voice deleted: voice_id=%s", voice_id)
        return True
    except Exception as e:
        logger.error("ElevenLabs voice delete failed: voice_id=%s error=%s", voice_id, e)
        return False


async def test_tamil_support(voice_id: str, tmp_path: str) -> bool:
    """
    Test whether a voice model produces acceptable Tamil output.
    Generates a 10-character Tamil test string.
    Returns True if generation succeeds without error.
    """
    test_text = "வணக்கம் நண்பா"
    try:
        await generate_audio(voice_id, test_text, tmp_path)
        return True
    except Exception as e:
        logger.warning(
            "Tamil support test failed for voice_id=%s: %s — will use Edge-TTS fallback",
            voice_id, e,
        )
        return False
