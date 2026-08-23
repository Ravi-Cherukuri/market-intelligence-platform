"""Employee identifier normalization."""

import re


class InvalidPhoneNumber(ValueError):
    pass


def normalize_indian_whatsapp_number(value: str) -> str:
    """Return a conservative E.164 number without a leading plus.

    Meta's ``wa_id`` is digit-only. Uploads may contain spaces, punctuation or a
    leading ``+``. Ten-digit Indian mobile numbers receive country code 91.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        if digits[0] not in "6789":
            raise InvalidPhoneNumber("Ten-digit Indian mobile numbers must start with 6, 7, 8, or 9")
        digits = f"91{digits}"
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise InvalidPhoneNumber("WhatsApp number must be a valid E.164 mobile number")
    return digits


def normalize_alias(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
