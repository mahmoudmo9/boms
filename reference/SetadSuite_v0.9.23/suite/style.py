"""Shell style. Every selector is scoped by an object name starting with 'S' so nothing leaks into
the two embedded sections, which keep their own style sheets. Colors come from suite.design tokens
(P is refreshed in place when the theme changes)."""

P = {
    'navy': '#0f2744', 'navy2': '#173b66', 'bg': '#f2f5f9', 'card': '#ffffff', 'border': '#e2e8f0',
    'text': '#0f172a', 'text2': '#334155', 'muted': '#64748b', 'faint': '#94a3b8', 'primary': '#1f5fa8',
    'primary_soft': '#e8f1fc', 'hover': '#f5f8fc', 'track': '#e6ecf3', 'divider': '#eef2f6',
    'primary_border': '#c4daf5', 'btn_hover_border': '#9fb4cc', 'pressed': '#eaf0f7', 'disabled_bg': '#f6f8fb',
    'select': '#e3eefc',
    'inq': '#0e9384', 'inq_soft': '#e3f6f3', 'ten': '#7a5af8', 'ten_soft': '#efebff',
    'red': '#b42318', 'red_soft': '#fdecea', 'amber': '#b45309', 'amber_soft': '#fdf3e2',
    'green': '#15803d', 'green_soft': '#e7f6ec', 'dark': 0,
}


def _asset(name):
    import sys
    from pathlib import Path
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return (base / 'assets' / name).as_posix()


def qss(font: str) -> str:
    p = P
    close, close_h = _asset('tab-close.svg'), _asset('tab-close-hover.svg')
    return f'''
QWidget#SRoot {{ background:{p['bg']}; }}
QFrame#STop {{ background:qlineargradient(x1:1,y1:0,x2:0,y2:0, stop:0 {p['navy']}, stop:1 {p['navy2']}); border:0; }}
QFrame#STop QLabel {{ background:transparent; color:white; font-family:"{font}"; }}
QLabel#SLogo {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2e7bd6, stop:1 #12a594); border-radius:12px;
  color:white; font-size:17pt; font-weight:800; }}
QLabel#STitle {{ font-size:14.5pt; font-weight:700; }}
QLabel#SSub {{ color:#b8c7da; font-size:9pt; }}
QLineEdit#SSearch {{ background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.18); border-radius:10px;
  color:white; padding:8px 14px; font-family:"{font}"; font-size:10pt; selection-background-color:#2e7bd6; }}
QLineEdit#SSearch:focus {{ background:rgba(255,255,255,0.16); border-color:#5b9be6; }}
QLabel#SPill {{ border-radius:13px; padding:5px 12px; font-size:9pt; font-weight:600; }}
QLabel#SPill[state="off"] {{ background:rgba(255,255,255,0.10); color:#c6d3e3; }}
QLabel#SPill[state="on"] {{ background:#d1fadf; color:#05603a; }}
QLabel#SPill[state="busy"] {{ background:#fef0c7; color:#93370d; }}
QLabel#SPill[state="error"] {{ background:#fee4e2; color:#b42318; }}

QPushButton#SToolBtn {{ border:0; border-radius:19px; background:rgba(255,255,255,0.16); min-width:38px; max-width:38px; min-height:38px; max-height:38px; }}
QPushButton#SToolBtn:hover {{ background:rgba(255,255,255,0.26); }}
QPushButton#SToolBtn[rec="true"] {{ background:#d92d20; }}
QPushButton#SConnect {{ border:0; border-radius:19px; padding:8px 18px; font-size:10pt; font-weight:700; color:#ffffff; background:rgba(255,255,255,0.16); }}
QPushButton#SConnect:hover {{ background:rgba(255,255,255,0.26); }}
QPushButton#SConnect[state="on"] {{ background:#d1fadf; color:#05603a; }}
QPushButton#SConnect[state="busy"] {{ background:#fef0c7; color:#93370d; }}
QPushButton#SRole {{ border:0; border-radius:19px; padding:8px 14px; font-size:9.6pt; font-weight:600; color:#ffffff; background:rgba(255,255,255,0.10); }}
QPushButton#SRole:hover {{ background:rgba(255,255,255,0.22); }}
QPushButton#SRole[hint="true"] {{ background:#fef0c7; color:#93370d; }}
QPushButton#SConnect[state="error"] {{ background:#fee4e2; color:#b42318; }}
QFrame#SDocStrip {{ background:{p['card']}; border:0; border-bottom:1px solid {p['border']}; }}
QLabel#SDocLabel {{ color:{p['muted']}; font-size:9pt; }}
QFrame#SDocChip {{ background:{p['bg']}; border:1px solid {p['border']}; border-radius:10px; }}
QFrame#SDocChip[on="true"] {{ background:{p['primary_soft']}; border:1px solid {p['primary']}; }}
QFrame#SDocChip QPushButton {{ border:0; background:transparent; color:{p['text']}; font-size:9.6pt; padding:3px 4px; }}
QFrame#SSide {{ background:{p['card']}; border:0; border-left:1px solid {p['border']}; }}
QLabel#SGroup {{ color:{p['faint']}; font-size:8.5pt; font-weight:600; padding:12px 18px 4px 0; font-family:"{font}"; }}
QFrame#SGroupLine {{ background:{p['divider']}; max-height:1px; min-height:1px; margin:8px 14px; }}
QPushButton#SNav {{ border:0; border-radius:10px; margin:1px 10px; background:transparent; }}
QLabel#SNavText {{ color:{p['text2']}; font-size:10.3pt; font-family:"{font}"; background:transparent; }}
QLabel#SNavText[on="true"] {{ color:{p['primary']}; font-weight:700; }}
QLabel#SNavText[sub="true"] {{ font-size:9.6pt; color:{p['muted']}; }}
QLabel#SNavText[sub="true"][on="true"] {{ color:{p['primary']}; font-weight:700; }}
QLabel#SArrow {{ color:{p['text2']}; background:transparent; font-size:13pt; font-weight:700; padding:0 6px; }}
QPushButton#SNav:hover {{ background:{p['hover']}; }}
QPushButton#SNav:checked {{ background:{p['primary_soft']}; }}
QPushButton#SNav[sub="true"]:checked {{ background:transparent; }}
QFrame#SSubRail {{ border:0; border-right:2px solid {p['divider']}; margin-right:26px; background:transparent; }}
QLabel#SBadge {{ background:{p['red_soft']}; color:{p['red']}; border-radius:10px; padding:0 8px; min-width:12px; font-size:8.5pt; font-weight:700; font-family:"{font}"; }}
QLabel#SBadge[tone="muted"] {{ background:{p['track']}; color:{p['muted']}; }}
QLabel#SBadge[tone="blue"] {{ background:{p['primary']}; color:white; }}
QLabel#SBadge[tone="green"] {{ background:{p['green_soft']}; color:{p['green']}; }}
QLabel#SFoot {{ color:{p['muted']}; font-size:8.5pt; padding:4px 16px; font-family:"{font}"; }}
QFrame#SThemeSeg {{ background:{p['track']}; border-radius:12px; margin:6px 12px; }}
QPushButton#SThemeBtn {{ border:0; border-radius:9px; padding:6px 10px; min-height:22px; color:{p['muted']};
  background:transparent; font-family:"{font}"; font-size:9.5pt; }}
QPushButton#SThemeBtn:checked {{ background:{p['card']}; color:{p['text']}; font-weight:700; }}
QPushButton#SCollapse {{ border:0; border-radius:9px; background:transparent; min-height:30px; max-height:30px; margin:2px 12px; }}
QPushButton#SCollapse:hover {{ background:{p['hover']}; }}

QWidget#SPage {{ background:{p['bg']}; }}
QWidget#SPage QLabel {{ font-family:"{font}"; color:{p['text']}; background:transparent; }}
QLabel#SH1 {{ font-size:17pt; font-weight:800; }}
QLabel#SH2 {{ font-size:11.5pt; font-weight:700; }}
QLabel#SMuted {{ color:{p['muted']}; font-size:9.3pt; }}
QWidget#SPage QLabel#SMuted {{ color:{p['muted']}; }}
QLabel#SFaint {{ color:{p['faint']}; font-size:9pt; }}
QWidget#SPage QLabel#SFaint {{ color:{p['faint']}; }}
QFrame#SCard {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:14px; }}
QFrame#SKpi {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:14px; }}
QFrame#SKpi[tone="red"] {{ border-color:{p['red']}; }}
QLabel#SKpiValue {{ font-size:21pt; font-weight:800; }}
QLabel#SKpiTitle {{ color:{p['text2']}; font-size:9.5pt; font-weight:600; }}
QWidget#SPage QLabel#SKpiTitle {{ color:{p['text2']}; }}
QLabel#SKpiIcon {{ border-radius:12px; }}
QFrame#SCol {{ background:{p['track']}; border-radius:14px; border:2px solid transparent; }}
QFrame#SCol[drop="true"] {{ border:2px dashed {p['primary']}; background:{p['primary_soft']}; }}
QFrame#SItem {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:12px; }}
QFrame#SItem:hover {{ border-color:{p['btn_hover_border']}; }}
QFrame#SItem[sel="true"] {{ border:2px solid {p['primary']}; }}
QFrame#SItem[gone="true"] {{ background:{p['disabled_bg']}; }}
QLabel#SItemTitle {{ font-size:10pt; font-weight:700; }}
QLabel#SNum {{ color:{p['muted']}; font-size:9pt; }}
QWidget#SPage QLabel#SNum {{ color:{p['muted']}; }}
QLabel#SCount {{ background:{p['card']}; border-radius:9px; padding:1px 8px; }}
QLabel#STag {{ border-radius:8px; padding:2px 8px; font-size:8.6pt; font-weight:700; }}
QPushButton#SChip {{ border:1px solid {p['border']}; background:{p['card']}; border-radius:15px; padding:4px 14px;
  min-height:22px; max-height:22px; color:{p['text2']}; font-family:"{font}"; font-size:9.5pt; }}
QPushButton#SChip:hover {{ border-color:{p['btn_hover_border']}; }}
QPushButton#SChip:checked {{ background:{p['primary_soft']}; color:{p['primary']}; border-color:{p['primary']}; font-weight:700; }}
QPushButton#SAction {{ border:1px solid {p['border']}; background:{p['card']}; border-radius:11px; padding:7px 14px;
  min-height:22px; max-height:22px; color:{p['text']}; font-family:"{font}"; font-size:10pt; text-align:right; }}
QPushButton#SAction:hover {{ border-color:{p['btn_hover_border']}; background:{p['hover']}; }}
QFrame#SHover {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:10px; }}
QToolButton#SIconBtn {{ border:0; border-radius:8px; background:transparent; padding:4px; }}
QToolButton#SIconBtn:hover {{ background:{p['hover']}; }}
QToolButton#SIconBtn[tone="primary"] {{ background:{p['primary_soft']}; }}
QFrame#SSelBar, QFrame#SToast {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:14px; }}
QFrame#SToast {{ background:#1d2939; border:0; }}
QFrame#SToast QLabel {{ color:white; font-family:"{font}"; background:transparent; }}
QPushButton#SToastBtn {{ border:0; background:transparent; color:#84adff; font-weight:700; font-family:"{font}"; padding:4px 8px; }}
QPushButton#SSelBtn {{ border:1px solid {p['border']}; background:{p['card']}; border-radius:10px; padding:7px 14px;
  min-height:22px; max-height:22px; color:{p['text']}; font-family:"{font}"; }}
QPushButton#SSelBtn:hover {{ background:{p['hover']}; }}
QPushButton#SSelBtn[tone="danger"] {{ color:{p['red']}; border-color:{p['red_soft']}; }}
QFrame#SDrop {{ border:2px dashed {p['border']}; border-radius:12px; background:transparent; }}
QFrame#SDrop[drop="true"] {{ border-color:{p['red']}; background:{p['red_soft']}; }}
QFrame#SRow {{ background:transparent; border:0; border-bottom:1px solid {p['divider']}; }}
QFrame#SRow:hover {{ background:{p['hover']}; }}
QScrollArea#SScroll {{ background:transparent; border:0; }}
QScrollArea#SScroll > QWidget > QWidget {{ background:transparent; }}
QScrollArea#SScroll QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; border:0; }}
QScrollArea#SScroll QScrollBar::handle:vertical {{ background:{p['track']}; border-radius:3px; min-height:30px; }}
QScrollArea#SScroll QScrollBar::handle:vertical:hover {{ background:{p['btn_hover_border']}; }}
QScrollArea#SScroll QScrollBar::add-line, QScrollArea#SScroll QScrollBar::sub-line {{ height:0; width:0; border:0; background:none; }}
QScrollArea#SScroll QScrollBar::add-page, QScrollArea#SScroll QScrollBar::sub-page {{ background:none; }}
QFrame#SPopup {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:12px; }}
QListWidget#SResults {{ border:0; background:{p['card']}; font-family:"{font}"; font-size:10pt; outline:0; }}
QListWidget#SResults::item {{ padding:8px 12px; border-bottom:1px solid {p['divider']}; color:{p['text']}; }}
QListWidget#SResults::item:selected {{ background:{p['primary_soft']}; color:{p['primary']}; }}
QFrame#SBar {{ background:{p['track']}; border-radius:4px; }}
QTabWidget#SDocTabs::pane {{ border:0; }}
QTabWidget#SDocTabs > QTabBar::tab {{ background:transparent; color:{p['muted']}; padding:8px 16px; margin-left:2px;
  border:0; border-bottom:3px solid transparent; font-family:"{font}"; }}
QTabWidget#SDocTabs > QTabBar::tab:selected {{ color:{p['primary']}; border-bottom:3px solid {p['primary']}; font-weight:700; }}
QTabWidget#SDocTabs > QTabBar::close-button {{ image:url("{close}"); subcontrol-position:left; width:14px; height:14px; margin:2px; }}
QTabWidget#SDocTabs > QTabBar::close-button:hover {{ image:url("{close_h}"); }}
QMenu {{ font-family:"{font}"; }}
'''
