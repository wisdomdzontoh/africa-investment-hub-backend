"""Cloudflare R2 storage service (PRD §14, §16).

All documents live in a private R2 bucket. Clients never get a public URL —
instead we mint short-lived presigned URLs (15-minute default) per request and
log every access for the audit trail. R2 is S3-compatible, accessed via boto3.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# MIME types we accept for uploads (PRD §7 — file validation).
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50MB (PRD §7)


@lru_cache
def _client() -> Any:
    """Process-wide boto3 S3 client pointed at the R2 endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def build_key(*, prefix: str, owner_id: uuid.UUID, filename: str) -> str:
    """Namespaced, collision-resistant object key."""
    safe = filename.replace("/", "_").replace("\\", "_")
    return f"{prefix}/{owner_id}/{uuid.uuid4().hex}_{safe}"


def validate_upload(content_type: str, size: int | None = None) -> None:
    from app.core.exceptions import ValidationError

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported content type: {content_type}",
            details={"allowed": sorted(ALLOWED_CONTENT_TYPES)},
        )
    if size is not None and size > MAX_FILE_BYTES:
        raise ValidationError("File exceeds the 50MB limit.", details={"max_bytes": MAX_FILE_BYTES})


def presign_put(key: str, content_type: str) -> str:
    """Presigned URL for a direct browser PUT upload."""
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.R2_PRESIGN_EXPIRY_SECONDS,
    )


def presign_get(key: str, *, accessor_id: uuid.UUID | None = None) -> str:
    """Presigned URL for download. Access is logged for the audit trail."""
    logger.info(
        "r2_access",
        extra={"r2_key": key, "accessor_id": str(accessor_id) if accessor_id else None},
    )
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key},
        ExpiresIn=settings.R2_PRESIGN_EXPIRY_SECONDS,
    )


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=settings.R2_BUCKET, Key=key)
