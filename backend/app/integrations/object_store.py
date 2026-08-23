"""Tenant-scoped S3 object storage."""

import hashlib
from datetime import datetime, timezone

import boto3


class S3MediaStore:
    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        # The host atomically rotates the worker's one-hour, S3-only credential
        # file. A fresh explicit Session makes each media batch reread it rather
        # than reusing boto3's process-global cached credentials.
        self.client = boto3.Session(region_name=region).client("s3")

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
