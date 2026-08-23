"""Tenant-scoped S3 object storage."""

import hashlib
from datetime import datetime, timezone

import boto3


class S3MediaStore:
    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    def put_inbound_media(
        self, *, company_id: str, media_id: str, content: bytes, mime_type: str, received_at: datetime | None = None
    ) -> tuple[str, str]:
        received_at = received_at or datetime.now(timezone.utc)
        digest = hashlib.sha256(content).hexdigest()
        key = f"companies/{company_id}/inbound/{received_at:%Y/%m/%d}/{media_id}"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=mime_type,
            ServerSideEncryption="AES256",
            Metadata={"sha256": digest},
        )
        return key, digest
