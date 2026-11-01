"""Setadiran Manager — Persian (RTL) Windows desktop app built on Qt / PySide6.

Installation: run setup_windows.bat, then run_windows.bat.
The real procurement website is accessed only in the user's own browser
session; no account passwords are requested or transmitted to this app.

Main parts
  * «فهرست نیازها»: the needs board read from Setad, with filters, stars, «جدید» badges,
    live deadlines and details opening directly under each row.
  * «تابلوی پیگیری»: kanban of the follow-up funnel; each card opens the case window
    (review → RFQs to suppliers → final choice & pricing → proforma → submission & result).
  * «تأمین‌کنندگان» and «صرف‌نظرشده».
  Everything is kept in a local SQLite database (%LOCALAPPDATA%\\SetadiranManager\\setadiran.db).
"""
from __future__ import annotations

import queue
from functools import lru_cache
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QAbstractItemModel, QByteArray, QModelIndex, QPoint, QPointF, QRectF, QSettings, QSize,
    QSortFilterProxyModel, Qt, QTimer, QUrl,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTabWidget, QTreeView, QVBoxLayout,
    QWidget,
)
from setad_tender.compact_box import CompactBox
from setad_tender.widgets import fa_digits

import jalali
import pipeline as P
from db import Store
from parser import Need, western_digits
from multipick import MultiCombo
from storage import export_csv
from ui_board import ArchiveView, BoardView, RejectDialog
from ui_case import CaseWindow
from ui_detail import DetailCard
from ui_kit import (
    C, StatBlock, app_home, build_stylesheet, button, card_frame, clean_need, fa, hline, label, load_fonts,
    make_icon, make_icon_label, need_group, norm, rtl, status_colors, tint, vline,
)
from ui_settings import SettingsDialog
from ui_suppliers import SuppliersView

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def num(value) -> str:
    """v0.9.13: Persian digits + thousands separator (۸٬۷۵۷), same as the tender page."""
    try:
        return f"{int(value or 0):,}".translate(_FA_DIGITS).replace(",", "٬")
    except (TypeError, ValueError):
        return str(value or "")

APP_NAME = "مدیریت نیازهای ستاد"
APP_VERSION = "0.5"
SETTINGS_VERSION = 6  # bump when the column set changes so saved widths are discarded

# ---------------------------------------------------------------- list model
COLUMNS = [
    # key, header, default width, alignment
    ("select", "☐", 44, "center"),
    ("star", "★", 56, "center"),
    ("row", "ردیف", 56, "center"),
    ("need_no", "شماره نیاز", 148, "center"),
    ("description", "شرح نیاز", 360, "start"),
    ("organization", "دستگاه خریدار", 190, "start"),
    ("province", "استان", 100, "center"),
    ("category", "نوع", 64, "center"),
    ("group", "گروه کالا / خدمت", 165, "start"),
    ("published", "تاریخ اعلام", 96, "center"),
    ("deadline", "مهلت پاسخ", 128, "center"),
    ("docs", "اسناد", 84, "center"),
    ("status", "مرحله / وضعیت", 176, "center"),
]
COL = {key: i for i, (key, *_rest) in enumerate(COLUMNS)}
# purchase list (embedded) shows the same default columns as the tender list; the rest come from «ستون‌ها»
DEFAULT_HIDDEN = ("row", "organization", "province", "category", "group", "published", "docs")
SORT_ROLE = Qt.UserRole + 1
_norm_cached = lru_cache(maxsize=60000)(norm)
NEED_ROLE = Qt.UserRole + 2
KIND_ROLE = Qt.UserRole + 3
_FLAGS_NONE = Qt.NoItemFlags            # v0.9.10: built once (combining enum flags per call was slow)
_FLAGS_DETAIL = Qt.ItemIsEnabled
_FLAGS_ROW = Qt.ItemIsEnabled | Qt.ItemIsSelectable


class NeedModel(QAbstractItemModel):
    """v0.9.11: holds only the CURRENT PAGE of the list (the whole list, filtering, sorting and paging live in ManagerUI).
    Qt's tree view asks the model about every row on each layout, so thousands of rows made it freeze.
    Every need on the page has exactly one child row that hosts its detail card (standalone mode only)."""

    def __init__(self, ui: "ManagerUI"):
        super().__init__()
        self.ui = ui
        self.needs: list[Need] = []
        self.pos: dict[str, int] = {}      # need_no -> row within the page
        self.offset = 0                    # position of the page's first row in the whole (filtered) list
        self.status: dict[str, str] = {}   # transient download status per need (all needs)
        self._alert = make_icon("alert", C["danger"], 16)

    # -- structure
    def index(self, row, column, parent=QModelIndex()):
        if column < 0 or column >= len(COLUMNS):
            return QModelIndex()
        if parent.isValid():
            if parent.internalId() != 0 or row != 0:
                return QModelIndex()
            return self.createIndex(0, column, parent.row() + 1)
        if 0 <= row < len(self.needs):
            return self.createIndex(row, column, 0)
        return QModelIndex()

    def parent(self, index=QModelIndex()):
        if not index.isValid() or index.internalId() == 0:
            return QModelIndex()
        return self.createIndex(index.internalId() - 1, 0, 0)

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self.needs)
        if parent.internalId() == 0 and parent.column() == 0:
            return 0 if self.ui.embedded else 1      # v0.9.1: no detail row under a need — the side panel shows it
        return 0

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return COLUMNS[section][1]
        if role == Qt.ToolTipRole and COLUMNS[section][0] == "star":
            return rtl("ستاره = اضافه شدن به پرونده‌های من")
        if role == Qt.ToolTipRole and COLUMNS[section][0] == "select":
            return rtl("انتخاب همهٔ ردیف‌های دیده‌شده / لغو انتخاب")
        return None

    def flags(self, index):
        if not index.isValid():
            return _FLAGS_NONE
        if index.internalId() != 0:
            return _FLAGS_DETAIL
        return _FLAGS_ROW

    def need_at(self, index) -> Need | None:
        if not index.isValid():
            return None
        row = index.row() if index.internalId() == 0 else index.internalId() - 1
        return self.needs[row] if 0 <= row < len(self.needs) else None

    def _display(self, need: Need, key: str, row: int) -> str:
        nn = need.need_no
        if key in ("select", "star"):
            return ""
        if key == "row":
            return str(self.offset + row + 1).translate(_FA_DIGITS)
        if key == "need_no":
            return nn
        if key == "description":
            return need.description
        if key == "organization":
            return need.organization
        if key == "province":
            return need.province
        if key == "category":
            return need.category
        if key == "group":
            return need_group(need)
        if key == "published":
            return need.published_date
        if key == "deadline":
            return self.ui.remaining_for(nn) or need.response_deadline
        if key == "docs":
            return self.ui.dl_text(nn)
        if key == "status":
            st = self.status.get(nn)
            if st and "در حال" in st:
                return st
            stage = self.ui.stage_of(nn)
            if stage:
                return P.STAGE_TITLE[stage]
            return st or ""
        return ""

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if index.internalId() != 0:
            if role == KIND_ROLE:
                return "detail"
            if role == NEED_ROLE:
                need = self.need_at(index)
                return need.need_no if need else None
            return None
        need = self.needs[index.row()]
        key = COLUMNS[index.column()][0]
        nn = need.need_no
        if role == Qt.DisplayRole:
            return "" if key == "star" else self._display(need, key, index.row())
        if role == KIND_ROLE:
            return "need"
        if role == NEED_ROLE:
            return nn
        if role == Qt.ToolTipRole:
            if key == "star":
                stage = self.ui.stage_of(nn)
                return rtl(f"مرحله: {P.STAGE_TITLE[stage]}" if stage else "افزودن به ستاره‌دارها")
            if key == "description":
                warns = self.ui.warnings_for(nn)
                return rtl(need.description + (f"\n⚠ هشدار: {'، '.join(warns)}" if warns else ""))
            if key in ("organization", "group"):
                text = self._display(need, key, index.row())
                return rtl(text) if text else None
            if key == "docs" and self.ui.dl_count(nn):
                st, n, total = self.ui.dl_state(nn)
                dg = lambda x: str(x).translate(_FA_DIGITS)
                return rtl(f"{dg(n)} از {dg(total)} فایل دانلود شده است." + ("" if st == "complete" else " دوباره دانلود کنید تا کامل شود."))
            if key == "row" and nn in self.ui.new_needs:
                return rtl("از دریافت قبلی به بعد اضافه شده")
        if role == Qt.DecorationRole and key == "description" and self.ui.warnings_for(nn):
            return self._alert
        if role == Qt.TextAlignmentRole:
            align = COLUMNS[index.column()][3]
            return int((Qt.AlignCenter if align == "center" else Qt.AlignLeading) | Qt.AlignVCenter)
        if role == Qt.FontRole and (key == "need_no" or (key == "description" and nn in self.ui.new_needs)):
            f = QFont()
            f.setWeight(QFont.DemiBold)
            return f
        if role == Qt.ForegroundRole and key in ("row", "published", "category"):
            return QColor(C["muted"])
        if role == Qt.ForegroundRole and key == "docs":
            return QColor(C["ok"] if self.ui.dl_state(nn)[0] == "complete" else C["warn"])
        if role == SORT_ROLE:
            if key == "select":
                return 0 if nn in self.ui.checked else 1
            if key == "star":
                stage = self.ui.stage_of(nn)
                return 0 if stage and stage != P.REJECTED else (2 if not stage else 1)
            if key == "row":
                return index.row()
            if key == "deadline":
                h = self.ui.remaining_hours_for(nn)
                return h if h is not None else 1e9
            if key == "docs":
                return -self.ui.dl_rank(nn)
            if key == "status":
                stage = self.ui.stage_of(nn)
                return P.STAGE_KEYS.index(stage) if stage in P.STAGE_KEYS else (90 if stage else 99)
            if key in ("need_no", "published"):
                return western_digits(self._display(need, key, index.row()))
            return self._display(need, key, index.row())
        return None

    # -- mutations
    def set_rows(self, needs: list[Need], offset: int = 0):
        self.beginResetModel()
        self.needs = list(needs)
        self.pos = {n.need_no: i for i, n in enumerate(self.needs)}
        self.offset = offset
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        # the header asks for a sort: ManagerUI sorts the whole list and re-cuts the page
        self.ui._sort_changed(column, order)

    def set_status(self, need_no: str, status: str):
        self.status[need_no] = status
        self.refresh_row(need_no)

    def refresh_row(self, need_no: str):
        row = self.pos.get(need_no)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def refresh_columns(self, *keys):
        if self.needs:
            for k in keys:
                c = COL[k]
                self.dataChanged.emit(self.index(0, c), self.index(len(self.needs) - 1, c))


# ---------------------------------------------------------------- delegate
class NeedDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 44

    def __init__(self, view: "NeedTree", ui: "ManagerUI"):
        super().__init__(view)
        self.view = view
        self.ui = ui

    def detail_width(self) -> int:
        return max(320, self.view.header().length() - self.view.indentation() - 2)

    def sizeHint(self, option, index):
        if index.data(KIND_ROLE) == "detail":
            widget = self.view.indexWidget(index)
            width = self.detail_width()
            if widget is None:
                return QSize(width, 1)
            height = widget.heightForWidth(width) if widget.hasHeightForWidth() else -1
            return QSize(width, max(height, widget.sizeHint().height()) if height < 0 else height)
        base = super().sizeHint(option, index)
        return QSize(base.width(), 54 if self.ui.embedded else self.ROW_HEIGHT)

    def _base(self, painter, option, index) -> QStyleOptionViewItem:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        opt.text = text
        return opt

    def _pill(self, painter, opt, text, fg, bg, dy: float = 0):
        font = QFont(opt.font)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
        font.setWeight(QFont.DemiBold)
        fm = QFontMetrics(font)
        h = fm.height() + 6
        w = min(fm.horizontalAdvance(text) + 22, opt.rect.width() - 10)
        rect = QRectF(opt.rect.center().x() - w / 2 + 1, opt.rect.center().y() - h / 2 + 1 + dy, w, h)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setLayoutDirection(Qt.RightToLeft)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(QColor(fg))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, int(w - 14)))
        painter.restore()

    def _chip(self, painter, opt, text, fg, bg, h=24, bold=False, dy=0, pad=20, small=False, dashed=False):
        """v0.9.1: the tender list's chip (rounded rectangle, radius 7) so both lists look the same."""
        font = QFont(opt.font)
        if small:
            font.setPointSizeF(max(7.5, font.pointSizeF() - 1.4))
        if bold:
            font.setWeight(QFont.DemiBold)
        fm = QFontMetrics(font)
        text = fm.elidedText(text, Qt.ElideRight, max(20, opt.rect.width() - 10 - pad))
        w = fm.horizontalAdvance(text) + pad
        rect = QRectF(opt.rect.center().x() - w / 2, opt.rect.center().y() - h / 2 + dy, w, h)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if dashed:
            pen = QPen(QColor(C["border_strong"]))
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(fg))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _paint_embedded(self, painter, option, index, key, nn) -> bool:
        """v0.9.1: the same row anatomy as the tender list (two lines, blue number, deadline chip with its date)."""
        if key not in ("select", "star", "need_no", "description", "deadline", "status", "docs"):
            return False
        opt = self._base(painter, option, index)
        r = opt.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        pass  # painter direction inherited from the app (RTL)
        painter.setPen(QColor(C["divider"]))
        painter.drawLine(r.bottomLeft(), r.bottomRight())
        need = self.ui.need_obj(nn)
        if key == "select":
            on = nn in self.ui.checked
            box = QRectF(r.center().x() - 8, r.center().y() - 8, 16, 16)
            painter.setPen(QPen(QColor(C["primary"] if on else "#98A2B3"), 1.5))
            painter.setBrush(QColor(C["primary"]) if on else QColor(C["card"]))
            painter.drawRoundedRect(box, 4, 4)
            if on:
                painter.setPen(QPen(QColor("#FFFFFF"), 2))
                painter.drawLine(box.left() + 3.5, box.center().y() + 0.5, box.center().x() - 1, box.bottom() - 4)
                painter.drawLine(box.center().x() - 1, box.bottom() - 4, box.right() - 3, box.top() + 4)
        elif key == "star":
            stage = self.ui.stage_of(nn)
            painter.setFont(QFont(opt.font))
            if stage and stage != P.REJECTED:
                painter.setPen(QColor("#F79009"))
                painter.drawText(r, Qt.AlignCenter, "★")
            else:
                painter.setPen(QColor("#98A2B3" if stage else "#C0C7D2"))
                painter.drawText(r, Qt.AlignCenter, "☆")
        elif key == "need_no":
            f = QFont(opt.font)
            f.setWeight(QFont.DemiBold)
            painter.setFont(f)
            painter.setPen(QColor(C["primary"]))
            painter.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignCenter, fa_digits(nn))
        elif key == "description" and need is not None:
            inner = r.adjusted(10, 7, -10, -7)
            f1 = QFont(opt.font)
            f1.setWeight(QFont.DemiBold)
            fm1 = QFontMetrics(f1)
            f2 = QFont(opt.font)
            f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.2))
            fm2 = QFontMetrics(f2)
            title = (need.description or "").replace("\n", " ").strip()
            warn = self.ui.warnings_for(nn)
            if warn:
                title = "⚠ " + title
            sub = " • ".join(x for x in (need.organization, need.province) if x)
            painter.setFont(f1)
            painter.setPen(QColor(C["text"]))
            painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), fm1.height() + 2),
                             Qt.AlignLeading | Qt.AlignVCenter, fm1.elidedText(fa_digits(title), Qt.ElideRight, inner.width()))
            painter.setFont(f2)
            painter.setPen(QColor(C["muted"]))
            painter.drawText(QRectF(inner.left(), inner.top() + fm1.height() + 4, inner.width(), fm2.height() + 2),
                             Qt.AlignLeading | Qt.AlignVCenter, fm2.elidedText(fa_digits(sub), Qt.ElideRight, inner.width()))
        elif key == "deadline" and need is not None:
            hours = self.ui.remaining_hours_for(nn)
            text = self.ui.remaining_for(nn)
            painter.restore()
            if text:
                fg, bg = self.ui.deadline_colors(hours)
                self._chip(painter, opt, text, fg, bg, h=20, bold=True, dy=-9, pad=16)
            painter.save()
            f2 = QFont(opt.font)
            f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.4))
            painter.setFont(f2)
            painter.setPen(QColor(C["muted"]))
            painter.drawText(QRectF(r.left(), r.center().y() + 5, r.width(), 16), Qt.AlignCenter, fa_digits(need.response_deadline or ""))
        elif key == "docs":
            st, n, total = self.ui.dl_state(nn)
            painter.restore()
            if st == "complete":
                self._chip(painter, opt, "کامل", C["ok"], C["ok_soft"], h=22, bold=True, pad=18)
            elif st == "partial":
                self._chip(painter, opt, "ناقص", C["warn"], C["warn_soft"], h=20, bold=True, dy=-9, pad=18)
                f2 = QFont(opt.font)
                f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.4))
                painter.save()
                painter.setFont(f2)
                painter.setPen(QColor(C["muted"]))
                painter.drawText(QRectF(r.left(), r.center().y() + 5, r.width(), 16), Qt.AlignCenter,
                                 f"{n} از {total}".translate(_FA_DIGITS))
                painter.restore()
            painter.save()
        elif key == "status":
            painter.restore()
            text = opt.text
            if text:
                stage = self.ui.stage_of(nn)
                if stage and text == P.STAGE_TITLE[stage]:
                    color = P.STAGE_COLOR[stage]
                    self._chip(painter, opt, text, color, tint(color, 0.13), small=True)
                else:
                    fg, bg = status_colors(text)
                    self._chip(painter, opt, text, fg, bg, small=True)
            elif need is not None:
                self._chip(painter, opt, "افزوده‌نشده", C["muted"], C["card"], small=True, dashed=True)
            painter.save()
        painter.restore()
        return True

    def paint(self, painter, option, index):
        if index.data(KIND_ROLE) == "detail":
            painter.fillRect(option.rect, QColor(C["primary_soft_2"]))
            return
        key = COLUMNS[index.column()][0]
        nn = index.data(NEED_ROLE)
        if self.ui.embedded and self._paint_embedded(painter, option, index, key, nn):
            return
        if key == "star":
            opt = self._base(painter, option, index)
            stage = self.ui.stage_of(nn)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            f = QFont(opt.font)
            f.setPointSizeF(15)
            painter.setFont(f)
            if stage and stage != P.REJECTED:
                painter.setPen(QColor("#F79009"))
                painter.drawText(opt.rect, Qt.AlignCenter, "★")
            else:
                painter.setPen(QColor("#98A2B3" if stage else "#C0C7D2"))
                painter.drawText(opt.rect, Qt.AlignCenter, "☆")
            painter.restore()
            return
        if key == "row" and nn in self.ui.new_needs:
            # v0.9.9: keep the row number and mark a new row with a small dot (the «جدید» pill used to hide the number)
            super().paint(painter, option, index)
            r = option.rect
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(C["primary"]))
            painter.drawEllipse(QPointF(r.right() - 9, r.center().y()), 3.5, 3.5)
            painter.restore()
            return
        if key == "deadline":
            opt = self._base(painter, option, index)
            if opt.text:
                hours = self.ui.remaining_hours_for(nn)
                fg, bg = self.ui.deadline_colors(hours)
                self._pill(painter, opt, opt.text, fg, bg)
            return
        if key == "status":
            opt = self._base(painter, option, index)
            if opt.text:
                stage = self.ui.stage_of(nn)
                if stage and opt.text == P.STAGE_TITLE[stage]:
                    color = P.STAGE_COLOR[stage]
                    self._pill(painter, opt, opt.text, color, tint(color, 0.13))
                else:
                    fg, bg = status_colors(opt.text)
                    self._pill(painter, opt, opt.text, fg, bg)
            return
        super().paint(painter, option, index)


class NeedTree(QTreeView):
    def __init__(self):
        super().__init__()
        self._last_width = -1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.width() != self._last_width:
            self._last_width = self.width()
            QTimer.singleShot(0, self.doItemsLayout)


# ---------------------------------------------------------------- main window
class ManagerUI(QMainWindow):
    def __init__(self, engine_factory: Callable | None = None, db_path: Path | None = None, embedded: bool = False):
        super().__init__()
        self.embedded = embedded  # True inside «سامانه مناقصات و استعلام‌های ستاد»
        self.setWindowTitle(f"{APP_NAME} — نسخه {APP_VERSION}")
        self.setWindowIcon(make_icon("app", C["primary"], 64))
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1480, 900)
        self.setMinimumSize(1180, 700)

        self.settings = QSettings("SetadiranManager", "SetadiranManager")
        self.home_dir = app_home()
        self.home_dir.mkdir(parents=True, exist_ok=True)
        default_out = self.home_dir / "Setadiran"
        saved_dir = self.settings.value("output_dir", "", str)
        self.output_dir = Path(saved_dir) if saved_dir else default_out
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(db_path or (self.home_dir / "setadiran.db"))

        self.tasks: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        if engine_factory is None:
            from engine import BrowserEngine
            engine_factory = BrowserEngine
        self.worker = engine_factory(self.tasks, self.events, self.cancel, self.home_dir)
        self.worker.start()

        self.detail_errors: dict[str, dict] = {}
        self._dl_counts: dict[str, int] = {}     # v0.9.18: need_no -> downloaded file count
        self._dl_info: dict[str, tuple] = {}
        self.detail_pending: set[str] = set()
        self.expanded: set[str] = set()
        self.search_text: dict[str, str] = {}
        self.meta: dict[str, dict] = {}
        self.stages: dict[str, str] = self.store.case_stages()
        self.new_needs: set[str] = set()
        self.checked: set[str] = set()         # ticked rows (batch actions)
        self._warn_cache: dict[str, list[str]] = {}
        self.case_windows: dict[str, CaseWindow] = {}
        self.busy = False
        self.browser_opened = False
        self.pages_read = 0
        self._has_prev_refresh = False
        self._shutting_down = False
        self._last_toggle = (None, 0.0)
        self._last_heavy = 0.0                 # v0.9.10: heavy list work is throttled while pages are still arriving
        self._heavy_pending = False
        self._fv_sig = None
        self._open_cache = (None, 0)

        # v0.9.11: the whole list lives here, the table model only gets the current page
        self.all_needs: list[Need] = []
        self.all_pos: dict[str, int] = {}
        self.visible: list[Need] = []          # filtered + sorted
        self.page = 0
        self.page_size = 200
        self._predicate = None
        self._sort = (-1, Qt.AscendingOrder)
        self._ready = False

        self.model = NeedModel(self)

        self._build()
        self._restore_settings()

        self.filter_timer = QTimer(self, singleShot=True, interval=180)
        self.filter_timer.timeout.connect(self._apply_filters)
        self.poll_timer = QTimer(self, interval=120)
        self.poll_timer.timeout.connect(self._poll_events)
        self.poll_timer.start()
        self.clock = QTimer(self, interval=60_000)
        self.clock.timeout.connect(self._tick)
        self.clock.start()

        self._ready = True
        QTimer.singleShot(0, self.scan_downloads)
        self._load_last_list()
        self._rebuild_visible()
        self._log("این نسخه آزمایشی است. ورود دستی و مجوز دسترسی خودتان به سایت الزامی است.")
        self._update_counts()

    # ------------------------------------------------------------ data access used by other views
    def need_obj(self, need_no: str) -> Need | None:
        row = self.all_pos.get(need_no)
        if row is not None:
            return self.all_needs[row]
        need = self.store.get_need(need_no)
        return clean_need(need) if need else None

    def detail_payload(self, need_no: str) -> dict | None:
        return self.store.get_detail(need_no) or self.detail_errors.get(need_no)

    def detail_pending_for(self, need_no: str) -> bool:
        return need_no in self.detail_pending

    def _meta_for(self, need_no: str) -> dict:
        m = self.meta.get(need_no)
        if m is None:
            m = self.store.need_meta([need_no]).get(need_no, {})
            self.meta[need_no] = m
        return m

    def remaining_hours_for(self, need_no: str) -> float | None:
        return P.remaining_hours(self._meta_for(need_no).get("deadline_at"))

    def remaining_for(self, need_no: str) -> str:
        return P.remaining_text(self._meta_for(need_no).get("deadline_at"))

    @staticmethod
    def deadline_colors(hours: float | None) -> tuple[str, str]:
        if hours is None:
            return C["neutral"], C["neutral_soft"]
        if hours <= 48:
            return C["danger"], C["danger_soft"]
        if hours <= 96:
            return C["warn"], C["warn_soft"]
        return C["ok"], C["ok_soft"]

    def stage_of(self, need_no: str) -> str | None:
        return self.stages.get(need_no)

    def warnings_for(self, need_no: str) -> list[str]:
        if need_no in self._warn_cache:
            return self._warn_cache[need_no]
        keywords = self.store.get("warn_keywords") or []
        result = []
        if keywords:
            need = self.need_obj(need_no)
            if need:
                payload = self.store.get_detail(need_no) or {}
                result = P.find_keywords(P.need_text_for_scan(need, payload.get("info")), keywords)
        self._warn_cache[need_no] = result
        return result

    def need_folder(self, need_no: str) -> Path:
        folder = self.output_dir / need_no
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def attachment_path(self, need_no: str, name: str):
        """v0.9.14: downloaded copy of an attachment (None if not downloaded); never creates folders."""
        from ui_preview import find_local
        return find_local(self.output_dir / need_no, name)

    def dl_count(self, need_no: str) -> int:
        return self._dl_counts.get(need_no, 0)

    def dl_state(self, need_no: str):
        """(«none» | «partial» | «complete», downloaded, expected)."""
        return self._dl_info.get(need_no, ("none", 0, 0))

    def dl_rank(self, need_no: str) -> int:
        return {"complete": 2, "partial": 1}.get(self.dl_state(need_no)[0], 0)

    def dl_text(self, need_no: str) -> str:
        st, n, total = self.dl_state(need_no)
        dg = lambda x: str(x).translate(_FA_DIGITS)
        return "" if st == "none" else "کامل" if st == "complete" else f"ناقص {dg(n)} از {dg(total)}"

    def _dl_state_of(self, need_no: str):
        """v0.9.19: complete when every attachment the site listed is on disk. The expected number comes from what was
        recorded at download time, else from the stored need details, else from the manifest itself (a file that was
        deleted by hand still counts as expected)."""
        from storage import load_manifest, recorded_attachment_total
        folder = self.output_dir / need_no
        manifest = load_manifest(folder) if folder.is_dir() else {}
        have = missing = 0
        for entry in manifest.values():
            f = entry.get("saved_as") if isinstance(entry, dict) else None
            if not f:
                continue
            if (folder / Path(f).name).is_file():
                have += 1
            else:
                missing += 1
        if not have:
            return "none", 0, 0
        expected = recorded_attachment_total(folder)
        if not expected:
            payload = self.store.get_detail(need_no)
            att = (payload or {}).get("attachments")
            expected = len(att) if isinstance(att, list) and att else 0
        expected = max(expected or 0, have + missing)
        return ("complete" if have >= expected else "partial"), have, expected

    def scan_downloads(self):
        """v0.9.18/19: downloaded count and complete/partial per need (one pass over the save folder; manifests only)."""
        import os
        counts, info = {}, {}
        try:
            with os.scandir(self.output_dir) as it:
                for e in it:
                    if e.is_dir() and e.name.isdigit():
                        st = self._dl_state_of(e.name)
                        if st[0] != "none":
                            counts[e.name] = st[1]
                            info[e.name] = st
        except OSError:
            pass
        self._dl_counts, self._dl_info = counts, info
        self.model.refresh_columns("docs")
        self._update_counts()
        if self.only_dl.isChecked():
            self._rebuild_visible()

    def _refresh_dl(self, need_no: str):
        st = self._dl_state_of(need_no)
        if st[0] != "none":
            self._dl_counts[need_no] = st[1]
            self._dl_info[need_no] = st
        else:
            self._dl_counts.pop(need_no, None)
            self._dl_info.pop(need_no, None)
        self.model.refresh_row(need_no)
        self._update_counts()
        if self.only_dl.isChecked():
            self._rebuild_visible()

    def downloaded_files(self, need_no: str) -> list[Path]:
        """v0.9.17: files the app itself downloaded for this need (from its manifest); never creates folders."""
        from storage import load_manifest, manifest_path
        folder = self.output_dir / need_no
        out = []
        if folder.is_dir():
            for entry in load_manifest(folder).values():
                f = entry.get("saved_as") if isinstance(entry, dict) else None
                if f and (folder / Path(f).name).is_file():
                    out.append(folder / Path(f).name)
        return out

    def open_download_folder(self, need_no: str):
        """v0.9.20: opens this need's own folder (never creates it)."""
        folder = self.output_dir / need_no
        if folder.is_dir():
            self._open_directory(str(folder))
        else:
            self._set_info("پوشهٔ این نیاز هنوز ساخته نشده؛ اول پیوست‌ها را دانلود کنید.")

    def downloaded_names(self, need_no: str) -> list[str]:
        """Original attachment names of the downloaded files (for the files tab when the site data is unavailable)."""
        from storage import load_manifest
        folder = self.output_dir / need_no
        out = []
        if folder.is_dir():
            for entry in load_manifest(folder).values():
                if isinstance(entry, dict) and entry.get("saved_as") and (folder / Path(entry["saved_as"]).name).is_file():
                    out.append(entry.get("original_name") or entry["saved_as"])
        return out

    def delete_downloads(self, need_no: str, ask: bool = True) -> bool:
        """«حذف فایل‌های دانلودشده»: removes what the app downloaded (+ its manifest) and the folder if nothing else is in it;
        the need's status goes back to «not downloaded». Star, work stage and notes are untouched."""
        from storage import manifest_path
        files = self.downloaded_files(need_no)
        folder = self.output_dir / need_no
        if not files:
            self._set_info("فایل دانلودشده‌ای برای این نیاز نیست.")
            self._forget_download_status(need_no)
            self._refresh_dl(need_no)
            return False
        if ask:
            box = CompactBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("حذف فایل‌های دانلودشده")
            box.setText(rtl(f"{fa(len(files))} فایل دانلودشدهٔ نیاز {fa(need_no)} از روی رایانه حذف شود؟"))
            box.setInformativeText(rtl("فقط فایل‌هایی که خود برنامه دانلود کرده پاک می‌شوند. ستاره و پرونده دست نمی‌خورد و "
                                       "هر وقت خواستید دوباره دانلود می‌کنید."))
            yes = box.addButton("بله، حذف کن", QMessageBox.YesRole)
            box.addButton("انصراف", QMessageBox.NoRole)
            box.exec()
            if box.clickedButton() is not yes:
                return False
        failed = 0
        for f in files:
            try:
                f.unlink()
            except OSError:
                failed += 1
        if not failed:
            for extra in (manifest_path(folder), folder / ".download_info.json"):
                try:
                    extra.unlink()
                except OSError:
                    pass
        try:
            folder.rmdir()                       # only succeeds when empty — anything else in it is left alone
            left = False
        except OSError:
            left = folder.is_dir()
        self._forget_download_status(need_no)
        self._refresh_dl(need_no)
        if self.store.get_case(need_no):
            self.store.add_event(need_no, "فایل‌های دانلودشده حذف شد")
        msg = f"{fa(len(files) - failed)} فایل حذف شد."
        if failed:
            msg += f" {fa(failed)} فایل حذف نشد (شاید باز است)."
        elif left:
            msg += " پوشه چون فایل دیگری هم دارد نگه داشته شد."
        self._set_info(msg)
        self.refresh_views()
        for win in self.case_windows.values():
            win.reload()
        return not failed

    def _forget_download_status(self, need_no: str):
        """Drop the stale «بررسی/دانلود تکمیل» text of a need whose files are gone."""
        if self.model.status.pop(need_no, None) is not None:
            self.model.refresh_row(need_no)

    def sync_download_status(self, need_no: str):
        """v0.9.17: the stored status says «downloaded» but the folder was removed by hand → back to «not downloaded»."""
        if self._dl_info.get(need_no, ("none", 0, 0)) != self._dl_state_of(need_no):
            self._refresh_dl(need_no)             # the docs column follows the disk
        st = self.model.status.get(need_no) or ""
        if st in ("بررسی/دانلود تکمیل", "تکمیل با خطا") and not (self.output_dir / need_no).is_dir():
            self._forget_download_status(need_no)

    def open_preview(self, need_no: str, names: list[str], current: str):
        from ui_preview import open_preview
        if open_preview(self, need_no, names, current) is None:
            self._set_info("این سند هنوز دانلود نشده؛ اول پیوست‌های نیاز را دانلود کنید.")

    def board_items(self) -> list[dict]:
        cases = self.store.cases(set(P.STAGE_KEYS))
        counts = self.store.rfq_counts()
        nos = [c["need_no"] for c in cases]
        meta = self.store.need_meta(nos)
        self.meta.update(meta)
        items = []
        for c in cases:
            need = self.need_obj(c["need_no"])
            if need is None:
                continue
            d = c["data"]
            stage = c["stage"]
            meta_text, colors = "", None
            if stage == "review":
                checks = d.get("checklist") or {}
                total = len(self.store.get("checklist"))
                done = sum(1 for v in checks.values() if v) if isinstance(checks, dict) else 0
                meta_text = f"بررسی {done}/{total}"
                if done and done >= total:
                    colors = (C["ok"], C["ok_soft"])
            elif stage in ("rfq_ready", "rfq"):
                n, a = counts.get(c["need_no"], (0, 0))
                meta_text = f"{n} استعلام · {a} پاسخ" if n else "هنوز استعلامی ارسال نشده"
                if a:
                    colors = (C["info"], C["info_soft"])
            elif stage == "final":
                grand = (d.get("totals") or {}).get("grand")
                meta_text = f"قیمت نهایی: {P.money(grand)} ریال" if grand and d.get("final_rfq") else "تأمین‌کننده انتخاب نشده"
                if d.get("proforma", {}).get("docx"):
                    meta_text += " · پیش‌فاکتور ✓"
                    colors = (C["ok"], C["ok_soft"])
            elif stage == "submitted":
                meta_text = f"ارسال: {jalali.fmt_stamp(d.get('submitted_at'), with_time=False)}"
                if d.get("submitted_amount"):
                    meta_text += f" · {P.money(d['submitted_amount'])} ریال"
            elif stage == "result":
                res = d.get("result")
                meta_text = dict(P.RESULTS).get(res, "")
                colors = {"won": (C["ok"], C["ok_soft"]), "lost": (C["danger"], C["danger_soft"])}.get(res)
            items.append({
                "need": need, "case": c, "hours": self.remaining_hours_for(c["need_no"]),
                "remaining": self.remaining_for(c["need_no"]), "warnings": self.warnings_for(c["need_no"]),
                "meta": meta_text, "meta_colors": colors,
            })
        return items

    # ------------------------------------------------------------ funnel actions
    def toggle_star(self, need_no: str):
        stage = self.stages.get(need_no)
        if stage is None:
            self.move_stage(need_no, "starred")
            self._set_info("به ستاره‌دارها اضافه شد؛ در «کارهای من» دیده می‌شود.")
        elif stage == P.REJECTED:
            self.restore_need(need_no)
        elif stage == "starred" and not self.store.case_has_work(need_no):
            self.delete_case(need_no)
        else:
            self.remove_from_funnel(need_no)

    def remove_from_funnel(self, need_no: str):
        """Ask whether to set the case aside (keeps everything) or delete it with its RFQs."""
        stage = self.stages.get(need_no)
        rfqs = len(self.store.rfqs(need_no))
        parts = [f"این نیاز در مرحله «{P.STAGE_TITLE.get(stage, stage)}» است"]
        if rfqs:
            parts.append(f"و {rfqs} استعلام ثبت‌شده دارد")
        box = CompactBox(self.case_windows.get(need_no) or self)
        box.setWindowTitle("برداشتن از پیگیری")
        box.setIcon(QMessageBox.Question)
        box.setText(rtl(" ".join(parts) + "."))
        box.setInformativeText(rtl("«صرف‌نظر» همه اطلاعات را نگه می‌دارد و از تب «صرف‌نظرشده» قابل بازگرداندن است. "
                                   "«حذف کامل» پرونده، استعلام‌ها و سابقه آن را پاک می‌کند (فایل‌های پوشه نیاز دست نمی‌خورند)."))
        b_reject = box.addButton("صرف‌نظر", QMessageBox.AcceptRole)
        b_delete = box.addButton("حذف کامل", QMessageBox.DestructiveRole)
        box.addButton("انصراف", QMessageBox.RejectRole)
        box.setDefaultButton(b_reject)
        box.exec()
        if box.clickedButton() is b_reject:
            self.reject_need(need_no)
        elif box.clickedButton() is b_delete:
            self.delete_case(need_no)

    def delete_case(self, need_no: str):
        self.store.delete_case(need_no)
        self.stages.pop(need_no, None)
        win = self.case_windows.pop(need_no, None)
        if win:
            win.close()
        self.refresh_views()

    def move_stage(self, need_no: str, stage: str, note: str | None = None):
        prev = self.stages.get(need_no)
        if prev == stage:
            return
        self.store.set_stage(need_no, stage, note)
        self.stages[need_no] = stage
        if stage in ("review", "rfq_ready", "rfq", "final") and not self.store.get_detail(need_no):
            self.request_detail(need_no)
        if stage == "review" and prev in (None, "starred"):
            self._auto_download(need_no)
        self.refresh_views()
        win = self.case_windows.get(need_no)
        if win:
            win.reload()

    def _auto_download(self, need_no: str):
        if not self.browser_opened:
            self._log(f"{need_no}: پیوست‌ها پس از باز کردن مرورگر از داخل پرونده دانلود شوند.", error=False)
            return
        payload = self.store.get_detail(need_no) or {}
        if (payload.get("info") or {}).get("attachment_count") == 0 or payload.get("attachments") == []:
            return
        folder = self.output_dir / need_no
        if folder.exists() and any(p.is_file() and not p.name.startswith(".") for p in folder.iterdir()):
            return
        need = self.need_obj(need_no)
        if need:
            self.download_needs([need], quiet=True)

    def reject_need(self, need_no: str):
        need = self.need_obj(need_no)
        dlg = RejectDialog(self.case_windows.get(need_no) or self, self.store.get("reject_reasons"),
                           need.description if need else need_no)
        if not dlg.exec():
            return
        prev = self.stages.get(need_no)
        reason = dlg.reason.currentText()
        self.store.set_stage(need_no, P.REJECTED, reason)
        # v0.9.17: a need that was never added («افزوده نشده») remembers that (""), so «برگرداندن» returns it to exactly that state
        self.store.update_case_data(need_no, rejected_from=prev or "", reject_reason=reason,
                                    reject_note=dlg.note.toPlainText().strip())
        self.stages[need_no] = P.REJECTED
        self.refresh_views()
        win = self.case_windows.get(need_no)
        if win:
            win.reload()

    def quick_waive(self, need_no: str, reason: str = "صرف‌نظر از «کارهای من»") -> str | None:
        """صرف‌نظر without the reasons dialog (kanban quick action); returns the previous stage for «برگرداندن»."""
        prev = self.stages.get(need_no)
        if prev is None or prev == P.REJECTED:
            return prev
        self.store.set_stage(need_no, P.REJECTED, reason)
        self.store.update_case_data(need_no, rejected_from=prev, reject_reason=reason, reject_note="")
        self.stages[need_no] = P.REJECTED
        win = self.case_windows.get(need_no)
        if win:
            win.reload()
        return prev

    def undo_waive(self, need_no: str, prev: str | None):
        if prev is None:
            self.delete_case(need_no)
        else:
            self.move_stage(need_no, prev, note="برگردانده شد")

    def restore_need(self, need_no: str):
        case = self.store.get_case(need_no)
        data = (case or {}).get("data", {})
        if "rejected_from" in data and not data["rejected_from"] and not self.store.case_has_work(need_no):
            self.delete_case(need_no)             # it was waived straight from «not added» → back to «not added»
            self._set_info("صرف‌نظر برداشته شد؛ نیاز به حالت «افزوده نشده» برگشت.")
            return
        target = data.get("rejected_from") or "starred"
        self.move_stage(need_no, target if target in P.STAGE_KEYS else "starred", note="بازگردانده شد")

    def open_case(self, need_no: str):
        if need_no not in self.stages:
            self.move_stage(need_no, "starred")
        host = getattr(self, "window_host", None)
        if host is not None:                      # inside the suite: opens as an in-app tab
            def make():
                w = CaseWindow(self, need_no)
                w.setStyleSheet(self.styleSheet())
                w.finished.connect(lambda *_: self.case_windows.pop(need_no, None))
                self.case_windows[need_no] = w
                return w
            host("inq", need_no, f"خرید {need_no}", make, lambda: self.refresh_views())
            return
        win = self.case_windows.get(need_no)
        if win is None:
            win = CaseWindow(self, need_no)
            if self.embedded:
                win.setStyleSheet(self.styleSheet())
            win.finished.connect(lambda *_: self.case_windows.pop(need_no, None))
            self.case_windows[need_no] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def refresh_views(self, board_only: bool = False):
        self.stages = self.store.case_stages()
        if getattr(self, "side", None) is not None and self.side.need_no:
            self.side.show_need(self.side.need_no)
        self.model.refresh_columns("star", "status")
        self._update_counts()
        if hasattr(self, "board"):
            self.board.refresh()
            if not board_only:
                self.archive.refresh()
                self.suppliers.refresh()

    # ------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(18, 16, 18, 10)
        page.setSpacing(10)
        self.header_frame = self._build_header()
        page.addWidget(self.header_frame)
        if self.embedded:
            self.header_frame.hide()
            page.setContentsMargins(20, 14, 20, 10)
            page.setSpacing(11)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setDocumentMode(True)
        list_page = QWidget()
        lv = QVBoxLayout(list_page)
        lv.setContentsMargins(0, 0 if self.embedded else 10, 0, 0)
        lv.setSpacing(11 if self.embedded else 10)
        lv.addWidget(self._build_actions())
        if not self.embedded:
            lv.addWidget(self._build_filters())
        self.side_mode = self.embedded or bool(self.settings.value("side_panel", False, bool))
        if self.side_mode:                      # v0.8: details in a side panel instead of under the row
            from ui_side import NeedSidePanel
            self.side = NeedSidePanel(self)
            split = QSplitter(Qt.Horizontal)
            split.setChildrenCollapsible(False)
            split.setHandleWidth(12)
            if self.embedded:               # v0.9.1: filters + batch bar + table are ONE card, like the tender page
                right = card_frame()
                rl = QVBoxLayout(right)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(0)
                rl.addWidget(self._build_filters())
                rl.addWidget(self._build_batch_bar())
                rl.addWidget(self._build_table(), 1)
                split.addWidget(right)
            else:
                split.addWidget(self._build_table())
            split.addWidget(self.side)
            split.setStretchFactor(0, 3)
            split.setStretchFactor(1, 2)
            split.setSizes([980, 560])
            split.setHandleWidth(14)
            split.setChildrenCollapsible(False)
            self.side.setMinimumWidth(560)
            lv.addWidget(split, 1)
        else:
            self.side = None
            lv.addWidget(self._build_table(), 1)
        self.board = BoardView(self)
        self.suppliers = SuppliersView(self)
        self.archive = ArchiveView(self)
        for w in (self.board, self.suppliers, self.archive):
            w.layout().setContentsMargins(0, 10, 0, 0)
        self.tabs.addTab(list_page, make_icon("list_check"), "فراخوان‌های خرید")
        self.tabs.addTab(self.board, make_icon("board"), "تابلوی پیگیری")
        self.tabs.addTab(self.suppliers, make_icon("users"), "تأمین‌کنندگان")
        self.tabs.addTab(self.archive, make_icon("archive"), "صرف‌نظرشده")
        self.tabs.currentChanged.connect(self._tab_changed)
        if self.embedded:
            self.tabs.tabBar().hide()  # the suite sidebar switches these pages

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self._build_log())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([760, 80])
        page.addWidget(self.splitter, 1)

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setContentsMargins(14, 2, 14, 4)
        self.info_label = label("برای شروع، مرورگر را باز و وارد سایت شوید.")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(160)
        self.busy_bar.hide()
        self.log_errors = 0
        self.btn_log = button("گزارش عملیات", "file", "ghost", "نمایش/پنهان کردن جزئیات عملیات و خطاها")
        self.btn_log.setCheckable(True)
        self.btn_log.toggled.connect(self._toggle_log)
        sb.addWidget(self.info_label, 1)
        sb.addPermanentWidget(self.busy_bar)
        sb.addPermanentWidget(self.btn_log)
        self.log.hide()

        QShortcut(QKeySequence.Find, self, activated=lambda: (self.tabs.setCurrentIndex(0), self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence(Qt.Key_Escape), self.search, activated=self.search.clear)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(22, 12, 22, 12)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label("مدیریت نیازهای ستاد ایران", "appTitle"))
        text.addWidget(label("از فراخوان تا پیش‌فاکتور: غربال نیازها، بررسی، استعلام از تأمین‌کنندگان، قیمت‌گذاری و پیگیری نتیجه.", "appSubtitle"))
        lay.addLayout(text, 1)
        self.conn_pill = label("مرورگر بسته است", "pill")
        self.conn_pill.setProperty("state", "off")
        lay.addWidget(self.conn_pill, 0, Qt.AlignVCenter)
        gear = QPushButton("تنظیمات")
        gear.setObjectName("headerBtn")
        gear.setIcon(make_icon("settings", "#FFFFFF"))
        gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(self._open_settings)
        lay.addSpacing(8)
        lay.addWidget(gear, 0, Qt.AlignVCenter)
        return header

    def _build_actions(self) -> QWidget:
        card = card_frame()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)
        self.btn_open = button("باز کردن مرورگر و ورود", "globe", "primary",
                               "مرورگر Edge/Chrome باز می‌شود؛ خودتان وارد حساب ستاد شوید.")
        self.btn_open.clicked.connect(self._launch)
        self.btn_refresh = button("دریافت / به‌روزرسانی نیازها", "refresh", "primary", "فهرست نیازها از سایت خوانده می‌شود.")
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_quick = button("به‌روزرسانی سریع", "refresh", None,
                                "فقط نیازهایی که از آخرین تاریخ اعلامِ فهرست فعلی به بعد آمده‌اند؛ فهرست پاک نمی‌شود.")
        self.btn_quick.clicked.connect(self._quick_refresh)
        self.pages_combo = QComboBox()
        self.pages_combo.addItems(["خودکار", "1", "5", "10", "20"])
        self.pages_combo.setFixedWidth(96)
        self.pages_combo.setToolTip(rtl("تعداد صفحه‌هایی که از سایت خوانده می‌شود"))
        self.btn_download = button("دانلود پیوست ستاره‌دارها", "download", "primary",
                                   "پیوست‌های نیازهای ستاره‌دارِ این فهرست، هر کدام در پوشه شماره نیاز ذخیره می‌شود.")
        self.btn_download.clicked.connect(self._download_starred)
        self.btn_stop = button("توقف", "stop", "danger", "عملیات جاری پس از درخواست فعلی متوقف می‌شود.")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setEnabled(False)
        if self.embedded:
            return self._build_actions_embedded(card)
        lay.addWidget(self.btn_open)
        lay.addSpacing(6)
        lay.addWidget(self.btn_refresh)
        lay.addWidget(label("صفحات:", "muted"))
        lay.addWidget(self.pages_combo)
        lay.addSpacing(6)
        lay.addWidget(self.btn_download)
        lay.addSpacing(4)
        lay.addWidget(self.btn_stop)
        lay.addStretch(1)
        lay.addWidget(vline())
        self.stat_total = StatBlock("کل نیازها")
        self.stat_visible = StatBlock("نمایش داده‌شده")
        self.stat_new = StatBlock("جدید")
        self.stat_active = StatBlock("پرونده فعال")
        for s in (self.stat_total, self.stat_visible, self.stat_new, self.stat_active):
            lay.addWidget(s)
        return card

    def _build_actions_embedded(self, card: QWidget) -> QWidget:
        """v0.9: same page skeleton as the tender page: title + buttons on one row, then the KPI strip."""
        from suite.kpi import KpiStrip
        card.deleteLater()
        card = QWidget()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label("فراخوان‌های خرید", "pageTitle"))
        self.counter = label("", "pageCount")          # v0.9.16: same small grey count as the tender page («N مورد»)
        row.addWidget(self.counter)
        row.addStretch(1)
        self.btn_refresh.setText("دریافت نیازها")
        self.btn_export = button("خروجی Excel", "spreadsheet", None, "خروجی ردیف‌های فیلترشده (CSV قابل باز شدن در Excel)")
        self.btn_export.setIcon(make_icon("spreadsheet", "#1d7a46"))
        self.btn_export.clicked.connect(self._export)
        for b in (self.btn_refresh, self.btn_quick, self.btn_download, self.btn_export, self.btn_stop):
            row.addWidget(b)
        self.btn_stop.hide()
        for w in (self.btn_open, self.pages_combo):   # the single «اتصال به ستاد» lives in the app header
            w.hide()
        v.addLayout(row)
        self.kpi = KpiStrip(["کل نیازها", "جدید", "مهلت‌دار", "پروندهٔ فعال"])
        v.addWidget(self.kpi)
        return card

    def _build_filters(self) -> QWidget:
        if self.embedded:
            return self._build_filters_embedded()
        card = card_frame()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(rtl("جست‌وجو در شماره، شرح، دستگاه و گروه…  (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(make_icon("search", C["muted"]), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda *_: self.filter_timer.start())
        lay.addWidget(self.search, 3)
        self.province_combo = self._filter_combo("همه استان‌ها", editable=False, width=140)
        self.category_combo = self._filter_combo("کالا و خدمات", editable=False, width=116)
        self.org_combo = self._org_picker(200)
        self.group_combo = self._filter_combo("همه گروه‌ها", editable=True, width=190)
        for caption, combo in (("استان", self.province_combo), ("نوع", self.category_combo),
                               ("دستگاه", self.org_combo), ("گروه", self.group_combo)):
            lay.addWidget(label(caption, "muted"))
            lay.addWidget(combo, 1 if (combo.isEditable() or isinstance(combo, MultiCombo)) else 0)
        self.only_star = button("ستاره‌دار", "star", "toggle")
        self.only_open = button("مهلت‌دار", None, "toggle")
        self.only_open.setToolTip(rtl("فقط نیازهایی که مهلتشان هنوز نگذشته"))
        self.only_new = button("فقط جدید", None, "toggle")
        for b in (self.only_star, self.only_open, self.only_new):
            b.setCheckable(True)
            b.toggled.connect(lambda *_: self.filter_timer.start())
            lay.addWidget(b)
        self.only_dl = button("دانلودشده", None, "toggle")
        self.only_dl.setCheckable(True)
        self.only_dl.toggled.connect(lambda *_: self.filter_timer.start())
        lay.addWidget(self.only_dl)
        self.btn_clear_filters = button("حذف فیلترها", "filter_off", "ghost")
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        lay.addWidget(self.btn_clear_filters)
        return card

    def _build_filters_embedded(self) -> QWidget:
        """Two rows like the tender page: search + drop-downs, then one row of chips."""
        card = QWidget()
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 8)
        v.setSpacing(8)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(rtl("جست‌وجو: شمارهٔ نیاز، شرح، دستگاه…  (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(make_icon("search", C["muted"]), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda *_: self.filter_timer.start())
        r1.addWidget(self.search, 3)
        self.province_combo = self._filter_combo("همه استان‌ها", editable=False, width=130)
        self.category_combo = self._filter_combo("کالا و خدمات", editable=False, width=116)
        self.org_combo = self._org_picker(190)
        self.group_combo = self._filter_combo("همه گروه‌ها", editable=True, width=170)
        for combo in (self.province_combo, self.org_combo, self.category_combo, self.group_combo):
            r1.addWidget(combo, 2 if (combo.isEditable() or isinstance(combo, MultiCombo)) else 1)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        self.only_open = button("مهلت‌دار", None, "toggle")
        self.only_open.setToolTip(rtl("فقط نیازهایی که مهلتشان هنوز نگذشته"))
        self.only_new = button("فقط جدید", None, "toggle")
        self.only_star = button("ستاره‌دار", None, "toggle")
        self.only_dl = button("دانلودشده", None, "toggle")
        self.only_dl.setToolTip(rtl("فقط نیازهایی که فایلشان روی رایانه دانلود شده"))
        for b in (self.only_open, self.only_new, self.only_star, self.only_dl):
            b.setCheckable(True)
            b.toggled.connect(lambda *_: self.filter_timer.start())
            b.toggled.connect(lambda *_: self._sync_more())
        r2.addWidget(self.only_open)
        # v0.9.13: «فیلترهای بیشتر» like the tender page; «فقط جدید» and «ستاره‌دار» live in the menu
        for b in (self.only_new, self.only_star, self.only_dl):
            b.setParent(card)
            b.hide()
        self.btn_more = button("فیلترهای بیشتر", "filter", "toggle")
        self.btn_more.setCheckable(True)
        self.btn_more.clicked.connect(self._more_filters_menu)
        r2.addWidget(self.btn_more)
        r2.addStretch(1)
        self.btn_clear_filters = button("حذف فیلترها", "filter_off", "ghost")
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        r2.addWidget(self.btn_clear_filters)
        self.btn_columns = button("ستون‌ها", "layers", "toggle", "انتخاب ستون‌های جدول")
        self.btn_columns.clicked.connect(self._columns_menu)
        r2.addWidget(self.btn_columns)
        v.addLayout(r2)
        return card

    def _more_filters(self):
        return ((self.only_new, "فقط جدید"), (self.only_star, "ستاره‌دار"), (self.only_dl, "دانلودشده"))

    def _sync_more(self):
        if not hasattr(self, "btn_more"):
            return
        n = sum(1 for b, _ in self._more_filters() if b.isChecked())
        self.btn_more.setText(f"فیلترهای بیشتر ({num(n)})" if n else "فیلترهای بیشتر")
        self.btn_more.setChecked(bool(n))

    def _more_filters_menu(self):
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        for b, name in self._more_filters():
            count = b.text().rsplit("  ", 1)[-1] if "  " in b.text() else ""
            a = m.addAction(f"{name}  {count}".strip())
            a.setCheckable(True)
            a.setChecked(b.isChecked())
            a.toggled.connect(b.setChecked)
        pos = self.btn_more.mapToGlobal(self.btn_more.rect().bottomRight())
        m.exec(pos - QPoint(m.sizeHint().width(), 0))
        self._sync_more()

    # ------------------------------------------------------------ batch (ticked rows) + columns menu
    def _build_batch_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("batchBar")
        bar.setStyleSheet(f"QFrame#batchBar {{ background:{C['text']}; border-radius:12px; }} "
                          "QFrame#batchBar QLabel { color:#FFFFFF; font-weight:600; background:transparent; } "
                          "QFrame#batchBar QPushButton { color:#FFFFFF; background:rgba(255,255,255,0.12); border:0; "
                          "border-radius:9px; padding:6px 14px; } "
                          "QFrame#batchBar QPushButton:hover { background:rgba(255,255,255,0.22); }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(8)
        self.batch_label = QLabel("")
        lay.addWidget(self.batch_label)
        lay.addStretch(1)
        for text, fn in (("انتخاب همهٔ نتایج", self.check_all_visible),
                         ("دانلود پیوست‌ها", self._batch_download),
                         ("ستاره‌دار کردن", self._batch_star),
                         ("برداشتن ستاره", self._batch_unstar),
                         ("صرف‌نظر", self._batch_reject),
                         ("خروجی Excel", self._batch_export),
                         ("لغو انتخاب", self.clear_checks)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(14, 0, 14, 6)
        wl.addWidget(bar)
        self.batch_bar = wrap
        wrap.hide()
        return wrap

    def toggle_check(self, need_no: str):
        if need_no in self.checked:
            self.checked.discard(need_no)
        else:
            self.checked.add(need_no)
        self._after_check()

    def check_all_visible(self):
        for n in self.visible:                 # every result, not only the current page
            self.checked.add(n.need_no)
        self._after_check()

    def clear_checks(self):
        self.checked.clear()
        self._after_check()

    def _header_clicked(self, section: int):
        if COLUMNS[section][0] != "select" or not self.embedded:
            return
        if self.checked:
            self.clear_checks()
        else:
            self.check_all_visible()

    def _after_check(self):
        self.model.refresh_columns("select")
        n = len(self.checked)
        if getattr(self, "batch_bar", None) is not None:
            self.batch_bar.setVisible(n > 0)
            self.batch_label.setText(rtl(f"{fa(n)} نیاز انتخاب شده"))

    def _checked_needs(self) -> list[Need]:
        return [n for n in self.all_needs if n.need_no in self.checked]

    def _batch_download(self):
        needs = self._checked_needs()
        if needs:
            self.download_needs(needs)

    def _batch_star(self):
        for n in self._checked_needs():
            if self.stages.get(n.need_no) is None:
                self.move_stage(n.need_no, "starred")
        self._set_info("نیازهای انتخاب‌شده به ستاره‌دارها اضافه شد؛ در «کارهای من» دیده می‌شوند.")
        self.refresh_views()

    def _plain_stars(self, needs=None) -> tuple[list[str], int]:
        """(need numbers whose star can be removed safely, number kept because they already have work in the pipeline).
        Only «ستاره‌دار» cases with nothing entered are removed; cases further along (or set aside) are never touched."""
        nos = [n.need_no for n in needs] if needs is not None else list(self.stages)
        plain, kept = [], 0
        for nn in nos:
            st = self.stages.get(nn)
            if st is None or st == P.REJECTED:
                continue
            if st == "starred" and not self.store.case_has_work(nn):
                plain.append(nn)
            else:
                kept += 1
        return plain, kept

    def _unstar_many(self, nos: list[str], kept: int, scope: str):
        if not nos:
            QMessageBox.information(self, "برداشتن ستاره", rtl("ستارهٔ ساده‌ای برای برداشتن پیدا نشد." + (
                f" {fa(kept)} نیاز در مراحل بعدی پیگیری هستند و دست نخوردند." if kept else "")))
            return
        box = CompactBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("برداشتن ستاره")
        box.setText(rtl(f"ستارهٔ {fa(len(nos))} نیاز ({scope}) برداشته شود؟"))
        extra = f" {fa(kept)} نیاز که پرونده‌شان کار ثبت‌شده دارد یا در مراحل بعدی است، دست نمی‌خورد." if kept else ""
        box.setInformativeText(rtl("فقط ستاره‌های ساده (بدون یادداشت و استعلام) برداشته می‌شوند." + extra))
        yes = box.addButton("بله، بردار", QMessageBox.YesRole)
        box.addButton("انصراف", QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        for nn in nos:
            self.store.delete_case(nn)
            self.stages.pop(nn, None)
            win = self.case_windows.pop(nn, None)
            if win:
                win.close()
        self.checked.clear()
        self._after_check()
        self.refresh_views()
        self._set_info(f"ستارهٔ {fa(len(nos))} نیاز برداشته شد.")

    def _batch_unstar(self):
        nos, kept = self._plain_stars(self._checked_needs())
        self._unstar_many(nos, kept, "انتخاب‌شده‌ها")

    def _unstar_all(self):
        nos, kept = self._plain_stars()
        self._unstar_many(nos, kept, "همهٔ ستاره‌دارها")

    def _batch_reject(self):
        needs = [n for n in self._checked_needs() if self.stages.get(n.need_no) != P.REJECTED]
        if not needs:
            return
        box = CompactBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("صرف‌نظر گروهی")
        box.setText(f"از {len(needs)} نیاز انتخاب‌شده صرف‌نظر شود؟")
        box.setInformativeText("فقط داخل برنامه کنار گذاشته می‌شوند و از تب «صرف‌نظرشده» قابل بازگرداندن‌اند.")
        yes = box.addButton("بله، صرف‌نظر", QMessageBox.YesRole)
        box.addButton("انصراف", QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        for n in needs:
            prev = self.stages.get(n.need_no)
            self.store.set_stage(n.need_no, P.REJECTED, "صرف‌نظر گروهی")
            self.store.update_case_data(n.need_no, rejected_from=prev or "starred", reject_reason="صرف‌نظر گروهی", reject_note="")
            self.stages[n.need_no] = P.REJECTED
        self.clear_checks()
        self.refresh_views()

    def _batch_export(self):
        needs = self._checked_needs()
        if not needs:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره نیازهای انتخاب‌شده", str(self.output_dir / "setadiran-needs-selected.csv"), "CSV UTF-8 (*.csv)")
        if path:
            export_csv(needs, Path(path))
            self._log(f"{len(needs)} ردیف در {path} ذخیره شد.")

    def _columns_menu(self):
        from PySide6.QtGui import QCursor
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        for i, (key, title, *_r) in enumerate(COLUMNS):
            if key in ("select", "star", "need_no", "description"):
                continue
            a = m.addAction(title)
            a.setCheckable(True)
            a.setChecked(not self.view.isColumnHidden(i))
            a.toggled.connect(lambda on, i=i: self._set_column(i, on))
        m.addSeparator()
        m.addAction("پیش‌فرض", self._reset_columns)
        m.exec(QCursor.pos())

    def _set_column(self, i: int, on: bool):
        self.view.setColumnHidden(i, not on)
        hidden = [k for j, (k, *_r) in enumerate(COLUMNS) if self.view.isColumnHidden(j)]
        self.settings.setValue("hidden_cols", ",".join(hidden))

    def _reset_columns(self):
        for i, (k, *_r) in enumerate(COLUMNS):
            self.view.setColumnHidden(i, k in DEFAULT_HIDDEN)
        self.settings.remove("hidden_cols")

    def _apply_hidden_columns(self):
        saved = self.settings.value("hidden_cols", None)
        if saved is not None and self.settings.value("cols_ver", 0, int) < 18:     # v0.9.18: the new «اسناد» column starts hidden for existing users too
            saved = (str(saved) + ",docs").strip(",")
            self.settings.setValue("hidden_cols", saved)
        self.settings.setValue("cols_ver", 18)
        hidden = set(str(saved).split(",")) if saved not in (None, "") else (set(DEFAULT_HIDDEN) if saved is None else set())
        for i, (k, *_r) in enumerate(COLUMNS):
            self.view.setColumnHidden(i, (k in hidden) if self.embedded else k == "select")

    def _org_picker(self, width: int) -> MultiCombo:
        combo = MultiCombo("همه دستگاه‌ها", "دستگاه", "دستگاه‌ها", width)
        combo.selectionChanged.connect(lambda *_: self.filter_timer.start())
        return combo

    def _filter_combo(self, all_text: str, editable: bool, width: int) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(editable)
        combo.setProperty("all_text", all_text)
        combo.addItem(all_text)
        if editable:
            combo.setCurrentIndex(-1)
            combo.setEditText("")
        combo.setMinimumWidth(width)
        combo.setMaxVisibleItems(18)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
        if editable:
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.lineEdit().setPlaceholderText(rtl(all_text))
            combo.lineEdit().setClearButtonEnabled(True)
            completer = QCompleter(combo.model(), combo)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            combo.setCompleter(completer)
            combo.editTextChanged.connect(lambda *_: self.filter_timer.start())
        else:
            combo.currentIndexChanged.connect(lambda *_: self.filter_timer.start())
        return combo

    def _build_table(self) -> QWidget:
        card = QWidget() if self.embedded else card_frame()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 12, 10)
        head.setSpacing(6)
        if not self.embedded:
            head.addWidget(label("فراخوان‌های خرید", "sectionTitle"))
            self.counter = label("", "muted")
            head.addSpacing(8)
            head.addWidget(self.counter)
            head.addStretch(1)
            self.list_hint = label("روی ردیف کلیک کنید تا جزئیات باز شود؛ روی ☆ کلیک کنید تا به تابلوی پیگیری برود.", "muted")
            head.addWidget(self.list_hint)
            v.addLayout(head)
        else:
            self.list_hint = label("", "muted")
            self.list_hint.hide()

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page(
            "inbox", "هنوز فهرستی دریافت نشده است",
            "۱) مرورگر را باز کنید و وارد حساب ستاد شوید.   ۲) «دریافت نیازها» را بزنید."))
        self.view = self._build_tree()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self._empty_page("search", "نتیجه‌ای با این فیلترها پیدا نشد",
                                              "عبارت جست‌وجو یا فیلترها را تغییر دهید.", with_clear=True))
        v.addWidget(self.stack, 1)
        self.pager = self._build_pager()
        v.addWidget(self.pager)

        foot = QHBoxLayout()
        foot.setContentsMargins(16, 10, 16, 12)
        foot.setSpacing(8)
        foot.addWidget(make_icon_label("folder", C["muted"]))
        foot.addWidget(label("پوشهٔ ذخیره:", "muted"))
        self.dir_edit = QLineEdit(str(self.output_dir))
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setLayoutDirection(Qt.LeftToRight)
        foot.addWidget(self.dir_edit, 1)
        b_choose = button("تغییر پوشه", "folder_edit")
        b_choose.clicked.connect(self._choose_directory)
        b_open = button("باز کردن پوشه", "folder")
        b_open.clicked.connect(lambda: self._open_directory())
        b_csv = button("خروجی CSV", "file")
        b_csv.clicked.connect(self._export)
        for b in ((b_choose, b_open) if self.embedded else (b_choose, b_open, b_csv)):
            foot.addWidget(b)
        v.addWidget(hline())
        v.addLayout(foot)
        return card

    def _empty_page(self, icon: str, title: str, text: str, with_clear: bool = False) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        ic = make_icon_label(icon, "#98A2B3", 44)
        ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "emptyTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        d = label(text, "emptyText")
        d.setAlignment(Qt.AlignCenter)
        lay.addWidget(d)
        if with_clear:
            b = button("حذف فیلترها", "filter_off")
            b.clicked.connect(self._clear_filters)
            lay.addWidget(b, 0, Qt.AlignCenter)
        lay.addStretch(1)
        return w

    def _build_tree(self) -> NeedTree:
        view = NeedTree()
        view.setModel(self.model)
        self.delegate = NeedDelegate(view, self)
        view.setItemDelegate(self.delegate)
        # v0.9.10: in the suite every row has the same fixed height (the details open in the side panel), so Qt must not
        # ask the delegate for the size of all ~8,000 rows on every change — that was the main cause of the freezing.
        view.setUniformRowHeights(bool(self.embedded))
        view.setAlternatingRowColors(not self.embedded)
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.setSelectionMode(QAbstractItemView.SingleSelection)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.setExpandsOnDoubleClick(False)
        view.setIndentation(0 if self.embedded else 26)
        view.setRootIsDecorated(not self.embedded)
        view.setAnimated(False)
        view.setMouseTracking(True)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.verticalScrollBar().setSingleStep(18)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        view.setTextElideMode(Qt.ElideRight)
        view.setWordWrap(False)
        view.setIconSize(QSize(16, 16))
        view.setContextMenuPolicy(Qt.CustomContextMenu)
        header = view.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(48)
        header.setDefaultAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        for i, (key, _title, width, _align) in enumerate(COLUMNS):
            header.setSectionResizeMode(i, QHeaderView.Stretch if key == "description" else QHeaderView.Interactive)
            if key != "description":
                header.resizeSection(i, width)
        header.setSortIndicator(-1, Qt.AscendingOrder)
        view.setSortingEnabled(True)
        header.setSortIndicatorShown(True)
        view.clicked.connect(self._on_clicked)
        header.sectionClicked.connect(self._header_clicked)
        view.expanded.connect(self._on_expanded)
        view.collapsed.connect(self._on_collapsed)
        view.customContextMenuRequested.connect(self._context_menu)
        self.model.modelReset.connect(lambda *_: QTimer.singleShot(0, self._reapply_expanded))
        return view

    def _build_log(self) -> QWidget:
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(600)
        self.log.setLayoutDirection(Qt.RightToLeft)
        opt = QTextOption(Qt.AlignRight)
        opt.setTextDirection(Qt.RightToLeft)
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.log.document().setDefaultTextOption(opt)
        self.log.setMinimumHeight(60)
        return self.log

    def _tab_changed(self, index: int):
        w = self.tabs.widget(index)
        if hasattr(w, "refresh"):
            w.refresh()

    # ------------------------------------------------------------ settings
    def _restore_settings(self):
        ok = self.settings.value("settings_version", 0, int) == SETTINGS_VERSION
        if ok:
            geo = None if self.embedded else self.settings.value("geometry")
            if isinstance(geo, QByteArray):
                self.restoreGeometry(geo)
            head = self.settings.value("header")
            if isinstance(head, QByteArray):
                self.view.header().restoreState(head)
                self.view.header().setSectionResizeMode(COL["description"], QHeaderView.Stretch)
            split = self.settings.value("splitter")
            if isinstance(split, QByteArray):
                self.splitter.restoreState(split)
            if self.settings.value("log_visible", False, bool):
                self.btn_log.setChecked(True)
        self._apply_hidden_columns()
        size = self.settings.value("page_size", 200, int)
        i = self.pager_size.findData(size)
        if i >= 0:
            self.pager_size.setCurrentIndex(i)
            self.page_size = size
        pages = self.settings.value("pages", "خودکار", str)
        if pages in [self.pages_combo.itemText(i) for i in range(self.pages_combo.count())]:
            self.pages_combo.setCurrentText(pages)

    def _save_settings(self):
        self.settings.setValue("settings_version", SETTINGS_VERSION)
        if not self.embedded:
            self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("header", self.view.header().saveState())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("log_visible", self.btn_log.isChecked())
        self.settings.setValue("output_dir", str(self.output_dir))
        self.settings.setValue("pages", self.pages_combo.currentText())
        self.settings.setValue("page_size", self.page_size)

    def _open_settings(self):
        if SettingsDialog(self).exec():
            self._warn_cache.clear()
            self.model.refresh_columns("description")
            self.refresh_views()
            for win in list(self.case_windows.values()):
                win.reload()
            self._set_info("تنظیمات ذخیره شد.")

    # ------------------------------------------------------------ helpers
    def _log(self, msg: str, error: bool | None = None):
        stamp = datetime.now().strftime("%H:%M")
        if error is None:
            error = msg.startswith(("خطا", "ناموفق", "نیاز ")) or "تأیید نشد" in msg
        self.log.appendPlainText(rtl(f"{stamp}   {'⚠ ' if error else ''}{msg}"))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        if error and not self.log.isVisible():
            self.log_errors += 1
            self._update_log_button()

    def _toggle_log(self, visible: bool):
        self.log.setVisible(visible)
        if visible:
            self.log_errors = 0
            sizes = self.splitter.sizes()
            if len(sizes) == 2 and sizes[1] < 60:
                total = sum(sizes)
                self.splitter.setSizes([max(200, total - 140), 140])
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        self._update_log_button()

    def _update_log_button(self):
        if self.log_errors:
            self.btn_log.setText(f"گزارش عملیات · {self.log_errors} خطا")
            self.btn_log.setProperty("kind", "ghostAlert")
        else:
            self.btn_log.setText("بستن گزارش" if self.btn_log.isChecked() else "گزارش عملیات")
            self.btn_log.setProperty("kind", "ghost")
        self.btn_log.style().unpolish(self.btn_log)
        self.btn_log.style().polish(self.btn_log)

    def _set_info(self, msg: str):
        self.info_label.setText(rtl(msg))

    def copy_text(self, text: str, note: str):
        QGuiApplication.clipboard().setText(text)
        self._set_info(note)

    def _set_pill(self, text: str, state: str):
        self.conn_pill.setText(rtl(text))
        self.conn_pill.setProperty("state", state)
        self.conn_pill.style().unpolish(self.conn_pill)
        self.conn_pill.style().polish(self.conn_pill)

    def _set_busy(self, busy: bool):
        self.busy = busy
        for b in (self.btn_open, self.btn_refresh, self.btn_quick, self.btn_download):
            b.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if self.embedded:
            self.btn_stop.setVisible(busy)
        self.busy_bar.setVisible(busy)
        if busy:
            self._set_pill("در حال کار…", "busy")
        else:
            self._set_pill("مرورگر متصل است" if self.browser_opened else "مرورگر بسته است",
                           "on" if self.browser_opened else "off")

    def _starred_in_list(self) -> list[Need]:
        return [n for n in self.all_needs if self.stages.get(n.need_no) not in (None, P.REJECTED)]

    def _open_count(self) -> int:
        """Needs whose deadline has not passed. Cached per (list size, minute): the full scan was repeated on every filter change."""
        needs = self.all_needs
        key = (len(needs), int(time.time() // 60), id(self.meta))
        if self._open_cache[0] == key:
            return self._open_cache[1]
        now = time.time()
        meta = self.meta
        n_open = 0
        for n in needs:
            m = meta.get(n.need_no)
            if m is None:
                m = self._meta_for(n.need_no)
            d = m.get("deadline_at")
            if d and d > now:
                n_open += 1
        self._open_cache = (key, n_open)
        return n_open

    def _update_counts(self):
        total = len(self.all_needs)
        visible = len(self.visible)
        active = sum(1 for s in self.stages.values() if s in P.STAGE_KEYS)
        pos = self.all_pos
        new_n = sum(1 for nn in self.new_needs if nn in pos)
        if hasattr(self, "stat_total"):
            self.stat_total.set(total)
            self.stat_visible.set(visible)
            self.stat_new.set(new_n)
            self.stat_active.set(active)
        starred = sum(1 for nn, st in self.stages.items() if st not in (None, P.REJECTED) and nn in pos)
        if getattr(self, "kpi", None) is not None:
            open_n = self._open_count()
            self.kpi.set_values([total, new_n, open_n, active])
            if self.embedded:
                # v0.9.1: counts on the chips (whole list), like the tender page
                for b, base, n in ((self.only_open, "مهلت‌دار", open_n), (self.only_new, "فقط جدید", new_n),
                                   (self.only_star, "ستاره‌دار", starred),
                                   (self.only_dl, "دانلودشده", sum(1 for nn in self._dl_counts if nn in pos))):
                    b.setText(f"{base}  {num(n)}")
        self.counter.setText(rtl(f"{num(visible)} مورد" if total else "") if self.embedded
                             else rtl(f"{num(visible)} از {num(total)} نیاز  ·  {num(starred)} ستاره‌دار" if total else ""))
        self.btn_download.setText(f"دانلود پیوست ستاره‌دارها ({num(starred)})" if starred else "دانلود پیوست ستاره‌دارها")
        self.tabs.setTabText(1, f"تابلوی پیگیری ({num(active)})" if active else "تابلوی پیگیری")
        rejected = sum(1 for s in self.stages.values() if s == P.REJECTED)
        self.tabs.setTabText(3, f"صرف‌نظرشده ({num(rejected)})" if rejected else "صرف‌نظرشده")
        if total == 0:
            self.stack.setCurrentIndex(0)
        elif visible == 0:
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(1)

    def _need_proxy_index(self, need_no: str) -> QModelIndex:
        row = self.model.pos.get(need_no)      # only the current page has rows
        if row is None:
            return QModelIndex()
        return self.model.index(row, 0)

    def _tick(self):
        """Once a minute: deadlines count down."""
        self.model.refresh_columns("deadline")
        if self.tabs.currentWidget() is self.board:
            self.board.refresh()

    # ------------------------------------------------------------ list persistence
    def _index_need(self, n: Need):
        self.search_text[n.need_no] = norm(" ".join([
            n.need_no, n.description, n.organization, n.province, n.category, n.goods_group, n.service_group, n.need_type,
        ]))

    def _load_last_list(self):
        last = self.store.get("last_refresh_at", 0) or 0
        if not last:
            return
        # v0.9.23: the list is everything kept since the last FULL refresh. (A quick update moved «last_refresh_at» and
        # used to hide all older needs after a restart.) No marker yet (older data) -> show everything stored.
        since = self.store.get("list_since", None)
        needs = [clean_need(n) for n in self.store.needs_seen_since(0 if since is None else since)]
        self.meta.update(self.store.need_meta([n.need_no for n in needs]))
        if self.store.get("prev_refresh_at", 0):
            self.new_needs = {n.need_no for n in needs if (self.meta.get(n.need_no) or {}).get("first_seen", 0) >= last}
        for n in needs:
            self._index_need(n)
        self._data_append(needs)
        self._refresh_filter_values()
        self._update_counts()
        if needs:
            self._set_info(f"آخرین فهرست دریافت‌شده ({jalali.fmt_stamp(last)}) نمایش داده شده است.")

    # ------------------------------------------------------------ filters
    def _combo_value(self, combo: QComboBox) -> str:
        text = combo.currentText().strip()
        return "" if not text or text == combo.property("all_text") else text

    def _apply_filters(self, reset_page: bool = True):
        if reset_page is not True:             # called from a signal with a different argument
            reset_page = bool(reset_page) if isinstance(reset_page, bool) else True
        terms = norm(self.search.text()).split()
        province = self._combo_value(self.province_combo)
        category = self._combo_value(self.category_combo)
        orgs = self.org_combo.selected()
        group = norm(self._combo_value(self.group_combo))
        only_star = self.only_star.isChecked()
        only_new = self.only_new.isChecked()
        only_open = self.only_open.isChecked()
        only_dl = self.only_dl.isChecked()
        index = self.search_text

        def predicate(n: Need) -> bool:
            if only_star and self.stages.get(n.need_no) in (None, P.REJECTED):
                return False
            if only_new and n.need_no not in self.new_needs:
                return False
            if only_dl and not self._dl_counts.get(n.need_no):
                return False
            if only_open:
                h = self.remaining_hours_for(n.need_no)
                if h is None or h <= 0:
                    return False
            if province and n.province != province:
                return False
            if category and n.category != category:
                return False
            if orgs and n.organization not in orgs:
                return False
            if group and group not in _norm_cached(need_group(n)):
                return False
            if terms:
                hay = index.get(n.need_no, "")
                return all(t in hay for t in terms)
            return True

        active = bool(terms or province or category or orgs or group or only_star or only_new or only_open or only_dl)
        self._predicate = predicate if active else None
        if reset_page:
            self.page = 0
        self._rebuild_visible()
        self._update_counts()
        QTimer.singleShot(0, self._reapply_expanded)

    # ------------------------------------------------------------ the list: all data here, the table shows one page
    def _data_clear(self):
        self.all_needs = []
        self.all_pos = {}
        self.visible = []
        self.page = 0
        self.model.status.clear()
        self.model.set_rows([], 0)
        self._open_cache = (None, 0)
        self._fv_sig = None

    def _data_append(self, needs: list[Need]):
        for n in needs:
            if n.need_no not in self.all_pos:
                self.all_pos[n.need_no] = len(self.all_needs)
                self.all_needs.append(n)

    def _sort_key(self, col: int):
        key = COLUMNS[col][0]
        stage_of = self.stage_of
        if key == "select":
            return lambda n: 0 if n.need_no in self.checked else 1
        if key == "star":
            def star_key(n):
                st = stage_of(n.need_no)
                return 0 if st and st != P.REJECTED else (2 if not st else 1)
            return star_key
        if key == "row":
            return lambda n: self.all_pos[n.need_no]
        if key == "docs":
            return lambda n: -self.dl_rank(n.need_no)
        if key == "deadline":
            def deadline_key(n):
                h = self.remaining_hours_for(n.need_no)
                return h if h is not None else 1e9
            return deadline_key
        if key == "status":
            def status_key(n):
                st = stage_of(n.need_no)
                return P.STAGE_KEYS.index(st) if st in P.STAGE_KEYS else (90 if st else 99)
            return status_key
        if key == "need_no":
            return lambda n: western_digits(n.need_no)
        if key == "published":
            return lambda n: western_digits(n.published_date)
        display = self.model._display
        return lambda n: display(n, key, 0)

    def _sort_changed(self, column: int, order=Qt.AscendingOrder):
        self._sort = (column, order)
        if self._ready:
            self.page = 0
            self._rebuild_visible()

    def _rebuild_visible(self):
        """Filter + sort the whole list (plain Python, milliseconds) and show the current page."""
        pred = self._predicate
        vis = [n for n in self.all_needs if pred(n)] if pred else list(self.all_needs)
        col, order = self._sort
        if 0 <= col < len(COLUMNS):
            vis.sort(key=self._sort_key(col), reverse=(order == Qt.DescendingOrder))
        self.visible = vis
        self._show_page()

    def _page_count(self) -> int:
        return max(1, -(-len(self.visible) // self.page_size))

    def _show_page(self):
        pages = self._page_count()
        self.page = min(max(self.page, 0), pages - 1)
        start = self.page * self.page_size
        chunk = self.visible[start:start + self.page_size]
        cur = self.model.needs
        same = (self.model.offset == start and len(cur) == len(chunk)
                and all(a is b for a, b in zip(cur, chunk)))
        if not same:
            sb = self.view.verticalScrollBar()
            keep = sb.value() if self.model.offset == start else 0
            self.model.set_rows(chunk, start)
            if keep:
                sb.setValue(keep)
        self._update_pager()

    def _update_pager(self):
        pager = getattr(self, "pager", None)
        if pager is None:
            return
        pages = self._page_count()
        total = len(self.visible)
        pager.setVisible(total > 0 and (pages > 1 or self.page_size < total))
        start = self.page * self.page_size
        end = min(total, start + self.page_size)
        self.pager_label.setText(rtl(f"صفحهٔ {num(self.page + 1)} از {num(pages)}  ·  {num(start + 1)}–{num(end)} از {num(total)}"))
        self.pager_prev.setEnabled(self.page > 0)
        self.pager_first.setEnabled(self.page > 0)
        self.pager_next.setEnabled(self.page < pages - 1)
        self.pager_last.setEnabled(self.page < pages - 1)

    def _go_page(self, page: int):
        self.page = page
        self._show_page()
        self.view.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._reapply_expanded)

    def _page_size_changed(self, *_):
        try:
            size = int(self.pager_size.currentData())
        except (TypeError, ValueError):
            return
        if size == self.page_size:
            return
        first = self.page * self.page_size
        self.page_size = size
        self.page = first // size
        self._show_page()

    def _build_pager(self) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(16, 6, 16, 8)
        hl.setSpacing(6)
        self.pager_first = button("", "arrow_prev", None, "صفحهٔ اول")
        self.pager_prev = button("قبلی", "arrow_prev", None, "صفحهٔ قبل")
        self.pager_label = label("", "muted")
        self.pager_next = button("بعدی", "arrow_next", None, "صفحهٔ بعد")
        self.pager_last = button("", "arrow_next", None, "صفحهٔ آخر")
        self.pager_first.clicked.connect(lambda: self._go_page(0))
        self.pager_prev.clicked.connect(lambda: self._go_page(self.page - 1))
        self.pager_next.clicked.connect(lambda: self._go_page(self.page + 1))
        self.pager_last.clicked.connect(lambda: self._go_page(self._page_count() - 1))
        for b in (self.pager_first, self.pager_prev):
            hl.addWidget(b)
        hl.addWidget(self.pager_label)
        for b in (self.pager_next, self.pager_last):
            hl.addWidget(b)
        hl.addStretch(1)
        hl.addWidget(label("ردیف در هر صفحه:", "muted"))
        self.pager_size = QComboBox()
        for n in (100, 200, 500, 1000):
            self.pager_size.addItem(num(n), n)
        self.pager_size.setCurrentIndex(1)
        self.pager_size.currentIndexChanged.connect(self._page_size_changed)
        hl.addWidget(self.pager_size)
        w.hide()
        return w

    def _clear_filters(self):
        widgets = (self.search, self.province_combo, self.category_combo, self.org_combo, self.group_combo, self.only_star, self.only_open, self.only_new, self.only_dl)
        for w in widgets:
            w.blockSignals(True)
        self.search.clear()
        for combo in (self.province_combo, self.category_combo):
            combo.setCurrentIndex(0)
        self.org_combo.clear_selection()
        for combo in (self.group_combo,):
            combo.setCurrentIndex(-1)
            combo.setEditText("")
        self.only_star.setChecked(False)
        self.only_open.setChecked(False)
        self.only_new.setChecked(False)
        self.only_dl.setChecked(False)
        for w in widgets:
            w.blockSignals(False)
        self._sync_more()
        self._apply_filters()

    def _refill_combo(self, combo: QComboBox, values: list[str]):
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(combo.property("all_text"))
        combo.addItems(values)
        if combo.isEditable():
            combo.setCurrentIndex(-1 if current in ("", combo.property("all_text")) else combo.findText(current))
            combo.setEditText("" if current == combo.property("all_text") else current)
        else:
            i = combo.findText(current)
            combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def _refresh_filter_values(self):
        needs = self.all_needs
        sig = (len(needs), needs[-1].need_no if needs else "")
        if sig == self._fv_sig:
            return
        self._fv_sig = sig
        self._refill_combo(self.province_combo, sorted({n.province for n in needs if n.province}))
        self._refill_combo(self.category_combo, sorted({n.category for n in needs if n.category}))
        self.org_combo.set_values(sorted({n.organization for n in needs if n.organization}))
        self._refill_combo(self.group_combo, sorted({g for g in map(need_group, needs) if g}))

    # ------------------------------------------------------------ row expansion
    def _on_clicked(self, index: QModelIndex):
        if not index.isValid() or index.parent().isValid():
            return
        top = index.siblingAtColumn(0)
        key = top.data(NEED_ROLE)
        if index.column() == COL["star"]:
            self.toggle_star(key)
            return
        if index.column() == COL["select"]:
            self.toggle_check(key)
            return
        if self.side is not None:
            self.side.show_need(key)
            if not self.store.get_detail(key) and key not in self.detail_errors and key not in self.detail_pending:
                self.request_detail(key)
            return
        now = time.monotonic()
        last_key, last_time = self._last_toggle
        if key == last_key and (now - last_time) * 1000 < QApplication.doubleClickInterval():
            return
        self._last_toggle = (key, now)
        self.view.setExpanded(top, not self.view.isExpanded(top))

    def _on_expanded(self, index: QModelIndex):
        if index.parent().isValid():
            return
        need_no = index.data(NEED_ROLE)
        self.expanded.add(need_no)
        self._install_card(index)
        if not self.store.get_detail(need_no) and need_no not in self.detail_errors:
            self.request_detail(need_no)
        QTimer.singleShot(40, lambda: self._scroll_to_open(index))

    def _scroll_to_open(self, index: QModelIndex):
        if not index.isValid():
            return
        row_rect = self.view.visualRect(index)
        child_rect = self.view.visualRect(self.model.index(0, 0, index))
        if row_rect.top() < 0 or child_rect.bottom() > self.view.viewport().height():
            self.view.scrollTo(index, QAbstractItemView.PositionAtTop)

    def _on_collapsed(self, index: QModelIndex):
        if index.parent().isValid():
            return
        self.expanded.discard(index.data(NEED_ROLE))

    def collapse_need(self, need_no: str):
        idx = self._need_proxy_index(need_no)
        if idx.isValid():
            self.view.collapse(idx)
            self.view.scrollTo(idx)
        self.expanded.discard(need_no)

    def _install_card(self, parent_index: QModelIndex, force: bool = False):
        need = self.model.need_at(parent_index)
        if need is None:
            return
        child = self.model.index(0, 0, parent_index)
        if not child.isValid():
            return
        self.view.setFirstColumnSpanned(0, parent_index, True)
        if force or self.view.indexWidget(child) is None:
            payload = None if need.need_no in self.detail_pending else self.detail_payload(need.need_no)
            self.view.setIndexWidget(child, DetailCard(self, need, payload))
            QTimer.singleShot(0, self.view.doItemsLayout)

    def _reapply_expanded(self):
        for need_no in list(self.expanded):
            if need_no not in self.all_pos:
                self.expanded.discard(need_no)
                continue
            idx = self._need_proxy_index(need_no)
            if not idx.isValid():
                continue
            self._install_card(idx)
            if not self.view.isExpanded(idx):
                self.view.setExpanded(idx, True)

    def _refresh_list_card(self, need_no: str):
        if need_no in self.expanded:
            idx = self._need_proxy_index(need_no)
            if idx.isValid():
                self._install_card(idx, force=True)

    def request_detail(self, need_no: str, force: bool = False):
        need = self.need_obj(need_no)
        if need is None or (need_no in self.detail_pending and not force):
            return
        self.detail_errors.pop(need_no, None)
        self.detail_pending.add(need_no)
        self._refresh_list_card(need_no)
        self.tasks.put({"command": "detail", "need": need})

    # ------------------------------------------------------------ context menu
    def _context_menu(self, pos: QPoint):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        need = self.model.need_at(index)
        if need is None:
            return
        nn = need.need_no
        top = self._need_proxy_index(nn)
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.RightToLeft)
        is_open = self.view.isExpanded(top)
        a_toggle = None if self.embedded else menu.addAction(make_icon("list_check"), "بستن جزئیات" if is_open else "نمایش جزئیات زیر همین ردیف")
        stage = self.stages.get(nn)
        a_case = menu.addAction(make_icon("folder"), "باز کردن پرونده" if stage else "ستاره‌دار کن و پرونده را باز کن")
        a_star = menu.addAction(make_icon("star"), "افزودن به ستاره‌دارها" if not stage else
                                ("بازگرداندن به پیگیری" if stage == P.REJECTED else "برداشتن از پیگیری…"))
        menu.addSeparator()
        a_copy_no = menu.addAction(make_icon("copy"), "کپی شماره نیاز")
        a_copy_desc = menu.addAction(make_icon("copy"), "کپی شرح نیاز")
        a_copy_url = menu.addAction(make_icon("copy"), "کپی آدرس صفحه جزئیات")
        menu.addSeparator()
        a_dl = menu.addAction(make_icon("download"), "دانلود پیوست‌های همین نیاز")
        menu.addSeparator()
        a_unstar_all = menu.addAction(make_icon("star"), "برداشتن ستارهٔ همهٔ ستاره‌دارها…")
        chosen = menu.exec(self.view.viewport().mapToGlobal(pos))
        if chosen is a_toggle:
            self.view.setExpanded(top, not is_open)
        elif chosen is a_case:
            self.open_case(nn)
        elif chosen is a_star:
            self.toggle_star(nn)
        elif chosen is a_copy_no:
            self.copy_text(nn, "شماره نیاز کپی شد.")
        elif chosen is a_copy_desc:
            self.copy_text(need.description, "شرح نیاز کپی شد.")
        elif chosen is a_copy_url:
            self.copy_text(need.detail_url, "آدرس صفحه جزئیات کپی شد.")
        elif chosen is a_dl:
            self.download_needs([need])
        elif chosen is a_unstar_all:
            self._unstar_all()

    # ------------------------------------------------------------ commands
    def _launch(self):
        self.tasks.put({"command": "launch"})
        self._log("در حال باز کردن مرورگر…")

    def _refresh(self):
        pages = self.pages_combo.currentText()
        self.tasks.put({"command": "refresh", "pages": 0 if pages == "خودکار" else int(pages)})
        self._log("در حال خواندن صفحه‌ها؛ لطفاً در طول عملیات صفحه مرورگر را تغییر ندهید.")

    def _quick_since(self):
        """Jalali date (yyyy/mm/dd) = newest announce date in the current list minus 3 days; None when unknown."""
        try:
            from setad_tender.dates import parse_jalali, jalali_of
            from datetime import timedelta
            dates = [d for d in (parse_jalali(n.published_date) for n in self.all_needs) if d]
            if not dates:
                return None
            return jalali_of(max(dates) - timedelta(days=3))
        except Exception:
            return None

    def _quick_refresh(self):
        since = self._quick_since()
        if not since:
            QMessageBox.information(self, "به‌روزرسانی سریع",
                                    rtl("ابتدا یک‌بار «دریافت نیازها» را بزنید تا فهرست پایه ساخته شود."))
            return
        self.tasks.put({"command": "refresh", "mode": "search", "since": since, "pages": 0})
        self._log(f"به‌روزرسانی سریع: نیازهای اعلام‌شده از {since} به بعد.")

    def _download_starred(self):
        needs = self._starred_in_list()
        if not needs:
            QMessageBox.information(self, "دانلود", rtl("ابتدا با کلیک روی ☆ نیازهای موردنظر را ستاره‌دار کنید."))
            return
        self.download_needs(needs)

    def download_needs(self, needs: list[Need], quiet: bool = False):
        self.tasks.put({"command": "download", "needs": needs, "directory": str(self.output_dir), "quiet": quiet})
        self._log(f"درخواست دانلود مدارک {len(needs)} نیاز ثبت شد.")
        self._quiet_download = quiet

    def _choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "انتخاب پوشه اصلی برای ذخیره نیازها", str(self.output_dir))
        if path:
            self.output_dir = Path(path)
            self.dir_edit.setText(str(self.output_dir))
            self.settings.setValue("output_dir", str(self.output_dir))
            self.scan_downloads()

    def _open_directory(self, path: str | None = None):
        dest = Path(path) if path else self.output_dir
        dest.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest)))

    def _export(self):
        if not self.all_needs:
            QMessageBox.information(self, "خروجی", rtl("ابتدا فهرست نیازها را دریافت کنید."))
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره فهرست نیازها", str(self.output_dir / "setadiran-needs.csv"), "CSV UTF-8 (*.csv)")
        if path:
            visible = list(self.visible)             # every filtered row, not just the current page
            export_csv(visible, Path(path))
            self._log(f"{len(visible)} ردیف در {path} ذخیره شد. برای حفظ شناسه‌های بلند در Excel، ستون شماره نیاز را Text وارد کنید.")

    def _stop(self):
        self.cancel.set()
        self._log("درخواست توقف ثبت شد. عملیات پس از پایان درخواست جاری متوقف می‌شود.")

    # ------------------------------------------------------------ engine events
    def _on_detail_event(self, message: dict):
        need_no = message["need_no"]
        self.detail_pending.discard(need_no)
        payload = {
            "content": message.get("content", ""), "rows": message.get("rows") or [], "info": message.get("info") or {},
            "attachments": message.get("attachments"), "attach_error": message.get("attach_error", ""),
            "error": message.get("error", ""),
        }
        if payload["error"]:
            if not self.store.get_detail(need_no):
                self.detail_errors[need_no] = payload
        else:
            self.detail_errors.pop(need_no, None)
            self.store.save_detail(need_no, payload)
            exact = P.exact_deadline(payload["info"])
            if exact:
                self.store.set_exact_deadline(need_no, exact)
                self.meta.pop(need_no, None)
            self._warn_cache.pop(need_no, None)
            self.model.refresh_row(need_no)
            if self.stages.get(need_no) == "review":
                self._auto_download(need_no)
        if need_no in self._dl_counts:
            self._refresh_dl(need_no)          # the site's list may change complete/partial
        self._refresh_list_card(need_no)
        if self.side is not None and self.side.need_no == need_no:
            self.side.show_need(need_no)
        win = self.case_windows.get(need_no)
        if win:
            win.on_detail()
        if self.stages.get(need_no):
            self.board.refresh()

    def _poll_events(self):
        if self._shutting_down:
            return
        needs_changed = False
        try:
            for _ in range(80):
                message = self.events.get_nowait()
                kind = message["kind"]
                if kind == "busy":
                    self._set_busy(bool(message["value"]))
                elif kind == "connected":
                    self.browser_opened = True
                    self._set_busy(self.busy)
                elif kind == "disconnected":
                    self.browser_opened = False
                    self._set_pill("مرورگر بسته است", "off")
                    self._log("پنجره مرورگر ستاد بسته شد؛ برای ادامه دوباره «باز کردن مرورگر و ورود» را بزنید.")
                elif kind == "clear_needs":
                    prev = self.store.get("last_refresh_at", 0) or 0
                    self.store.set("prev_refresh_at", prev)
                    self.store.set("last_refresh_at", time.time())
                    self.store.set("list_since", time.time())
                    self._has_prev_refresh = bool(prev)
                    self.view.collapseAll()
                    self.expanded.clear()
                    self.detail_errors.clear()
                    self.search_text.clear()
                    self.new_needs.clear()
                    self._data_clear()
                    self.pages_read = 0
                    needs_changed = True
                elif kind == "captcha":
                    self._log(message["message"])
                    self._set_info(message["message"])
                    try:
                        if getattr(self, "_captcha_box", None) is not None:
                            self._captcha_box.close()
                        box = QMessageBox(QMessageBox.Warning, "کپچا", rtl(message["message"]), QMessageBox.Ok, self)
                        box.setWindowModality(Qt.NonModal)
                        box.setAttribute(Qt.WA_DeleteOnClose, True)
                        box.show()
                        self._captcha_box = box
                    except Exception:
                        pass
                elif kind == "captcha_done":
                    try:
                        if getattr(self, "_captcha_box", None) is not None:
                            self._captcha_box.close()
                    except Exception:
                        pass
                    self._captcha_box = None
                    self._set_info("کپچا وارد شد؛ دریافت ادامه دارد.")
                elif kind == "quick_start":
                    prev = self.store.get("last_refresh_at", 0) or 0
                    self.store.set("prev_refresh_at", prev)
                    self.store.set("last_refresh_at", time.time())
                    self._has_prev_refresh = True
                elif kind == "needs":
                    fresh = [clean_need(n) for n in message["needs"] if n.need_no not in self.all_pos]
                    if fresh:
                        brand_new = self.store.upsert_needs(fresh)
                        if self._has_prev_refresh:
                            self.new_needs.update(brand_new)
                        self.meta.update(self.store.need_meta([n.need_no for n in fresh]))
                        for n in fresh:
                            self._index_need(n)
                        self._data_append(fresh)
                    if "pages" in message:
                        self.pages_read = int(message["pages"])
                    needs_changed = True
                elif kind == "detail":
                    self._on_detail_event(message)
                elif kind == "status":
                    self.model.set_status(message["need_no"], message["status"])
                elif kind == "progress":
                    self._set_info(message["message"])
                elif kind == "info":
                    self._log(message["message"])
                    self._set_info(message["message"])
                elif kind == "error":
                    self._log("خطا: " + message["message"])
                    QMessageBox.critical(self, "اشکال در عملیات", rtl(message["message"]))
                elif kind == "completed_refresh":
                    self._log(f"دریافت فهرست تکمیل شد: {message['count']} نیاز یکتا؛ {message['duplicates']} تکراری.")
                    newc = len(self.new_needs)
                    self._set_info("فهرست آماده است." + (f" {newc} نیاز جدید از دریافت قبلی." if newc else ""))
                elif kind == "completed_download":
                    self._on_download_done(message)
        except queue.Empty:
            pass
        if needs_changed:
            self._heavy_pending = True
        if self._heavy_pending:
            now = time.monotonic()
            # while pages are still arriving refresh the list at most every 2.5 s; at the end do it once
            if not self.busy or now - self._last_heavy >= 2.5:
                self._heavy_pending = False
                self._last_heavy = now
                self._refresh_filter_values()
                self._apply_filters(reset_page=False)

    def _on_download_done(self, message: dict):
        r = message["results"]
        summary = (f"دانلودشده: {r['downloaded']}  |  قبلاً موجود: {r['skipped']}  |  ناموفق: {r['failed']}"
                   f"  |  غیرمجاز: {r['restricted']}  |  بدون پیوست: {r['no_files']}")
        self._log(summary)
        self._set_info(summary)
        self.scan_downloads()
        for win in self.case_windows.values():
            win.reload()
        if self.side is not None and getattr(self.side, "need_no", None):
            self.side.show_need(self.side.need_no)      # v0.9.14: chips know what is downloaded now
        if getattr(self, "_quiet_download", False) and not r["failed"]:
            return
        box = CompactBox(self)
        box.setWindowTitle("پایان عملیات")
        box.setIcon(QMessageBox.Information)
        box.setText(rtl(summary))
        box.setInformativeText(message["directory"])
        open_btn = box.addButton("باز کردن پوشه", QMessageBox.AcceptRole)
        box.addButton("بستن", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_directory(message.get("folder") or message["directory"])  # v0.9.10: a single need opens its own folder

    # ------------------------------------------------------------ shutdown
    def closeEvent(self, event):
        if not self._shutting_down:
            self._save_settings()
            for win in list(self.case_windows.values()):
                win.close()
            self._shutting_down = True
            self.poll_timer.stop()
            self.clock.stop()
            self.cancel.set()
            shutdown = getattr(self.worker, "shutdown", None)
            if shutdown is not None:
                shutdown.set()
            self.tasks.put({"command": "quit"})
            self._set_info("در حال بستن ایمن مرورگر و برنامه…")
            self.setEnabled(False)
            self._close_deadline = time.monotonic() + 20
            QTimer.singleShot(120, self._finish_exit)
            event.ignore()
            return
        event.accept()

    def _finish_exit(self):
        if self.worker.is_alive() and time.monotonic() < self._close_deadline:
            QTimer.singleShot(150, self._finish_exit)
        else:
            self.store.close()
            QApplication.instance().quit()


# ---------------------------------------------------------------- entry point
def create_app(argv=None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("SetadiranManager")
    app.setLayoutDirection(Qt.RightToLeft)
    app.setStyle("Fusion")
    family = load_fonts()
    font = QFont(family, 10)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(family))
    return app


def main():
    app = create_app(sys.argv)
    window = ManagerUI()
    if window.settings.value("geometry") is None:
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
