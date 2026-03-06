import asyncio
import time
import logging
import tempfile
import os
import edge_tts
from app.models import VoiceMode

logger = logging.getLogger(__name__)

# ── Legacy voice map (kept for backward compatibility with old jobs) ──────────
VOICE_MAP = {
    VoiceMode.MALE_NEWSREADER:       "ta-LK-KumarNeural",
    VoiceMode.MALE_CONVERSATIONAL:   "ta-LK-KumarNeural",
    VoiceMode.FEMALE_NEWSREADER:     "ta-LK-SaranyaNeural",
    VoiceMode.FEMALE_CONVERSATIONAL: "ta-LK-SaranyaNeural",
}

# ── Dialect + gender matrix ───────────────────────────────────────────────────
VOICE_MATRIX = {
    "ta-IN": {"male": "ta-IN-ValluvarNeural",  "female": "ta-IN-PallaviNeural"},
    "ta-MY": {"male": "ta-MY-SuryaNeural",     "female": "ta-MY-KaniNeural"},
    "ta-LK": {"male": "ta-LK-KumarNeural",     "female": "ta-LK-SaranyaNeural"},
    "ta-SG": {"male": "ta-SG-AnbuNeural",      "female": "ta-SG-VenbaNeural"},
}
DEFAULT_DIALECT = "ta-LK"
DEFAULT_GENDER  = "female"


def get_voice_name(dialect: str, gender: str) -> str:
    d = dialect if dialect in VOICE_MATRIX else DEFAULT_DIALECT
    g = gender  if gender  in ("male", "female") else DEFAULT_GENDER
    return VOICE_MATRIX[d][g]


def build_rate_str(speed: float, rate_percent: int = 0) -> str:
    """
    Combine speed slider (0.75–1.5) with preset rate_percent (-30 to +30).
    speed=1.0 + rate_percent=0  → "+0%"
    speed=1.1 + rate_percent=10 → "+20%"
    """
    speed_contribution = round((speed - 1.0) * 100)
    total = speed_contribution + rate_percent
    total = max(-50, min(50, total))
    return f"+{total}%" if total >= 0 else f"{total}%"


def build_pitch_str(pitch_percent: int = 0) -> str:
    """
    Convert pitch_percent (-30 to +30) to Edge-TTS Hz offset string.
    Edge-TTS pitch is in Hz, roughly 1% ≈ 2Hz for typical Tamil voices.
    """
    hz = round(pitch_percent * 2)
    hz = max(-100, min(100, hz))
    return f"+{hz}Hz" if hz >= 0 else f"{hz}Hz"


def build_volume_str(volume_percent: int = 0) -> str:
    volume_percent = max(-50, min(50, volume_percent))
    return f"+{volume_percent}%" if volume_percent >= 0 else f"{volume_percent}%"


async def _synthesize_async(
    text: str, voice: str, rate: str, pitch: str, volume: str, output_path: str
):
    communicate = edge_tts.Communicate(
        text=text, voice=voice, rate=rate, pitch=pitch, volume=volume
    )
    await communicate.save(output_path)


def synthesize_chunk(
    text:          str,
    voice_mode:    "VoiceMode | str | None" = None,
    speed:         float = 1.0,
    max_retries:   int = 2,
    # New preset-based params (take priority over voice_mode if provided)
    voice_name:    str | None = None,
    rate_str:      str | None = None,
    pitch_str:     str | None = None,
    volume_str:    str | None = None,
) -> bytes:
    """
    Synthesize a text chunk via Edge-TTS.

    Can be called two ways:
    1. Legacy: synthesize_chunk(text, voice_mode=vm, speed=1.0)
    2. Preset: synthesize_chunk(text, voice_name="ta-LK-KumarNeural",
                                rate_str="+5%", pitch_str="+4Hz", volume_str="+0%")
    """
    # ── Resolve voice name ────────────────────────────────────────────────────
    if not voice_name:
        if voice_mode is not None:
            # Legacy path — look up from VOICE_MAP
            try:
                vm = VoiceMode(voice_mode) if isinstance(voice_mode, str) else voice_mode
                voice_name = VOICE_MAP.get(vm, "ta-LK-SaranyaNeural")
            except ValueError:
                # voice_mode is a raw Edge-TTS voice name (e.g. "ta-IN-PallaviNeural")
                voice_name = voice_mode if voice_mode else "ta-LK-SaranyaNeural"
        else:
            voice_name = "ta-LK-SaranyaNeural"

    # ── Resolve rate/pitch/volume ─────────────────────────────────────────────
    if not rate_str:
        is_newsreader = voice_mode in (
            VoiceMode.MALE_NEWSREADER, VoiceMode.FEMALE_NEWSREADER
        ) if voice_mode else False
        base_rate = -5 if is_newsreader else 0
        rate_str = build_rate_str(speed, base_rate)

    if not pitch_str:
        pitch_str = "+0Hz"

    if not volume_str:
        volume_str = "+0%"

    # ── Synthesize with retries ───────────────────────────────────────────────
    last_exc = None
    for attempt in range(1, max_retries + 1):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            asyncio.run(_synthesize_async(
                text, voice_name, rate_str, pitch_str, volume_str, tmp_path
            ))
            with open(tmp_path, "rb") as f:
                audio = f.read()
            if not audio or len(audio) < 100:
                raise ValueError(f"Empty audio response ({len(audio)} bytes)")
            logger.info(
                "edge-tts synthesized %d bytes voice=%s rate=%s pitch=%s vol=%s",
                len(audio), voice_name, rate_str, pitch_str, volume_str,
            )
            return audio
        except Exception as e:
            last_exc = e
            logger.warning(
                "edge-tts attempt %d/%d failed: %s", attempt, max_retries, str(e)
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    raise RuntimeError(
        f"TTS synthesis failed after {max_retries} attempts: {last_exc}"
    )


# ── Coqui provider routing ────────────────────────────────────────────────────
import urllib.request
import json as _json
import base64 as _base64


def _coqui_service_healthy(url: str) -> bool:
    """
    Health-check the Coqui inference service.
    2-second timeout. Returns False on any error — falls through to ElevenLabs.
    """
    try:
        req = urllib.request.Request(
            f"{url}/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_tts_provider(voice_model_id: str | None, coqui_inference_url: str) -> str:
    """
    Determine which TTS provider to use for a job.

    Priority chain (Phase 9 — CPU dev mode):
      1. coqui   — if voice_model_id set AND coqui service healthy
      2. edge_tts — fallback (ElevenLabs path handled separately in tasks.py)

    Returns: "coqui" | "edge_tts"
    """
    if voice_model_id and _coqui_service_healthy(coqui_inference_url):
        logger.info(f"resolve_tts_provider → coqui (voice_model_id={voice_model_id})")
        return "coqui"
    if voice_model_id:
        logger.warning(
            "resolve_tts_provider — coqui service unreachable, falling back to edge_tts"
        )
    return "edge_tts"


def synthesize_chunk_coqui(
    text: str,
    voice_model_path: str,
    language: str = "ta",
    pitch: int = 0,
    rate: float = 1.0,
    volume: float = 1.0,
    coqui_inference_url: str = "http://127.0.0.1:8002",
    internal_secret: str = "",
) -> bytes:
    """
    Call the tamiltts-coqui-service /infer endpoint.
    Returns raw MP3 bytes.
    Raises RuntimeError on failure — caller falls back to edge_tts.
    """
    payload = _json.dumps({
        "voice_model_path": voice_model_path,
        "text": text,
        "language": language,
        "params": {
            "pitch": pitch,
            "rate": rate,
            "volume": volume,
        },
    }).encode()

    req = urllib.request.Request(
        f"{coqui_inference_url}/infer",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Secret": internal_secret,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = _json.loads(resp.read())
            mp3_bytes = _base64.b64decode(body["audio_b64"])
            logger.info(
                f"synthesize_chunk_coqui OK — duration_ms={body.get('duration_ms')} "
                f"engine={body.get('engine')}"
            )
            return mp3_bytes
    except Exception as e:
        raise RuntimeError(f"Coqui inference failed: {e}") from e
