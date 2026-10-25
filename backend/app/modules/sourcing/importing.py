"""Item import without AI: pasted table or text list, .csv or .xlsx -> rows -> column mapping -> preview.

Nothing is saved here. The preview returns item dicts (editable in the UI) plus per-row errors; the client then
saves the rows it keeps through the normal bulk create.
"""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.text import normalize_fa
from app.modules.system.models import Unit

MAX_ROWS = 2000
MAX_XLSX_BYTES = 10 * 1024 * 1024
INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# header words -> field (English and Persian); used only to suggest a mapping
HEADER_HINTS = {
    "name": ("name", "item", "product", "description of goods", "goods", "نام", "کالا", "شرح کالا", "قلم"),
    "description": ("description", "desc", "spec", "specification", "شرح", "توضیحات", "مشخصات"),
    "quantity": ("qty", "quantity", "amount", "تعداد", "مقدار"),
    "unit": ("unit", "uom", "واحد"),
    "target_price": ("price", "target price", "unit price", "قیمت"),
    "target_currency": ("currency", "cur", "ارز"),
    "packaging": ("packaging", "packing", "بسته‌بندی", "بسته بندی"),
    "hs_code": ("hs", "hs code", "tariff", "تعرفه", "کد تعرفه"),
    "required_by": ("required by", "delivery date", "due", "تاریخ تحویل"),
    "incoterm": ("incoterm", "incoterms", "terms", "شرایط تحویل"),
    "notes": ("notes", "note", "remarks", "یادداشت"),
}


def _clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).replace("\r", "").split("\n")).strip()


DELIMITERS = {"tab": "\t", "comma": ",", "semicolon": ";"}


def parse_text(text: str, delimiter: str = "auto") -> list[list[str]]:
    """Tab-, semicolon- or comma-separated table; a plain list (one item per line) gives one column.

    ``delimiter``: auto | tab | comma | semicolon | lines (one item per line, no splitting).
    """
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return []
    sample = "\n".join(lines[:20])
    sep = DELIMITERS.get(delimiter)
    if sep is None and delimiter == "auto":
        if "\t" in sample:
            sep = "\t"
        elif sample.count(";") >= len(lines[:20]):
            sep = ";"
        elif all("," in line for line in lines[:20]):
            sep = ","
    if sep:
        delimiter = sep
    else:
        # text list: strip bullets / numbering ("1. ", "- ", "• ")
        return [[re.sub(r"^\s*(?:[-*•·]|\(?\d+[.)\-])\s*", "", line).strip()] for line in lines][:MAX_ROWS]
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    return [[_clean_cell(c) for c in row] for row in rows][:MAX_ROWS]


def parse_csv(data: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return parse_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise AppError("unreadable_file", "The file could not be read as text", status=422)


def parse_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    if len(data) > MAX_XLSX_BYTES:
        raise AppError("file_too_large", "The spreadsheet is too large", status=422)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - any openpyxl/zip error means "not a readable xlsx"
        raise AppError("unreadable_file", "The file is not a readable .xlsx workbook", status=422) from None
    sheet = workbook.worksheets[0]
    rows = []
    for row in sheet.iter_rows(values_only=True):
        cells = [_clean_cell(c) for c in row]
        if any(cells):
            rows.append(cells)
        if len(rows) >= MAX_ROWS:
            break
    workbook.close()
    width = max((len(r) for r in rows), default=0)
    while width and all(len(r) < width or not r[width - 1] for r in rows):
        width -= 1
    return [r[:width] + [""] * (width - len(r[:width])) for r in rows]


def parse_upload(filename: str, data: bytes) -> list[list[str]]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        return parse_xlsx(data)
    if name.endswith((".csv", ".txt", ".tsv")):
        return parse_csv(data)
    raise AppError("unsupported_file", "Use .xlsx or .csv (or paste the table)", status=422)


def suggest_mapping(rows: list[list[str]]) -> tuple[list[dict], bool]:
    """Guess field per column from a header row. Returns (mapping, first_row_is_header)."""
    if not rows:
        return [], False
    header = [(normalize_fa(c) or "").lower() for c in rows[0]]
    mapping, used = [], set()
    for index, cell in enumerate(header):
        for field, hints in HEADER_HINTS.items():
            if field not in used and cell and any(cell == h or cell.startswith(h) for h in hints):
                mapping.append({"column": index, "field": field})
                used.add(field)
                break
    if mapping:
        if "name" not in used:
            free = [i for i in range(len(header)) if i not in {m["column"] for m in mapping}]
            if free:
                mapping.append({"column": free[0], "field": "name"})
        return sorted(mapping, key=lambda m: m["column"]), True
    # no header: first column is the name, a numeric second column the quantity, a short third column the unit
    mapping = [{"column": 0, "field": "name"}]
    width = max(len(r) for r in rows)
    if width > 1 and all(parse_decimal(r[1]) is not None for r in rows if len(r) > 1 and r[1]):
        mapping.append({"column": 1, "field": "quantity"})
        if width > 2:
            mapping.append({"column": 2, "field": "unit"})
    return mapping, False


def parse_decimal(value: str) -> Decimal | None:
    text = (value or "").translate(_DIGITS).replace("٬", "").replace("،", "").replace("٫", ".").strip()
    if not text:
        return None
    text = text.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"\d+,\d+", text):
        text = text.replace(",", ".")
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def parse_date(value: str) -> date | None:
    text = (value or "").translate(_DIGITS).strip()
    for pattern in (r"(\d{4})-(\d{1,2})-(\d{1,2})", r"(\d{4})/(\d{1,2})/(\d{1,2})"):
        m = re.fullmatch(pattern, text[:10])
        if m:
            year, month, day = map(int, m.groups())
            if year < 1700:  # Jalali dates are not converted on import
                return None
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _unit_index(db: Session) -> dict[str, str]:
    index = {}
    for unit in db.scalars(select(Unit).where(Unit.active)):
        for label in (unit.code, unit.name_en, unit.name_fa):
            index[(normalize_fa(label) or "").lower()] = unit.code
    return index


def preview(db: Session, rows: list[list[str]], mapping: list[dict], skip_header: bool) -> list[dict]:
    """Rows -> [{row, item, errors}]. A row with errors is flagged, not dropped."""
    units = _unit_index(db)
    out = []
    for number, row in enumerate(rows[1:] if skip_header else rows, start=2 if skip_header else 1):
        item: dict = {"specs": []}
        errors: list[dict] = []

        def cell(column: int) -> str:
            return row[column].strip() if column < len(row) and row[column] else ""

        for m in mapping:
            value, field = cell(m["column"]), m["field"]
            if not value:
                continue
            if field == "quantity":
                quantity = parse_decimal(value)
                if quantity is None or quantity <= 0:
                    errors.append({"field": "quantity", "code": "invalid_number", "value": value})
                else:
                    item["quantity"] = str(quantity)
            elif field == "target_price":
                price = parse_decimal(value)
                if price is None or price < 0:
                    errors.append({"field": "target_price", "code": "invalid_number", "value": value})
                else:
                    item["target_price"] = str(price)
            elif field == "unit":
                code = units.get((normalize_fa(value) or "").lower())
                item["unit_code" if code else "unit_text"] = code or value
            elif field == "target_currency":
                if re.fullmatch(r"[A-Za-z]{3}", value):
                    item["target_currency"] = value.upper()
                else:
                    errors.append({"field": "target_currency", "code": "invalid_currency", "value": value})
            elif field == "required_by":
                parsed = parse_date(value)
                if parsed is None:
                    errors.append({"field": "required_by", "code": "invalid_date", "value": value})
                else:
                    item["required_by"] = parsed.isoformat()
            elif field == "incoterm":
                if value.upper()[:3] in INCOTERMS:
                    item["incoterm"] = value.upper()[:3]
                    place = value[3:].strip(" ,-")
                    if place:
                        item["incoterm_place"] = place
                else:
                    errors.append({"field": "incoterm", "code": "invalid_incoterm", "value": value})
            elif field == "hs_code":
                digits = re.sub(r"[.\s]", "", value.translate(_DIGITS))
                if re.fullmatch(r"\d{2,10}", digits):
                    item["hs_code"] = digits
                else:
                    errors.append({"field": "hs_code", "code": "invalid_hs_code", "value": value})
            elif field == "spec":
                item["specs"].append({"key": (m.get("spec_key") or f"#{m['column'] + 1}").strip(), "value": value})
            elif field in ("description", "notes") and item.get(field):
                item[field] += "\n" + value
            else:
                item[field] = value
        if not item.get("name"):
            errors.append({"field": "name", "code": "name_required"})
        if not any(cell(c) for c in range(len(row))):
            continue
        out.append({"row": number, "item": item, "errors": errors})
    return out
