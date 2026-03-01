import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # App
    APP_NAME: str = "TamilTTS Studio"
    SECRET_KEY: str = os.environ["SECRET_KEY"]
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.environ["DATABASE_URL"]

    # Redis / Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # GCP
    GOOGLE_APPLICATION_CREDENTIALS: str = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

    # Storage
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "/var/lib/tamiltts/outputs")
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))  # 5MB

    # Auth / JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24h

    # Rate limiting
    RATE_LIMIT_JOBS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_JOBS_PER_HOUR", "10"))

    # Chunking
    CHUNK_TARGET_MIN: int = int(os.getenv("CHUNK_TARGET_MIN", "1200"))
    CHUNK_TARGET_MAX: int = int(os.getenv("CHUNK_TARGET_MAX", "1800"))

    # Silence between chunks (ms)
    SILENCE_MS: int = int(os.getenv("SILENCE_MS", "350"))

    # Keep per-chunk debug files
    KEEP_CHUNK_FILES: bool = os.getenv("KEEP_CHUNK_FILES", "false").lower() == "true"

settings = Settings()
