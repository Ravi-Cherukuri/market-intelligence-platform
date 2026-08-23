"""Official Meta WhatsApp Cloud API adapter.

Media is streamed into a bounded buffer and accepted only when both the
declared MIME type and file signature match the pilot's voice/photo scope.
"""

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass

import httpx


class WhatsAppConfigurationError(RuntimeError):
    pass


class WhatsAppMediaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadedMedia:
    content: bytes
    mime_type: str
    provider_sha256: str | None


_SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/aac",
    "audio/amr",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/3gpp",
}


def _normalized_mime_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def validate_supported_media(content: bytes, claimed_mime_type: str | None) -> str:
    """Return the normalized MIME type after signature verification."""
    mime_type = _normalized_mime_type(claimed_mime_type)
    if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES | _SUPPORTED_AUDIO_MIME_TYPES:
        raise WhatsAppMediaValidationError("WhatsApp media MIME type is not supported")

    is_jpeg = content.startswith(b"\xff\xd8\xff")
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    is_ogg = content.startswith(b"OggS")
    is_iso_media = len(content) >= 12 and content[4:8] == b"ftyp"
    is_amr = content.startswith((b"#!AMR\n", b"#!AMR-WB\n"))
    is_id3 = content.startswith(b"ID3")
    is_adts_or_mpeg = len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0

    matches = {
        "image/jpeg": is_jpeg,
        "image/png": is_png,
        "image/webp": is_webp,
        "audio/ogg": is_ogg,
        "audio/mp4": is_iso_media,
        "audio/3gpp": is_iso_media,
        "audio/amr": is_amr,
        "audio/mpeg": is_id3 or is_adts_or_mpeg,
        "audio/aac": is_adts_or_mpeg,
    }
    if not matches[mime_type]:
        raise WhatsAppMediaValidationError("WhatsApp media signature does not match its MIME type")
    return mime_type


def validate_provider_sha256(content: bytes, provider_sha256: str | None) -> None:
    """Verify Meta's digest when supplied, accepting its documented encodings."""
    if not provider_sha256:
        return
    expected = provider_sha256.strip()
    digest = hashlib.sha256(content).digest()
    matches_hex = len(expected) == 64 and hmac.compare_digest(expected.lower(), digest.hex())
    try:
        decoded = base64.b64decode(expected, validate=True)
        matches_base64 = hmac.compare_digest(decoded, digest)
    except (binascii.Error, ValueError):
        matches_base64 = False
    if not (matches_hex or matches_base64):
        raise WhatsAppMediaValidationError("WhatsApp media checksum validation failed")


class WhatsAppClient:
    def __init__(self, *, base_url: str, api_version: str, access_token: str, timeout_seconds: float = 30):
        if not api_version or not access_token:
            raise WhatsAppConfigurationError("WhatsApp API version and access token are required")
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.access_token = access_token
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def send_text(self, phone_number_id: str, recipient_wa_id: str, body: str) -> str:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/{self.api_version}/{phone_number_id}/messages",
                headers=self.headers,
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_wa_id,
                    "type": "text",
                    "text": {"preview_url": False, "body": body},
                },
            )
            response.raise_for_status()
            data = response.json()
            return str(data["messages"][0]["id"])

    def download_media(self, media_id: str, max_bytes: int = 25_000_000) -> DownloadedMedia:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            metadata_response = client.get(
                f"{self.base_url}/{self.api_version}/{media_id}", headers=self.headers
            )
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            declared_size = metadata.get("file_size")
            if declared_size is not None and int(declared_size) > max_bytes:
                raise WhatsAppMediaValidationError("WhatsApp media exceeds configured size limit")
            content = bytearray()
            response_mime_type: str | None = None
            with client.stream("GET", metadata["url"], headers=self.headers) as response:
                response.raise_for_status()
                response_mime_type = response.headers.get("content-type")
                content_length = response.headers.get("content-length")
                if content_length is not None and int(content_length) > max_bytes:
                    raise WhatsAppMediaValidationError("WhatsApp media exceeds configured size limit")
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise WhatsAppMediaValidationError("WhatsApp media exceeds configured size limit")
            raw_content = bytes(content)
            mime_type = validate_supported_media(
                raw_content,
                str(metadata.get("mime_type") or response_mime_type or ""),
            )
            validate_provider_sha256(raw_content, metadata.get("sha256"))
            return DownloadedMedia(
                content=raw_content,
                mime_type=mime_type,
                provider_sha256=metadata.get("sha256"),
            )
