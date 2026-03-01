import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean,
    DateTime, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ChunkStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class VoiceMode(str, enum.Enum):
    MALE_NEWSREADER = "male_newsreader"
    MALE_CONVERSATIONAL = "male_conversational"
    FEMALE_NEWSREADER = "female_newsreader"
    FEMALE_CONVERSATIONAL = "female_conversational"


# Voice mode → Google TTS voice name mapping
# ta-IN voices available as of 2024:
#   ta-IN-Standard-A  (Female)
#   ta-IN-Standard-B  (Male)
#   ta-IN-Standard-C  (Female) — slightly higher pitch, more expressive
#   ta-IN-Standard-D  (Male)   — slightly deeper
#   ta-IN-Wavenet-A   (Female) — best quality female
#   ta-IN-Wavenet-B   (Male)   — best quality male
#   ta-IN-Wavenet-C   (Female)
#   ta-IN-Wavenet-D   (Male)
#
# "Newsreader" style: Google TTS does not have a dedicated newsreader voice
# for ta-IN. We approximate with Wavenet voices (higher quality, more neutral).
# "Conversational" style: Standard voices tend to sound slightly less formal.
# This is a best-effort approximation — document this to users.

VOICE_MAP = {
    VoiceMode.MALE_NEWSREADER:       "ta-IN-Wavenet-D",
    VoiceMode.MALE_CONVERSATIONAL:   "ta-IN-Standard-B",
    VoiceMode.FEMALE_NEWSREADER:     "ta-IN-Wavenet-A",
    VoiceMode.FEMALE_CONVERSATIONAL: "ta-IN-Standard-A",
}


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    jobs = relationship("Job", back_populates="user")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    original_text = Column(Text, nullable=False)
    voice_mode = Column(SAEnum(VoiceMode), nullable=False)
    speed = Column(Float, default=1.0)
    status = Column(SAEnum(JobStatus), default=JobStatus.QUEUED, index=True)
    error_message = Column(Text, nullable=True)
    output_path = Column(String(512), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="jobs")
    chunks = relationship("JobChunk", back_populates="job", order_by="JobChunk.chunk_index")
    share_tokens = relationship("ShareToken", back_populates="job")


class JobChunk(Base):
    __tablename__ = "job_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    status = Column(SAEnum(ChunkStatus), default=ChunkStatus.PENDING)
    output_path = Column(String(512), nullable=True)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="chunks")


class ShareToken(Base):
    __tablename__ = "share_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="share_tokens")
