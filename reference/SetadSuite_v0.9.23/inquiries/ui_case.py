"""Case window (پرونده نیاز): review → RFQs → final choice & pricing → submission & result."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

import jalali
import pipeline as P
import proforma
from ui_board import deadline_pill
from ui_detail import DetailCard
from ui_kit import (
    C, FlowRow, button, card_frame, clear_layout, label, make_icon, pill, resource_dir, rtl, tint,
)
from ui_suppliers import SupplierDialog


def scroll_wrap(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(widget)
    return sa


def selected_row(table: QTableWidget) -> int:
    rows = table.selectionModel().selectedRows()
    if rows:
        return rows[0].row()
    if table.currentRow() >= 0:
        return table.currentRow()
    return 0 if table.rowCount() == 1 else -1


def ro_item(text, align=None, data=None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    if align is not None:
        it.setTextAlignment(align)
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


def make_table(headers: list[str], widths: list[int], stretch: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(38)
    for i, w in enumerate(widths):
        t.horizontalHeader().resizeSection(i, w)
    if stretch is not None:
        t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def amount_edit(value: float | int | None = None, placeholder: str = "") -> QLineEdit:
    ed = QLineEdit(P.money(value) if value else "")
    ed.setLayoutDirection(Qt.LeftToRight)
    ed.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
    ed.setPlaceholderText(placeholder)

    def reformat():
        v = P.parse_amount(ed.text())
        ed.setText(P.money(v) if v is not None else "")
    ed.editingFinished.connect(reformat)
    return ed


# ---------------------------------------------------------------- quote dialog
class QuoteDialog(QDialog):
    def __init__(self, parent, need_folder: Path, supplier: str, items: list[P.Item], data: dict, required_valid: str):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle(f"پاسخ {supplier}")
        self.resize(820, 560)
        self.items = items
        self.folder = need_folder
        self.supplier = supplier
        self.files: list[str] = list(data.get("files") or [])
        v = QVBoxLayout(self)
        v.addWidget(label(f"قیمت‌های اعلام‌شده توسط «{supplier}» (ریال، بدون ارزش افزوده)", "sectionTitle"))
        self.table = make_table(["شرح", "تعداد", "واحد", "فی (ریال)", "مبلغ (ریال)"], [330, 80, 90, 150, 150], stretch=0)
        prices = data.get("prices") or []
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            self.table.setItem(i, 0, ro_item(it.name))
            self.table.setItem(i, 1, ro_item(P._qty(it.qty), Qt.AlignCenter))
            self.table.setItem(i, 2, ro_item(it.unit, Qt.AlignCenter))
            price = prices[i] if i < len(prices) else None
            cell = QTableWidgetItem(P.money(price) if price else "")
            cell.setTextAlignment(Qt.AlignCenter)
            cell.setBackground(QColor(C["primary_soft_2"]))
            self.table.setItem(i, 3, cell)
            self.table.setItem(i, 4, ro_item("", Qt.AlignCenter))
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.itemChanged.connect(self._recalc)
        if items:
            self.table.setCurrentCell(0, 3)
        v.addWidget(self.table, 1)
        self.total = label("", "detailSection")
        v.addWidget(self.total)
        f = QFormLayout()
        self.delivery = QSpinBox()
        self.delivery.setRange(0, 365)
        self.delivery.setSuffix(" روز")
        self.delivery.setValue(int(data.get("delivery_days") or 0))
        self.valid = QLineEdit(data.get("valid_until") or required_valid or jalali.add_days(jalali.today(), 30))
        self.valid.setPlaceholderText("1405/08/30")
        self.valid.setMaximumWidth(160)
        self.note = QPlainTextEdit(data.get("note", ""))
        self.note.setMaximumHeight(70)
        f.addRow("زمان تحویل تأمین‌کننده:", self.delivery)
        f.addRow("اعتبار قیمت تا:", self.valid)
        if required_valid:
            f.addRow("", label(f"خریدار اعتبار قیمت را حداقل تا {required_valid} خواسته است.", "muted"))
        f.addRow("یادداشت:", self.note)
        files_row = QHBoxLayout()
        self.files_label = label("", "muted", wrap=True)
        attach = button("پیوست پیش‌فاکتور تأمین‌کننده…", "paperclip")
        attach.clicked.connect(self._attach)
        files_row.addWidget(attach)
        files_row.addWidget(self.files_label, 1)
        f.addRow("فایل:", files_row)
        v.addLayout(f)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("ذخیره پاسخ")
        box.button(QDialogButtonBox.Cancel).setText("انصراف")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self._recalc()
        self._show_files()

    def _prices(self) -> list[int | None]:
        return [P.parse_amount(self.table.item(i, 3).text()) for i in range(len(self.items))]

    def _recalc(self, *_):
        self.table.blockSignals(True)
        total = 0
        complete = True
        for i, (it, p) in enumerate(zip(self.items, self._prices())):
            self.table.item(i, 4).setText(P.money(p * it.qty) if p else "")
            if p:
                self.table.item(i, 3).setText(P.money(p))
                total += p * it.qty
            else:
                complete = False
        self.table.blockSignals(False)
        self.total.setText(rtl(f"جمع: {P.money(total)} ریال" + ("" if complete else "  (قیمت بعضی اقلام وارد نشده)")))

    def _attach(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل تأمین‌کننده", str(Path.home()))
        if not path:
            return
        dest_dir = self.folder / "استعلام‌ها"
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in self.supplier)
        dest = dest_dir / f"{safe} - {Path(path).name}"
        shutil.copy2(path, dest)
        self.files.append(str(dest))
        self._show_files()

    def _show_files(self):
        self.files_label.setText(rtl("، ".join(Path(f).name for f in self.files) or "فایلی پیوست نشده"))

    def value(self) -> dict:
        return {"prices": self._prices(), "delivery_days": self.delivery.value() or None,
                "valid_until": self.valid.text().strip(), "note": self.note.toPlainText().strip(), "files": self.files}


# ---------------------------------------------------------------- the window
class CaseWindow(QDialog):
    def __init__(self, ui, need_no: str):
        super().__init__(None)
        self.ui = ui
        self.store = ui.store
        self.need_no = need_no
        self.setWindowTitle(f"پرونده نیاز {need_no}")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setObjectName("root")
        self.resize(1320, 880)
        self._loading = False
        self.note_timer = QTimer(self, singleShot=True, interval=700)
        self.note_timer.timeout.connect(self._save_note)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        self.header = card_frame()
        self.header_layout = QVBoxLayout(self.header)
        self.header_layout.setContentsMargins(18, 14, 18, 12)
        root.addWidget(self.header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("caseTabs")
        root.addWidget(self.tabs, 1)

        self.review_tab = QWidget()
        self.rfq_tab = QWidget()
        self.final_tab = QWidget()
        self.submit_tab = QWidget()
        self.tabs.addTab(self.review_tab, make_icon("search"), "۱. جزئیات و بررسی")
        self.tabs.addTab(self.rfq_tab, make_icon("send"), "۲. استعلام از تأمین‌کنندگان")
        self.tabs.addTab(self.final_tab, make_icon("calc"), "۳. انتخاب نهایی و قیمت‌گذاری")
        self.tabs.addTab(self.submit_tab, make_icon("check"), "۴. ارسال پاسخ و نتیجه")
        self._build_review()
        self._build_rfq()
        self._build_final()
        self._build_submit()
        self.reload()
        stage = self.case["stage"] if self.case else "starred"
        self.tabs.setCurrentIndex({"rfq_ready": 1, "rfq": 1, "final": 2, "submitted": 3, "result": 3}.get(stage, 0))

    # ------------------------------------------------------------ data helpers
    @property
    def data(self) -> dict:
        return (self.case or {}).get("data", {})

    def _update(self, **changes):
        self.store.update_case_data(self.need_no, **changes)
        self.case = self.store.get_case(self.need_no)

    def _move(self, stage: str, note: str | None = None):
        self.ui.move_stage(self.need_no, stage, note=note)

    def _advance_to(self, stage: str):
        """Move forward to `stage` only if the case is currently behind it."""
        cur = self.case["stage"] if self.case else None
        if cur in P.STAGE_KEYS and P.STAGE_KEYS.index(cur) < P.STAGE_KEYS.index(stage):
            self._move(stage)

    def folder(self) -> Path:
        return self.ui.need_folder(self.need_no)

    # ------------------------------------------------------------ reload all
    def reload(self):
        self._loading = True
        self.need = self.ui.need_obj(self.need_no)
        self.case = self.store.get_case(self.need_no)
        self.payload = self.ui.detail_payload(self.need_no)
        self.info = (self.payload or {}).get("info") or {}
        self.items = P.items_of(self.need, self.info)
        self.settings = self.store.settings()
        self._fill_header()
        self._fill_review()
        self._fill_rfq()
        self._fill_final()
        self._fill_submit()
        self._loading = False

    def on_detail(self):
        self.reload()

    # ------------------------------------------------------------ header & stepper
    def _fill_header(self):
        clear_layout(self.header_layout)
        need = self.need
        top = QHBoxLayout()
        title = label(need.description, "detailTitle", wrap=True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(title, 1)
        stage = self.case["stage"] if self.case else None
        if stage:
            color = P.STAGE_COLOR[stage]
            top.addWidget(pill(P.STAGE_TITLE[stage], color, tint(color, 0.14)), 0, Qt.AlignTop)
        self.header_layout.addLayout(top)

        chips = [label(f"شماره نیاز  {need.need_no}", "chipAccent"), label(need.organization, "chip")]
        if need.province:
            chips.append(label(f"استان {need.province}", "chip"))
        grp = need.goods_group or need.service_group
        if grp:
            chips.append(label(grp, "chip"))
        rem = self.ui.remaining_for(self.need_no)
        if rem and (stage in P.OPEN_STAGES or stage is None):
            chips.append(deadline_pill(rem, self.ui.remaining_hours_for(self.need_no)))
        for w in chips:
            w.setTextInteractionFlags(Qt.TextSelectableByMouse) if isinstance(w, QLabel) else None
        self.header_layout.addWidget(FlowRow(chips))

        bar = QHBoxLayout()
        bar.setSpacing(4)
        if stage == P.REJECTED:
            d = self.data
            msg = f"صرف‌نظر شده — {d.get('reject_reason', '')}" + (f": {d['reject_note']}" if d.get("reject_note") else "")
            bar.addWidget(label(msg, "noticeError", wrap=True), 1)
            restore = button("بازگرداندن به تابلو", "retry", "primary")
            restore.clicked.connect(lambda: self.ui.restore_need(self.need_no))
            bar.addWidget(restore)
        else:
            for i, (key, ttl, color) in enumerate(P.STAGES):
                b = QPushButton(f"{i + 1}. {ttl}")
                b.setCursor(Qt.PointingHandCursor)
                b.setProperty("kind", "step")
                cur_idx = P.STAGE_KEYS.index(stage) if stage in P.STAGE_KEYS else -1
                if key == stage:
                    b.setStyleSheet(f"QPushButton {{ background:{color}; color:white; border:1px solid {color}; font-weight:700; }}")
                elif i < cur_idx:
                    b.setStyleSheet(f"QPushButton {{ background:{tint(color, 0.12)}; color:{color}; border:1px solid {tint(color, 0.3)}; }}")
                b.setToolTip(rtl("انتقال پرونده به این مرحله"))
                b.clicked.connect(lambda _=False, k=key: self._move(k))
                bar.addWidget(b)
            bar.addStretch(1)
            rej = button("صرف‌نظر / حذف", "archive", "danger")
            rej.clicked.connect(lambda: self.ui.remove_from_funnel(self.need_no))
            bar.addWidget(rej)
        fold = button("پوشه", "folder")
        fold.setToolTip(rtl("باز کردن پوشه این نیاز"))
        fold.clicked.connect(lambda: proforma.open_path(self.folder()))
        bar.addWidget(fold)
        self.header_layout.addLayout(bar)

    # ------------------------------------------------------------ tab 1: review
    def _build_review(self):
        lay = QHBoxLayout(self.review_tab)
        lay.setContentsMargins(0, 8, 0, 0)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split)
        self.detail_holder = QVBoxLayout()
        dw = QWidget()
        dw.setLayout(self.detail_holder)
        split.addWidget(scroll_wrap(dw))

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(4, 0, 4, 0)
        sv.setSpacing(10)
        box = card_frame()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.addWidget(label("نکات و هشدارها", "detailSection"))
        self.warn_box = QVBoxLayout()
        bv.addLayout(self.warn_box)
        sv.addWidget(box)

        box = card_frame()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.addWidget(label("چک‌لیست بررسی", "detailSection"))
        self.check_box = QVBoxLayout()
        bv.addLayout(self.check_box)
        sv.addWidget(box)

        box = card_frame()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.addWidget(label("یادداشت", "detailSection"))
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText(rtl("نکات بررسی، تماس‌ها، سؤال‌ها…"))
        self.note.setMinimumHeight(90)
        self.note.textChanged.connect(lambda: None if self._loading else self.note_timer.start())
        bv.addWidget(self.note)
        sv.addWidget(box)

        box = card_frame()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        hb = QHBoxLayout()
        hb.addWidget(label("فایل‌های ذخیره‌شده", "detailSection"))
        hb.addStretch(1)
        dl = button("دانلود پیوست‌ها", "download", "ghost")
        dl.clicked.connect(lambda: self.need and self.ui.download_needs([self.need]))
        hb.addWidget(dl)
        bv.addLayout(hb)
        self.files = QListWidget()
        self.files.setMaximumHeight(130)
        self.files.itemDoubleClicked.connect(lambda it: proforma.open_path(Path(it.data(Qt.UserRole))))
        bv.addWidget(self.files)
        sv.addWidget(box)

        self.btn_to_rfq = button("تأیید برای استعلام", "arrow_next", "primary")
        self.btn_to_rfq.clicked.connect(lambda: (self._move("rfq_ready"), self.tabs.setCurrentIndex(1)))
        sv.addWidget(self.btn_to_rfq)
        sv.addStretch(1)
        split.addWidget(scroll_wrap(side))
        split.setSizes([820, 440])

    def _fill_review(self):
        clear_layout(self.detail_holder)
        if self.payload:
            self.detail_holder.addWidget(DetailCard(self.ui, self.need, self.payload, embedded=True))
        else:
            pending = self.ui.detail_pending_for(self.need_no)
            msg = "در حال دریافت جزئیات از سایت…" if pending else "جزئیات این نیاز هنوز دریافت نشده است."
            self.detail_holder.addWidget(label(msg, "notice", wrap=True))
            if not pending:
                get = button("دریافت جزئیات از سایت", "download", "primary")
                get.clicked.connect(lambda: (self.ui.request_detail(self.need_no), self.reload()))
                self.detail_holder.addWidget(get, 0, Qt.AlignLeading)
        self.detail_holder.addStretch(1)

        clear_layout(self.warn_box)
        notes = []
        kw = self.ui.warnings_for(self.need_no)
        if kw:
            notes.append(("danger", "شرط‌های هشدار در متن نیاز: " + "، ".join(kw)))
        months = P.payment_months(self.info.get("buyer_note", "")) if self.info else None
        if months is not None:
            notes.append(("info", "شرایط پرداخت خریدار: " + ("نقدی" if months == 0 else f"تسویه {months} ماهه")))
        rv = P.required_validity(self.info)
        if rv:
            notes.append(("info", f"اعتبار قیمت باید حداقل تا {rv} باشد."))
        dates = [it.need_date for it in self.items if it.need_date]
        if dates:
            notes.append(("info", "تاریخ نیاز خریدار: " + "، ".join(sorted(set(dates)))))
        cnt = self.info.get("attachment_count") if self.info else None
        if cnt is not None:
            notes.append(("info", f"تعداد پیوست‌های سایت: {cnt}"))
        if not self.payload:
            notes.append(("info", "پس از دریافت جزئیات، نکات بیشتری اینجا نمایش داده می‌شود."))
        for kind, text in notes:
            self.warn_box.addWidget(label(text, "noticeError" if kind == "danger" else "notice", wrap=True))

        clear_layout(self.check_box)
        state = self.data.get("checklist") or {}
        if isinstance(state, list):
            state = {}
        items = self.settings["checklist"]
        for text in items:
            cb = QCheckBox(text)
            cb.setChecked(bool(state.get(text)))
            cb.toggled.connect(self._save_checklist)
            self.check_box.addWidget(cb)
        self._checks = [self.check_box.itemAt(i).widget() for i in range(self.check_box.count())]

        if self.note.toPlainText() != self.data.get("note", ""):
            self.note.setPlainText(self.data.get("note", ""))

        self.files.clear()
        folder = self.ui.output_dir / self.need_no
        if folder.exists():
            for f in sorted(folder.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    it = QListWidgetItem(make_icon("file"), str(f.relative_to(folder)))
                    it.setData(Qt.UserRole, str(f))
                    self.files.addItem(it)
        if not self.files.count():
            self.files.addItem(QListWidgetItem(rtl("هنوز فایلی ذخیره نشده")))
        stage = self.case["stage"] if self.case else None
        self.btn_to_rfq.setVisible(stage in ("starred", "review"))

    def _save_checklist(self, *_):
        if self._loading or not self.case:
            return
        self._update(checklist={cb.text(): cb.isChecked() for cb in self._checks})
        self.ui.refresh_views(board_only=True)

    def _save_note(self):
        if self.case:
            self._update(note=self.note.toPlainText())

    # ------------------------------------------------------------ tab 2: RFQs
    def _build_rfq(self):
        v = QVBoxLayout(self.rfq_tab)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)
        add_card = card_frame()
        av = QVBoxLayout(add_card)
        av.setContentsMargins(16, 12, 16, 12)
        row = QHBoxLayout()
        row.addWidget(label("افزودن تأمین‌کننده به استعلام:", "detailSection"))
        self.sup_combo = QComboBox()
        self.sup_combo.setEditable(True)
        self.sup_combo.setInsertPolicy(QComboBox.NoInsert)
        self.sup_combo.setMinimumWidth(320)
        self.sup_combo.lineEdit().setPlaceholderText(rtl("نام یا تلفن را تایپ کنید…"))
        comp = QCompleter(self.sup_combo.model(), self.sup_combo)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.sup_combo.setCompleter(comp)
        row.addWidget(self.sup_combo)
        add = button("افزودن", "plus", "primary")
        add.clicked.connect(self._add_selected_supplier)
        new = button("تأمین‌کننده جدید…", "users")
        new.clicked.connect(self._new_supplier)
        row.addWidget(add)
        row.addWidget(new)
        row.addStretch(1)
        av.addLayout(row)
        self.suggest_row = QHBoxLayout()
        av.addLayout(self.suggest_row)
        v.addWidget(add_card)

        split = QSplitter(Qt.Horizontal)
        left = card_frame()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 12, 14, 12)
        lv.addWidget(label("استعلام‌ها", "detailSection"))
        self.rfq_table = make_table(["تأمین‌کننده", "تلفن", "وضعیت", "ارسال", "جمع قیمت (ریال)", "تحویل", "اعتبار تا", "هشدار"],
                                    [165, 112, 92, 88, 128, 62, 88, 160], stretch=7)
        self.rfq_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rfq_table.doubleClicked.connect(lambda *_: self._record_quote())
        lv.addWidget(self.rfq_table, 1)
        btns = QHBoxLayout()
        b1 = button("کپی متن و ثبت ارسال", "send", "primary")
        b1.clicked.connect(self._copy_and_mark_sent)
        b2 = button("ثبت پاسخ / قیمت", "edit", "primary")
        b2.clicked.connect(self._record_quote)
        b3 = button("جواب نداد", None)
        b3.clicked.connect(lambda: self._set_rfq_status("no_answer"))
        b4 = button("موجود ندارد", None)
        b4.clicked.connect(lambda: self._set_rfq_status("unavailable"))
        b5 = button("حذف", "trash", "danger")
        b5.clicked.connect(self._delete_rfq)
        for b in (b1, b2, b3, b4):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(b5)
        lv.addLayout(btns)
        self.rfq_hint = label("", "muted", wrap=True)
        lv.addWidget(self.rfq_hint)
        split.addWidget(left)

        right = card_frame()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        hb = QHBoxLayout()
        hb.addWidget(label("متن استعلام", "detailSection"))
        hb.addStretch(1)
        regen = button("ساخت دوباره", "retry", "ghost")
        regen.clicked.connect(lambda: self.rfq_text.setPlainText(self._default_rfq_text()))
        copy = button("کپی", "copy", "ghost")
        copy.clicked.connect(lambda: self.ui.copy_text(self.rfq_text.toPlainText(), "متن استعلام کپی شد."))
        hb.addWidget(regen)
        hb.addWidget(copy)
        rv.addLayout(hb)
        self.rfq_text = QPlainTextEdit()
        self.rfq_text.textChanged.connect(lambda: None if self._loading else self._update(rfq_text=self.rfq_text.toPlainText()))
        rv.addWidget(self.rfq_text, 1)
        rv.addWidget(label("متن از جدول کالاهای همین نیاز ساخته شده؛ می‌توانید ویرایشش کنید. برای واتساپ، بله یا ایمیل کپی کنید.", "muted", wrap=True))
        split.addWidget(right)
        split.setSizes([900, 380])
        v.addWidget(split, 1)
        self.btn_to_final = button("رفتن به انتخاب نهایی و قیمت‌گذاری", "arrow_next", "primary")
        self.btn_to_final.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        v.addWidget(self.btn_to_final, 0, Qt.AlignLeading)

    def _default_rfq_text(self) -> str:
        hours = self.ui.remaining_hours_for(self.need_no)
        reply_by = ""
        if hours and hours > 30:
            reply_by = jalali.from_date(jalali.datetime.fromtimestamp(time.time() + (hours - 24) * 3600))
        return P.rfq_text(self.need, self.info, self.settings["seller_name"], reply_by=reply_by,
                          validity=P.required_validity(self.info))

    def _fill_rfq(self):
        self.sup_combo.blockSignals(True)
        self.sup_combo.clear()
        self._suppliers = self.store.suppliers()
        for s in self._suppliers:
            self.sup_combo.addItem(s["name"] + (f"  —  {s['phone']}" if s["phone"] else ""), s["id"])
        self.sup_combo.setCurrentIndex(-1)
        self.sup_combo.setEditText("")
        self.sup_combo.blockSignals(False)

        clear_layout(self.suggest_row)
        rfqs = self.store.rfqs(self.need_no)
        in_rfq = {r["supplier_id"] for r in rfqs}
        grp = self.need.goods_group or self.need.service_group
        sugg = [s for s in self.store.suggested_suppliers(grp, self.need_no) if s["id"] not in in_rfq]
        if sugg:
            self.suggest_row.addWidget(label(f"پیشنهاد برای «{grp}»:", "muted"))
            for s in sugg[:8]:
                extra = f" ({s['answered']} پاسخ)" if s.get("answered") else ""
                b = button("+ " + s["name"] + extra, None, "ghost")
                b.clicked.connect(lambda _=False, sid=s["id"]: self._add_supplier(sid))
                self.suggest_row.addWidget(b)
            self.suggest_row.addStretch(1)

        text = self.data.get("rfq_text") or self._default_rfq_text()
        if self.rfq_text.toPlainText() != text:
            self.rfq_text.setPlainText(text)

        rv = P.required_validity(self.info)
        self.rfq_table.setRowCount(len(rfqs))
        answered = 0
        for i, r in enumerate(rfqs):
            d = r["data"]
            q = P.Quote(r["id"], r["supplier"], d.get("prices") or [], d.get("delivery_days"), d.get("valid_until", ""))
            total = q.total(self.items) if r["status"] == "answered" else None
            warns = P.quote_warnings(q, self.items, rv) if r["status"] == "answered" else []
            answered += r["status"] == "answered"
            status = P.RFQ_STATUS_TITLE.get(r["status"], r["status"])
            vals = [r["supplier"], r["phone"], status, jalali.fmt_stamp(r["sent_at"], with_time=False),
                    P.money(total) if total else "", f"{d['delivery_days']} روز" if d.get("delivery_days") else "",
                    d.get("valid_until", "") if r["status"] == "answered" else "", "؛ ".join(warns)]
            for j, val in enumerate(vals):
                it = ro_item(val, Qt.AlignCenter if j in (2, 3, 4, 5, 6) else None, r["id"])
                if j == 3 and r["sent_at"]:
                    it.setToolTip(rtl(f"ارسال: {jalali.fmt_stamp(r['sent_at'])}" + (f"\nپاسخ: {jalali.fmt_stamp(r['responded_at'])}" if r["responded_at"] else "")))
                if j == 2:
                    color = {"answered": C["ok"], "sent": C["info"], "no_answer": C["danger"], "unavailable": C["danger"]}.get(r["status"], C["muted"])
                    it.setForeground(QColor(color))
                if j == 7 and warns:
                    it.setForeground(QColor(C["danger"]))
                    it.setToolTip(rtl("\n".join(warns)))
                self.rfq_table.setItem(i, j, it)
        sent = sum(1 for r in rfqs if r["status"] != "draft")
        self.rfq_hint.setText(rtl(f"{len(rfqs)} تأمین‌کننده · {sent} استعلام ارسال‌شده · {answered} پاسخ" if rfqs else
                                  "هنوز تأمین‌کننده‌ای اضافه نشده. از بالا انتخاب کنید یا «تأمین‌کننده جدید» را بزنید."))
        self.btn_to_final.setEnabled(answered > 0)

    def _add_supplier(self, sid: int):
        self.store.add_rfq(self.need_no, sid)
        self.store.add_event(self.need_no, f"افزودن به استعلام: {self.store.get_supplier(sid)['name']}")
        self.reload()
        self.ui.refresh_views(board_only=True)

    def _add_selected_supplier(self):
        idx = self.sup_combo.currentIndex()
        text = self.sup_combo.currentText().strip()
        sid = self.sup_combo.itemData(idx) if idx >= 0 and self.sup_combo.itemText(idx) == text else None
        if sid is None and text:
            matches = [s for s in self._suppliers if text in s["name"] or (s["phone"] and text in s["phone"])]
            if len(matches) == 1:
                sid = matches[0]["id"]
        if sid is None:
            if text and QMessageBox.question(self, "تأمین‌کننده", rtl(f"«{text}» در فهرست نیست. به‌عنوان تأمین‌کننده جدید ثبت شود؟")) == QMessageBox.Yes:
                self._new_supplier(text)
            return
        self._add_supplier(sid)

    def _new_supplier(self, name_hint: str = ""):
        tags = self.need.goods_group or self.need.service_group
        dlg = SupplierDialog(self, {"tags": tags} if tags else None, name_hint=name_hint if isinstance(name_hint, str) else "")
        dlg.sid = None
        dlg.setWindowTitle("تأمین‌کننده جدید")
        if dlg.exec():
            sid = self.store.save_supplier(dlg.value())
            self._add_supplier(sid)

    def _current_rfq(self) -> dict | None:
        row = selected_row(self.rfq_table)
        it = self.rfq_table.item(row, 0) if row >= 0 else None
        if not it:
            QMessageBox.information(self, "استعلام", rtl("ابتدا یک ردیف از جدول استعلام‌ها را انتخاب کنید."))
            return None
        rid = it.data(Qt.UserRole)
        return next((r for r in self.store.rfqs(self.need_no) if r["id"] == rid), None)

    def _copy_and_mark_sent(self):
        r = self._current_rfq()
        if not r:
            return
        self.ui.copy_text(self.rfq_text.toPlainText(), f"متن استعلام برای «{r['supplier']}» کپی شد.")
        if r["status"] in ("draft", "no_answer"):
            self.store.update_rfq(r["id"], "sent")
            self.store.add_event(self.need_no, f"ارسال استعلام به {r['supplier']}")
        self._advance_to("rfq")
        self.reload()

    def _record_quote(self):
        r = self._current_rfq()
        if not r:
            return
        dlg = QuoteDialog(self, self.folder(), r["supplier"], self.items, r["data"], P.required_validity(self.info))
        if dlg.exec():
            val = dlg.value()
            self.store.update_rfq(r["id"], "answered", **val)
            q = P.Quote(r["id"], r["supplier"], val["prices"])
            total = q.total(self.items)
            self.store.add_event(self.need_no, f"پاسخ {r['supplier']}" + (f": {P.money(total)} ریال" if total else ""))
            self._advance_to("rfq")
            self.reload()

    def _set_rfq_status(self, status: str):
        r = self._current_rfq()
        if r:
            self.store.update_rfq(r["id"], status)
            self.store.add_event(self.need_no, f"{r['supplier']}: {P.RFQ_STATUS_TITLE[status]}")
            self.reload()
            self.ui.refresh_views(board_only=True)

    def _delete_rfq(self):
        r = self._current_rfq()
        if r and QMessageBox.question(self, "حذف", rtl(f"«{r['supplier']}» از استعلام‌های این نیاز حذف شود؟")) == QMessageBox.Yes:
            self.store.delete_rfq(r["id"])
            if self.data.get("final_rfq") == r["id"]:
                self._update(final_rfq=None)
            self.reload()
            self.ui.refresh_views(board_only=True)

    # ------------------------------------------------------------ tab 3: final & pricing
    def _build_final(self):
        outer = QVBoxLayout(self.final_tab)
        outer.setContentsMargins(0, 8, 0, 0)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(10)
        outer.addWidget(scroll_wrap(body))

        comp = card_frame()
        cv = QVBoxLayout(comp)
        cv.setContentsMargins(14, 12, 14, 12)
        hb = QHBoxLayout()
        hb.addWidget(label("مقایسه پاسخ تأمین‌کنندگان", "detailSection"))
        hb.addStretch(1)
        choose = button("انتخاب این تأمین‌کننده", "check", "primary")
        choose.clicked.connect(self._choose_supplier)
        hb.addWidget(choose)
        cv.addLayout(hb)
        self.cmp_table = make_table(["", "تأمین‌کننده", "جمع خرید (ریال)", "تحویل", "اعتبار تا", "هشدار"],
                                    [40, 220, 160, 90, 110, 300], stretch=5)
        self.cmp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cmp_table.setMaximumHeight(200)
        self.cmp_table.doubleClicked.connect(lambda *_: self._choose_supplier())
        cv.addWidget(self.cmp_table)
        v.addWidget(comp)

        price = card_frame()
        pv = QVBoxLayout(price)
        pv.setContentsMargins(14, 12, 14, 12)
        pv.addWidget(label("قیمت‌گذاری", "detailSection"))
        grid = QHBoxLayout()
        grid.setSpacing(14)

        def spin(suffix, lo, hi, dec=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSuffix(suffix)
            s.valueChanged.connect(self._pricing_changed)
            return s
        self.p_margin = spin(" ٪", 0, 500)
        self.p_months = spin(" ماه", 0, 36, 0)
        self.p_finance = spin(" ٪ ماهانه", 0, 50)
        self.p_vat = spin(" ٪", 0, 50)
        self.p_shipping = amount_edit(placeholder="0")
        self.p_shipping.setMaximumWidth(150)
        self.p_shipping.editingFinished.connect(self._pricing_changed)
        for cap, w in (("حاشیه سود", self.p_margin), ("هزینه حمل کل (ریال)", self.p_shipping),
                       ("مدت تسویه خریدار", self.p_months), ("هزینه مالی", self.p_finance), ("ارزش افزوده", self.p_vat)):
            col = QVBoxLayout()
            col.addWidget(label(cap, "fieldLabel"))
            col.addWidget(w)
            grid.addLayout(col)
        grid.addStretch(1)
        pv.addLayout(grid)
        self.months_hint = label("", "muted", wrap=True)
        pv.addWidget(self.months_hint)
        self.price_table = make_table(["شرح", "تعداد", "واحد", "فی خرید", "فی پیشنهادی", "فی نهایی (قابل ویرایش)", "مبلغ نهایی"],
                                      [300, 70, 80, 130, 130, 170, 150], stretch=0)
        self.price_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.price_table.itemChanged.connect(self._override_changed)
        pv.addWidget(self.price_table)
        self.summary = QGridLayout()
        self.summary.setHorizontalSpacing(26)
        self.summary.setVerticalSpacing(6)
        pv.addLayout(self.summary)
        v.addWidget(price)

        pf = card_frame()
        fv = QVBoxLayout(pf)
        fv.setContentsMargins(14, 12, 14, 12)
        fv.addWidget(label("پیش‌فاکتور", "detailSection"))
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.pf_addressee = QLineEdit()
        self.pf_delivery = QLineEdit()
        self.pf_payment = QLineEdit()
        self.pf_shipping = QLineEdit()
        self.pf_validity = QLineEdit()
        self.pf_validity.setMaximumWidth(160)
        self.pf_notes = QLineEdit()
        self.pf_notes.setPlaceholderText(rtl("اختیاری؛ اگر خالی باشد در پیش‌فاکتور نمی‌آید"))
        form.addRow("خطاب:", self.pf_addressee)
        form.addRow("زمان تحویل:", self.pf_delivery)
        form.addRow("نحوه پرداخت:", self.pf_payment)
        form.addRow("هزینه حمل:", self.pf_shipping)
        form.addRow("اعتبار تا:", self.pf_validity)
        form.addRow("توضیحات:", self.pf_notes)
        fv.addLayout(form)
        brow = QHBoxLayout()
        self.btn_make_pf = button("ساخت پیش‌فاکتور (Word و PDF)", "file", "primary")
        self.btn_make_pf.clicked.connect(self._make_proforma)
        self.btn_open_pdf = button("باز کردن PDF", "file")
        self.btn_open_doc = button("باز کردن Word", "file")
        self.btn_open_pdf.clicked.connect(lambda: self._open_pf("pdf"))
        self.btn_open_doc.clicked.connect(lambda: self._open_pf("docx"))
        brow.addWidget(self.btn_make_pf)
        brow.addWidget(self.btn_open_pdf)
        brow.addWidget(self.btn_open_doc)
        brow.addStretch(1)
        fv.addLayout(brow)
        self.pf_status = label("", "muted", wrap=True)
        fv.addWidget(self.pf_status)
        v.addWidget(pf)
        nxt = button("رفتن به ارسال پاسخ", "arrow_next", "primary")
        nxt.clicked.connect(lambda: self.tabs.setCurrentIndex(3))
        v.addWidget(nxt, 0, Qt.AlignLeading)
        v.addStretch(1)

    def _answered_quotes(self) -> list[tuple[dict, P.Quote]]:
        out = []
        for r in self.store.rfqs(self.need_no):
            if r["status"] == "answered":
                d = r["data"]
                out.append((r, P.Quote(r["id"], r["supplier"], d.get("prices") or [], d.get("delivery_days"), d.get("valid_until", ""))))
        return out

    def _chosen_quote(self) -> P.Quote | None:
        fid = self.data.get("final_rfq")
        for r, q in self._answered_quotes():
            if r["id"] == fid:
                return q
        return None

    def _params(self) -> P.PricingParams:
        return P.PricingParams(
            margin_pct=self.p_margin.value(), shipping=P.parse_amount(self.p_shipping.text()) or 0,
            payment_months=self.p_months.value(), finance_monthly_pct=self.p_finance.value(),
            vat_pct=self.p_vat.value(), rounding=int(self.settings["rounding"]))

    def _fill_final(self):
        quotes = self._answered_quotes()
        rv = P.required_validity(self.info)
        chosen = self.data.get("final_rfq")
        cheapest = min((q.total(self.items) for _, q in quotes if q.total(self.items)), default=None)
        self.cmp_table.setRowCount(len(quotes))
        for i, (r, q) in enumerate(quotes):
            total = q.total(self.items)
            warns = P.quote_warnings(q, self.items, rv)
            mark = "✓" if r["id"] == chosen else ""
            name = r["supplier"] + ("  (کمترین قیمت)" if total and total == cheapest and len(quotes) > 1 else "")
            vals = [mark, name, P.money(total) if total else "ناقص", f"{q.delivery_days} روز" if q.delivery_days else "",
                    q.valid_until, "؛ ".join(warns) or "—"]
            for j, val in enumerate(vals):
                it = ro_item(val, Qt.AlignCenter if j in (0, 2, 3, 4) else None, r["id"])
                if r["id"] == chosen:
                    it.setBackground(QColor(C["ok_soft"]))
                if j == 5 and warns:
                    it.setForeground(QColor(C["danger"]))
                self.cmp_table.setItem(i, j, it)

        pr = self.data.get("pricing") or {}
        detected = P.payment_months(self.info.get("buyer_note", "")) if self.info else None
        for w in (self.p_margin, self.p_months, self.p_finance, self.p_vat):
            w.blockSignals(True)
        self.p_margin.setValue(float(pr.get("margin_pct", self.settings["margin_pct"])))
        self.p_months.setValue(float(pr.get("payment_months", detected if detected is not None else self.settings["default_payment_months"])))
        self.p_finance.setValue(float(pr.get("finance_monthly_pct", self.settings["finance_monthly_pct"])))
        self.p_vat.setValue(float(pr.get("vat_pct", self.settings["vat_pct"])))
        self.p_shipping.setText(P.money(pr["shipping"]) if pr.get("shipping") else "")
        for w in (self.p_margin, self.p_months, self.p_finance, self.p_vat):
            w.blockSignals(False)
        self.months_hint.setText(rtl(f"مدت تسویه از توضیحات خریدار تشخیص داده شد: {'نقدی' if detected == 0 else f'{detected} ماه'}.")
                                 if detected is not None else "")

        d = self.data
        s = self.settings
        q = self._chosen_quote()
        days = q.delivery_days if q and q.delivery_days else "…"
        pf = d.get("proforma") or {}
        self.pf_addressee.setText(pf.get("addressee") or s["addressee"].replace("{خریدار}", self.need.organization))
        self.pf_delivery.setText(pf.get("delivery") or s["delivery_text"].replace("{روز}", str(days)))
        self.pf_payment.setText(pf.get("payment") or s["payment_text"])
        self.pf_shipping.setText(pf.get("shipping") or s["shipping_text"])
        self.pf_validity.setText(pf.get("validity") or rv or jalali.add_days(jalali.today(), 30))
        self.pf_notes.setText(pf.get("notes", ""))
        self._render_pricing()

    def _plan(self) -> P.PricePlan | None:
        q = self._chosen_quote()
        if not q or q.total(self.items) is None:
            return None
        overrides = {int(k): float(v) for k, v in (self.data.get("overrides") or {}).items()}
        return P.price_plan(self.items, [float(p) for p in q.unit_prices[:len(self.items)]], self._params(), overrides)

    def _render_pricing(self):
        plan = self._plan()
        self.price_table.blockSignals(True)
        clear_layout(self.summary)
        if plan is None:
            self.price_table.setRowCount(0)
            msg = ("ابتدا از جدول مقایسه، تأمین‌کننده منتخب را انتخاب کنید." if self._answered_quotes()
                   else "هنوز پاسخی از تأمین‌کنندگان ثبت نشده است (بخش ۲).")
            self.summary.addWidget(label(msg, "notice", wrap=True), 0, 0)
            self.btn_make_pf.setEnabled(False)
            self.price_table.blockSignals(False)
            self._update_pf_buttons()
            return
        self.btn_make_pf.setEnabled(True)
        self.price_table.setRowCount(len(plan.lines))
        for i, line in enumerate(plan.lines):
            vals = [line.item.name, P._qty(line.item.qty), line.item.unit, P.money(line.cost_unit), P.money(line.suggested_unit)]
            for j, val in enumerate(vals):
                self.price_table.setItem(i, j, ro_item(val, Qt.AlignCenter if j else None))
            final = QTableWidgetItem(P.money(line.final_unit))
            final.setTextAlignment(Qt.AlignCenter)
            final.setBackground(QColor(C["primary_soft_2"]))
            if line.final_unit != line.suggested_unit:
                final.setForeground(QColor(C["primary"]))
            self.price_table.setItem(i, 5, final)
            self.price_table.setItem(i, 6, ro_item(P.money(line.final_total), Qt.AlignCenter))
        self.price_table.setFixedHeight(46 + 38 * len(plan.lines))
        self.price_table.blockSignals(False)
        cells = [("جمع خرید از تأمین‌کننده", plan.cost_total), ("هزینه حمل", plan.shipping),
                 ("هزینه مالی (خواب پول)", plan.finance_cost), ("جمع فروش", plan.sale_total),
                 ("ارزش افزوده", plan.vat), ("مبلغ قابل پرداخت خریدار", plan.grand_total)]
        for i, (cap, val) in enumerate(cells):
            r, c = divmod(i, 3)
            self.summary.addWidget(label(cap, "fieldLabel"), r * 2, c)
            self.summary.addWidget(label(f"{P.money(val)} ریال", "detailValue"), r * 2 + 1, c)
        good = plan.profit > 0
        prof = pill(f"سود خالص: {P.money(plan.profit)} ریال  ({plan.profit_pct:.1f}٪)",
                    C["ok"] if good else C["danger"], C["ok_soft"] if good else C["danger_soft"])
        self.summary.addWidget(prof, 0, 3, 2, 1)
        self._update(totals={"cost": plan.cost_total, "sale": plan.sale_total, "vat": plan.vat,
                             "grand": plan.grand_total, "profit": plan.profit, "profit_pct": plan.profit_pct})
        self._update_pf_buttons()

    def _pricing_changed(self, *_):
        if self._loading or not self.case:
            return
        p = self._params()
        self._update(pricing={"margin_pct": p.margin_pct, "shipping": p.shipping, "payment_months": p.payment_months,
                              "finance_monthly_pct": p.finance_monthly_pct, "vat_pct": p.vat_pct})
        self._render_pricing()

    def _override_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 5:
            return
        plan = self._plan()
        if plan is None:
            return
        value = P.parse_amount(item.text())
        ov = dict(self.data.get("overrides") or {})
        line = plan.lines[item.row()]
        if not value or value == line.suggested_unit:
            ov.pop(str(item.row()), None)
        else:
            ov[str(item.row())] = value
        self._update(overrides=ov)
        QTimer.singleShot(0, self._render_pricing)

    def _choose_supplier(self):
        row = selected_row(self.cmp_table)
        it = self.cmp_table.item(row, 0) if row >= 0 else None
        if not it:
            return
        rid = it.data(Qt.UserRole)
        name = next((r["supplier"] for r, _ in self._answered_quotes() if r["id"] == rid), "")
        self._update(final_rfq=rid, overrides={}, proforma={**(self.data.get("proforma") or {}), "delivery": ""})
        self.store.add_event(self.need_no, f"تأمین‌کننده منتخب: {name}")
        self._advance_to("final")
        self.reload()

    def _pf_fields(self) -> dict:
        return {"addressee": self.pf_addressee.text().strip(), "delivery": self.pf_delivery.text().strip(),
                "payment": self.pf_payment.text().strip(), "shipping": self.pf_shipping.text().strip(),
                "validity": self.pf_validity.text().strip(), "notes": self.pf_notes.text().strip()}

    def _make_proforma(self):
        plan = self._plan()
        if plan is None:
            return
        fields = self._pf_fields()
        rv = P.required_validity(self.info)
        if rv and jalali.to_date(fields["validity"]) and jalali.to_date(fields["validity"]) < jalali.to_date(rv):
            if QMessageBox.question(self, "اعتبار", rtl(f"اعتبار پیش‌فاکتور ({fields['validity']}) از حداقل خواسته خریدار ({rv}) کمتر است. ادامه می‌دهید؟")) != QMessageBox.Yes:
                return
        s = self.store.settings()
        template = Path(s["proforma_template"]) if s["proforma_template"] else proforma.default_template(resource_dir())
        if not template.exists():
            QMessageBox.critical(self, "قالب", rtl(f"فایل قالب پیدا نشد:\n{template}"))
            return
        pf = dict(self.data.get("proforma") or {})
        number = pf.get("number")
        if not number:
            number, counters = P.proforma_number(s.get("proforma_counters") or {})
            self.store.set("proforma_counters", counters)
        date_j = jalali.today()
        ctx = proforma.build_context(number=number, date_j=date_j, addressee=fields["addressee"], need=self.need,
                                     info=self.info, seller=s, plan=plan, vat_pct=self.p_vat.value(),
                                     validity=fields["validity"], delivery=fields["delivery"], payment=fields["payment"],
                                     shipping=fields["shipping"], notes=fields["notes"])
        out = self.folder() / f"پیش‌فاکتور {self.need_no}.docx"
        try:
            proforma.render_docx(template, ctx, out)
        except PermissionError:
            QMessageBox.critical(self, "پیش‌فاکتور", rtl("فایل Word قبلی باز است. آن را ببندید و دوباره امتحان کنید."))
            return
        except Exception as exc:
            QMessageBox.critical(self, "پیش‌فاکتور", rtl(f"ساخت پیش‌فاکتور ناموفق بود: {exc}"))
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pdf, err = proforma.to_pdf(out)
        finally:
            QGuiApplication.restoreOverrideCursor()
        pf.update(fields)
        pf.update({"number": number, "date": date_j, "docx": str(out), "pdf": str(pdf) if pdf else "", "at": time.time(),
                   "grand": plan.grand_total})
        self._update(proforma=pf)
        self.store.add_event(self.need_no, f"ساخت پیش‌فاکتور {number} — {P.money(plan.grand_total)} ریال")
        if err:
            self.pf_status.setText(rtl("فایل Word ساخته شد ولی PDF نه: " + err))
        self._update_pf_buttons()
        self.ui.refresh_views(board_only=True)

    def _update_pf_buttons(self):
        pf = self.data.get("proforma") or {}
        has_doc = bool(pf.get("docx")) and Path(pf["docx"]).exists()
        has_pdf = bool(pf.get("pdf")) and Path(pf["pdf"]).exists()
        self.btn_open_doc.setEnabled(has_doc)
        self.btn_open_pdf.setEnabled(has_pdf)
        if has_doc:
            stale = abs((pf.get("grand") or 0) - ((self.data.get("totals") or {}).get("grand") or 0)) > 0.5
            msg = f"پیش‌فاکتور شماره {pf.get('number')} — {pf.get('date')} — {P.money(pf.get('grand'))} ریال"
            if stale:
                msg += "  ⚠ قیمت‌ها بعد از ساخت تغییر کرده؛ دوباره بسازید."
            self.pf_status.setText(rtl(msg))
            self.btn_make_pf.setText("ساخت دوباره پیش‌فاکتور")
        elif not self.pf_status.text().startswith("‏فایل Word"):
            self.pf_status.setText(rtl("شماره پیش‌فاکتور هنگام اولین ساخت تعیین می‌شود. فایل‌ها در پوشه همین نیاز ذخیره می‌شوند."))
            self.btn_make_pf.setText("ساخت پیش‌فاکتور (Word و PDF)")

    def _open_pf(self, kind: str):
        path = (self.data.get("proforma") or {}).get(kind)
        if path and Path(path).exists():
            proforma.open_path(Path(path))

    # ------------------------------------------------------------ tab 4: submit & result
    def _build_submit(self):
        outer = QVBoxLayout(self.submit_tab)
        outer.setContentsMargins(0, 8, 0, 0)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(10)
        outer.addWidget(scroll_wrap(body))

        c1 = card_frame()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(14, 12, 14, 12)
        l1.addWidget(label("قیمت‌ها برای واردکردن در سامانه ستاد", "detailSection"))
        l1.addWidget(label("پاسخ و بارگذاری پیش‌فاکتور را در خود سایت ستاد انجام دهید؛ این جدول فقط برای راحتی واردکردن قیمت‌هاست.", "muted", wrap=True))
        self.sub_table = make_table(["شرح", "تعداد", "فی نهایی (ریال)", "مبلغ (ریال)", "کپی"], [380, 80, 170, 170, 60], stretch=0)
        self.sub_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        l1.addWidget(self.sub_table)
        self.sub_totals = label("", "detailValue", wrap=True)
        l1.addWidget(self.sub_totals)
        row = QHBoxLayout()
        self.btn_submitted = button("پاسخ در ستاد ارسال شد", "send", "primary")
        self.btn_submitted.clicked.connect(self._mark_submitted)
        row.addWidget(self.btn_submitted)
        self.sub_info = label("", "muted", wrap=True)
        row.addWidget(self.sub_info, 1)
        l1.addLayout(row)
        v.addWidget(c1)

        c2 = card_frame()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(14, 12, 14, 12)
        l2.addWidget(label("نتیجه", "detailSection"))
        rr = QHBoxLayout()
        self.result_group = QButtonGroup(self)
        for key, title in P.RESULTS:
            rb = QRadioButton(title)
            rb.setProperty("key", key)
            self.result_group.addButton(rb)
            rr.addWidget(rb)
        rr.addStretch(1)
        l2.addLayout(rr)
        f = QFormLayout()
        self.win_price = amount_edit(placeholder="اگر مشخص است")
        self.win_price.setMaximumWidth(200)
        self.result_note = QLineEdit()
        f.addRow("مبلغ برنده (ریال):", self.win_price)
        f.addRow("توضیح:", self.result_note)
        l2.addLayout(f)
        save = button("ثبت نتیجه", "check", "primary")
        save.clicked.connect(self._save_result)
        l2.addWidget(save, 0, Qt.AlignLeading)
        v.addWidget(c2)

        c3 = card_frame()
        l3 = QVBoxLayout(c3)
        l3.setContentsMargins(14, 12, 14, 12)
        l3.addWidget(label("سابقه پرونده", "detailSection"))
        self.history = QListWidget()
        self.history.setMinimumHeight(160)
        l3.addWidget(self.history)
        v.addWidget(c3)
        v.addStretch(1)

    def _fill_submit(self):
        plan = self._plan()
        lines = plan.lines if plan else []
        self.sub_table.setRowCount(len(lines))
        for i, line in enumerate(lines):
            for j, val in enumerate([line.item.name, P._qty(line.item.qty), P.money(line.final_unit), P.money(line.final_total)]):
                self.sub_table.setItem(i, j, ro_item(val, Qt.AlignCenter if j else None))
            cp = button("", "copy", "ghost", "کپی فی نهایی")
            cp.clicked.connect(lambda _=False, v=int(line.final_unit): self.ui.copy_text(str(v), "فی کپی شد."))
            self.sub_table.setCellWidget(i, 4, cp)
        self.sub_table.setFixedHeight(46 + 38 * max(1, len(lines)))
        if plan:
            self.sub_totals.setText(rtl(f"جمع فروش: {P.money(plan.sale_total)} ریال   ·   ارزش افزوده: {P.money(plan.vat)} ریال   ·   "
                                        f"مبلغ کل: {P.money(plan.grand_total)} ریال"))
        else:
            self.sub_totals.setText(rtl("قیمت نهایی هنوز تعیین نشده است (بخش ۳)."))
        d = self.data
        if d.get("submitted_at"):
            self.sub_info.setText(rtl(f"ارسال‌شده در {jalali.fmt_stamp(d['submitted_at'])} با مبلغ {P.money(d.get('submitted_amount'))} ریال"))
            self.btn_submitted.setText("ثبت دوباره ارسال")
        else:
            self.sub_info.setText("")
            self.btn_submitted.setText("پاسخ در ستاد ارسال شد")
        self.btn_submitted.setEnabled(plan is not None)
        for b in self.result_group.buttons():
            b.setChecked(b.property("key") == d.get("result"))
        self.win_price.setText(P.money(d["winner_price"]) if d.get("winner_price") else "")
        self.result_note.setText(d.get("result_note", ""))
        self.history.clear()
        for e in self.store.events(self.need_no):
            self.history.addItem(QListWidgetItem(rtl(f"{jalali.fmt_stamp(e['at'])}   {e['text']}")))

    def _mark_submitted(self):
        plan = self._plan()
        if not plan:
            return
        self._update(submitted_at=time.time(), submitted_amount=plan.grand_total)
        self.store.add_event(self.need_no, f"پاسخ در ستاد ارسال شد — {P.money(plan.grand_total)} ریال")
        self._move("submitted")

    def _save_result(self):
        btn = self.result_group.checkedButton()
        if not btn:
            QMessageBox.information(self, "نتیجه", rtl("یکی از گزینه‌های نتیجه را انتخاب کنید."))
            return
        key = btn.property("key")
        self._update(result=key, winner_price=P.parse_amount(self.win_price.text()), result_note=self.result_note.text().strip())
        self.store.add_event(self.need_no, f"نتیجه: {dict(P.RESULTS)[key]}")
        self._move("result")
