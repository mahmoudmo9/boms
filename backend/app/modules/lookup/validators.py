"""Validation as you type (v0.9.0 section 8.3). Each validator returns ``{valid, normalized, reason}``; the same code
serves the API and the backend checks.

- IBAN: ISO 13616 (country length table, mod-97 = 1).
- BIC: ISO 9362 format (4 bank letters, 2 country letters, 2 location characters, optional 3 branch characters).
- Iranian national ID: 10-digit individual code (check digit) and 11-digit legal-entity ID (weighted check digit).
- Iranian economic code: 12 digits (legacy) or the 11-digit national ID of a legal entity (current practice).
- Chinese Unified Social Credit Code: 18 characters, GB 32100-2015 check character.
- Phone: E.164 with the existing ``phonenumbers``.
- E-mail: the practical address grammar (local@domain.tld).
- Container number: ISO 6346 check digit."""
import re

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
IBAN_LENGTHS = {"AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29,
                "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FR": 27,
                "GB": 22, "GE": 22, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IR": 26, "IS": 26,
                "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27,
                "MT": 31, "NL": 18, "NO": 15, "OM": 23, "PK": 24, "PL": 28, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
                "RU": 33, "SA": 24, "SE": 24, "SI": 19, "SK": 24, "TR": 26, "UA": 29}
USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
USCC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def _out(valid: bool, normalized: str | None = None, reason: str | None = None, **extra) -> dict:
    return {"valid": valid, "normalized": normalized, "reason": None if valid else reason, **extra}


def _clean(value: str) -> str:
    return re.sub(r"[\s\-.]", "", (value or "").translate(FA_DIGITS)).upper()


def iban(value: str) -> dict:
    v = _clean(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", v):
        return _out(False, v, "format")
    if v[:2] in IBAN_LENGTHS and len(v) != IBAN_LENGTHS[v[:2]]:
        return _out(False, v, "length", expected=IBAN_LENGTHS[v[:2]])
    rearranged = v[4:] + v[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    if int(number) % 97 != 1:
        return _out(False, v, "checksum")
    return _out(True, " ".join(v[i:i + 4] for i in range(0, len(v), 4)))


def bic(value: str) -> dict:
    v = _clean(value)
    if not re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", v):
        return _out(False, v, "format")
    return _out(True, v)


def national_id_ir(value: str) -> dict:
    """10 digits: an individual's code; 11 digits: a legal entity's national ID."""
    v = _clean(value)
    if re.fullmatch(r"\d{10}", v):
        if len(set(v)) == 1:
            return _out(False, v, "checksum")
        s = sum(int(v[i]) * (10 - i) for i in range(9)) % 11
        check = s if s < 2 else 11 - s
        return _out(check == int(v[9]), v, "checksum", kind="individual")
    if re.fullmatch(r"\d{11}", v):
        d = int(v[9]) + 2
        weights = [29, 27, 23, 19, 17, 29, 27, 23, 19, 17]
        s = sum((int(v[i]) + d) * weights[i] for i in range(10)) % 11
        return _out((0 if s == 10 else s) == int(v[10]), v, "checksum", kind="legal_entity")
    return _out(False, v, "length")


def economic_code_ir(value: str) -> dict:
    v = _clean(value)
    if re.fullmatch(r"\d{12}", v):
        return _out(True, v, kind="legacy")
    if re.fullmatch(r"\d{11}", v):
        return {**national_id_ir(v), "kind": "national_id"}
    return _out(False, v, "length")


def uscc(value: str) -> dict:
    v = _clean(value)
    if len(v) != 18 or any(c not in USCC_CHARS for c in v):
        return _out(False, v, "format")
    total = sum(USCC_CHARS.index(v[i]) * USCC_WEIGHTS[i] for i in range(17))
    check = USCC_CHARS[(31 - total % 31) % 31]
    return _out(check == v[17], v, "checksum")


def phone(value: str, region: str | None = None) -> dict:
    import phonenumbers

    try:
        parsed = phonenumbers.parse((value or "").translate(FA_DIGITS), (region or "IR").upper())
    except phonenumbers.NumberParseException:
        return _out(False, value, "format")
    if not phonenumbers.is_valid_number(parsed):
        return _out(False, value, "invalid")
    return _out(True, phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
                region=phonenumbers.region_code_for_number(parsed))


def email(value: str) -> dict:
    v = (value or "").strip()
    ok = re.fullmatch(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", v) is not None
    return _out(ok, v.lower() if ok else v, "format")


def container(value: str) -> dict:
    from app.modules.reference.service import container_number_valid

    v = _clean(value)
    if not re.fullmatch(r"[A-Z]{3}[UJZ]\d{7}", v):
        return _out(False, v, "format")
    return _out(container_number_valid(v), v, "checksum")


VALIDATORS = {"iban": iban, "bic": bic, "national_id_ir": national_id_ir, "economic_code_ir": economic_code_ir,
              "uscc": uscc, "phone": phone, "email": email, "container": container}
