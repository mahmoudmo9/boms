"""Persian text normalization.

``normalize_fa`` must give exactly the same output as the SQL function
``core.normalize_fa(text)`` created in migration 0001. Both are built from the
same character tables below (the migration holds a frozen copy); the test
suite compares them on a shared fixture list.

Rules:
- Arabic yeh/alef maksura -> Persian yeh, Arabic kaf -> Persian kaf, teh marbuta -> heh
- Persian and Arabic-Indic digits -> Latin digits
- tatweel and Arabic diacritics are removed
- ZWNJ and other zero-width/format characters -> space
- all whitespace collapsed to a single space, trimmed
- Latin letters lowercased (ASCII and Latin-1 uppercase only, so SQL matches exactly)
"""

# 1:1 replacements. Characters at the same index map to each other.
MAP_FROM = (
    "يى"  # ي ى
    "ك"  # ك
    "ة"  # ة
    "۰۱۲۳۴۵۶۷۸۹"  # Persian digits
    "٠١٢٣٤٥٦٧٨٩"  # Arabic-Indic digits
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏ"
    "ÐÑÒÓÔÕÖØÙÚÛÜÝÞ"
)
MAP_TO = (
    "یی"
    "ک"
    "ه"
    "01234567890123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "àáâãäåæçèéêëìíîï"
    "ðñòóôõöøùúûüýþ"
)

# Characters that become a space: whitespace plus zero-width / bidi format characters.
SPACE_CHARS = (
    "\t\n\u000b\u000c\r\u0085  "
    "           "
    "    　"
    "​‌‍‎‏⁠﻿᠎"
    "‪‫‬‭‮⁦⁧⁨⁩"
)

# Characters that are removed: tatweel and Arabic diacritics/marks.
REMOVE_CHARS = (
    "ـ"
    + "".join(chr(c) for c in range(0x0610, 0x061B))
    + "".join(chr(c) for c in range(0x064B, 0x0660))
    + "ٰ"
)

assert len(MAP_FROM) == len(MAP_TO)

_TABLE = str.maketrans(
    MAP_FROM + SPACE_CHARS, MAP_TO + " " * len(SPACE_CHARS), REMOVE_CHARS
)


def normalize_fa(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.translate(_TABLE)
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip(" ")
