"""Small security primitives kept separate from replaceable pilot auth."""

import hashlib
import hmac


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Validate Meta's ``X-Hub-Signature-256`` over the exact request bytes."""
    if not signature_header or not app_secret or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=")
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def constant_time_credentials_match(
    supplied_user: str, supplied_password: str, expected_user: str, expected_password: str
) -> bool:
    return hmac.compare_digest(supplied_user, expected_user) and hmac.compare_digest(
        supplied_password, expected_password
    )
