# Ported unchanged from SetadSuite v0.9.23 inquiries/jalali.py.
"""Jalali (Persian) calendar helpers — no external dependency."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
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
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_days = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return gy, gm, gd


def to_date(text: str | None) -> date | None:
    """'1405/07/30' (any digits, optional time after it) → datetime.date."""
    if not text:
        return None
    m = re.search(r"(1[34]\d\d)\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})", str(text).translate(_FA_TO_EN))
    if not m:
        return None
    jy, jm, jd = (int(x) for x in m.groups())
    if not (1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    try:
        return date(*jalali_to_gregorian(jy, jm, jd))
    except ValueError:
        return None


def to_datetime(text: str | None, default_time: tuple[int, int] = (23, 59)) -> datetime | None:
    """'1405/07/30 ساعت 14:00' or '1405/07/28 - 14:00' → naive local datetime."""
    d = to_date(text)
    if d is None:
        return None
    rest = str(text).translate(_FA_TO_EN)
    t = re.search(r"(\d{1,2}):(\d{2})", rest[rest.find("/") + 6:] if "/" in rest else rest)
    hh, mm = (int(t.group(1)), int(t.group(2))) if t else default_time
    return datetime(d.year, d.month, d.day, min(hh, 23), min(mm, 59))


def from_date(d: date | datetime) -> str:
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def today() -> str:
    return from_date(date.today())


def add_days(text: str, days: int) -> str:
    d = to_date(text) or date.today()
    return from_date(d + timedelta(days=days))


def fmt_stamp(ts: float | None, with_time: bool = True) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts)
    return from_date(dt) + (dt.strftime("  %H:%M") if with_time else "")
