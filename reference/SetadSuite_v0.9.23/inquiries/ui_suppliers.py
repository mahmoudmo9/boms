"""Supplier registry: list, add/edit dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import pipeline as P
from ui_kit import button, card_frame, label, make_icon, rtl


class SupplierDialog(QDialog):
    """Add or edit one supplier. Only the name is required."""

    def __init__(self, parent, supplier: dict | None = None, name_hint: str = ""):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("ویرایش تأمین‌کننده" if supplier else "تأمین‌کننده جدید")
        self.resize(520, 420)
        sup = supplier or {}
        self.sid = sup.get("id")
        f = QFormLayout()
        f.setVerticalSpacing(9)
        self.name = QLineEdit(sup.get("name", name_hint))
        self.contact = QLineEdit(sup.get("contact", ""))
        self.phone = QLineEdit(sup.get("phone", ""))
        self.phone.setLayoutDirection(Qt.LeftToRight)
        self.email = QLineEdit(sup.get("email", ""))
        self.email.setLayoutDirection(Qt.LeftToRight)
        self.city = QLineEdit(sup.get("city", ""))
        self.tags = QLineEdit(sup.get("tags", ""))
        self.tags.setPlaceholderText(rtl("گروه‌های کالا یا کلمات، با ویرگول جدا"))
        self.note = QPlainTextEdit(sup.get("note", ""))
        self.note.setMaximumHeight(90)
        f.addRow("نام شرکت / فروشنده *", self.name)
        f.addRow("شخص رابط", self.contact)
        f.addRow("موبایل / تلفن / واتساپ", self.phone)
        f.addRow("ایمیل", self.email)
        f.addRow("شهر", self.city)
        f.addRow("زمینه‌ها", self.tags)
        f.addRow("یادداشت", self.note)
        v = QVBoxLayout(self)
        v.addLayout(f)
        v.addWidget(label("فقط نام لازم است؛ بقیه را هر وقت خواستید کامل کنید.", "muted"))
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("ذخیره")
        box.button(QDialogButtonBox.Cancel).setText("انصراف")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        v.addWidget(box)

    def _ok(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "تأمین‌کننده", rtl("نام تأمین‌کننده را وارد کنید."))
            return
        self.accept()

    def value(self) -> dict:
        return {"id": self.sid, "name": self.name.text(), "contact": self.contact.text(), "phone": self.phone.text(),
                "email": self.email.text(), "city": self.city.text(), "tags": self.tags.text(),
                "note": self.note.toPlainText()}


COLS = [("name", "نام", 220), ("contact", "رابط", 140), ("phone", "تلفن", 140), ("email", "ایمیل", 190),
        ("city", "شهر", 100), ("tags", "زمینه‌ها", 220), ("rfq_count", "استعلام", 80),
        ("answer_count", "پاسخ", 70), ("win_count", "برنده", 70)]


class SuppliersView(QWidget):
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
        head.addWidget(label("تأمین‌کنندگان", "sectionTitle"))
        self.count = label("", "muted")
        head.addWidget(self.count)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(rtl("جست‌وجو در نام، تلفن، شهر، زمینه…"))
        self.search.addAction(make_icon("search"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.refresh)
        head.addWidget(self.search)
        add = button("تأمین‌کننده جدید", "plus", "primary")
        add.clicked.connect(self.add)
        edit = button("ویرایش", "edit")
        edit.clicked.connect(self.edit_current)
        delete = button("حذف", "trash", "danger")
        delete.clicked.connect(self.delete_current)
        for b in (add, edit, delete):
            head.addWidget(b)
        v.addLayout(head)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        h = self.table.horizontalHeader()
        for i, (_, _, w) in enumerate(COLS):
            h.resizeSection(i, w)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda *_: self.edit_current())
        v.addWidget(self.table, 1)
        self.empty = label("هنوز تأمین‌کننده‌ای ثبت نشده. از «تأمین‌کننده جدید» یا داخل پرونده هر نیاز (بخش استعلام) اضافه کنید.", "emptyText", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)

    def refresh(self):
        rows = self.ui.store.suppliers()
        q = self.search.text().strip().casefold()
        if q:
            rows = [r for r in rows if q in " ".join(str(r.get(k, "")) for k in ("name", "contact", "phone", "email", "city", "tags", "note")).casefold()]
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, (key, _, _) in enumerate(COLS):
                val = r.get(key, "")
                it = QTableWidgetItem(str(val if val not in (None, "") else ("0" if key.endswith("count") else "")))
                it.setData(Qt.UserRole, r["id"])
                if key.endswith("count"):
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, it)
        total = len(self.ui.store.suppliers())
        self.count.setText(rtl(f"{total} تأمین‌کننده"))
        self.empty.setVisible(total == 0)
        self.table.setVisible(total > 0)

    def _current_id(self):
        row = self.table.currentRow()
        it = self.table.item(row, 0) if row >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def add(self):
        dlg = SupplierDialog(self)
        if dlg.exec():
            self.ui.store.save_supplier(dlg.value())
            self.refresh()

    def edit_current(self):
        sid = self._current_id()
        if sid is None:
            return
        dlg = SupplierDialog(self, self.ui.store.get_supplier(sid))
        if dlg.exec():
            self.ui.store.save_supplier(dlg.value())
            self.refresh()
            self.ui.refresh_views()

    def delete_current(self):
        sid = self._current_id()
        if sid is None:
            return
        store = self.ui.store
        sup = store.get_supplier(sid)
        usage = store.supplier_usage(sid)
        blocking = [u for u in usage if u["chosen"] and u["stage"] in P.STAGE_KEYS]
        if blocking:
            QMessageBox.information(self, "حذف", rtl(
                f"«{sup['name']}» تأمین‌کننده منتخب این پرونده‌هاست و حذف نمی‌شود:\n"
                + "\n".join(f"• {u['need_no']} ({P.STAGE_TITLE[u['stage']]})" for u in blocking)
                + "\n\nابتدا در پرونده، تأمین‌کننده دیگری انتخاب کنید یا پرونده را کنار بگذارید."))
            return
        if usage:
            lines = "\n".join(f"• {u['need_no']} ({P.STAGE_TITLE.get(u['stage'], 'بدون پرونده')})" for u in usage[:8])
            more = f"\n… و {len(usage) - 8} مورد دیگر" if len(usage) > 8 else ""
            msg = (f"«{sup['name']}» در {len(usage)} استعلام استفاده شده:\n{lines}{more}\n\n"
                   "تأمین‌کننده همراه با این استعلام‌ها حذف شود؟")
        else:
            msg = f"«{sup['name']}» حذف شود؟"
        if QMessageBox.question(self, "حذف تأمین‌کننده", rtl(msg)) != QMessageBox.Yes:
            return
        store.delete_supplier(sid, with_rfqs=True)
        self.refresh()
        self.ui.refresh_views()
        for win in list(self.ui.case_windows.values()):
            win.reload()
