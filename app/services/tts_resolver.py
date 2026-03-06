"""
TTS Provider Resolver
Tamil TTS Studio — VoxTN

Decides which engine handles a given job:
  - ElevenLabs: ONLY when voice_model_id is set AND model is active AND consent valid
  - Edge-TTS:   everything else (default, presets, watermark, fallback)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Edge-TTS voice matrix — dialect + gender
VOICE_MATRIX = {
    "ta-IN": {"male": "ta-IN-ValluvarNeural",  "female": "ta-IN-PallaviNeural"},
    "ta-MY": {"male": "ta-MY-SuryaNeural",     "female": "ta-MY-KaniNeural"},
    "ta-LK": {"male": "ta-LK-KumarNeural",     "female": "ta-LK-SaranyaNeural"},
    "ta-SG": {"male": "ta-SG-AnbuNeural",      "female": "ta-SG-VenbaNeural"},
}
DEFAULT_DIALECT = "ta-IN"
DEFAULT_GENDER  = "female"


def get_edge_tts_voice(dialect: Optional[str], gender: Optional[str]) -> str:
    """Return the Edge-TTS voice name for a given dialect + gender."""
    d = dialect if dialect in VOICE_MATRIX else DEFAULT_DIALECT
    g = gender  if gender  in ("male", "female") else DEFAULT_GENDER
    return VOICE_MATRIX[d][g]


async def resolve_provider(
    voice_model_id: Optional[str],
    dialect:        Optional[str],
    gender:         Optional[str],
    db,
) -> dict:
    """
    Resolve which TTS provider and voice to use for a job.

    Returns:
        {
            "provider":         "elevenlabs" | "edge_tts",
            "voice_id":         str,          # ElevenLabs voice_id OR Edge-TTS voice name
            "fallback_reason":  str | None,   # set if ElevenLabs was skipped
        }
    """
    # No voice model requested — use Edge-TTS directly
    if not voice_model_id:
        return {
            "provider":        "edge_tts",
            "voice_id":        get_edge_tts_voice(dialect, gender),
            "fallback_reason": None,
        }

    # Load voice model from DB
    from sqlalchemy import text
    row = db.execute(
        text("SELECT id, elevenlabs_voice_id, status, tamil_supported "
             "FROM voice_models WHERE id = :id"),
        {"id": voice_model_id},
    ).fetchone()

    if not row:
        logger.warning("resolve_provider: voice_model_id=%s not found", voice_model_id)
        return {
            "provider":        "edge_tts",
            "voice_id":        get_edge_tts_voice(dialect, gender),
            "fallback_reason": "voice_model_not_found",
        }

    if row.status != "active":
        logger.warning("resolve_provider: voice_model_id=%s status=%s", voice_model_id, row.status)
        return {
            "provider":        "edge_tts",
            "voice_id":        get_edge_tts_voice(dialect, gender),
            "fallback_reason": f"voice_model_status_{row.status}",
        }

    if not row.elevenlabs_voice_id:
        return {
            "provider":        "edge_tts",
            "voice_id":        get_edge_tts_voice(dialect, gender),
            "fallback_reason": "elevenlabs_voice_id_not_set",
        }

    # Check Tamil support — fallback if unsupported
    if dialect and dialect != "en" and not row.tamil_supported:
        logger.warning(
            "resolve_provider: voice_model_id=%s tamil_supported=False — fallback",
            voice_model_id,
        )
        return {
            "provider":        "edge_tts",
            "voice_id":        get_edge_tts_voice(dialect, gender),
            "fallback_reason": "elevenlabs_tamil_unsupported",
        }

    # All checks passed — use ElevenLabs
    return {
        "provider":        "elevenlabs",
        "voice_id":        row.elevenlabs_voice_id,
        "fallback_reason": None,
    }
