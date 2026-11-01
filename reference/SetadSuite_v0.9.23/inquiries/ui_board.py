"""Follow-up board (kanban), archive of rejected needs, and the reject dialog."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QScrollArea, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import jalali
import pipeline as P
from ui_kit import C, button, card_frame, clear_layout, label, make_icon, pill, rtl

MIME = "application/x-setad-need"


def deadline_pill(text: str, hours: float | None) -> QLabel:
    if hours is None:
        fg, bg = C["neutral"], C["neutral_soft"]
    elif hours <= 0 or hours <= 48:
        fg, bg = C["danger"], C["danger_soft"]
    elif hours <= 96:
        fg, bg = C["warn"], C["warn_soft"]
    else:
        fg, bg = C["ok"], C["ok_soft"]
    return pill("⏱ " + text, fg, bg)


class RejectDialog(QDialog):
    def __init__(self, parent, reasons: list[str], title: str):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("صرف‌نظر نیاز")
        self.resize(480, 260)
        v = QVBoxLayout(self)
        v.addWidget(label(title, "detailTitle", wrap=True))
        f = QFormLayout()
        self.reason = QComboBox()
        self.reason.addItems(reasons)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText(rtl("توضیح کوتاه (اختیاری)"))
        self.note.setMaximumHeight(80)
        f.addRow("دلیل:", self.reason)
        f.addRow("توضیح:", self.note)
        v.addLayout(f)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("صرف‌نظر")
        box.button(QDialogButtonBox.Cancel).setText("انصراف")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)


class BoardCard(QFrame):
    def __init__(self, ui, item: dict):
        super().__init__()
        self.ui = ui
        self.need_no = item["need"].need_no
        self.setObjectName("kcardResult" if item["case"]["stage"] == "result" else "kcard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(210)
        self._press: QPoint | None = None
        need = item["need"]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        text = need.description[:90] + ("…" if len(need.description) > 90 else "")
        title = label(text, "kdesc", wrap=True)
        title.setToolTip(rtl(need.description))
        v.addWidget(title)
        v.addWidget(label(" · ".join(x for x in (need.organization, need.province) if x), "korg", wrap=True))
        row = QHBoxLayout()
        row.setSpacing(5)
        if item["remaining"] and item["case"]["stage"] in P.OPEN_STAGES:
            row.addWidget(deadline_pill(item["remaining"], item["hours"]))
        row.addStretch(1)
        if item["warnings"]:
            warn = QLabel()
            warn.setPixmap(make_icon("alert", C["danger"], 16).pixmap(16, 16))
            warn.setToolTip(rtl("هشدار: " + "، ".join(item["warnings"])))
            row.addWidget(warn)
        v.addLayout(row)
        if item["meta"]:
            fg, bg = item.get("meta_colors") or (C["text_2"], C["neutral_soft"])
            meta = pill(item["meta"], fg, bg, bold=False)
            meta.setWordWrap(True)
            v.addWidget(meta, 0, Qt.AlignLeading)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, self.need_no.encode())
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(e.position().toPoint())
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.ui.open_case(self.need_no)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.RightToLeft)
        menu.addAction(make_icon("folder"), "باز کردن پرونده", lambda: self.ui.open_case(self.need_no))
        move = menu.addMenu("انتقال به مرحله")
        current = self.ui.stage_of(self.need_no)
        for key, title, _ in P.STAGES:
            act = move.addAction(title, lambda k=key: self.ui.move_stage(self.need_no, k))
            act.setEnabled(key != current)
        menu.addSeparator()
        menu.addAction(make_icon("archive"), "صرف‌نظر / حذف…", lambda: self.ui.remove_from_funnel(self.need_no))
        menu.exec(e.globalPos())


class BoardColumn(QFrame):
    def __init__(self, ui, key: str, title: str, color: str):
        super().__init__()
        self.ui = ui
        self.key = key
        self.setObjectName("kcol")
        self.setAcceptDrops(True)
        self.setFixedWidth(232)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        stripe = QFrame()
        stripe.setFixedHeight(5)
        stripe.setStyleSheet(f"background:{color}; border-radius:2px;")
        v.addWidget(stripe)
        head = QHBoxLayout()
        head.addWidget(label(title, "kcolTitle"))
        head.addStretch(1)
        self.count = label("0", "kcolCount")
        head.addWidget(self.count)
        v.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        holder = QWidget()
        self.cards = QVBoxLayout(holder)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(8)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

    def set_items(self, items: list[dict]):
        clear_layout(self.cards)
        for it in items:
            self.cards.addWidget(BoardCard(self.ui, it))
        if not items:
            hint = label("کارتی اینجا نیست", "muted")
            hint.setAlignment(Qt.AlignCenter)
            self.cards.addWidget(hint)
        self.cards.addStretch(1)
        self.count.setText(str(len(items)))

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            self.setProperty("drop", True)
            self.style().unpolish(self)
            self.style().polish(self)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.setProperty("drop", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, e):
        self.dragLeaveEvent(e)
        need_no = bytes(e.mimeData().data(MIME)).decode()
        e.acceptProposedAction()
        if need_no and self.ui.stage_of(need_no) != self.key:
            self.ui.move_stage(need_no, self.key)


class BoardView(QWidget):
    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.setLayoutDirection(Qt.RightToLeft)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        bar = card_frame()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.addWidget(label("تابلوی پیگیری", "sectionTitle"))
        self.summary = label("", "muted")
        bl.addWidget(self.summary)
        bl.addStretch(1)
        bl.addWidget(label("کارت‌ها را بین ستون‌ها بکشید یا روی کارت کلیک کنید تا پرونده باز شود.", "muted"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(rtl("جست‌وجو در کارت‌ها…"))
        self.search.addAction(make_icon("search"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.refresh)
        bl.addWidget(self.search)
        v.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.columns: dict[str, BoardColumn] = {}
        for key, title, color in P.STAGES:
            col = BoardColumn(ui, key, title, color)
            col.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.columns[key] = col
            row.addWidget(col)
        row.addStretch(1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

    def refresh(self):
        items = self.ui.board_items()
        q = self.search.text().strip()
        if q:
            qn = P.norm_text(q)
            items = [it for it in items if qn in P.norm_text(" ".join(
                (it["need"].need_no, it["need"].description, it["need"].organization, it["need"].province)))]
        by_stage: dict[str, list] = {k: [] for k in self.columns}
        for it in items:
            by_stage.setdefault(it["case"]["stage"], []).append(it)
        for key, col in self.columns.items():
            lst = by_stage.get(key, [])
            if key in P.OPEN_STAGES:
                lst.sort(key=lambda it: it["hours"] if it["hours"] is not None else 1e9)
            else:
                lst.sort(key=lambda it: -it["case"]["updated_at"])
            col.set_items(lst)
        urgent = sum(1 for it in items if it["case"]["stage"] in P.OPEN_STAGES and it["hours"] is not None and 0 < it["hours"] <= 48)
        self.summary.setText(rtl(f"{len(items)} پرونده فعال" + (f"  ·  {urgent} پرونده با مهلت کمتر از ۲ روز" if urgent else "")))


class ArchiveView(QWidget):
    COLS = [("شماره نیاز", 150), ("شرح نیاز", 380), ("دستگاه خریدار", 220), ("دلیل", 200), ("توضیح", 220),
            ("از مرحله", 160), ("تاریخ", 140)]

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.setLayoutDirection(Qt.RightToLeft)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = card_frame()
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        head.addWidget(label("صرف‌نظرشده", "sectionTitle"))
        self.count = label("", "muted")
        head.addWidget(self.count)
        head.addStretch(1)
        restore = button("بازگرداندن به تابلو", "retry", "primary")
        restore.clicked.connect(self._restore)
        open_case = button("باز کردن پرونده", "folder")
        open_case.clicked.connect(lambda: self._current() and self.ui.open_case(self._current()))
        delete = button("حذف کامل", "trash", "danger")
        delete.clicked.connect(self._delete)
        head.addWidget(restore)
        head.addWidget(open_case)
        head.addWidget(delete)
        v.addLayout(head)
        self.stats = label("", "muted", wrap=True)
        v.addWidget(self.stats)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        for i, (_, w) in enumerate(self.COLS):
            self.table.horizontalHeader().resizeSection(i, w)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda *_: self._current() and self.ui.open_case(self._current()))
        v.addWidget(self.table, 1)

    def _current(self):
        row = self.table.currentRow()
        it = self.table.item(row, 0) if row >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def _restore(self):
        nn = self._current()
        if nn:
            self.ui.restore_need(nn)

    def _delete(self):
        nn = self._current()
        if not nn:
            return
        n = len(self.ui.store.rfqs(nn))
        msg = f"پرونده {nn}" + (f" و {n} استعلام آن" if n else "") + " برای همیشه حذف شود؟"
        if QMessageBox.question(self, "حذف کامل", rtl(msg)) == QMessageBox.Yes:
            self.ui.delete_case(nn)

    def refresh(self):
        cases = self.ui.store.cases({P.REJECTED})
        self.table.setRowCount(len(cases))
        reasons: dict[str, int] = {}
        for i, c in enumerate(cases):
            need = self.ui.need_obj(c["need_no"])
            d = c["data"]
            reason = d.get("reject_reason", "")
            reasons[reason] = reasons.get(reason, 0) + 1
            values = [c["need_no"], need.description if need else "", need.organization if need else "", reason,
                      d.get("reject_note", ""), P.STAGE_TITLE.get(d.get("rejected_from", ""), ""),
                      jalali.fmt_stamp(c["updated_at"], with_time=False)]
            for j, val in enumerate(values):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, c["need_no"])
                if j == 1:
                    it.setToolTip(rtl(val))
                self.table.setItem(i, j, it)
        self.count.setText(rtl(f"{len(cases)} مورد"))
        top = sorted(reasons.items(), key=lambda kv: -kv[1])
        self.stats.setText(rtl("دلایل: " + "  ·  ".join(f"{k or 'بدون دلیل'} ({n})" for k, n in top)) if top else "")
