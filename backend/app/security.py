"""Small security primitives kept separate from replaceable pilot auth."""

import base64
import hashlib
import hmac
import os


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


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Create the portable scrypt verifier used by FastAPI and Next.js."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return f"scrypt$16384$8$1${encode(salt)}${encode(digest)}"


def verify_password(password: str, verifier: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = verifier.split("$")
        if algorithm != "scrypt":
            return False
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        expected = decode(digest_text)
        actual = hashlib.scrypt(
            password.encode(), salt=decode(salt_text), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
