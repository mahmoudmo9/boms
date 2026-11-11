"""Where a draft field comes from in its source (v0.10.0 section 0.2.3): the region on a PDF page, the rows of a sheet,
or the span in pasted text - so the review screen can highlight it for the field in focus.

A field carries ``source = {"page": n, "original": "the wording"}`` (from the model). The position itself is found
here, from the document, never taken from the model: PyMuPDF searches the page's text layer for the wording (the whole
phrase first, then its words, keeping the lines where most of them meet). A scanned page has no text layer: the page
is shown without a region and the answer says so (``found: false``)."""
import math
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFound

RENDER_DPI = 110
MAX_TOKENS = 14
_SPACE = re.compile(r"\s+")
_FA_AR = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ۀ": "ه", "ة": "ه",
                        **{c: str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}, **{c: str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}})


def norm(text: Any) -> str:
    """Comparison form: Arabic/Persian letter variants and digits unified, case and spacing ignored."""
    return _SPACE.sub(" ", str(text or "").translate(_FA_AR).replace("‌", " ").casefold()).strip()


def _tokens(text: str) -> list[str]:
    seen, out = set(), []
    for word in re.findall(r"[^\s,;:|()\[\]«»\"']+", text or ""):
        key = norm(word)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            out.append(word)
    return sorted(out, key=len, reverse=True)[:MAX_TOKENS]


def _pdf_bytes(db: Session, source: dict) -> bytes | None:
    from app.modules.documents import service as documents

    if not source.get("document_id"):
        return None
    try:
        return documents.file_path(documents.get(db, source["document_id"])).read_bytes()
    except (NotFound, OSError):
        return None


def pdf_regions(data: bytes, page_no: int, wording: str) -> dict:
    """Rectangles (fractions of the page: x, y, w, h from the top-left) that hold ``wording`` on page ``page_no``."""
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not 1 <= page_no <= doc.page_count:
            return {"page": page_no, "pages": doc.page_count, "found": False, "rects": []}
        page = doc[page_no - 1]
        width, height = page.rect.width, page.rect.height
        rects = [r * page.rotation_matrix for r in page.search_for(wording.strip())] if wording.strip() else []
        if not rects:
            rects = _by_words(page, wording)
        out = [{"x": round(max(r.x0, 0) / width, 5), "y": round(max(r.y0, 0) / height, 5),
                "w": round(min(r.width, width) / width, 5), "h": round(min(r.height, height) / height, 5)}
               for r in rects if r.width > 0 and r.height > 0]
        return {"page": page_no, "pages": doc.page_count, "found": bool(out), "rects": out[:40]}


def _by_words(page, wording: str) -> list:
    """The lines of the page where most words of the wording are found (a phrase broken by layout or by RTL order)."""
    import pymupdf

    tokens = _tokens(wording)
    if not tokens:
        return []
    lines: dict[int, dict] = {}
    for n, token in enumerate(tokens):
        for r in page.search_for(token):
            r = r * page.rotation_matrix
            key = round((r.y0 + r.y1) / 2 / 4)                 # words within ~4 pt of each other share a line
            line = lines.setdefault(key, {"tokens": set(), "rect": pymupdf.Rect(r)})
            line["tokens"].add(n)
            line["rect"] |= r
    if not lines:
        return []
    best = max(len(v["tokens"]) for v in lines.values())
    need = 1 if len(tokens) == 1 else max(2, math.ceil(best * 0.6))
    if best < need:
        return []
    return [v["rect"] for _, v in sorted(lines.items()) if len(v["tokens"]) >= need]


def sheet_rows(preview: list[list], page: Any, wording: str) -> list[int]:
    """1-based rows of the sheet preview that hold the wording; else the row the model named."""
    target = norm(wording)
    rows = [i for i, row in enumerate(preview or [], start=1)
            if target and (target in norm(" ".join(str(c) for c in row))
                           or any(norm(c) and norm(c) == target for c in row))] if target else []
    if not rows and target:
        tokens = [norm(t) for t in _tokens(wording)]
        scored = [(sum(t in norm(" ".join(str(c) for c in row)) for t in tokens), i)
                  for i, row in enumerate(preview or [], start=1)]
        best = max((s for s, _ in scored), default=0)
        if best >= max(2, math.ceil(len(tokens) * 0.6)):
            rows = [i for s, i in scored if s == best]
    if not rows and isinstance(page, int) and 1 <= page <= len(preview or []):
        rows = [page]
    return rows[:20]


def text_span(text: str, wording: str) -> tuple[int, int] | None:
    """Character span of the wording in pasted text (spacing and letter variants ignored)."""
    if not (text and wording and wording.strip()):
        return None
    at = text.find(wording.strip())
    if at >= 0:
        return at, at + len(wording.strip())
    words = [re.escape(w) for w in wording.split()]
    try:
        m = re.search(r"\s+".join(words), text, flags=re.IGNORECASE)
    except re.error:
        m = None
    return (m.start(), m.end()) if m else None


def locate(db: Session, draft, field) -> dict:
    """The source of one field: which source of the draft, and where in it."""
    src = field.source or {}
    wording = str(src.get("original") or "")
    page = src.get("page")
    page_no = page if isinstance(page, int) and page > 0 else 1
    out: dict = {"field_id": str(field.id), "kind": None, "source_index": None, "found": False, "original": wording or None}
    if not wording and not page:
        return out
    sources = list(draft.sources or [])
    fallback: dict | None = None
    for index, s in enumerate(sources):
        kind = s.get("kind")
        if kind == "pdf":
            data = _pdf_bytes(db, s)
            if data is None:
                continue
            found = pdf_regions(data, page_no, wording)
            hit = {**out, "kind": "pdf", "source_index": index, **found,
                   "image": f"/api/ai/drafts/{draft.id}/sources/{index}/pages/{page_no}"}
            if found["found"]:
                return hit
            if fallback is None and page_no <= found["pages"]:
                fallback = hit
        elif kind == "sheet":
            rows = sheet_rows(s.get("preview") or [], page, wording)
            if rows:
                return {**out, "kind": "sheet", "source_index": index, "found": True, "rows": rows}
        elif kind == "pasted":
            span = text_span(s.get("text") or "", wording)
            if span:
                return {**out, "kind": "pasted", "source_index": index, "found": True, "start": span[0], "end": span[1]}
        elif kind == "image" and fallback is None and len(sources) == 1:
            fallback = {**out, "kind": "image", "source_index": index}
    return fallback or out


def page_png(db: Session, draft, index: int, page_no: int) -> bytes:
    """One page of a PDF source of the draft, rendered for the review screen."""
    import pymupdf

    sources = list(draft.sources or [])
    if not 0 <= index < len(sources) or sources[index].get("kind") != "pdf":
        raise NotFound("not_found", "This draft has no such PDF source")
    data = _pdf_bytes(db, sources[index])
    if data is None:
        raise NotFound("not_found", "The source file is no longer available")
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not 1 <= page_no <= doc.page_count:
            raise NotFound("not_found", "No such page")
        return doc[page_no - 1].get_pixmap(dpi=RENDER_DPI).tobytes("png")
