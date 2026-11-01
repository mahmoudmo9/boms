"""Full-width card with a need's details (used under list rows and inside the case window)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from parser import Need
from ui_kit import C, FlowRow, button, fa, hline, label, make_icon, need_group, rtl, strip_english_gloss


class AttachChip(QLabel):
    """v0.9.14: attachment chip — click selects it (enables «پیش‌نمایش»), double-click opens the preview."""
    clicked = Signal(object)
    doubleClicked = Signal(object)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self)
        super().mouseDoubleClickEvent(event)


class DetailCard(QWidget):
    """Full-width card shown directly under a need's row."""

    def __init__(self, ui, need: Need, payload: dict | None, embedded: bool = False, part: str | None = None):
        """part: None = everything (inline card / case window); 'info' or 'files' = one tab of the side panel."""
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.setAutoFillBackground(False)
        self.ui = ui
        self._need_no = need.need_no
        self._attach_names: list[str] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*((0, 0, 0, 0) if embedded else (14, 6, 10, 12)))
        card = QFrame()
        card.setObjectName("detailCard" if part is None else "detailPlain")
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(*((18, 14, 18, 14) if part is None else (2, 6, 2, 6)))
        v.setSpacing(10)

        info = (payload or {}).get("info") or {}
        self._chips: list[AttachChip] = []
        self._selected: AttachChip | None = None
        self.b_preview = None
        self.b_rm = None
        self.b_open = None
        if part is None:
            title = label(fa(info.get("description")) or need.description or "بدون شرح", "detailTitle", wrap=True)
            title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(title)

            chips = [self._chip(f"شماره نیاز  {need.need_no}", accent=True)]
            if need.organization:
                chips.append(self._chip(need.organization))
            if need.province:
                chips.append(self._chip(f"استان {need.province}"))
            if need.category:
                chips.append(self._chip(need.category))
            if need_group(need):
                chips.append(self._chip(need_group(need)))
            remaining = ui.remaining_for(need.need_no) if hasattr(ui, "remaining_for") else need.response_deadline
            if remaining:
                chips.append(self._chip(f"مهلت: {remaining}"))
            v.addWidget(FlowRow(chips))
            v.addWidget(hline())

        want_info = part in (None, "info")
        want_files = part in (None, "files")
        # v0.9.18: when the site data is missing/unavailable, the files tab still lists what is downloaded on this computer
        offline = []
        if want_files and hasattr(ui, "downloaded_names") and (payload is None or payload.get("error") or payload.get("attachments") is None):
            offline = ui.downloaded_names(need.need_no)
        if payload is None:
            v.addWidget(label("در حال دریافت اطلاعات تکمیلی از سایت…", "notice", wrap=True))
            if offline:
                self._add_attachments(v, {"attachments": offline})
        elif payload.get("error"):
            msg = payload["error"]
            if "ابتدا" in msg or "مرورگر" in msg:
                text = "برای دیدن جزئیات کامل، ابتدا از بالای برنامه به ستاد وصل شوید."
            else:
                text = "دریافت جزئیات ناموفق بود: " + msg
            v.addWidget(label(text, "noticeError", wrap=True))
            if offline:
                v.addWidget(label("اطلاعات سایت در دسترس نیست؛ فایل‌های دانلودشده نمایش داده می‌شوند.", "muted", wrap=True))
                self._add_attachments(v, {"attachments": offline})
        elif info.get("found"):
            if want_info:
                self._add_need_form(v, info)
            if want_files:
                self._add_attachments(v, dict(payload, attachments=offline) if offline else payload)
        else:
            if want_info:
                self._add_rows(v, payload.get("rows") or [], payload.get("content", ""))
            if want_files:
                self._add_attachments(v, dict(payload, attachments=offline) if offline else payload)
        if part == "info":
            v.addStretch(1)
            from PySide6.QtWidgets import QSizePolicy as _SP0
            self.setSizePolicy(_SP0.Ignored, _SP0.Preferred)
            return

        actions = QHBoxLayout()
        actions.setSpacing(8)
        if not embedded and hasattr(ui, "stage_of"):
            if ui.stage_of(need.need_no):
                case_btn = button("باز کردن پرونده", "folder", "primary")
                case_btn.clicked.connect(lambda: ui.open_case(need.need_no))
            else:
                case_btn = button("افزودن به ستاره‌دارها", "star", "primary")
                case_btn.clicked.connect(lambda: ui.toggle_star(need.need_no))
            actions.addWidget(case_btn)
        dl = button("دانلود پیوست‌های همین نیاز", "download", None if not embedded else "primary")
        dl.clicked.connect(lambda: ui.download_needs([need]))
        if payload is not None and (payload.get("attachments") == [] or info.get("attachment_count") == 0):
            dl.setEnabled(False)
            dl.setToolTip(rtl("طبق صفحه سایت، این نیاز پیوستی ندارد."))
        cp = button("کپی شماره نیاز", "copy")
        cp.clicked.connect(lambda: ui.copy_text(need.need_no, "شماره نیاز کپی شد."))
        actions.addWidget(dl)
        actions.addWidget(cp)
        if self._chips:                                   # v0.9.14: enabled once a downloaded attachment is selected
            self.b_preview = button("پیش‌نمایش", "eye")
            self.b_preview.setEnabled(False)
            self.b_preview.setToolTip(rtl("اول یکی از پیوست‌ها را انتخاب کنید."))
            self.b_preview.clicked.connect(self._open_preview)
            actions.insertWidget(actions.indexOf(cp), self.b_preview)      # v0.9.20: preview and «باز کردن پوشه» sit right after «دانلود»
        if self._chips and hasattr(ui, "delete_downloads"):          # v0.9.17: undo a download from the same place
            n_dl = len(ui.downloaded_files(need.need_no))
            self.b_open = button("باز کردن پوشه", "folder")
            self.b_open.setEnabled(n_dl > 0)
            self.b_open.setToolTip(rtl("پوشهٔ همین نیاز را در ویندوز باز می‌کند." if n_dl else "هنوز چیزی برای این نیاز دانلود نشده است."))
            self.b_open.clicked.connect(lambda: ui.open_download_folder(need.need_no))
            actions.insertWidget(actions.indexOf(self.b_preview) + 1, self.b_open)
            self.b_rm = button("حذف دانلودها", "trash", "danger")
            self.b_rm.setEnabled(n_dl > 0)
            self.b_rm.setToolTip(rtl("فایل‌هایی که برنامه برای این نیاز دانلود کرده از روی رایانه پاک می‌شود و وضعیت به «دانلود نشده» برمی‌گردد."
                                     if n_dl else "هنوز چیزی برای این نیاز دانلود نشده است."))
            self.b_rm.clicked.connect(lambda: ui.delete_downloads(need.need_no))
            actions.addWidget(self.b_rm)
        if payload is not None and payload.get("error"):
            again = button("تلاش دوباره", "retry")
            again.clicked.connect(lambda: ui.request_detail(need.need_no, force=True))
            actions.addWidget(again)
        if embedded:                 # narrow side panel: let the buttons wrap
            ws = [actions.itemAt(i).widget() for i in range(actions.count()) if actions.itemAt(i).widget()]
            v.addWidget(FlowRow(ws, spacing=8))
            if part == "files":
                v.addStretch(1)                           # v0.9.14: header, chips and buttons stay together (no stretched gaps)
            from PySide6.QtWidgets import QSizePolicy as _SP
            self.setSizePolicy(_SP.Ignored, _SP.Preferred)
            return
        actions.addStretch(1)
        if not embedded:
            close = button("بستن", "x", "ghost")
            close.clicked.connect(lambda: ui.collapse_need(need.need_no))
            actions.addWidget(close)
        v.addLayout(actions)

    def _local_path(self, name: str):
        fn = getattr(self.ui, "attachment_path", None)
        return fn(self._need_no, name) if fn else None

    def _select_chip(self, chip: AttachChip):
        for c in self._chips:
            c.setProperty("selected", c is chip)
            c.style().unpolish(c)
            c.style().polish(c)
        self._selected = chip
        local = self._local_path(chip.property("name")) is not None
        chip.setProperty("local", local)
        if self.b_preview is not None:
            self.b_preview.setEnabled(local)
            self.b_preview.setToolTip(rtl("باز کردن پیش‌نمایش سند انتخاب‌شده." if local
                                          else "این سند هنوز دانلود نشده؛ اول «دانلود پیوست‌های همین نیاز» را بزنید."))

    def _open_preview(self):
        if self._selected is None or not hasattr(self.ui, "open_preview"):
            return
        self.ui.open_preview(self._need_no, self._attach_names, self._selected.property("name"))

    @staticmethod
    def _chip(text: str, accent: bool = False) -> QLabel:
        chip = label(text, "chipAccent" if accent else "chip")
        chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return chip

    @staticmethod
    def _pairs_grid(pairs: list[tuple[str, str]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        for i, (k, val) in enumerate(pairs):
            r, c = divmod(i, 2)
            key = label(k, "detailKey", wrap=len(k) > 40)
            key.setAlignment(Qt.AlignLeading | Qt.AlignTop)
            value = label(val, "detailValue", wrap=True)
            value.setAlignment(Qt.AlignLeading | Qt.AlignTop)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(key, r, c * 2)
            grid.addWidget(value, r, c * 2 + 1)
        return grid

    def _add_need_form(self, v: QVBoxLayout, info: dict):
        """Render only the site's «جزئیات اطلاعات نیاز» form."""
        v.addWidget(label("جزئیات اطلاعات نیاز", "detailSection"))
        pairs = [(fa(k), fa(x)) for k, x in info.get("fields") or [] if fa(x)]
        if pairs:
            v.addLayout(self._pairs_grid(pairs))

        items = info.get("items") or {}
        headers = [fa(h) for h in items.get("headers") or []]
        rows = [[fa(c) for c in r] for r in items.get("rows") or []]
        if info.get("group") or rows:
            v.addWidget(hline())
            v.addWidget(label(fa(info.get("items_title")) or "اطلاعات کالاها / خدمات مورد نیاز", "detailSection"))
            if info.get("group"):
                v.addLayout(self._pairs_grid([(fa(info.get("group_label")) or "گروه", fa(info["group"]))]))
            if rows:
                v.addWidget(self._items_table(headers, rows))

        note = fa(info.get("buyer_note"))
        if note:
            v.addWidget(hline())
            v.addWidget(label("توضیحات خریدار", "detailSection"))
            # The site separates conditions with «/»; show them as a list (dates like 1405/08/05 stay intact).
            parts = [x.strip() for x in re.split(r"(?<!\d)/|/(?!\d)", note) if x.strip()]
            text = "\n".join("•  " + x for x in parts) if len(parts) >= 3 else note
            box = label(text, "noteBox", wrap=True)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(box)
        v.addWidget(hline())

    @staticmethod
    def _items_table(headers: list[str], rows: list[list[str]]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("itemsTable")
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        ncols = max([len(headers)] + [len(r) for r in rows])
        wide = {i for i, h in enumerate(headers) if "نام" in h or "شرح" in h}
        for c in range(ncols):
            grid.setColumnStretch(c, 3 if c in wide else 1)
        for c, h in enumerate(headers):
            cell = label(h, "th", wrap=True)
            cell.setAlignment(Qt.AlignCenter)
            grid.addWidget(cell, 0, c)
        for r, row in enumerate(rows, start=1):
            for c in range(ncols):
                text = row[c] if c < len(row) else ""
                cell = label(text, "td" if r % 2 else "tdAlt", wrap=True)
                cell.setAlignment((Qt.AlignLeading if c in wide else Qt.AlignCenter) | Qt.AlignVCenter)
                cell.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(cell, r, c)
        return frame

    def _add_rows(self, v: QVBoxLayout, rows: list[list[str]], content: str):
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        r = 0
        pairs: list[tuple[str, str]] = []

        def flush():
            nonlocal r, pairs
            for i in range(0, len(pairs), 2):
                for j, (k, val) in enumerate(pairs[i:i + 2]):
                    key = label(k, "detailKey", wrap=True)
                    key.setAlignment(Qt.AlignLeading | Qt.AlignTop)
                    value = label(val, "detailValue", wrap=True)
                    value.setAlignment(Qt.AlignLeading | Qt.AlignTop)
                    value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    grid.addWidget(key, r, j * 2)
                    grid.addWidget(value, r, j * 2 + 1)
                r += 1
            pairs = []

        shown = 0
        for fields in rows:
            fields = [fa(x) for x in fields if fa(x)]
            if not fields:
                continue
            if len(fields) % 2 == 0 and all(len(fields[i]) <= 60 for i in range(0, len(fields), 2)):
                for i in range(0, len(fields), 2):
                    pairs.append((strip_english_gloss(fields[i]), fields[i + 1]))
                    shown += 1
            elif len(fields) == 1 and len(fields[0]) <= 50:
                flush()
                grid.addWidget(label(strip_english_gloss(fields[0]), "detailSection"), r, 0, 1, 4)
                r += 1
            else:
                flush()
                text = "  ·  ".join(strip_english_gloss(x) if len(x) <= 60 else x for x in fields)
                value = label(text, "detailValue", wrap=True)
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(value, r, 0, 1, 4)
                r += 1
                shown += 1
        flush()
        if shown:
            v.addLayout(grid)
        elif content:
            text = label(fa(content), "detailValue", wrap=True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(text)
        else:
            v.addWidget(label("اطلاعات تکمیلی در صفحه جزئیات پیدا نشد.", "notice", wrap=True))

    def _add_attachments(self, v: QVBoxLayout, payload: dict):
        attachments = payload.get("attachments")
        if attachments is None and ((payload.get("info") or {}).get("attachment_count") == 0):
            attachments = []
        row = QHBoxLayout()
        row.setSpacing(8)
        icon_lab = QLabel()
        icon_lab.setPixmap(make_icon("paperclip", C["primary"], 16).pixmap(16, 16))
        row.addWidget(icon_lab, 0, Qt.AlignVCenter)
        if attachments:
            row.addWidget(label(f"پیوست‌ها ({len(attachments)})", "detailSection"), 0, Qt.AlignVCenter)
            row.addStretch(1)
            v.addLayout(row)
            items = []
            for name in attachments:
                chip = AttachChip(name)
                chip.setObjectName("attach")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setProperty("name", name)
                chip.setProperty("local", self._local_path(name) is not None)
                chip.setToolTip(rtl("برای پیش‌نمایش کلیک کنید؛ دابل‌کلیک پنجرهٔ پیش‌نمایش را باز می‌کند."
                                    if chip.property("local") else "این سند هنوز دانلود نشده است."))
                chip.clicked.connect(self._select_chip)
                chip.doubleClicked.connect(lambda c: (self._select_chip(c), self._open_preview()))
                items.append(chip)
                self._chips.append(chip)
            self._attach_names = list(attachments)
            v.addWidget(FlowRow(items, spacing=6))
        else:
            if attachments is not None:
                msg = "این نیاز پیوستی ندارد."
            elif payload.get("attach_error"):
                msg = "فهرست پیوست‌ها خوانده نشد: " + payload["attach_error"]
            else:
                msg = "فهرست پیوست‌ها در دسترس نیست."
            row.addWidget(label(msg, "muted", wrap=True), 1)
            v.addLayout(row)


