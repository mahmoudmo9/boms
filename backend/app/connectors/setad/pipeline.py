"""Business helpers of the purchase-call (need) side: numbers in words, deadlines, items from the detail page.

Ported from SetadSuite v0.9.23 inquiries/pipeline.py: only the parts BOMS uses are kept, unchanged (the funnel
stages, RFQ text, supplier quotes, pricing and proforma numbering are replaced by BOMS's own sourcing, costing and
quotes modules). DEFAULT_SETTINGS supplies the seeded checklist, dismiss reasons and Setad proforma texts.
Pure Python (no Qt, no database) so it can be unit-tested.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import jalali
from .eproc_parser import Need, western_digits

DEFAULT_SETTINGS = {
    "seller_name": "شرکت صنعت آبی الوند",
    "national_id": "",
    "economic_code": "",
    "signer": "",
    "vat_pct": 10.0,
    "margin_pct": 15.0,
    "finance_monthly_pct": 3.0,
    "default_payment_months": 1,
    "rounding": 1000,
    "proforma_template": "",
    "proforma_counters": {},
    "addressee": "مدیریت محترم امور تدارکات {خریدار}",
    "delivery_text": "حداکثر {روز} روز کاری پس از ابلاغ سفارش",
    "payment_text": "طبق شرایط اعلامی خریدار در سامانه ستاد",
    "shipping_text": "بر عهده فروشنده",
    "checklist": [
        "کالا/خدمت در حوزه کاری ما است",
        "شرایط و الزامات خریدار قابل تأمین است",
        "محل تحویل و هزینه ارسال قابل قبول است",
        "شرایط پرداخت قابل قبول است",
        "مهلت برای گرفتن قیمت از تأمین‌کننده کافی است",
    ],
    "warn_keywords": [],
    "reject_reasons": [
        "خارج از حوزه کاری",
        "مهلت کافی نیست",
        "الزامات خریدار قابل تأمین نیست",
        "تأمین‌کننده پیدا نشد",
        "قیمت تأمین‌کننده بالا است",
        "شرایط پرداخت نامناسب",
        "سایر",
    ],
}

# ---------------------------------------------------------------- numbers & text
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_NORM = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ۀ": "ه", "ة": "ه", "‌": " ", "ـ": ""})


def fa_digits(value) -> str:
    return str(value).translate(_FA_DIGITS)


def fa_text(text: str) -> str:
    """Persian digits for words without Latin letters (keeps codes like «S7-1200» untouched)."""
    return " ".join(tok if re.search(r"[A-Za-z]", tok) else fa_digits(tok) for tok in str(text or "").split(" "))


def money(value: float | int | None) -> str:
    """1234000 → '1,234,000' (UI font shows Persian digits)."""
    if value is None:
        return ""
    return f"{int(round(value)):,}"


def money_fa(value: float | int) -> str:
    """For documents: Persian digits and Persian thousands separator."""
    return fa_digits(money(value))


def parse_amount(text) -> int | None:
    t = western_digits(str(text or "")).replace(",", "").replace("٬", "").replace("،", "").strip()
    t = re.sub(r"[^\d.]", "", t)
    if not t:
        return None
    try:
        return int(round(float(t)))
    except ValueError:
        return None


def parse_number(text) -> float | None:
    t = western_digits(str(text or "")).replace(",", "").replace("٬", "").replace("/", ".").strip()
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_SCALES = ["", "هزار", "میلیون", "میلیارد", "هزار میلیارد", "میلیون میلیارد"]


def _three(n: int) -> str:
    parts = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if 10 <= rest < 20:
        parts.append(_TEENS[rest - 10])
    else:
        t, o = divmod(rest, 10)
        if t:
            parts.append(_TENS[t])
        if o:
            parts.append(_ONES[o])
    return " و ".join(parts)


def number_words(n: int) -> str:
    n = int(n)
    if n == 0:
        return "صفر"
    if n < 0:
        return "منفی " + number_words(-n)
    groups, i = [], 0
    while n:
        n, g = divmod(n, 1000)
        if g:
            groups.append((_three(g) + " " + _SCALES[i]).strip())
        i += 1
    return " و ".join(reversed(groups))


def norm_text(text: str) -> str:
    return " ".join(western_digits(str(text or "")).translate(_NORM).casefold().split())


# ---------------------------------------------------------------- deadline
def deadline_hours_from_text(text: str) -> float | None:
    t = western_digits(text or "")
    d = re.search(r"(\d+)\s*روز", t)
    h = re.search(r"(\d+)\s*ساعت", t)
    m = re.search(r"(\d+)\s*دقیقه", t)
    if not (d or h or m):
        return None
    return (int(d.group(1)) * 24 if d else 0) + (int(h.group(1)) if h else 0) + (int(m.group(1)) / 60 if m else 0)


def remaining_text(deadline_at: float | None, now: float | None = None) -> str:
    if not deadline_at:
        return ""
    now = now if now is not None else datetime.now().timestamp()
    secs = deadline_at - now
    if secs <= 0:
        return "مهلت گذشته"
    hours = int(secs // 3600)
    days, hours = divmod(hours, 24)
    if days and hours:
        return f"{days} روز و {hours} ساعت"
    if days:
        return f"{days} روز"
    if hours:
        return f"{hours} ساعت"
    return f"{max(1, int(secs // 60))} دقیقه"


def remaining_hours(deadline_at: float | None, now: float | None = None) -> float | None:
    if not deadline_at:
        return None
    now = now if now is not None else datetime.now().timestamp()
    return (deadline_at - now) / 3600


# ---------------------------------------------------------------- need details
@dataclass
class Item:
    name: str
    qty: float
    unit: str
    need_date: str = ""
    code: str = ""


def _col(headers: list[str], *words) -> int | None:
    for i, h in enumerate(headers):
        hn = norm_text(h)
        if any(norm_text(w) in hn for w in words):
            return i
    return None


def items_of(need: Need, info: dict | None) -> list[Item]:
    """Items from the detail page's goods table; one generic item when there is none."""
    info = info or {}
    table = info.get("items") or {}
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    i_name = _col(headers, "نام کالا", "شرح", "نام خدمت", "عنوان")
    i_qty = _col(headers, "تعداد", "مقدار")
    i_unit = _col(headers, "واحد")
    i_date = _col(headers, "تاریخ نیاز", "تاريخ نياز")
    i_code = _col(headers, "کد کالا", "کد")
    out = []
    for r in rows:
        def at(i):
            return r[i].strip() if i is not None and i < len(r) else ""
        name = at(i_name) or (info.get("description") or need.description)
        qty = parse_number(at(i_qty)) or 1
        code = at(i_code)
        out.append(Item(name=name, qty=qty, unit=at(i_unit), need_date=at(i_date),
                        code="" if code in ("--", "-") else code))
    if not out:
        out.append(Item(name=info.get("description") or need.description, qty=1, unit=""))
    return out


def detail_field(info: dict | None, label: str) -> str:
    for k, v in (info or {}).get("fields") or []:
        if norm_text(label) in norm_text(k):
            return v
    return ""


def required_validity(info: dict | None) -> str:
    """Jalali date until which the buyer requires prices to stay valid ('' when unknown)."""
    d = jalali.to_date(detail_field(info, "حداقل تاریخ اعتبار"))
    return jalali.from_date(d) if d else ""


def exact_deadline(info: dict | None) -> float | None:
    dt = jalali.to_datetime(detail_field(info, "مهلت ارسال پاسخ"))
    return dt.timestamp() if dt else None


_MONTH_WORDS = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8,
                "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12}


def payment_months(text: str) -> int | None:
    """Detect payment terms such as «تسویه سه ماهه» / «پرداخت 2 ماه پس از...» / «نقدی»."""
    t = norm_text(text)
    m = re.search(r"(\d{1,2}|" + "|".join(sorted(_MONTH_WORDS, key=len, reverse=True)) + r")\s*ماه", t)
    if m and re.search(r"تسویه|پرداخت|مدت|اعتباری|چک", t):
        g = m.group(1)
        return int(g) if g.isdigit() else _MONTH_WORDS[g]
    if re.search(r"\bنقد", t):
        return 0
    return None


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    hay = norm_text(text)
    return [k for k in keywords if k.strip() and norm_text(k) in hay]


def need_text_for_scan(need: Need, info: dict | None) -> str:
    info = info or {}
    parts = [need.description, info.get("description", ""), info.get("buyer_note", "")]
    parts += [" ".join(r) for r in (info.get("items") or {}).get("rows") or []]
    return " ".join(parts)
