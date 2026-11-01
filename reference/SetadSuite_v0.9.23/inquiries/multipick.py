"""v0.9.21: a drop-down that lets you tick several values (used for «دستگاه / برگزارکننده» in purchase and tender).

It is a real QComboBox (so it looks exactly like the other filters); only the pop-up is replaced by a small panel with a
search box and a checkable list. The combo shows «همه …», the single chosen name, or «N دستگاه»."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

try:
    from ui_kit import resource_dir
except ImportError:
    from inquiries.ui_kit import resource_dir

_TR = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ـ": "", "‌": " "})


def _norm(text: str) -> str:
    return (text or "").translate(_TR).casefold()


class _Panel(QFrame):
    def __init__(self, owner: "MultiCombo"):
        super().__init__(owner.window(), Qt.Popup)
        self.owner = owner
        self.setLayoutDirection(Qt.RightToLeft)
        self.setObjectName("multiPanel")
        a = (resource_dir() / "assets").as_posix()
        self.setStyleSheet(
            "QFrame#multiPanel { background:#ffffff; border:1px solid #D0D5DD; border-radius:10px; }"
            "QListWidget { border:none; background:transparent; outline:0; color:#1D2939; }"
            "QListWidget::item { padding:5px 8px; color:#1D2939; background:transparent; }"
            "QListWidget::item:hover, QListWidget::item:selected, QListWidget::item:selected:active { background:#F2F4F7; color:#1D2939; }"
            "QListWidget::indicator { width:18px; height:18px; }"
            f"QListWidget::indicator:unchecked {{ image: url('{a}/box.svg'); }}"
            f"QListWidget::indicator:unchecked:hover {{ image: url('{a}/box-hover.svg'); }}"
            f"QListWidget::indicator:checked {{ image: url('{a}/box-checked.svg'); }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو در " + owner.noun_plural + "…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        v.addWidget(self.search)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.itemChanged.connect(self._item_changed)
        v.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.count = QLabel("")
        self.count.setStyleSheet("color:#667085;")
        foot.addWidget(self.count, 1)
        self.b_clear = QPushButton("پاک کردن")
        self.b_clear.setCursor(Qt.PointingHandCursor)
        self.b_clear.clicked.connect(self._clear)
        self.b_close = QPushButton("بستن")
        self.b_close.setCursor(Qt.PointingHandCursor)
        self.b_close.clicked.connect(self.close)
        foot.addWidget(self.b_clear)
        foot.addWidget(self.b_close)
        v.addLayout(foot)
        self._busy = False

    def fill(self):
        self._busy = True
        self.list.clear()
        sel = self.owner._sel
        ordered = [x for x in self.owner._values if x in sel] + [x for x in self.owner._values if x not in sel]
        for text in ordered:
            it = QListWidgetItem(text)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if text in sel else Qt.Unchecked)
            it.setData(Qt.UserRole, _norm(text))
            self.list.addItem(it)
        self._busy = False
        self.search.clear()
        self._update_count()

    def _filter(self, text: str):
        terms = _norm(text).split()
        for i in range(self.list.count()):
            it = self.list.item(i)
            hay = it.data(Qt.UserRole)
            it.setHidden(not all(t in hay for t in terms))

    def _item_changed(self, it: QListWidgetItem):
        if self._busy:
            return
        text = it.text()
        if it.checkState() == Qt.Checked:
            self.owner._sel.add(text)
        else:
            self.owner._sel.discard(text)
        self._update_count()
        self.owner._selection_changed()

    def _clear(self):
        self._busy = True
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)
        self._busy = False
        self.owner._sel.clear()
        self._update_count()
        self.owner._selection_changed()

    def _update_count(self):
        n = len(self.owner._sel)
        self.count.setText((f"{n} انتخاب‌شده".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))) if n else "")


class MultiCombo(QComboBox):
    selectionChanged = Signal()

    def __init__(self, all_text: str, noun_one: str = "دستگاه", noun_plural: str = "دستگاه‌ها", width: int = 160):
        super().__init__()
        self.all_text, self.noun_one, self.noun_plural = all_text, noun_one, noun_plural
        self._values: list[str] = []
        self._sel: set[str] = set()
        self._panel: _Panel | None = None
        self.setMinimumWidth(width)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self._show_summary()

    # -- data
    def set_values(self, values: list[str]):
        self._values = list(values)
        self._sel &= set(values)
        self._show_summary()

    def selected(self) -> set[str]:
        return set(self._sel)

    def clear_selection(self, emit: bool = False):
        self._sel.clear()
        self._show_summary()
        if emit:
            self.selectionChanged.emit()

    # -- display
    def _summary(self) -> str:
        n = len(self._sel)
        if not n:
            return self.all_text
        if n == 1:
            return next(iter(self._sel))
        return f"{n} {self.noun_one}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    def _show_summary(self):
        self.blockSignals(True)
        self.clear()
        self.addItem(self._summary())
        self.setCurrentIndex(0)
        self.setToolTip("\n".join(sorted(self._sel)) if len(self._sel) > 1 else "")
        self.blockSignals(False)

    def _selection_changed(self):
        self._show_summary()
        self.selectionChanged.emit()

    # -- pop-up
    def showPopup(self):
        if self._panel is None:
            self._panel = _Panel(self)
        p = self._panel
        p.fill()
        width = max(self.width(), 340)
        p.resize(width, 380)
        pos = self.mapToGlobal(QPoint(self.width() - width if self.layoutDirection() == Qt.RightToLeft else 0, self.height() + 2))
        p.move(pos)
        p.show()
        p.search.setFocus()

    def hidePopup(self):
        if self._panel is not None:
            self._panel.close()
