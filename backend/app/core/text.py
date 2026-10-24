"""Persian/Arabic text normalization used for every search index and query.

The SQL function core.normalize_fa(text) is generated from the constants in
this module (see migrations/versions/0001_core.py), so both implementations
apply exactly the same character mapping. Changing anything here requires a
new migration that recreates core.normalize_fa and rebuilds dependent indexes.

Steps (single pass, then whitespace collapse):
- Arabic YEH/ALEF MAKSURA -> Persian YEH, Arabic KAF -> Persian KEHEH, TEH MARBUTA -> HEH
- remove TATWEEL and Arabic diacritics
- Persian and Arabic-Indic digits -> Latin digits
- zero-width characters (ZWNJ etc.) and all whitespace -> a single space
- uppercase Latin letters -> lowercase
"""

import re

# Characters removed entirely: tatweel, Arabic harakat/diacritics, superscript alef.
DELETE_CHARS = "ـ" + "".join(chr(c) for c in range(0x064B, 0x0660)) + "ٰ"

_ARABIC_TO_PERSIAN = {"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"}
_DIGITS = {chr(0x06F0 + i): str(i) for i in range(10)} | {chr(0x0660 + i): str(i) for i in range(10)}
_ZERO_WIDTH = "​‌‍‎‏⁠﻿"
_WHITESPACE = (
    "\t\n\u000B\u000C\r\u0085  "
    + "".join(chr(c) for c in range(0x2000, 0x200B))
    + "    　"
)


def _latin_lower_pairs() -> dict[str, str]:
    """Uppercase -> lowercase for Basic Latin, Latin-1 and Latin Extended-A/B."""
    pairs = {}
    for cp in range(0x0041, 0x0250):
        ch = chr(cp)
        low = ch.lower()
        if ch.isupper() and len(low) == 1 and low != ch:
            pairs[ch] = low
    return pairs


MAP: dict[str, str] = (
    _ARABIC_TO_PERSIAN
    | _DIGITS
    | {c: " " for c in _ZERO_WIDTH}
    | {c: " " for c in _WHITESPACE}
    | _latin_lower_pairs()
)
MAP_FROM = "".join(MAP.keys())
MAP_TO = "".join(MAP.values())

_TABLE = str.maketrans(MAP_FROM, MAP_TO, DELETE_CHARS)
_SPACES = re.compile(" {2,}")


def normalize_fa(value: str | None) -> str | None:
    if value is None:
        return None
    return _SPACES.sub(" ", value.translate(_TABLE)).strip(" ")


def sql_unicode_literal(value: str) -> str:
    """Render a string as a PostgreSQL U&'' literal using only ASCII."""
    return "U&'" + "".join(f"\\{ord(c):04X}" if ord(c) < 0x10000 else f"\\+{ord(c):06X}" for c in value) + "'"


def normalize_fa_sql() -> str:
    """CREATE statement for core.normalize_fa, built from the constants above."""
    from_lit = sql_unicode_literal(MAP_FROM + DELETE_CHARS)
    to_lit = sql_unicode_literal(MAP_TO)
    return (
        "CREATE OR REPLACE FUNCTION core.normalize_fa(t text) RETURNS text\n"
        "LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE\n"
        f"RETURN btrim(regexp_replace(translate(t, {from_lit}, {to_lit}), ' {{2,}}', ' ', 'g'), ' ')"
    )
