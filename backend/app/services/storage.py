import io
import logging
from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger("shakambari.storage")


class StorageService:
    def __init__(self):
        self.backend = (settings.storage_backend or "local").lower().strip()
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, filename: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """Stores a file and returns its identifier/path."""
        if self.backend in ("s3", "supabase") and settings.s3_bucket:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url,
                    aws_access_key_id=settings.s3_access_key_id,
                    aws_secret_access_key=settings.s3_secret_access_key,
                )
                s3.put_object(
                    Bucket=settings.s3_bucket,
                    Key=f"uploads/{filename}",
                    Body=data,
                    ContentType=content_type,
                )
                log.info("Saved %s to object storage (%s)", filename, self.backend)
                return filename
            except Exception as e:
                log.warning("Object storage upload failed, falling back to local disk: %s", e)

        # Fallback to local disk
        target = self.upload_dir / filename
        target.write_bytes(data)
        return filename

    def get_file(self, filename: str) -> Optional[bytes]:
        """Reads file bytes from storage."""
        if self.backend in ("s3", "supabase") and settings.s3_bucket:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url,
                    aws_access_key_id=settings.s3_access_key_id,
                    aws_secret_access_key=settings.s3_secret_access_key,
                )
                resp = s3.get_object(Bucket=settings.s3_bucket, Key=f"uploads/{filename}")
                return resp["Body"].read()
            except Exception as e:
                log.warning("Object storage read failed, attempting local fallback: %s", e)

        target = self.upload_dir / filename
        if target.exists():
            return target.read_bytes()
        return None

    def delete_file(self, filename: str) -> bool:
        """Deletes a file from storage."""
        deleted = False
        if self.backend in ("s3", "supabase") and settings.s3_bucket:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url,
                    aws_access_key_id=settings.s3_access_key_id,
                    aws_secret_access_key=settings.s3_secret_access_key,
                )
                s3.delete_object(Bucket=settings.s3_bucket, Key=f"uploads/{filename}")
                deleted = True
            except Exception as e:
                log.warning("Failed to delete from object storage: %s", e)

        target = self.upload_dir / filename
        if target.exists():
            try:
                target.unlink()
                deleted = True
            except Exception as e:
                log.warning("Failed to delete local file %s: %s", filename, e)

        return deleted


storage = StorageService()
