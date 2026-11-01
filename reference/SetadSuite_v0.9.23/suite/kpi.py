"""Compact KPI strip shared by the purchase and tender pages (same look, different numbers)."""
from __future__ import annotations

import weakref

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from . import design

_LIVE: "weakref.WeakSet[KpiStrip]" = weakref.WeakSet()


def fa(n) -> str:
    try:
        s = f'{int(n):,}'.replace(',', '٬')
    except Exception:
        s = str(n)
    return s.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


class KpiStrip(QWidget):
    """labels: list of captions; set_values(list of numbers) fills them. A caption may be clickable (callback)."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.setObjectName('KpiStrip')
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedHeight(42)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._cards = []
        for cap in labels:
            f = QFrame()
            f.setObjectName('KpiCard')
            h = QHBoxLayout(f)
            h.setContentsMargins(16, 0, 16, 0)
            h.setSpacing(8)
            n = QLabel('—')
            n.setObjectName('KpiNum')
            c = QLabel(cap)
            c.setObjectName('KpiCap')
            h.addWidget(n)
            h.addWidget(c)
            h.addStretch()
            lay.addWidget(f, 1)
            self._cards.append((f, n, c))
        _LIVE.add(self)
        self.restyle()

    def set_values(self, values):
        for (f, n, c), v in zip(self._cards, values):
            n.setText('—' if v is None else fa(v))

    def restyle(self):
        t = design.tokens()
        self.setStyleSheet(
            f"QFrame#KpiCard{{background:{t['card']};border:1px solid {t['border']};border-radius:12px;}}"
            f"QLabel#KpiNum{{font-size:15pt;font-weight:800;color:{t['text']};background:transparent;}}"
            f"QLabel#KpiCap{{font-size:9.5pt;color:{t['muted']};background:transparent;}}")

    @staticmethod
    def restyle_all():
        for k in list(_LIVE):
            try:
                k.restyle()
            except RuntimeError:
                pass
