"""Official Meta WhatsApp Cloud API adapter."""

from dataclasses import dataclass

import httpx


class WhatsAppConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedMedia:
    content: bytes
    mime_type: str
    provider_sha256: str | None


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
            response = client.get(metadata["url"], headers=self.headers)
            response.raise_for_status()
            if len(response.content) > max_bytes:
                raise ValueError("WhatsApp media exceeds configured size limit")
            return DownloadedMedia(
                content=response.content,
                mime_type=str(metadata.get("mime_type") or response.headers.get("content-type") or "application/octet-stream"),
                provider_sha256=metadata.get("sha256"),
            )
