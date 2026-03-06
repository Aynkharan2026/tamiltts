from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app.config import settings

logger = logging.getLogger(__name__)

class R2StorageService:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        self.bucket      = settings.R2_BUCKET_NAME
        self.cdn_domain  = settings.R2_PUBLIC_DOMAIN
        self.expiry_days = int(getattr(settings, "R2_SIGNED_URL_EXPIRY_DAYS", 7))

    def upload_mp3(self, local_path: str, job_id: str, filename: str, tenant_id: str = "cms") -> str:
        r2_key = f"{tenant_id}/{job_id}/{filename}"
        self._client.upload_file(
            Filename=local_path, Bucket=self.bucket, Key=r2_key,
            ExtraArgs={"ContentType": "audio/mpeg", "CacheControl": "public, max-age=604800",
                       "Metadata": {"job-id": job_id, "tenant-id": tenant_id}},
        )
        logger.info(f"R2 upload complete: {r2_key}")
        return r2_key

    def generate_signed_url(self, r2_key: str, expiry_days: Optional[int] = None) -> dict:
        days    = expiry_days or self.expiry_days
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": r2_key},
            ExpiresIn=days * 86400,
        )
        if self.cdn_domain:
            r2_host = f"{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            url = url.replace(r2_host, self.cdn_domain)
        return {"url": url, "expires_at": expires_at.isoformat(), "r2_key": r2_key}

    def delete_object(self, r2_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=r2_key)
            logger.info(f"R2 object deleted: {r2_key}")
        except ClientError as e:
            logger.error(f"R2 delete error for {r2_key}: {e}")
            raise

    def get_file_size(self, r2_key: str) -> Optional[int]:
        try:
            resp = self._client.head_object(Bucket=self.bucket, Key=r2_key)
            return resp.get("ContentLength")
        except ClientError:
            return None
