"""One compact confirmation dialog shared by the whole app (replaces QMessageBox for add / remove / waive / delete).

Drop-in subset of the QMessageBox API: setIcon / setWindowTitle / setText / setInformativeText / addButton(text, role)
/ setDefaultButton / exec / clickedButton. Fixed 420 px width, height follows the text — no empty space."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .theme import C


class CompactBox(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setFixedWidth(420)
        self._icon = QMessageBox.Question
        self._clicked = None
        self._default = None
        self._buttons = []
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(8)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setStyleSheet('font-weight:700; font-size:11pt;')
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setStyleSheet(f"color:{C['muted']};")
        self._info.hide()
        v.addWidget(self._text)
        v.addWidget(self._info)
        self._row = QHBoxLayout()
        self._row.setSpacing(8)
        self._row.addStretch()
        v.addSpacing(6)
        v.addLayout(self._row)

    def setIcon(self, icon):
        self._icon = icon

    def setText(self, t):
        self._text.setText(t)

    def setInformativeText(self, t):
        self._info.setText(t)
        self._info.setVisible(bool(t))

    def addButton(self, text, role=QMessageBox.AcceptRole):
        b = QPushButton(text)
        b.setMinimumHeight(36)
        b.setCursor(Qt.PointingHandCursor)
        if role in (QMessageBox.DestructiveRole,):
            b.setStyleSheet(f"QPushButton{{background:{C['red']};color:#fff;border:0;border-radius:9px;padding:0 16px;font-weight:700;}}")
        elif role in (QMessageBox.AcceptRole, QMessageBox.YesRole):
            b.setStyleSheet(f"QPushButton{{background:{C['primary']};color:#fff;border:0;border-radius:9px;padding:0 16px;font-weight:700;}}")
        b.clicked.connect(lambda _=False, b=b: (setattr(self, '_clicked', b), self.accept()))
        self._row.insertWidget(1 if False else self._row.count(), b)
        self._buttons.append(b)
        if self._default is None:
            self._default = b
        return b

    def setDefaultButton(self, b):
        self._default = b

    def clickedButton(self):
        return self._clicked

    def exec(self):
        # every button gets the same width and height (the widest label decides)
        w = max([b.sizeHint().width() for b in self._buttons] + [110])
        for b in self._buttons:
            b.setFixedSize(w, 38)
        if self._default is not None:
            self._default.setDefault(True)
            self._default.setFocus()
        self.adjustSize()
        return super().exec()
