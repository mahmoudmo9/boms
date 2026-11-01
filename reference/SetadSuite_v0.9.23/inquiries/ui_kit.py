"""Shared look & feel: palette, text helpers, icons, style sheet and small widgets."""
from __future__ import annotations

import dataclasses
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from parser import Need, western_digits

RLM = "‏"  # right-to-left mark: forces RTL paragraph direction for mixed text

# ---------------------------------------------------------------- palette
C = {
    "bg": "#F3F5F9",
    "surface": "#FFFFFF",
    "border": "#E4E7EC",
    "border_strong": "#D0D5DD",
    "text": "#101828",
    "text_2": "#344054",
    "muted": "#667085",
    "primary": "#0F766E",
    "primary_hover": "#115E59",
    "primary_soft": "#E6F4F2",
    "primary_soft_2": "#F0FAF8",
    "header_a": "#0F2A3D",
    "header_b": "#14505C",
    "danger": "#B42318", "danger_soft": "#FEF3F2",
    "warn": "#B54708", "warn_soft": "#FFF6E5",
    "ok": "#067647", "ok_soft": "#ECFDF3",
    "info": "#175CD3", "info_soft": "#EFF8FF",
    "neutral": "#475467", "neutral_soft": "#F2F4F7",
    "hover": "#F5F8FC", "row_alt": "#F8FAFC", "divider": "#EEF2F6", "head_bg": "#F8FAFC", "hover_card": "#FBFDFF",
    "primary_border": "#C4DAF5", "amber_border": "#F1D6A8", "red_border": "#F3C3BD", "green_border": "#BFE3CF",
    "scroll": "#CBD5E1", "scroll_hover": "#94A3B8", "track": "#E6ECF3", "disabled_bg": "#F6F8FB", "faint": "#94A3B8",
    "btn_hover_border": "#9FB4CC", "input": "#FFFFFF", "card": "#FFFFFF", "select": "#E3EEFC", "pressed": "#EAF0F7",
}


def resource_dir() -> Path:
    """Folder holding fonts/ and assets/ (also works inside a PyInstaller build)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "inquiries" / "fonts").exists():   # inside the suite's EXE build
        return Path(meipass) / "inquiries"
    return Path(meipass) if meipass else Path(__file__).resolve().parent


def app_home() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    else:
        base = Path.home() / ".local" / "share"
    return base / "SetadiranManager"


# ---------------------------------------------------------------- text helpers
_FA_FIX = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})
_SEARCH_FIX = str.maketrans({
    "ي": "ی", "ك": "ک", "ى": "ی", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "‌": " ", "‏": "", "‎": "", "ـ": "",
})
_EN_GLOSS = re.compile(r"\s*\(\s*[A-Za-z][A-Za-z0-9 .,/&'\-]*\)\s*")


def fa(value) -> str:
    """Display-normalise Persian text: Arabic Yeh/Kaf → Persian, tidy spaces."""
    text = " ".join(str(value or "").split()).translate(_FA_FIX)
    return "" if text.lower() == "null" else text


def strip_english_gloss(label: str) -> str:
    """'شماره نیاز (Need No)' → 'شماره نیاز' so labels are not half English."""
    cleaned = _EN_GLOSS.sub(" ", label).strip(" :：")
    return cleaned or label.strip(" :：")


def norm(value: str) -> str:
    """Normalisation used only for searching."""
    return " ".join(western_digits(str(value)).translate(_SEARCH_FIX).casefold().split())


def rtl(text: str) -> str:
    return RLM + text if text else text


def deadline_hours(text: str) -> float | None:
    t = western_digits(text or "")
    d = re.search(r"(\d+)\s*روز", t)
    h = re.search(r"(\d+)\s*ساعت", t)
    m = re.search(r"(\d+)\s*دقیقه", t)
    if not (d or h or m):
        return None
    return (int(d.group(1)) * 24 if d else 0) + (int(h.group(1)) if h else 0) + (int(m.group(1)) / 60 if m else 0)


def deadline_colors(text: str) -> tuple[str, str]:
    hours = deadline_hours(text)
    if hours is None:
        return C["neutral"], C["neutral_soft"]
    if hours <= 48:
        return C["danger"], C["danger_soft"]
    if hours <= 96:
        return C["warn"], C["warn_soft"]
    return C["ok"], C["ok_soft"]


def status_colors(text: str) -> tuple[str, str]:
    if "خطا" in text or "ناموفق" in text:
        return C["danger"], C["danger_soft"]
    if "تکمیل" in text:
        return C["ok"], C["ok_soft"]
    if "در حال" in text:
        return C["info"], C["info_soft"]
    return C["neutral"], C["neutral_soft"]


def need_group(need: Need) -> str:
    return need.goods_group or need.service_group


def clean_need(need: Need) -> Need:
    """Return a copy with display-normalised text fields (ids/urls untouched)."""
    changes = {
        f: fa(getattr(need, f))
        for f in ("description", "organization", "province", "need_type", "category",
                  "goods_group", "service_group", "published_date", "response_deadline")
    }
    return dataclasses.replace(need, **changes)


# ---------------------------------------------------------------- icons
_ICON_PATHS = {
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.4-5.7L20 8.5"/><path d="M20 3.5v5h-5"/>',
    "download": '<path d="M12 4v11"/><path d="m7 10.5 5 5 5-5"/><path d="M5 20h14"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "folder_edit": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v2"/><path d="M3.5 7.5V17a2 2 0 0 0 2 2H11"/><path d="m14 19 .5-2.5 4.8-4.8a1.4 1.4 0 0 1 2 2l-4.8 4.8z"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "spreadsheet": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h2"/><path d="M14 13h2"/><path d="M8 17h2"/><path d="M14 17h2"/>',
    "file": '<path d="M14 3.5H7.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/><path d="M14 3.5V8h4.5"/><path d="M9 13h6M9 16.5h4"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    "check_all": '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="m8 12.2 2.8 2.8L16.5 9"/>',
    "list_check": '<path d="M10 6h10M10 12h10M10 18h10"/><path d="m3.5 6 1.5 1.5L7.5 5M3.5 12l1.5 1.5L7.5 11M3.5 18l1.5 1.5L7.5 17"/>',
    "x": '<path d="M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5v-2a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
    "filter_off": '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/><path d="m15.5 15.5 5 5M20.5 15.5l-5 5"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "rotate_cw": '<path d="M20 4v6h-6"/><path d="M19.5 15a8 8 0 1 1-2-8.3L20 10"/>',
    "rotate_ccw": '<path d="M4 4v6h6"/><path d="M4.5 15a8 8 0 1 0 2-8.3L4 10"/>',
    "paperclip": '<path d="m20 11.5-7.8 7.8a5 5 0 0 1-7-7l8.3-8.3a3.3 3.3 0 0 1 4.7 4.7L9.9 17a1.7 1.7 0 0 1-2.4-2.4l7.4-7.4"/>',
    "inbox": '<path d="M3.5 13.5 6 5.5h12l2.5 8"/><path d="M3.5 13.5v5a1.5 1.5 0 0 0 1.5 1.5h14a1.5 1.5 0 0 0 1.5-1.5v-5h-5l-1.5 2.5h-4l-1.5-2.5z"/>',
    "retry": '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 3.5v5h5"/>',
    "star": '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    "board": '<rect x="3.5" y="4" width="5" height="16" rx="1.5"/><rect x="9.5" y="4" width="5" height="11" rx="1.5"/><rect x="15.5" y="4" width="5" height="7" rx="1.5"/>',
    "users": '<circle cx="9" cy="8.5" r="3.5"/><path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><circle cx="17" cy="9" r="2.6"/><path d="M16.5 14.6c2.4.2 4 1.7 4.5 4.4"/>',
    "archive": '<rect x="3.5" y="4.5" width="17" height="4.5" rx="1.2"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="m4 20 1-4.5L15.5 5a2.1 2.1 0 0 1 3 3L8 18.5z"/><path d="M13.5 7l3 3"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "send": '<path d="M20.5 3.5 10 14"/><path d="m20.5 3.5-6.5 17-4-6.5-6.5-4z"/>',
    "calc": '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M8.5 7.5h7M8.5 12h1M12 12h1M15.5 12h0M8.5 16h1M12 16h1M15.5 16h0"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "arrow_next": '<path d="M15 6l-6 6 6 6"/>',
    "arrow_prev": '<path d="M9 6l6 6-6 6"/>',
    "alert": '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    "app": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M3.5 9h17"/><path d="M8 13h8M8 16h5"/>',
}


def make_icon(name: str, color: str = C["text_2"], size: int = 18) -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        f'{_ICON_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


# ---------------------------------------------------------------- style sheet
def build_stylesheet(font_family: str) -> str:
    a = (resource_dir() / "assets").as_posix()
    return f"""
* {{ font-family: "{font_family}"; }}
QMainWindow, QWidget#root {{ background: {C['bg']}; }}
QToolTip {{ background: {C['text']}; color: white; border: none; padding: 6px 9px; border-radius: 6px; }}

QFrame#header {{
    border-radius: 14px;
    background: qlineargradient(x1:1, y1:0, x2:0, y2:1, stop:0 {C['header_a']}, stop:1 {C['header_b']});
}}
QLabel#appTitle {{ color: white; font-size: 17pt; font-weight: 700; }}
QLabel#appSubtitle {{ color: #B9CCD8; font-size: 9.5pt; }}
QLabel#pill {{ border-radius: 12px; padding: 4px 12px; font-size: 9pt; font-weight: 600; }}
QLabel#pill[state="off"] {{ background: rgba(255,255,255,0.10); color: #D0DCE5; }}
QLabel#pill[state="on"] {{ background: #D1FADF; color: #05603A; }}
QLabel#pill[state="busy"] {{ background: #FEF0C7; color: #93370D; }}

QFrame#card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px; }}
QFrame#vline {{ background: {C['border']}; max-width: 1px; min-width: 1px; }}
QLabel {{ color: {C['text_2']}; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 700; color: {C['text']}; }}
QLabel#pageTitle {{ font-size: 16pt; font-weight: 800; color: {C['text']}; }}
QLabel#muted {{ color: {C['muted']}; }}
QLabel#pageCount {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#fieldLabel {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#statValue {{ font-size: 15pt; font-weight: 700; color: {C['header_a']}; }}
QLabel#statLabel {{ color: {C['muted']}; font-size: 8.5pt; }}

QPushButton {{
    background: {C['surface']}; border: 1px solid {C['border_strong']}; border-radius: 9px;
    padding: 7px 14px; color: {C['text_2']}; font-weight: 600;
}}
QPushButton:hover {{ background: {C['hover']}; border-color: {C['btn_hover_border']}; }}
QPushButton:pressed {{ background: {C['neutral_soft']}; }}
QPushButton:disabled {{ color: {C['faint']}; background: {C['hover']}; border-color: {C['border']}; }}
QPushButton[kind="primary"] {{
    background: {C['primary']}; border: 1px solid {C['primary']}; color: white;
    font-weight: 600; padding: 7px 18px;
}}
QPushButton[kind="primary"]:hover {{ background: {C['primary_hover']}; border-color: {C['primary_hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {C['primary_hover']}; }}
QPushButton[kind="primary"]:disabled {{ background: {C['disabled_bg']}; border-color: {C['disabled_bg']}; color: {C['faint']}; }}
QPushButton[kind="danger"] {{ color: {C['danger']}; border-color: {C['red_border']}; }}
QPushButton[kind="danger"]:hover {{ background: {C['danger_soft']}; border-color: {C['red_border']}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {C['primary']}; padding: 6px 10px; }}
QPushButton[kind="ghost"]:hover {{ background: {C['primary_soft']}; }}
QPushButton[kind="ghost"]:disabled {{ color: {C['faint']}; }}
QPushButton[kind="ghost"]:checked {{ background: {C['primary_soft']}; }}
QPushButton[kind="ghostAlert"] {{
    background: {C['danger_soft']}; border: 1px solid {C['red_border']}; color: {C['danger']};
    padding: 6px 10px; font-weight: 600;
}}

QLineEdit, QComboBox {{
    background: {C['surface']}; border: 1px solid {C['border_strong']}; border-radius: 9px;
    padding: 6px 10px; min-height: 22px; color: {C['text']};
    selection-background-color: {C['primary_soft']}; selection-color: {C['text']};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: {C['btn_hover_border']}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {C['primary']}; }}
QLineEdit[readOnly="true"] {{ background: {C['neutral_soft']}; color: {C['text_2']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{a}/chevron-combo.svg"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 4px;
    selection-background-color: {C['primary_soft']}; selection-color: {C['text']}; outline: 0;
}}

QTreeView {{
    background: {C['surface']}; border: none; outline: 0;
    alternate-background-color: {C['row_alt']}; color: {C['text']};
}}
QTreeView::item {{ border-bottom: 1px solid {C['divider']}; padding: 0 4px; }}
QTreeView::item:hover {{ background: {C['primary_soft_2']}; }}
QTreeView::item:selected {{ background: {C['primary_soft']}; color: {C['text']}; }}
QTreeView::branch {{ border-bottom: 1px solid {C['divider']}; }}
QTreeView::branch:hover {{ background: {C['primary_soft_2']}; }}
QTreeView::branch:selected {{ background: {C['primary_soft']}; }}
QTreeView::branch:has-children:closed {{ image: url("{a}/chevron-closed.svg"); }}
QTreeView::branch:has-children:open {{ image: url("{a}/chevron-open.svg"); }}
QTreeView::indicator {{ width: 18px; height: 18px; }}
QTreeView::indicator:unchecked {{ image: url("{a}/box.svg"); }}
QTreeView::indicator:unchecked:hover {{ image: url("{a}/box-hover.svg"); }}
QTreeView::indicator:checked {{ image: url("{a}/box-checked.svg"); }}
QHeaderView {{ background: {C['head_bg']}; border: none; }}
QHeaderView::section {{
    background: {C['head_bg']}; color: {C['muted']}; font-weight: 600; font-size: 9pt;
    padding: 9px 8px; border: none; border-bottom: 1px solid {C['border']};
    border-left: 1px solid {C['divider']};
}}
QHeaderView::section:hover {{ background: {C['hover']}; color: {C['text_2']}; }}

QFrame#detailCard {{
    background: {C['hover_card']}; border: 1px solid {C['primary_border']}; border-right: 4px solid {C['primary']};
    border-radius: 10px;
}}
QLabel#detailTitle {{ font-size: 12.5pt; font-weight: 700; color: {C['text']}; }}
QLabel#chip {{
    background: {C['neutral_soft']}; color: {C['text_2']}; border-radius: 11px; padding: 3px 11px; font-size: 9pt;
}}
QLabel#chipAccent {{
    background: {C['primary_soft']}; color: {C['primary']}; border-radius: 11px; padding: 3px 11px;
    font-size: 9pt; font-weight: 600;
}}
QLabel#detailKey {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#detailValue {{ color: {C['text']}; }}
QLabel#detailSection {{ color: {C['primary']}; font-weight: 700; font-size: 9.5pt; padding-top: 4px; }}
QLabel#attach {{
    background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 4px 10px; color: {C['text_2']};
}}
QLabel#attach[local="false"] {{ color: {C['muted']}; }}
QLabel#attach[selected="true"] {{ background: {C['primary_soft']}; border: 1px solid {C['primary']}; color: {C['primary']}; font-weight: 600; }}
QLabel#notice {{ color: {C['muted']}; background: {C['neutral_soft']}; border-radius: 8px; padding: 8px 12px; }}
QLabel#noticeError {{ color: {C['danger']}; background: {C['danger_soft']}; border-radius: 8px; padding: 8px 12px; }}
QLabel#noteBox {{
    background: {C['warn_soft']}; color: {C['text']}; border: 1px solid {C['amber_border']}; border-radius: 8px;
    padding: 9px 12px; line-height: 160%;
}}
QFrame#itemsTable {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; }}
QLabel#th {{
    background: {C['head_bg']}; color: {C['text_2']}; font-weight: 600; font-size: 9pt; padding: 7px 8px;
    border-bottom: 1px solid {C['border']};
}}
QLabel#td, QLabel#tdAlt {{ color: {C['text']}; padding: 7px 8px; border-bottom: 1px solid {C['divider']}; }}
QLabel#tdAlt {{ background: {C['row_alt']}; }}
QFrame#hline {{ background: {C['divider']}; max-height: 1px; min-height: 1px; }}

QLabel#emptyTitle {{ font-size: 13pt; font-weight: 700; color: {C['text']}; }}
QLabel#emptyText {{ color: {C['muted']}; }}

QPlainTextEdit#log {{
    background: {C['head_bg']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 6px 10px;
    color: {C['text_2']}; font-size: 9pt;
}}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:vertical {{ height: 8px; }}

QStatusBar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; color: {C['text_2']}; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{ background: {C['primary_soft']}; border: none; border-radius: 3px; max-height: 6px; min-width: 140px; }}
QProgressBar::chunk {{ background: {C['primary']}; border-radius: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['scroll']}; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {C['scroll_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C['scroll']}; border-radius: 4px; min-width: 36px; }}
QScrollBar::handle:horizontal:hover {{ background: {C['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 22px; border-radius: 6px; color: {C['text_2']}; }}
QMenu::item:selected {{ background: {C['primary_soft']}; color: {C['text']}; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 4px 8px; }}
QMessageBox QLabel {{ color: {C['text']}; }}
QPushButton[state="busy"] {{ background: {C['primary_soft']}; color: {C['primary']}; border: 1px solid {C['primary_border']}; }}
QPushButton[state="ok"] {{ background: {C['ok_soft']}; color: {C['ok']}; border: 1px solid {C['green_border']}; }}
QPushButton[state="err"] {{ background: {C['danger_soft']}; color: {C['danger']}; border: 1px solid {C['red_border']}; }}
QLabel {{ background: transparent; }}
QDialog {{ background: {C['bg']}; }}

QPushButton#headerBtn {{
    background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.22);
    border-radius: 9px; padding: 6px 14px; font-weight: 600;
}}
QPushButton#headerBtn:hover {{ background: rgba(255,255,255,0.22); }}
QPushButton[kind="toggle"] {{ padding: 4px 13px; border-radius: 15px; }}
QPushButton[kind="toggle"]:checked {{ background: {C['primary_soft']}; border-color: {C['primary']}; color: {C['primary']}; font-weight: 600; }}
QPushButton[kind="step"] {{ padding: 6px 10px; font-size: 9pt; border-radius: 8px; color: {C['muted']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {C['muted']}; font-weight: 600; padding: 9px 18px; margin-left: 4px;
    border: none; border-bottom: 3px solid transparent;
}}
QTabBar::tab:hover {{ color: {C['text_2']}; }}
QTabBar::tab:selected {{ color: {C['primary']}; border-bottom: 3px solid {C['primary']}; }}
QTabWidget#caseTabs QTabBar::tab {{ padding: 8px 16px; }}

QTableWidget {{
    background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; gridline-color: {C['divider']};
    alternate-background-color: {C['row_alt']}; selection-background-color: {C['primary_soft']}; selection-color: {C['text']};
}}
QTableWidget::item {{ padding: 0 6px; }}
QListWidget {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 4px 6px; }}
QAbstractSpinBox {{ qproperty-buttonSymbols: NoButtons; }}
QSpinBox, QDoubleSpinBox {{
    background: {C['surface']}; border: 1px solid {C['border_strong']}; border-radius: 8px; padding: 5px 8px; min-height: 22px;
}}
QPlainTextEdit {{ background: {C['surface']}; border: 1px solid {C['border_strong']}; border-radius: 8px; padding: 6px; }}
QCheckBox, QRadioButton {{ spacing: 8px; color: {C['text']}; padding: 3px 0; }}

QFrame#kcol {{ background: {C['track']}; border-radius: 12px; border: 2px solid transparent; }}
QFrame#kcol[drop="true"] {{ border: 2px dashed {C['primary']}; background: {C['primary_soft_2']}; }}
QLabel#kcolTitle {{ font-weight: 700; font-size: 10.5pt; color: {C['text']}; }}
QLabel#kcolCount {{ background: {C['surface']}; color: {C['muted']}; border-radius: 9px; padding: 1px 9px; font-size: 8.5pt; font-weight: 600; }}
QFrame#kcard {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QFrame#kcard:hover {{ border-color: {C['primary']}; }}
QFrame#kcardResult {{ background: {C['surface']}; border: 1px solid {C['border']}; border-right: 4px solid {C['ok']}; border-radius: 10px; }}
QLabel#kdesc {{ color: {C['text']}; font-weight: 600; font-size: 9.5pt; }}
QLabel#korg {{ color: {C['muted']}; font-size: 8.5pt; }}
"""



# ---------------------------------------------------------------- small widgets
def card_frame() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("vline")
    return f


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    return f


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(rtl(text))
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
    return lab


def button(text: str, icon: str | None = None, kind: str | None = None, tip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon:
        color = "#FFFFFF" if kind == "primary" else C["danger"] if kind == "danger" else C["primary"] if kind == "ghost" else C["text_2"]
        b.setIcon(make_icon(icon, color))
        b.setIconSize(QSize(17, 17))
        b.setProperty("_icon", icon)
    if tip:
        b.setToolTip(rtl(tip))
    b.setCursor(Qt.PointingHandCursor)
    if kind == "toggle":
        b.setFixedHeight(32)                       # filter chip
    elif kind not in ("step", "link"):
        b.setFixedHeight(38)                       # one height for every normal button
        if not text:
            b.setFixedWidth(38)                    # icon-only button: square
    return b


class StatBlock(QWidget):
    def __init__(self, title: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 2, 14, 2)
        lay.setSpacing(0)
        self.value = label("۰", "statValue")
        self.value.setAlignment(Qt.AlignCenter)
        cap = label(title, "statLabel")
        cap.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.value)
        lay.addWidget(cap)

    def set(self, value):
        self.value.setText(str(value))


class FlowRow(QWidget):
    """Horizontal row of chips that wraps onto further lines when space runs out."""

    def __init__(self, widgets: list[QWidget], spacing: int = 6):
        super().__init__()
        self._widgets = widgets
        self._spacing = spacing
        for w in widgets:
            w.setParent(self)
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(width, apply=False)

    def sizeHint(self):
        w = sum(x.sizeHint().width() + self._spacing for x in self._widgets)
        return QSize(w, self._layout(max(w, 1), apply=False))

    def minimumSizeHint(self):
        return QSize(60, self._widgets[0].sizeHint().height() if self._widgets else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout(self.width(), apply=True)

    def _layout(self, width: int, apply: bool) -> int:
        x = y = line_h = 0
        for w in self._widgets:
            hint = w.sizeHint()
            if x and x + hint.width() > width:
                x = 0
                y += line_h + self._spacing
                line_h = 0
            if apply:
                # right-to-left placement
                w.setGeometry(width - x - hint.width(), y, hint.width(), hint.height())
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h



def recolor_icons(root):
    """Re-draw button icons after a theme switch."""
    for b in root.findChildren(QPushButton):
        name = b.property("_icon")
        if not name or name not in _ICON_PATHS:
            continue
        kind = b.property("kind")
        color = "#FFFFFF" if kind == "primary" else C["danger"] if kind == "danger" else C["primary"] if kind == "ghost" else C["text_2"]
        b.setIcon(make_icon(name, color))


def make_icon_label(name: str, color: str, size: int = 17) -> QLabel:
    lab = QLabel()
    lab.setPixmap(make_icon(name, color, size).pixmap(size, size))
    return lab


# ---------------------------------------------------------------- entry point
def load_fonts() -> str:
    family = None
    for path in sorted((resource_dir() / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0 and family is None:
            fams = QFontDatabase.applicationFontFamilies(fid)
            family = fams[0] if fams else None
    if family:
        return family
    available = set(QFontDatabase.families())
    return next((f for f in ("Vazirmatn", "Vazir", "Tahoma", "Segoe UI") if f in available), QFont().family())




def pill(text: str, fg: str, bg: str, bold: bool = True) -> QLabel:
    lab = QLabel(rtl(text))
    lab.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:10px; padding:2px 10px;"
                      f" font-size:9pt; font-weight:{600 if bold else 400};")
    return lab


def tint(hex_color: str, alpha: float = 0.12) -> str:
    """Light background version of a strong colour (blend with white)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: int(255 - (255 - c) * alpha)
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def section(title: str) -> QLabel:
    return label(title, "sectionTitle")


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
