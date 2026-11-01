"""Pure HTML parsers for the Setadiran needs board and appendix pages.
No network access, session handling, or browser-control logic lives here.

Ported unchanged from SetadSuite v0.9.23 inquiries/parser.py.
"""
from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, asdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup

PERSIAN_NUMBERS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def western_digits(value: str) -> str:
    return str(value).translate(PERSIAN_NUMBERS)


def compact(value: str | None) -> str:
    return " ".join(html.unescape(value or "").split())


@dataclass(frozen=True)
class Need:
    need_no: str
    request_id: str
    description: str
    organization: str
    province: str
    need_type: str
    category: str
    goods_group: str
    service_group: str
    published_date: str
    response_deadline: str
    detail_url: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Attachment:
    file_id: str
    file_name: str


def parse_board(page_html: str, base_url: str) -> list[Need]:
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.select_one("#aList")
    if table is None:
        raise ValueError("جدول نیازها (#aList) در صفحه پیدا نشد. ممکن است وارد حساب نشده باشید.")

    out = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 11:
            continue
        values = []
        for td in tds:
            titled = td.find(attrs={"title": True})
            long_value = titled.get("title", "") if titled else ""
            values.append(compact(long_value if long_value.strip().lower() != "null" and long_value.strip() else td.get_text(" ", strip=True)))
        link = tds[1].find("a")
        onclick = link.get("onclick", "") if link else ""
        match = re.search(r"showPurchaseNeed\(\s*['\"]([^'\"]+)['\"]", onclick)
        if not match:
            continue
        detail_url = urljoin(base_url, html.unescape(match.group(1)))
        req_match = re.search(r"[?&]requestId=(\d+)", detail_url)
        request_id = req_match.group(1) if req_match else ""
        if not request_id:
            continue
        out.append(Need(
            need_no=western_digits(values[1]), request_id=request_id,
            description=values[2], organization=values[3], province=values[4],
            need_type=values[5], category=values[6], goods_group=values[7],
            service_group=values[8], published_date=western_digits(values[9]),
            response_deadline=values[10], detail_url=detail_url
        ))
    return out


def parse_search_results(page_html: str, base_url: str) -> list[Need]:
    """Rows of the «جستجوی پیشرفته» result table: 12 cells (the board has 11 — here the city is a separate cell,
    merged into «province» below); the detail link is postLink("purchaseNeedView.do?...requestId=N...")."""
    soup = BeautifulSoup(page_html, "html.parser")
    out = []
    for tr in soup.select("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 12:
            continue
        link = tds[1].find("a")
        onclick = link.get("onclick", "") if link else ""
        match = re.search(r"""['"]([^'"]*requestId=\d+[^'"]*)['"]""", html.unescape(onclick))
        if not match:
            continue
        values = []
        for td in tds:
            titled = td.find(attrs={"title": True})
            long_value = titled.get("title", "") if titled else ""
            values.append(compact(long_value if long_value.strip().lower() != "null" and long_value.strip() else td.get_text(" ", strip=True)))
        detail_url = urljoin(base_url, html.unescape(match.group(1)))
        req_match = re.search(r"[?&]requestId=(\d+)", detail_url)
        if not req_match:
            continue
        out.append(Need(
            need_no=western_digits(values[1]), request_id=req_match.group(1),
            description=values[2], organization=values[3],
            province=values[4] + (("، " + values[5]) if values[5] else ""),
            need_type=values[6], category=values[7], goods_group=values[8],
            service_group=values[9], published_date=western_digits(values[10]),
            response_deadline=values[11], detail_url=detail_url
        ))
    return out


def find_pagination(page_html: str, visible_rows: int) -> tuple[int, str | None]:
    """Return page count and the actual query parameter (e.g. d-146909-p)."""
    soup = BeautifulSoup(page_html, "html.parser")
    pagebanner = soup.select_one(".pagebanner")
    total_results = None
    if pagebanner:
        normalized = western_digits(compact(pagebanner.get_text(" ", strip=True)))
        match = re.search(r"\b([\d,]+)\s*مورد", normalized)
        if match:
            total_results = int(match.group(1).replace(",", ""))
    page_key, highest = None, 1
    for a in soup.select('a[href*="-p="]'):
        href = html.unescape(a.get("href", ""))
        match = re.search(r"(?:[?&])(d-\d+-p)=(\d+)", href)
        if match:
            page_key = match.group(1)
            highest = max(highest, int(match.group(2)))
    if total_results is not None and visible_rows > 0:
        highest = max(highest, math.ceil(total_results / visible_rows))
    return highest, page_key


def parse_appendix_link(page_html: str, base_url: str) -> str | None:
    """Find the appendix URL embedded in anonymousShowAppendix(), without executing JS."""
    match = re.search(
        r"function\s+anonymousShowAppendix\s*\(\s*\)\s*\{(.*?)\n\s*\}",
        page_html, re.S
    )
    block = match.group(1) if match else page_html
    if "anonymousAppendixDocument.do" not in block:
        return None
    values = {}
    for name in ("docId", "docNo", "docState", "docType"):
        token = re.search(r"[&?]" + name + r"=(\d+)", block)
        if not token:
            return None
        values[name] = token.group(1)
    return urljoin(
        base_url,
        "anonymousAppendixDocument.do?method=checkCaptcha&"
        + "&".join(f"{k}={v}" for k, v in values.items())
    )


def parse_attachments(page_html: str) -> list[Attachment]:
    soup = BeautifulSoup(page_html, "html.parser")
    if not soup.select("table"):
        raise ValueError("صفحه فهرست پیوست‌ها نمایش داده نشد.")
    result = []
    seen = set()
    for radio in soup.select('input[type="radio"][name="sel"][id^="r"]'):
        fid = radio.get("id", "")[1:]
        if not fid.isdigit() or fid in seen:
            continue
        tr = radio.find_parent("tr")
        cols = tr.find_all("td", recursive=False) if tr else []
        if len(cols) < 3:
            continue
        name = compact(cols[2].get_text(" ", strip=True))
        if not name:
            continue
        result.append(Attachment(file_id=fid, file_name=name))
        seen.add(fid)
    return result


# ---------------------------------------------------------------------------
# Need detail page («جزئيات اطلاعات نياز» form on purchaseNeedView.do)
# ---------------------------------------------------------------------------
# The site keeps every value inside readonly <input>/<textarea> elements, so the
# fields are read by their form names. Anything unknown that still has a value
# is picked up afterwards with the label printed next to it.

_DETAIL_FIELDS = (
    ("شماره نیاز", ("purchaseNeedDto.needNo",)),
    ("تاریخ و ساعت اعلان عمومی", ("sendDate",)),
    ("نام دستگاه خریدار", ("purchaseNeedDto.purchaseRequestDto.organization.name",)),
    ("ایجادکننده درخواست", ("purchaseNeedDto.creatorInfo",)),
    ("مهلت ارسال پاسخ", ("deadlineDurationDateStr", "deadlineDurationTimeStr")),
    ("حداقل تاریخ اعتبار قیمت", ("purchaseNeedDto.priceValidDurationDate", "purchaseNeedDto.priceValidDurationTime")),
    ("استان محل تحویل", ("purchaseNeedDto.purchaseRequestDto.deliveryLocation.parentLocation.name",)),
    ("شهر محل تحویل", ("purchaseNeedDto.purchaseRequestDto.deliveryLocation.name",)),
)
_DETAIL_RADIOS = (
    ("طبقه‌بندی موضوعی", "purchaseNeedDto.needType"),
    ("نوع فرآیند خرید", "purchaseNeedDto.purchaseRequestDto.purchaseType"),
)
_DESCRIPTION_NAME = "purchaseNeedDto.needName"
_BUYER_NOTE_NAME = "purchaseNeedDto.description"
_SKIP_NAMES = {"remainTime", "urlProhibition", "method"}


def _field_value(el) -> str:
    if el is None:
        return ""
    if el.name == "textarea":
        return compact(el.get_text(" ", strip=True))
    return compact(el.get("value", ""))


def _label_before(el) -> str:
    """Text of the table cell that precedes the cell holding `el` (its printed label)."""
    td = el.find_parent("td")
    while td is not None:
        td = td.find_previous_sibling("td")
        if td is None:
            break
        text = compact(td.get_text(" ", strip=True))
        if text:
            return text.rstrip(" :：")
    return ""


def _radio_label(radio) -> str:
    """Text written right after a radio/checkbox (e.g. «کالا»)."""
    parts = []
    for sib in radio.next_siblings:
        if getattr(sib, "name", None) == "input":
            break
        text = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib)
        text = compact(text)
        if text:
            parts.append(text)
    return compact(" ".join(parts))


def parse_need_detail(page_html: str) -> dict:
    """Extract only the need-detail form of purchaseNeedView.do.

    Returns {
      "fields": [(label, value), ...]   in page order,
      "description": str,                شرح کلی نیاز
      "group_label": str, "group": str,  گروه کالا / گروه خدمت
      "items_title": str,                e.g. «اطلاعات کالاهای مورد نیاز»
      "items": {"headers": [...], "rows": [[...], ...]},
      "buyer_note": str,                 توضیحات خریدار
      "attachment_count": int | None,    from «مشاهده مدارک پیوستی (n)»
      "found": bool                      False when the form is not on the page
    }
    """
    soup = BeautifulSoup(page_html, "html.parser")
    form = soup.find("form", attrs={"name": "PurchaseNeedViewForm"}) or soup.find(
        "form", action=re.compile(r"purchaseNeedView\.do"))
    root = form or soup
    used: set[str] = set()

    def named(name):
        return root.find(["input", "textarea"], attrs={"name": name})

    fields: list[tuple[str, str]] = []
    for label, names in _DETAIL_FIELDS:
        values = []
        for name in names:
            used.add(name)
            value = _field_value(named(name))
            if value:
                values.append(western_digits(value) if name != names[0] or len(names) == 1 else value)
        if not values:
            continue
        value = " ساعت ".join(values) if len(values) == 2 else values[0]
        if names[0] == "deadlineDurationDateStr":
            day = _field_value(named("durationDto.day"))
            hour = _field_value(named("durationDto.hour"))
            if day or hour:
                remaining = " و ".join(x for x in (f"{day} روز" if day else "", f"{hour} ساعت" if hour else "") if x)
                value += f"  (باقی‌مانده هنگام دریافت: {remaining})"
        fields.append((label, value))
    used.update({"durationDto.day", "durationDto.hour", "durationDto.minute", "durationDto.second"})

    for label, name in _DETAIL_RADIOS:
        used.add(name)
        checked = root.find("input", attrs={"name": name, "checked": True})
        if checked is not None:
            text = _radio_label(checked)
            if text:
                fields.append((label, text))

    treasury = root.find("input", attrs={"name": "islamicTreasury"})
    if treasury is not None:
        used.add("islamicTreasury")
        fields.append(("پرداخت از محل اسناد خزانه اسلامی", "بله" if treasury.has_attr("checked") else "خیر"))

    description = _field_value(named(_DESCRIPTION_NAME))
    buyer_note = _field_value(named(_BUYER_NOTE_NAME))
    used.update({_DESCRIPTION_NAME, _BUYER_NOTE_NAME})

    group_label, group = "", ""
    group_el = root.find("textarea", attrs={"name": re.compile(r"ClassifyDto\.name$")})
    if group_el is not None:
        used.add(group_el.get("name"))
        group = _field_value(group_el)
        group_label = _label_before(group_el) or "گروه"

    # Any other visible field with a value (keeps pages of other need types complete).
    for el in root.find_all(["input", "textarea"]):
        name = el.get("name") or el.get("id") or ""
        if not name or name in used or name in _SKIP_NAMES:
            continue
        if el.name == "input" and (el.get("type") or "text").lower() not in ("text", ""):
            continue
        value = _field_value(el)
        label = _label_before(el)
        if value and label:
            used.add(name)
            fields.append((label, value))

    items_title = ""
    for td in root.find_all("td"):
        text = compact(td.get_text(" ", strip=True))
        if text.startswith("اطلاعات") and "مورد نياز" in text.replace("مورد نیاز", "مورد نياز") and len(text) < 60:
            items_title = text
            break
    headers: list[str] = []
    rows: list[list[str]] = []
    grid = root.select_one("table#aList") or root.select_one("table.grid")
    if grid is not None:
        headers = [compact(th.get_text(" ", strip=True)) for th in grid.select("thead th")]
        for tr in grid.select("tbody tr"):
            cells = [compact(td.get_text(" ", strip=True)) for td in tr.find_all("td", recursive=False)]
            if any(cells):
                rows.append(cells)

    attachment_count = None
    for btn in root.find_all("input", attrs={"type": "button"}):
        m = re.search(r"پيوستي|پیوستی", btn.get("value", ""))
        if m:
            num = re.search(r"\((\d+)\)", western_digits(btn.get("value", "")))
            if num:
                attachment_count = int(num.group(1))
            break

    return {
        "fields": fields,
        "description": description,
        "group_label": group_label,
        "group": group,
        "items_title": items_title,
        "items": {"headers": headers, "rows": rows},
        "buyer_note": buyer_note,
        "attachment_count": attachment_count,
        "found": form is not None,
    }
