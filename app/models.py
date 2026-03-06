import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean,
    DateTime, ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
import enum
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    QUEUED     = "queued"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"


class ChunkStatus(str, enum.Enum):
    PENDING = "pending"
    DONE    = "done"
    FAILED  = "failed"


class VoiceMode(str, enum.Enum):
    # Legacy values — kept for backward compatibility with production
    MALE_NEWSREADER       = "male_newsreader"
    MALE_CONVERSATIONAL   = "male_conversational"
    FEMALE_NEWSREADER     = "female_newsreader"
    FEMALE_CONVERSATIONAL = "female_conversational"
    # Edge TTS voices — all 8 across 5 dialects
    TA_IN_PALLAVI  = "ta-IN-PallaviNeural"   # India Female
    TA_IN_VALLUVAR = "ta-IN-ValluvarNeural"  # India Male
    TA_MY_KANI     = "ta-MY-KaniNeural"      # Malaysia Female
    TA_MY_SURYA    = "ta-MY-SuryaNeural"     # Malaysia Male
    TA_LK_SARANYA  = "ta-LK-SaranyaNeural"   # Sri Lanka Female
    TA_LK_KUMAR    = "ta-LK-KumarNeural"     # Sri Lanka Male
    TA_SG_VENBA    = "ta-SG-VenbaNeural"     # Singapore Female
    TA_SG_ANBU     = "ta-SG-AnbuNeural"      # Singapore Male


# Dialect + gender → Edge TTS voice name
VOICE_MATRIX = {
    "ta-IN": {"male": "ta-IN-ValluvarNeural",  "female": "ta-IN-PallaviNeural"},
    "ta-MY": {"male": "ta-MY-SuryaNeural",     "female": "ta-MY-KaniNeural"},
    "ta-LK": {"male": "ta-LK-KumarNeural",     "female": "ta-LK-SaranyaNeural"},
    "ta-SG": {"male": "ta-SG-AnbuNeural",      "female": "ta-SG-VenbaNeural"},
}


class User(Base):
    __tablename__ = "users"

    id              = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    email           = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active       = Column(Boolean,     default=True)
    is_admin        = Column(Boolean,     default=False)
    is_suspended    = Column(Boolean,     default=False)
    suspended_at    = Column(DateTime(timezone=True), nullable=True)
    suspended_by    = Column(String(36),  nullable=True)
    suspend_reason  = Column(String(255), nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    ghl_contact_id     = Column(String(255), nullable=True)
    tenant_id          = Column(String(36),  nullable=True)
    created_at      = Column(DateTime(timezone=True), default=utcnow)

    jobs = relationship("Job", back_populates="user")


class Job(Base):
    __tablename__ = "jobs"

    id             = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id        = Column(String(36),  ForeignKey("users.id"), nullable=False)
    title          = Column(String(255), nullable=True)
    original_text  = Column(Text,        nullable=False)
    voice_mode     = Column(String(50),  nullable=False)
    speed          = Column(Float,       default=1.0)
    status         = Column(SAEnum(JobStatus, values_callable=lambda x: [e.value for e in x]),
                            default=JobStatus.QUEUED, index=True)
    error_message  = Column(Text,        nullable=True)
    output_path    = Column(String(512), nullable=True)
    r2_key         = Column(String(500), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    created_at     = Column(DateTime(timezone=True), default=utcnow)
    updated_at     = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # CMS integration columns (migration 002)
    article_id      = Column(String(255), nullable=True, index=True)
    submitted_by    = Column(String(255), nullable=True)
    callback_url    = Column(String(512), nullable=True)
    idempotency_key = Column(String(255), nullable=True, unique=True)
    routing_tags    = Column(JSON,        nullable=True, default=dict)
    output_filename = Column(String(255), nullable=True)
    preset_id       = Column(String(100), nullable=True, default="conversational")
    dialect         = Column(String(10),  nullable=True, default="ta-LK")

    user         = relationship("User", back_populates="jobs")
    chunks       = relationship("JobChunk",   back_populates="job",
                                order_by="JobChunk.chunk_index", cascade="all, delete-orphan")
    share_tokens = relationship("ShareToken", back_populates="job",
                                cascade="all, delete-orphan")


class JobChunk(Base):
    __tablename__ = "job_chunks"

    id            = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id        = Column(String(36),  ForeignKey("jobs.id"), nullable=False)
    chunk_index   = Column(Integer,     nullable=False)
    text          = Column(Text,        nullable=False)
    status        = Column(SAEnum(ChunkStatus, values_callable=lambda x: [e.value for e in x]),
                           default=ChunkStatus.PENDING)
    output_path   = Column(String(512), nullable=True)
    error_message = Column(Text,        nullable=True)
    attempts      = Column(Integer,     default=0)
    created_at    = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="chunks")


class ShareToken(Base):
    __tablename__ = "share_tokens"

    id         = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id     = Column(String(36),  ForeignKey("jobs.id"), nullable=False)
    token      = Column(String(64),  unique=True, nullable=False, index=True)
    is_active  = Column(Boolean,     default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="share_tokens")
