"""Playwright engine of the purchase calls (needs on eproc.setadiran.ir). The operator logs in manually.
No credentials are collected or saved by this app.

Ported from SetadSuite v0.9.23 inquiries/engine.py. BOMS changes: the worker thread and its task/event queues are
gone (the Setad agent calls the methods directly, one command at a time, on its own thread) and events go to a
callback (`sink`) instead of a queue. The engine always works in the shared browser (`hub`, a SetadBrowser), so
SetadSuite's stand-alone browser launch is removed. The site-reading logic (advanced search walk, captcha wait and
recovery, pacing, board fallback, detail and attachment download) is unchanged.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as BrowserTimeout

from bs4 import BeautifulSoup
from .eproc_parser import western_digits, Need, parse_board, parse_search_results, find_pagination, parse_appendix_link, parse_attachments, parse_need_detail
from .eproc_storage import (
    need_folder, load_manifest, is_downloaded, target_path,
    validate_download, record_download, record_attachment_total,
)

BOARD_URL = "https://eproc.setadiran.ir/eproc/needBoardInfo-load.do"
SEARCH_URL = "https://eproc.setadiran.ir/eproc/needAdvancedSearch.do?pager=true"
SEARCH_PAGE_DELAY_MS = 150           # fast again: when the site asks for a captcha the user solves it and the program resumes
CAPTCHA_WAIT_SECONDS = 1800


class BrowserEngine:
    def __init__(self, hub, sink, cancel: threading.Event, root_dir: Path):
        self.sink = sink       # BOMS: callback(kind, values) instead of SetadSuite's event queue
        self.cancel = cancel
        self.root_dir = root_dir
        self.context = None
        self.board_page = None
        self.pl = None
        self.shutdown = threading.Event()
        self.browser_channel = None
        self.hub = hub         # the shared Setad browser (SetadBrowser); always set in BOMS

    def emit(self, kind: str, **values) -> None:
        if kind == "error" and values.get("message"):
            try:
                from .bridge import friendly_error
                values["message"] = friendly_error(values["message"])
            except Exception:
                pass
        self.sink(kind, values)

    def handle(self, task: dict) -> bool:
        """Run one task. Returns False for «quit»."""
        command = task.get("command")
        if command == "quit":
            return False
        if self.shutdown.is_set():
            return True
        self.cancel.clear()
        self.emit("busy", value=True)
        try:
            if command == "launch":
                self._launch()
            elif command == "refresh":
                pages = int(task.get("pages", 1))
                mode = task.get("mode", "search")
                since = task.get("since")
                if mode == "search":
                    try:
                        self._refresh_search(pages, since)
                        return True
                    except Exception as exc:
                        if self.cancel.is_set() or since:
                            raise
                        first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                        self.emit("info", message="جستجوی پیشرفته در دسترس نبود (" + first_line[:120] +
                                  ")؛ از برد اعلان عمومی استفاده شد (حداکثر ۶۰۰ نیاز).")
                try:
                    self._refresh(pages)
                except RuntimeError as exc:
                    if self.hub is None or "جدول نیازها" not in str(exc):
                        raise
                    # the Setad role was changed meanwhile: switch back to «تامین کننده» and retry once
                    self.hub.role = None
                    self._prepare()
                    self._refresh(pages)
            elif command == "detail":
                self._detail(task["need"])
            elif command == "download":
                self._download(task.get("needs", []), Path(task["directory"]))
        except Exception as exc:
            self.emit("error", message=str(exc))
        finally:
            self.emit("busy", value=False)
        return True

    # ---------------------------------------------------------------- shared browser (suite)
    def _prepare(self):
        """Suite mode: use the shared browser, our own «نیازها» tab, and the «تامین کننده» role."""
        hub = self.hub
        if not hub.alive():
            hub.open(start=BOARD_URL)
        self.context = hub.context
        self.pl = hub.playwright
        self.browser_channel = hub.channel
        self.board_page = hub.work_page()          # one shared tab for both sections
        if hub.role != "EPROC":
            self.emit("info", message="در حال تغییر نقش ستاد به «تامین کننده»…")
        try:
            hub.ensure_eproc(self.board_page, wait_login=True,
                             cancelled=lambda: self.cancel.is_set() or self.shutdown.is_set(),
                             say=lambda m: self.emit("info", message=m))
            self.board_page = hub.work_page()
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        self.emit("connected")

    def _launch(self):
        self._prepare()
        try:
            self.board_page.bring_to_front()
        except Exception:
            pass
        self.emit("info", message="به ستاد وصل است (نقش «تامین کننده»). «دریافت نیازها» را بزنید.")

    def _ensure(self):
        self._prepare()

    def _refresh(self, page_limit: int):
        self._ensure()
        page_limit = max(1, min(500, page_limit)) if page_limit else 500
        page = self.board_page
        page.goto(BOARD_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            page.locator("#aList").wait_for(state="attached", timeout=20000)
        except BrowserTimeout as exc:
            raise RuntimeError("جدول نیازها پیدا نشد؛ در پنجره مرورگر ورود را کامل کنید و صفحه فهرست نیازها را باز کنید.") from exc

        page_html = page.content()
        first = parse_board(page_html, page.url)
        if not first:
            raise RuntimeError("جدول دیده شد اما هیچ ردیف قابل‌استخراجی در صفحه فعلی وجود ندارد.")
        total_pages, page_key = find_pagination(page_html, len(first))
        num_pages = min(page_limit, total_pages)
        href_pattern = None
        if page_key:
            for link in page.locator("a[href]").all():
                href = link.get_attribute("href") or ""
                if f"{page_key}=" in href:
                    href_pattern = urljoin(page.url, href)
                    break
        unique: dict[str, Need] = {}
        duplicates = 0
        self.emit("clear_needs")
        for i in range(1, num_pages + 1):
            if self.cancel.is_set():
                self.emit("info", message="دریافت نیازها متوقف شد.")
                break
            if i > 1:
                if not href_pattern or not page_key:
                    self.emit("info", message="ساختار صفحه‌بندی شناخته نشد؛ فقط صفحه اول خوانده شد.")
                    break
                dest = re.sub(r"(?<=" + re.escape(page_key) + r"=)\d+", str(i), href_pattern)
                page.goto(dest, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.locator("#aList").wait_for(state="attached", timeout=12000)
                except BrowserTimeout:
                    self.emit("info", message=f"صفحه {i} جدول معتبری برنگرداند؛ دریافت متوقف شد.")
                    break
                rows = parse_board(page.content(), page.url)
            else:
                rows = first
            new_count = 0
            for item in rows:
                if item.need_no in unique:
                    duplicates += 1
                else:
                    unique[item.need_no] = item
                    new_count += 1
            self.emit("progress", message=f"صفحه {i} از {num_pages} | {len(rows)} ردیف | {new_count} جدید")
            self.emit("needs", needs=list(unique.values()), expected=total_pages, duplicates=duplicates, pages=i)
            page.wait_for_timeout(350)
        self.emit("completed_refresh", count=len(unique), duplicates=duplicates, pages=num_pages)

    @staticmethod
    def _page_kind(page_html: str, url: str = "") -> str:
        """rows | empty («اطلاعاتی یافت نشد») | captcha | form (search form) | unknown.
        A captcha is an image / visible input that belongs to a captcha — NOT the bare word «captcha»,
        which is in every eproc page (hidden field checkCaptcha)."""
        if parse_search_results(page_html, url):
            return "rows"
        soup = BeautifulSoup(page_html or "", "html.parser")
        text = " ".join(soup.get_text(" ").split())
        for img in soup.find_all("img"):
            blob = " ".join(str(img.get(k, "")) for k in ("src", "id", "name", "class", "alt")).lower()
            if "captcha" in blob or "کپچا" in blob or "کد امنیتی" in blob:
                return "captcha"
        for inp in soup.find_all("input"):
            if (inp.get("type") or "text").lower() in ("hidden", "submit", "button", "image", "checkbox", "radio"):
                continue
            blob = f"{inp.get('name', '')} {inp.get('id', '')}".lower()
            if "captcha" in blob:
                return "captcha"
        if "کد امنیتی" in text or "تصویر امنیتی" in text or "کپچا" in text:
            return "captcha"
        if "یافت نشد" in western_digits(text):
            return "empty"
        if soup.find("input", attrs={"name": "purchaseNeedDto.needNo"}) is not None:
            return "form"
        return "unknown"

    @staticmethod
    def _banner_start(page_html: str):
        try:
            text = BeautifulSoup(page_html, "html.parser").select_one(".pagebanner")
            if text is None:
                return None
            m = re.search(r"نمایش\s*([\d,]+)\s*تا", western_digits(" ".join(text.get_text(" ").split())))
            return int(m.group(1).replace(",", "")) if m else None
        except Exception:
            return None

    def _rows_if_right_page(self, page, i: int, per_page: int):
        """(kind, rows): rows only if the page on screen really is result page `i`."""
        html_ = page.content()
        kind = self._page_kind(html_, page.url)
        if kind != "rows":
            return kind, None
        rows = parse_search_results(html_, page.url)
        start = self._banner_start(html_)
        if start is None or start == (i - 1) * per_page + 1:
            return kind, rows
        return "wrong_page", None

    def _resubmit_search(self, page):
        """What the user does by hand: open the search form and click «جستجو» again (same `since` as this run)."""
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
        page.locator('input[name="purchaseNeedDto.needNo"]').wait_for(state="attached", timeout=20000)
        with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            page.evaluate(self.JS_SUBMIT_SEARCH, getattr(self, "_search_since", "") or "")

    def _recover_page(self, page, dest, i: int, per_page: int, tries: int = 3):
        """The page is not what we asked for (typically «اطلاعاتی یافت نشد» right after a captcha):
        open the page address again; if that fails, search again and then open the address. None = not recovered."""
        for attempt in range(tries):
            if self.cancel.is_set() or self.shutdown.is_set():
                return None
            try:
                page.wait_for_timeout(1500 * (attempt + 1))
                if attempt == tries - 1 and (dest or i == 1):
                    self._resubmit_search(page)
                    if dest and i > 1:
                        page.goto(dest, wait_until="domcontentloaded", timeout=45000)
                elif dest:
                    page.goto(dest, wait_until="domcontentloaded", timeout=45000)
                kind, rows = self._rows_if_right_page(page, i, per_page)
            except Exception:
                continue
            if rows:
                return rows
            if kind in ("captcha", "unknown"):
                return None
        return None

    def _load_search_page(self, page, dest: str, i: int, per_page: int):
        """Open result page `i` in the visible tab (like a person). On a captcha: warn and wait for the user, then continue."""
        page.goto(dest, wait_until="domcontentloaded", timeout=45000)
        kind, rows = self._rows_if_right_page(page, i, per_page)
        if rows:
            return rows
        if kind in ("captcha", "unknown"):
            return self._wait_captcha(page, dest, i, per_page)
        rows = self._recover_page(page, dest, i, per_page)
        if rows:
            return rows
        kind = self._page_kind(page.content(), page.url)
        if kind in ("captcha", "unknown"):
            return self._wait_captcha(page, dest, i, per_page)
        return None

    def _wait_captcha(self, page, dest, i: int, per_page: int):
        """The site shows a captcha: bring the browser forward, tell the user, and wait until result page `i` is on screen.
        Once the captcha is solved the site usually shows «اطلاعاتی یافت نشد» or page 1 — the program then opens the
        page address itself (and searches again if needed), so the user does not have to click anything."""
        self.emit("captcha", message=f"سایت در صفحهٔ {i} کپچا خواست. آن را در مرورگر برنامه وارد کنید؛ بعد از وارد کردن، دریافت خودکار ادامه می‌یابد.")
        try:
            if self.hub is not None:
                self.hub.restore()
            page.bring_to_front()
        except Exception:
            pass
        t0 = time.time()
        recovers = 0
        while time.time() - t0 < CAPTCHA_WAIT_SECONDS:
            if self.cancel.is_set() or self.shutdown.is_set():
                break
            try:
                page.wait_for_timeout(1500)
                kind, rows = self._rows_if_right_page(page, i, per_page)
            except Exception:
                continue
            if rows:
                self.emit("captcha_done")
                return rows
            if kind in ("captcha", "unknown"):
                recovers = 0
                continue  # the user is still typing the captcha — do not touch the page
            if recovers < 3:  # captcha is gone but the wanted page is not shown: reopen it
                recovers += 1
                rows = self._recover_page(page, dest, i, per_page, tries=2 if recovers < 3 else 3)
                if rows:
                    self.emit("captcha_done")
                    return rows
        self.emit("captcha_done")
        return None

    JS_SUBMIT_SEARCH = """(since) => {
        const first = document.querySelector('input[name="purchaseNeedDto.needNo"]');
        if (!first || !first.form) return false;
        const f = first.form;
        const set = (n, v) => {
            let e = f.elements[n];
            if (!e) { e = document.createElement('input'); e.type = 'hidden'; e.name = n; f.appendChild(e); }
            e.value = v;
        };
        set('method', 'doSearch'); set('searchClicked', 'true'); set('checkCaptcha', 'true'); set('totalRecord', '0');
        const cur = f.elements['currentDate'] ? f.elements['currentDate'].value : '';
        if (f.elements['responseDateFrom'] && !f.elements['responseDateFrom'].value && cur) f.elements['responseDateFrom'].value = cur;
        if (since) set('needDateFrom', since);
        HTMLFormElement.prototype.submit.call(f);
        return true;
    }"""

    def _refresh_search(self, page_limit: int, since: str | None = None):
        """All open needs through «جستجوی پیشرفته» without filters (the board shows only the first ~600).
        `since` (Jalali yyyy/mm/dd): quick update — only needs announced from that date on; the list is not cleared."""
        self._ensure()
        page_limit = max(1, min(2000, page_limit)) if page_limit else 2000
        page = self.board_page
        self._search_since = since or ""
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            page.locator('input[name="purchaseNeedDto.needNo"]').wait_for(state="attached", timeout=20000)
        except BrowserTimeout as exc:
            raise RuntimeError("فرم جستجوی پیشرفته پیدا نشد؛ ورود یا نقش «تامین کننده» را بررسی کنید.") from exc
        with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            ok = page.evaluate(self.JS_SUBMIT_SEARCH, since or "")
            if not ok:
                raise RuntimeError("فرم جستجوی پیشرفته شناخته نشد.")
        page_html = page.content()
        first = parse_search_results(page_html, page.url)
        if not first and self._page_kind(page_html, page.url) in ("captcha", "unknown"):
            first = self._wait_captcha(page, None, 1, 30) or []
            page_html = page.content()
        if not first:
            if since:
                self.emit("quick_start")
                self.emit("completed_refresh", count=0, duplicates=0, pages=0)
                return
            raise RuntimeError("نتیجهٔ جستجوی پیشرفته ردیف قابل‌خواندن نداشت.")
        total_pages, page_key = find_pagination(page_html, len(first))
        num_pages = min(page_limit, total_pages)
        href_pattern = None
        if page_key:
            for link in page.locator("a[href]").all():
                href = link.get_attribute("href") or ""
                if f"{page_key}=" in href:
                    href_pattern = urljoin(page.url, href)
                    break
        unique: dict[str, Need] = {}
        duplicates = 0
        self.emit("quick_start" if since else "clear_needs")
        failed_pages = 0
        for i in range(1, num_pages + 1):
            if self.cancel.is_set():
                self.emit("info", message="دریافت نیازها متوقف شد.")
                break
            if i > 1:
                if not href_pattern or not page_key:
                    self.emit("info", message="ساختار صفحه‌بندی شناخته نشد؛ فقط صفحه اول خوانده شد.")
                    break
                dest = re.sub(r"(?<=" + re.escape(page_key) + r"=)\d+", str(i), href_pattern)
                rows = self._load_search_page(page, dest, i, len(first))
                if not rows:
                    failed_pages += 1
                    self.emit("info", message=f"صفحه {i} خوانده نشد؛ دریافت متوقف شد.")
                    break
            else:
                rows = first
            new_count = 0
            page_new = []
            for item in rows:
                if item.need_no in unique:
                    duplicates += 1
                else:
                    unique[item.need_no] = item
                    page_new.append(item)
                    new_count += 1
            self.emit("progress", message=f"صفحه {i} از {num_pages} | {len(rows)} ردیف | {new_count} جدید")
            # v0.9.10: only this page's new rows (the whole accumulated list used to be sent every time)
            self.emit("needs", needs=page_new, expected=total_pages, duplicates=duplicates, pages=i)
            page.wait_for_timeout(SEARCH_PAGE_DELAY_MS)
        self.emit("completed_refresh", count=len(unique), duplicates=duplicates, pages=num_pages)

    def _fetch_html(self, url: str):
        """(html, final_url) through the browser session's cookies without opening a tab; (None, None) if that fails
        or the answer does not look like the real page (login redirect, error page)."""
        try:
            resp = self.context.request.get(url, timeout=45000)
            if not resp.ok:
                return None, None
            text = resp.text()
            low = text.lower()
            if "<tr" not in low or "j_security_check" in low or 'type="password"' in low:
                return None, None
            return text, resp.url
        except Exception:
            return None, None

    def _detail(self, need: Need):
        """Read a need's detail page and emit it both as structured rows and as legacy text.

        Event payload: rows (list of field lists, in page order), attachments
        (list of file names, or None when the appendix could not be read) and
        error (non-empty only when the whole detail page failed).
        """
        page = None
        try:
            self._ensure()
            # v0.9: read through the session's request API — no tab is opened, so the visible browser never pops up
            page_html, page_url = self._fetch_html(need.detail_url)
            if page_html is None:
                page = self.context.new_page()
                page.goto(need.detail_url, wait_until="domcontentloaded", timeout=45000)
                page_html, page_url = page.content(), page.url
            info = parse_need_detail(page_html)
            soup = BeautifulSoup(page_html, "html.parser")
            for el in soup(["script", "style", "nav", "footer", "header"]):
                el.decompose()
            rows: list[list[str]] = []
            seen = set()
            for tr in soup.select("tr"):
                fields = [" ".join(td.stripped_strings) for td in tr.find_all(["th", "td"], recursive=False)]
                fields = [v for v in fields if v]
                key = tuple(fields)
                if fields and len(" | ".join(fields)) < 800 and key not in seen:
                    seen.add(key)
                    rows.append(fields)
            attachments = None
            attach_error = ""
            appendix = parse_appendix_link(page_html, page_url)
            if info.get("attachment_count") == 0:
                attachments = []  # the site's button already says «(0)»; no need to open the list
            elif appendix:
                try:
                    html2, _u = self._fetch_html(appendix)
                    if html2 is None:
                        if page is None:
                            page = self.context.new_page()
                        page.goto(appendix, wait_until="domcontentloaded", timeout=45000)
                        html2 = page.content()
                    attachments = [a.file_name for a in parse_attachments(html2)]
                except Exception as exc:
                    attach_error = str(exc).splitlines()[0]
            else:
                attach_error = "لینک فهرست پیوست‌ها در صفحه جزئیات پیدا نشد"
            chunks = [" | ".join(r) for r in rows]
            if attachments is not None:
                chunks.append("پیوست‌ها: " + ("، ".join(attachments) if attachments else "فایلی شناسایی نشد"))
            elif attach_error:
                chunks.append("فهرست پیوست‌ها قابل دریافت نبود: " + attach_error)
            content = "\n".join(chunks)[:9000]
            self.emit(
                "detail", need_no=need.need_no,
                content=content or "اطلاعات تکمیلی قابل خواندن نبود.",
                rows=rows[:80], info=info, attachments=attachments, attach_error=attach_error, error="",
            )
        except Exception as exc:
            message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            self.emit(
                "detail", need_no=need.need_no, content="خطا در دریافت جزئیات: " + message,
                rows=[], attachments=None, attach_error="", error=message,
            )
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def _make_background_page(self):
        """Create a hidden browser context that reuses the authenticated session.

        This avoids visible tab switching during download. If it fails, callers can
        fall back to the already-open visible context.
        """
        storage = self.context.storage_state()
        kwargs = {"channel": self.browser_channel} if self.browser_channel else {}
        browser = self.pl.chromium.launch(headless=True, **kwargs)
        ctx = browser.new_context(
            accept_downloads=True,
            storage_state=storage,
            locale="fa-IR",
            viewport={"width": 1360, "height": 900},
        )
        page = ctx.new_page()
        return browser, ctx, page

    def _download_one(self, page, appendix_url: str, need: Need, folder: Path, manifest: dict, attachment, results: dict, ni: int, total_needs: int, fi: int, total_files: int):
        fid = attachment.file_id
        if not page.locator(f'input[type="radio"][id="r{fid}"]').count():
            page.goto(appendix_url, wait_until="domcontentloaded", timeout=45000)
        page.locator(f'input[type="radio"][id="r{fid}"]').click(timeout=12000)
        selected_id = page.locator('input[name="fileId"]').input_value()
        permission = page.locator('input[name="viewBySupplier"]').input_value()
        if selected_id != fid or permission != "2":
            results["restricted"] += 1
            self.emit("info", message=f"دسترسی نمایش فایل {fid} توسط سایت تأیید نشد.")
            return False

        self.emit("progress", message=(
            f"نیاز {ni}/{total_needs} | پیوست {fi}/{total_files}: {attachment.file_name}"
        ))
        file_url = urljoin(page.url, f"appendixDocument.do?method=viewFile&fileId={fid}")
        page.evaluate(
            """url => {
                document.querySelectorAll('[data-setadiran-link]').forEach(e=>e.remove());
                const a = document.createElement('a');
                a.href = url;
                a.target = '_self';
                a.textContent = 'download';
                a.setAttribute('data-setadiran-link', '1');
                document.body.appendChild(a);
            }""",
            file_url,
        )
        with page.expect_download(timeout=25000) as download_info:
            page.locator('[data-setadiran-link="1"]').click(timeout=10000)
        download = download_info.value
        save_to = target_path(folder, attachment.file_name, fid)
        download.save_as(str(save_to))
        validate_download(save_to)
        record_download(folder, manifest, fid, attachment.file_name, save_to.name)
        results["downloaded"] += 1
        self.emit("info", message=f"دانلود شد: {need.need_no}/{save_to.name}")
        return True

    def _download(self, needs: list[Need], directory: Path):
        self._ensure()
        if not needs:
            raise RuntimeError("هیچ نیازی انتخاب نشده است.")

        directory.mkdir(parents=True, exist_ok=True)
        results = {"downloaded": 0, "skipped": 0, "failed": 0, "restricted": 0, "no_files": 0}
        need_folders: list[str] = []

        # Try a hidden download browser first so the user does not see navigation.
        hidden_browser = hidden_context = hidden_page = None
        visible_fallback = False
        try:
            hidden_browser, hidden_context, hidden_page = self._make_background_page()
            self.emit("info", message="دانلودها در پس‌زمینه آماده شد.")
        except Exception:
            visible_fallback = True
            self.emit("info", message="حالت دانلود پس‌زمینه در دسترس نبود؛ دانلود با مرورگر باز انجام می‌شود.")

        work_page = None
        if visible_fallback:
            work_page = self.context.new_page()
        page = hidden_page or work_page

        try:
            for ni, need in enumerate(needs, start=1):
                if self.cancel.is_set():
                    self.emit("info", message="دانلود به درخواست شما متوقف شد.")
                    break
                self.emit("status", need_no=need.need_no, status="در حال بررسی پیوست‌ها")
                self.emit("progress", message=f"بررسی نیاز {ni}/{len(needs)}: {need.need_no}")
                try:
                    page.goto(need.detail_url, wait_until="domcontentloaded", timeout=45000)
                    appendix_url = parse_appendix_link(page.content(), page.url)
                    if not appendix_url:
                        raise ValueError("لینک فهرست پیوست‌ها در جزئیات این نیاز یافت نشد")
                    page.goto(appendix_url, wait_until="domcontentloaded", timeout=45000)
                    attachments = parse_attachments(page.content())
                    if not attachments:
                        results["no_files"] += 1
                        self.emit("status", need_no=need.need_no, status="بدون پیوست")
                        continue
                    folder = need_folder(directory, need.need_no)
                    need_folders.append(str(folder))
                    manifest = load_manifest(folder)
                    record_attachment_total(folder, len(attachments))
                    self.emit("info", message=f"{need.need_no}: {len(attachments)} پیوست پیدا شد.")
                    fail_this_need = 0

                    for fi, attachment in enumerate(attachments, start=1):
                        if self.cancel.is_set():
                            break
                        fid = attachment.file_id
                        if is_downloaded(folder, manifest, fid):
                            results["skipped"] += 1
                            continue
                        try:
                            self._download_one(page, appendix_url, need, folder, manifest, attachment, results, ni, len(needs), fi, len(attachments))
                        except Exception as exc:
                            results["failed"] += 1
                            fail_this_need += 1
                            self.emit("info", message=f"ناموفق: {need.need_no}/{attachment.file_name} — {str(exc).splitlines()[0][:130]}")
                        page.wait_for_timeout(350)
                    self.emit("status", need_no=need.need_no, status="تکمیل با خطا" if fail_this_need else "بررسی/دانلود تکمیل")
                except Exception as exc:
                    results["failed"] += 1
                    self.emit("status", need_no=need.need_no, status="خطا")
                    self.emit("info", message=f"نیاز {need.need_no}: {str(exc).splitlines()[0][:170]}")

            self.emit("completed_download", results=results, directory=str(directory),
                      folder=need_folders[0] if len(needs) == 1 and need_folders else "")
        finally:
            try:
                if hidden_page:
                    hidden_page.close()
            except Exception:
                pass
            try:
                if hidden_context:
                    hidden_context.close()
            except Exception:
                pass
            try:
                if hidden_browser:
                    hidden_browser.close()
            except Exception:
                pass
            try:
                if work_page:
                    work_page.close()
            except Exception:
                pass
