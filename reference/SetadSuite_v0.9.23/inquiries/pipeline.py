"""Business logic of the follow-up funnel: stages, checks, RFQ text and pricing.

Pure Python (no Qt, no database) so it can be unit-tested.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import jalali
from parser import Need, western_digits

# ---------------------------------------------------------------- stages
STAGES = [
    ("starred", "ستاره‌دار", "#F79009"),
    ("review", "در حال بررسی", "#175CD3"),
    ("rfq_ready", "انتخاب‌شده برای استعلام", "#7A5AF8"),
    ("rfq", "در حال استعلام", "#0E9384"),
    ("final", "انتخاب نهایی و قیمت‌گذاری", "#B54708"),
    ("submitted", "پاسخ ارسال شد", "#0F766E"),
    ("result", "نتیجه", "#067647"),
]
REJECTED = "rejected"
STAGE_KEYS = [k for k, _, _ in STAGES]
STAGE_TITLE = {k: t for k, t, _ in STAGES} | {REJECTED: "صرف‌نظرشده"}
STAGE_COLOR = {k: c for k, _, c in STAGES} | {REJECTED: "#667085"}
OPEN_STAGES = {"starred", "review", "rfq_ready", "rfq", "final"}   # deadline still matters

RESULTS = [("won", "برنده"), ("lost", "بازنده"), ("cancelled", "لغو شد"), ("no_result", "نامشخص")]
RFQ_STATUSES = [("draft", "ارسال نشده"), ("sent", "ارسال‌شده"), ("answered", "پاسخ داده"),
                ("no_answer", "جواب نداد"), ("unavailable", "موجود ندارد")]
RFQ_STATUS_TITLE = dict(RFQ_STATUSES)

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


# ---------------------------------------------------------------- RFQ text
def _qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


def rfq_text(need: Need, info: dict | None, seller: str, reply_by: str = "", validity: str = "") -> str:
    items = items_of(need, info)
    city = detail_field(info, "شهر محل تحویل")
    province = detail_field(info, "استان محل تحویل") or need.province
    lines = ["با سلام و احترام،", "لطفاً قیمت، زمان تحویل و مدت اعتبار قیمت اقلام زیر را اعلام فرمایید:", ""]
    for i, it in enumerate(items, start=1):
        unit = f" {it.unit}" if it.unit else ""
        lines.append(f"{i}) {it.name} — {_qty(it.qty)}{unit}")
    lines.append("")
    if province or city:
        lines.append("محل تحویل: " + "، ".join(x for x in (province, city) if x))
    if validity:
        lines.append(f"اعتبار قیمت حداقل تا: {validity}")
    if reply_by:
        lines.append(f"لطفاً تا {reply_by} پاسخ دهید.")
    lines += ["", "با تشکر", seller]
    return "\n".join(lines)


# ---------------------------------------------------------------- quotes & pricing
@dataclass
class Quote:
    rfq_id: int
    supplier: str
    unit_prices: list[float | None]
    delivery_days: int | None = None
    valid_until: str = ""

    def total(self, items: list[Item]) -> float | None:
        if not self.unit_prices or any(p is None for p in self.unit_prices[:len(items)]) or len(self.unit_prices) < len(items):
            return None
        return sum(p * it.qty for p, it in zip(self.unit_prices, items))


def quote_warnings(q: Quote, items: list[Item], required_valid: str, today: date | None = None) -> list[str]:
    today = today or date.today()
    warns = []
    if q.total(items) is None:
        warns.append("قیمت همه اقلام وارد نشده")
    if required_valid and q.valid_until:
        rv, qv = jalali.to_date(required_valid), jalali.to_date(q.valid_until)
        if rv and qv and qv < rv:
            warns.append(f"اعتبار قیمت ({q.valid_until}) کمتر از حد لازم ({required_valid})")
    if q.delivery_days is not None:
        arrive = today + timedelta(days=int(q.delivery_days))
        dates = [jalali.to_date(it.need_date) for it in items if it.need_date]
        dates = [d for d in dates if d]
        if dates and arrive > min(dates):
            warns.append(f"تحویل ({q.delivery_days} روز) دیرتر از تاریخ نیاز خریدار ({jalali.from_date(min(dates))})")
    return warns


@dataclass
class PricingParams:
    margin_pct: float = 15.0
    shipping: float = 0.0
    payment_months: float = 1
    finance_monthly_pct: float = 3.0
    vat_pct: float = 10.0
    rounding: int = 1000


@dataclass
class PriceLine:
    item: Item
    cost_unit: float
    suggested_unit: float
    final_unit: float

    @property
    def final_total(self) -> float:
        return self.final_unit * self.item.qty


@dataclass
class PricePlan:
    lines: list[PriceLine] = field(default_factory=list)
    cost_total: float = 0
    shipping: float = 0
    finance_cost: float = 0
    sale_total: float = 0
    vat: float = 0
    grand_total: float = 0
    profit: float = 0

    @property
    def profit_pct(self) -> float:
        base = self.cost_total + self.shipping + self.finance_cost
        return 100 * self.profit / base if base else 0


def _ceil_to(value: float, step: int) -> float:
    step = max(1, int(step or 1))
    return math.ceil(value / step) * step


def price_plan(items: list[Item], cost_units: list[float], params: PricingParams,
               overrides: dict[int, float] | None = None) -> PricePlan:
    """Supplier cost → suggested selling price per unit.

    unit = (cost + share of shipping) × (1 + payment months × monthly finance %) × (1 + margin %),
    rounded up to `rounding` rials. VAT is added on top of the selling total.
    """
    overrides = overrides or {}
    cost_total = sum(c * it.qty for c, it in zip(cost_units, items))
    finance = 1 + params.payment_months * params.finance_monthly_pct / 100
    lines = []
    for i, (it, cost) in enumerate(zip(items, cost_units)):
        line_cost = cost * it.qty
        ship_share = params.shipping * (line_cost / cost_total) if cost_total else params.shipping / max(len(items), 1)
        base_unit = (cost + ship_share / it.qty) * finance
        suggested = _ceil_to(base_unit * (1 + params.margin_pct / 100), params.rounding)
        final = overrides.get(i) or suggested
        lines.append(PriceLine(it, cost, suggested, final))
    plan = PricePlan(lines=lines, cost_total=cost_total, shipping=params.shipping)
    plan.finance_cost = (cost_total + params.shipping) * (finance - 1)
    plan.sale_total = sum(line.final_total for line in lines)
    plan.vat = round(plan.sale_total * params.vat_pct / 100)
    plan.grand_total = plan.sale_total + plan.vat
    plan.profit = plan.sale_total - cost_total - params.shipping - plan.finance_cost
    return plan


def proforma_number(counters: dict, year: str | None = None) -> tuple[str, dict]:
    """Next number like '1405/001' plus the updated counters dict."""
    year = year or jalali.today()[:4]
    n = int(counters.get(year, 0)) + 1
    new = dict(counters)
    new[year] = n
    return f"{year}/{n:03d}", new
