import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    APP_NAME: str = "Tamil TTS Studio"
    SECRET_KEY: str = os.environ["SECRET_KEY"]
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    DATABASE_URL: str = os.environ["DATABASE_URL"]
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/2")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/2")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/3")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "/var/lib/tamiltts-saas/outputs")
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    RATE_LIMIT_JOBS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_JOBS_PER_HOUR", "10"))
    CHUNK_TARGET_MIN: int = int(os.getenv("CHUNK_TARGET_MIN", "1200"))
    CHUNK_TARGET_MAX: int = int(os.getenv("CHUNK_TARGET_MAX", "1800"))
    SILENCE_MS: int = int(os.getenv("SILENCE_MS", "350"))
    KEEP_CHUNK_FILES: bool = os.getenv("KEEP_CHUNK_FILES", "false").lower() == "true"

    # CMS Integration
    CMS_HMAC_SECRET: str = os.getenv("CMS_HMAC_SECRET", "")
    CMS_WEBHOOK_TIMEOUT_SEC: int = int(os.getenv("CMS_WEBHOOK_TIMEOUT_SEC", "300"))
    RATE_LIMIT_CMS_JOBS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_CMS_JOBS_PER_HOUR", "100"))

    # Cloudflare R2
    R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "tts-audio-saas")
    R2_VOICE_SAMPLES_BUCKET: str = os.getenv("R2_VOICE_SAMPLES_BUCKET", "tts-voice-samples")
    R2_PUBLIC_DOMAIN: str = os.getenv("R2_PUBLIC_DOMAIN", "")
    R2_SIGNED_URL_EXPIRY_DAYS: int = int(os.getenv("R2_SIGNED_URL_EXPIRY_DAYS", "7"))

    # Sanity
    SANITY_PROJECT_ID: str = os.getenv("SANITY_PROJECT_ID", "1s8ffj9x")
    SANITY_DATASET: str = os.getenv("SANITY_DATASET", "production")
    SANITY_API_TOKEN: str = os.getenv("SANITY_API_TOKEN", "")
    SANITY_WEBHOOK_SECRET: str = os.getenv("SANITY_WEBHOOK_SECRET", "")

    # Webhook
    WEBHOOK_RETRY_COUNT: int = int(os.getenv("WEBHOOK_RETRY_COUNT", "3"))
    WEBHOOK_RETRY_BACKOFF: str = os.getenv("WEBHOOK_RETRY_BACKOFF", "5,15,45")

    # Channels
    # Coqui Inference Service
    COQUI_INFERENCE_URL: str = os.getenv("COQUI_INFERENCE_URL", "http://127.0.0.1:8002")
    INTERNAL_API_SECRET: str = os.getenv("INTERNAL_API_SECRET", "")

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    WHATSAPP_PROVIDER: str = os.getenv("WHATSAPP_PROVIDER", "meta")
    WHATSAPP_API_TOKEN: str = os.getenv("WHATSAPP_API_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_BROADCAST_NUMBER: str = os.getenv("WHATSAPP_BROADCAST_NUMBER", "")
    ZAPI_ENDPOINT: str = os.getenv("ZAPI_ENDPOINT", "")
    NEWSLETTER_PROVIDER: str = os.getenv("NEWSLETTER_PROVIDER", "")
    MAILCHIMP_API_KEY: str = os.getenv("MAILCHIMP_API_KEY", "")
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    NEWSLETTER_FROM_EMAIL: str = os.getenv("NEWSLETTER_FROM_EMAIL", "hello@voxtn.com")
    YOUTUBE_OAUTH_TOKEN: str = os.getenv("YOUTUBE_OAUTH_TOKEN", "")
    RSS_BASE_DOMAIN: str = os.getenv("RSS_BASE_DOMAIN", "tts.voxtn.com")

    CLERK_WEBHOOK_SECRET: str = os.getenv("CLERK_WEBHOOK_SECRET", "")
settings = Settings()
