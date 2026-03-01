"""
Audio stitching using ffmpeg.

- Concatenates chunk MP3 files into one final MP3.
- Inserts silence between chunks (configurable ms).
- Optionally normalizes loudness (loudnorm filter).
"""

import os
import subprocess
import tempfile
import logging
from typing import List
from app.config import settings

logger = logging.getLogger(__name__)

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")


def generate_silence(output_path: str, duration_ms: int = 350):
    """Generate a silent MP3 file of given duration."""
    duration_s = duration_ms / 1000.0
    cmd = [
        FFMPEG_BIN, "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=22050:cl=mono",
        "-t", str(duration_s),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        output_path,
    ]
    _run(cmd, "generate silence")


def stitch_chunks(
    chunk_paths: List[str],
    output_path: str,
    silence_ms: int = None,
    normalize: bool = True,
) -> str:
    """
    Stitch chunk MP3s into one final MP3 with silence between.
    Returns output_path on success.
    """
    if silence_ms is None:
        silence_ms = settings.SILENCE_MS

    if not chunk_paths:
        raise ValueError("No chunk paths provided for stitching")

    with tempfile.TemporaryDirectory() as tmpdir:
        silence_path = os.path.join(tmpdir, "silence.mp3")
        generate_silence(silence_path, silence_ms)

        # Build ordered list with silence interleaved
        all_parts = []
        for i, path in enumerate(chunk_paths):
            all_parts.append(path)
            if i < len(chunk_paths) - 1:
                all_parts.append(silence_path)

        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for p in all_parts:
                f.write(f"file '{p}'\n")

        intermediate = os.path.join(tmpdir, "intermediate.mp3")

        # Step 1: Concatenate
        concat_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            intermediate,
        ]
        _run(concat_cmd, "concatenate chunks")

        # Step 2: Normalize loudness (EBU R128)
        if normalize:
            norm_cmd = [
                FFMPEG_BIN, "-y",
                "-i", intermediate,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-codec:a", "libmp3lame",
                "-q:a", "2",
                output_path,
            ]
            _run(norm_cmd, "loudness normalize")
        else:
            import shutil
            shutil.copy2(intermediate, output_path)

    logger.info("Stitched %d chunks → %s", len(chunk_paths), output_path)
    return output_path


def _run(cmd: List[str], label: str):
    logger.debug("ffmpeg [%s]: %s", label, " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg [{label}] failed (rc={result.returncode}):\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
