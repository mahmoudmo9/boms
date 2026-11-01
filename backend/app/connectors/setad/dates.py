"""Jalali date helpers (no external dependency).

Ported from SetadSuite v0.9.23 setad_tender/dates.py; g2j moved in from setad_tender/widgets.py."""
from __future__ import annotations
import re
from datetime import date, datetime
from functools import lru_cache

_FA = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def j2g(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    months = [0, 31, 29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return gy, gm, gd


@lru_cache(maxsize=50000)
def _parse_jalali_str(s: str) -> date | None:
    return _parse_jalali(s)


def parse_jalali(value: str) -> date | None:
    """Cached wrapper: the same few thousand date strings are parsed again on every list refresh."""
    return _parse_jalali_str(str(value or ''))


def _parse_jalali(value: str) -> date | None:
    """'1405/07/29 14:00' (Persian or Latin digits) -> date; None when unparseable."""
    s = str(value or '').translate(_FA)
    m = re.search(r'(1[34]\d{2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})', s)
    if not m:
        return None
    jy, jm, jd = (int(x) for x in m.groups())
    if not (1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    try:
        return date(*j2g(jy, jm, jd))
    except ValueError:
        return None


def days_left(value: str, today: date | None = None) -> int | None:
    d = parse_jalali(value)
    if d is None:
        return None
    return (d - (today or datetime.now().date())).days


def g2j(gy,gm,gd):
    # BOMS port: moved here from setad_tender/widgets.py (a Qt module) unchanged
    g_d_m=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+(365*gy)+((gy2+3)//4)-((gy2+99)//100)+((gy2+399)//400)+gd+g_d_m[gm-1]
    jy=-1595+(33*(days//12053));days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:
        jy+=(days-1)//365;days=(days-1)%365
    if days<186:jm=1+days//31;jd=1+days%31
    else:jm=7+(days-186)//30;jd=1+(days-186)%30
    return jy,jm,jd


def jalali_of(d: date) -> str:
    y, m, dd = g2j(d.year, d.month, d.day)
    return f'{y}/{m:02d}/{dd:02d}'
