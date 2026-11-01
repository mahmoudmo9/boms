"""One design system for the whole suite: color tokens (light/dark), sizes, and the instant theme switch.

The three style sheets (shell, tenders section, inquiries section) all read their colors from the same
tokens. Switching theme updates the token dicts in place and re-applies every style sheet, then asks each
section to rebuild its cards so colors baked into small widgets follow too."""
from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication, QPushButton

from setad_tender import theme as T

BTN_H = 38          # every normal button has this height
CHIP_H = 32         # filter chips
ICON_BTN = 38       # square icon-only buttons
SETTINGS = ('Blue Alvand Industry', 'Setad Tender Manager')

# category colors (purchase vs tender) – same meaning everywhere
CATEGORY = {
    'light': dict(inq='#0e9384', inq_soft='#e3f6f3', ten='#7a5af8', ten_soft='#efebff'),
    'dark': dict(inq='#2cc4b0', inq_soft='#12312e', ten='#a78bfa', ten_soft='#2a2145'),
}


def current() -> str:
    return 'dark' if T.C.get('dark') else 'light'


def saved_theme() -> str:
    v = QSettings(*SETTINGS).value('theme', 'light')
    return 'dark' if v == 'dark' else 'light'


def tokens() -> dict:
    t = dict(T.C)
    t.update(CATEGORY[current()])
    return t


def inquiries_palette(t: dict) -> dict:
    """The inquiries section's palette keys, filled from the shared tokens (primary is the shared blue)."""
    return {
        'bg': t['bg'], 'surface': t['card'], 'border': t['border'], 'border_strong': t['border2'],
        'text': t['text'], 'text_2': t['text2'], 'muted': t['muted'],
        'primary': t['primary'], 'primary_hover': t['primary_hover'], 'primary_soft': t['primary_soft'],
        'primary_soft_2': t['hover'], 'header_a': t['navy'], 'header_b': t['navy2'],
        'danger': t['red'], 'danger_soft': t['red_soft'], 'warn': t['amber'], 'warn_soft': t['amber_soft'],
        'ok': t['green'], 'ok_soft': t['green_soft'], 'info': t['primary'], 'info_soft': t['primary_soft'],
        'neutral': t['muted'], 'neutral_soft': t['hover'],
        # extra shared tokens used by the style sheet
        'hover': t['hover'], 'row_alt': t['row_alt'], 'divider': t['divider'], 'head_bg': t['head_bg'],
        'hover_card': t['hover_card'], 'primary_border': t['primary_border'], 'amber_border': t['amber_border'],
        'red_border': t['red_border'], 'green_border': t['green_border'], 'scroll': t['scroll'],
        'scroll_hover': t['scroll_hover'], 'track': t['track'], 'disabled_bg': t['disabled_bg'],
        'faint': t['faint'], 'btn_hover_border': t['btn_hover_border'], 'input': t['input'], 'card': t['card'],
        'select': t['select'], 'pressed': t['pressed'],
    }


def shell_palette(t: dict) -> dict:
    return {
        'navy': t['navy'], 'navy2': t['navy2'], 'bg': t['bg'], 'card': t['card'], 'border': t['border'],
        'text': t['text'], 'text2': t['text2'], 'muted': t['muted'], 'faint': t['faint'],
        'primary': t['primary'], 'primary_soft': t['primary_soft'], 'hover': t['hover'], 'track': t['track'],
        'divider': t['divider'], 'primary_border': t['primary_border'], 'btn_hover_border': t['btn_hover_border'],
        'inq': t['inq'], 'inq_soft': t['inq_soft'], 'ten': t['ten'], 'ten_soft': t['ten_soft'],
        'red': t['red'], 'red_soft': t['red_soft'], 'amber': t['amber'], 'amber_soft': t['amber_soft'],
        'green': t['green'], 'green_soft': t['green_soft'], 'dark': t.get('dark', 0),
        'pressed': t['pressed'], 'disabled_bg': t['disabled_bg'], 'select': t['select'],
    }


def apply_tokens(name: str):
    """Update every palette dict in place (no widget is touched)."""
    T.apply_theme(name)
    t = tokens()
    try:
        from . import style
        style.P.clear()
        style.P.update(shell_palette(t))
    except Exception:
        pass
    try:
        import ui_kit  # inquiries section (top-level module)
        ui_kit.C.update(inquiries_palette(t))
    except Exception:
        pass


def set_theme(shell, name: str):
    """Instant switch: tokens → style sheets → rebuild cards/icons."""
    name = 'dark' if name == 'dark' else 'light'
    QSettings(*SETTINGS).setValue('theme', name)
    apply_tokens(name)
    app = QApplication.instance()
    if shell is not None and hasattr(shell, 'restyle'):
        shell.restyle()
    if app is not None:
        for w in app.topLevelWidgets():
            w.update()


# in-button feedback lives in setad_tender.widgets so both sections can use it
from setad_tender.widgets import busy_btn as busy, done_btn as done  # noqa: E402,F401


def button_rules(t: dict, scope: str = '') -> str:
    """Shared button sizing/state rules appended to every section's style sheet (equal height 38)."""
    s = scope
    return f'''
{s}QPushButton {{ min-height:{BTN_H - 16}px; max-height:{BTN_H - 16}px; padding-top:7px; padding-bottom:7px; }}
{s}QPushButton[state="busy"] {{ background:{t['primary_soft']}; color:{t['primary']}; border:1px solid {t['primary_border']}; }}
{s}QPushButton[state="ok"] {{ background:{t['green_soft']}; color:{t['green']}; border:1px solid {t['green_border']}; }}
{s}QPushButton[state="err"] {{ background:{t['red_soft']}; color:{t['red']}; border:1px solid {t['red_border']}; }}
'''
