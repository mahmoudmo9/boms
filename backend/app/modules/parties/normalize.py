"""Normalization of contact-method values for duplicate detection (``core.contact_method.value_norm``).

Phone and WhatsApp numbers become international digits without "+": Persian/Arabic digits are
converted, "+98", "0098" and a national leading "0" all give the same result, so
0912 345 6789, +98 912 345 6789, 0098-912-345-6789 and ۰۹۱۲۳۴۵۶۷۸۹ collide.
A national number (single leading 0) is assumed to be in DEFAULT_CALLING_CODE (Iran, 98).
"""

import re

from app.core.text import normalize_fa

DEFAULT_CALLING_CODE = "98"
PHONE_TYPES = {"phone", "whatsapp"}


def normalize_phone(value: str) -> str:
    text = (normalize_fa(value) or "").strip()
    international = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if international:
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return DEFAULT_CALLING_CODE + digits[1:]
    return digits


def normalize_method(method_type: str, value: str) -> str:
    if method_type in PHONE_TYPES:
        return normalize_phone(value)
    text = normalize_fa(value) or ""
    if method_type == "email":
        return text.replace(" ", "")
    if method_type == "telegram":
        return text.lstrip("@").replace(" ", "")
    return text
