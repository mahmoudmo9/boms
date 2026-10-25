"""Normalization of contact-method values (``core.contact_method.value_norm``).

Phone and WhatsApp numbers are parsed with ``phonenumbers`` and stored as E.164 with a leading "+"
(``+989123456789``). The region used for numbers typed without "+"/"00" is the one sent by the client,
else the party's country, else Iran. Impossible numbers are rejected (InvalidPhone), never stored.
Email is lowercased; Telegram loses the leading "@".
"""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, ValidationResult

from app.core.text import normalize_fa

DEFAULT_REGION = "IR"
PHONE_TYPES = {"phone", "whatsapp"}

_REASONS = {
    ValidationResult.INVALID_COUNTRY_CODE: "invalid_country_code",
    ValidationResult.TOO_SHORT: "too_short",
    ValidationResult.TOO_LONG: "too_long",
    ValidationResult.INVALID_LENGTH: "invalid_length",
}
_PARSE_REASONS = {
    NumberParseException.INVALID_COUNTRY_CODE: "invalid_country_code",
    NumberParseException.NOT_A_NUMBER: "not_a_number",
    NumberParseException.TOO_SHORT_AFTER_IDD: "too_short",
    NumberParseException.TOO_SHORT_NSN: "too_short",
    NumberParseException.TOO_LONG: "too_long",
}


class InvalidPhone(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def known_region(region: str | None) -> str | None:
    region = (region or "").upper()
    return region if region and phonenumbers.country_code_for_region(region) else None


def normalize_phone(value: str, region: str | None = None) -> str:
    """Typed number -> E.164 ("+989123456789"). Accepts local, "+..." and "00..." forms and Persian digits."""
    region = known_region(region) or DEFAULT_REGION
    text = (value or "").strip()
    try:
        number = phonenumbers.parse(text, region)
    except NumberParseException as exc:
        raise InvalidPhone(_PARSE_REASONS.get(exc.error_type, "not_a_number")) from None
    result = phonenumbers.is_possible_number_with_reason(number)
    if result not in (ValidationResult.IS_POSSIBLE, ValidationResult.IS_POSSIBLE_LOCAL_ONLY):
        raise InvalidPhone(_REASONS.get(result, "not_possible"))
    if result == ValidationResult.IS_POSSIBLE_LOCAL_ONLY:
        raise InvalidPhone("local_only")
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


def normalize_method(method_type: str, value: str, region: str | None = None) -> str:
    if method_type in PHONE_TYPES:
        return normalize_phone(value, region)
    text = normalize_fa(value) or ""
    if method_type == "email":
        return text.replace(" ", "")
    if method_type == "telegram":
        return text.lstrip("@").replace(" ", "")
    return text


def display_value(method_type: str, value: str, value_norm: str) -> str:
    """International format with spaces for phones ("+98 912 345 6789"); the stored value otherwise."""
    if method_type in PHONE_TYPES:
        try:
            return phonenumbers.format_number(phonenumbers.parse(value_norm, None), PhoneNumberFormat.INTERNATIONAL)
        except NumberParseException:
            return value_norm
    return value


def phone_regions(countries: list[tuple[str, str, str]]) -> list[dict]:
    """[(iso2, name_fa, name_en)] -> the ones phonenumbers knows, with their calling code."""
    out = []
    for iso2, name_fa, name_en in countries:
        code = phonenumbers.country_code_for_region(iso2)
        if code:
            out.append({"iso2": iso2, "name_fa": name_fa, "name_en": name_en, "calling_code": code})
    return out
