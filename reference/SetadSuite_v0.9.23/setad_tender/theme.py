"""Colors and Qt stylesheet (light + dark). Theme is applied at start-up: C is updated in place before any widget is built."""

LIGHT = dict(
    navy='#0f2744', navy2='#173b66', primary='#1f5fa8', primary_hover='#1a5291', primary_soft='#e8f1fc',
    teal='#0f8f80', teal_soft='#e3f5f2', amber='#b45309', amber_soft='#fdf3e2', red='#b42318', red_soft='#fdecea',
    green='#15803d', green_soft='#e7f6ec', bg='#f2f5f9', card='#ffffff', border='#e2e8f0', border2='#cfd8e3',
    text='#0f172a', text2='#334155', muted='#64748b', faint='#94a3b8', row_alt='#f8fafc', select='#e3eefc',
    hover='#f5f8fc', pressed='#eaf0f7', disabled_bg='#f6f8fb', ghost_hover='#e9eef5', hover_card='#fbfdff',
    input='#ffffff', head_bg='#f8fafc', scroll='#cbd5e1', scroll_hover='#94a3b8', track='#e6ecf3', divider='#eef2f6',
    primary_border='#c4daf5', green_border='#bfe3cf', amber_border='#f1d6a8', red_border='#f3c3bd', step_hover='#9fbfe6',
    btn_hover_border='#9fb4cc', danger_border='#f0c9c4', amber_btn_border='#f1d6a8', violet='#7c3aed', violet_soft='#f1ebfd',
    info_label_bg='#f4f7fb', dark=0,
)
DARK = dict(
    navy='#0a121c', navy2='#12304f', primary='#5aa0f0', primary_hover='#74b0f6', primary_soft='#1a2e48',
    teal='#2cc4b0', teal_soft='#12312e', amber='#e8a851', amber_soft='#3a2d14', red='#f2776d', red_soft='#3d1c1a',
    green='#4ccf80', green_soft='#13331e', bg='#0e1621', card='#172230', border='#263548', border2='#34465c',
    text='#e8eef6', text2='#c5d0de', muted='#93a4b8', faint='#6f8197', row_alt='#1a2635', select='#22406a',
    hover='#1e2c3d', pressed='#25364a', disabled_bg='#131d2a', ghost_hover='#213044', hover_card='#1c2a3b',
    input='#111b27', head_bg='#1a2635', scroll='#38495f', scroll_hover='#51667f', track='#223044', divider='#213043',
    primary_border='#2b4a73', green_border='#235a37', amber_border='#6b4f1d', red_border='#703632', step_hover='#3a6aa5',
    btn_hover_border='#4a6283', danger_border='#703632', amber_btn_border='#6b4f1d', violet='#a78bfa', violet_soft='#2a2145',
    info_label_bg='#1b2838', dark=1,
)
C = dict(LIGHT)


def apply_theme(name: str):
    """'dark' or 'light'. Call before building any widget."""
    C.clear();C.update(DARK if name == 'dark' else LIGHT)


def make_qss() -> str:
    return _qss()


def _assets() -> str:
    try:
        from inquiries.ui_kit import resource_dir
        return (resource_dir() / 'assets').as_posix()
    except Exception:
        return ''


def _qss() -> str:
    ASSETS = _assets()
    return f'''
* {{ font-family: "Vazirmatn"; }}
QWidget {{ color:{C['text']}; font-size:10pt; }}
QMainWindow, QWidget#Root, QDialog {{ background:{C['bg']}; }}
QToolTip {{ background:{C['navy']}; color:#fff; border:0; padding:6px 9px; border-radius:6px; }}

/* Header */
QFrame#Header {{ background:qlineargradient(x1:1,y1:0,x2:0,y2:0, stop:0 {C['navy']}, stop:1 {C['navy2']}); border:0; }}
QFrame#Header QLabel {{ background:transparent; color:white; }}
QLabel#AppTitle {{ font-size:16pt; font-weight:700; }}
QLabel#AppSubtitle {{ color:#b8c7da; font-size:9pt; }}
QLabel#Logo {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2e7bd6, stop:1 #12a594);
  border-radius:12px; color:white; font-size:17pt; font-weight:800; }}
QLabel#Version {{ color:#93a8c3; font-size:8.5pt; border:1px solid #2f507a; border-radius:9px; padding:3px 9px; }}
QLabel#Pill {{ border-radius:14px; padding:6px 14px; font-weight:600; font-size:9.5pt; }}
QLabel#Pill[state="off"] {{ background:#24466f; color:#c6d3e3; }}
QLabel#Pill[state="wait"] {{ background:#5a4214; color:#ffd88a; }}
QLabel#Pill[state="on"] {{ background:#0e4d3d; color:#8ff0cf; }}
QLabel#Pill[state="err"] {{ background:#5c1d1d; color:#ffb4ab; }}

/* Cards */
QFrame#Card {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:12px; }}
QFrame#Card QLabel, QFrame#Card QCheckBox {{ background:transparent; }}
QLabel#CardTitle {{ font-size:11pt; font-weight:700; color:{C['text']}; }}
QLabel#Muted {{ color:{C['muted']}; font-size:9pt; }}
QLabel#Faint {{ color:{C['faint']}; font-size:9pt; }}

/* Steps */
QPushButton#Step {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:12px; padding:8px 14px 8px 18px;
  text-align:right; font-weight:600; color:{C['text2']}; min-height:42px; }}
QPushButton#Step:hover {{ border-color:{C['step_hover']}; background:{C['hover_card']}; }}
QPushButton#Step[state="current"] {{ border:1.5px solid {C['primary']}; background:{C['primary_soft']}; color:{C['primary']}; }}
QPushButton#Step[state="done"] {{ border-color:{C['green_border']}; background:{C['green_soft']}; color:{C['green']}; }}
QPushButton#Step:disabled {{ color:{C['faint']}; background:{C['disabled_bg']}; }}

/* Stats */
QFrame#Stat {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:12px; }}
QFrame#Stat[clickable="true"]:hover {{ border-color:{C['step_hover']}; background:{C['hover_card']}; }}
QFrame#Stat QLabel {{ background:transparent; }}
QLabel#StatValue {{ font-size:16pt; font-weight:700; color:{C['text']}; }}
QLabel#StatLabel {{ color:{C['muted']}; font-size:9pt; font-weight:600; }}
QLabel#StatSub {{ color:{C['faint']}; font-size:8pt; }}
QLabel#StatIcon {{ border-radius:10px; }}

/* Buttons */
QPushButton {{ background:{C['card']}; border:1px solid {C['border2']}; border-radius:8px; padding:7px 14px;
  font-weight:600; color:{C['text2']}; min-height:22px; }}
QPushButton:hover {{ background:{C['hover']}; border-color:{C['btn_hover_border']}; }}
QPushButton:pressed {{ background:{C['pressed']}; }}
QPushButton:disabled {{ color:{C['faint']}; background:{C['disabled_bg']}; border-color:{C['border']}; }}
QPushButton[kind="primary"] {{ background:{C['primary']}; border:1px solid {C['primary']}; color:#fff; }}
QPushButton[kind="primary"]:hover {{ background:{C['primary_hover']}; }}
QPushButton[kind="primary"]:disabled {{ background:{C['scroll']}; border-color:{C['scroll']}; color:{C['card']}; }}
QPushButton[state="busy"] {{ background:{C['primary_soft']}; color:{C['primary']}; border:1px solid {C['primary_border']}; }}
QPushButton[state="ok"] {{ background:{C['green_soft']}; color:{C['green']}; border:1px solid {C['green_border']}; }}
QPushButton[state="err"] {{ background:{C['red_soft']}; color:{C['red']}; border:1px solid {C['red_border']}; }}
QPushButton[kind="ghost"] {{ background:transparent; border:1px solid transparent; color:{C['text2']}; }}
QPushButton[kind="ghost"]:hover {{ background:{C['ghost_hover']}; border-color:transparent; }}
QPushButton[kind="danger"] {{ color:{C['red']}; border-color:{C['danger_border']}; background:{C['card']}; }}
QPushButton[kind="danger"]:hover {{ background:{C['red_soft']}; }}
QPushButton[kind="amber"] {{ color:{C['amber']}; border-color:{C['amber_btn_border']}; background:{C['card']}; }}
QPushButton[kind="amber"]:hover {{ background:{C['amber_soft']}; }}
QPushButton[kind="link"] {{ background:transparent; border:0; color:{C['primary']}; padding:2px 4px; }}
QPushButton[kind="link"]:hover {{ text-decoration:underline; }}
QPushButton::menu-indicator {{ image:none; width:0; }}

/* Inputs */
QLineEdit, QComboBox {{ background:{C['input']}; border:1px solid {C['border2']}; border-radius:8px; padding:6px 10px; min-height:22px;
  selection-background-color:#bcd5f2; }}
QLineEdit:focus, QComboBox:focus {{ border:1.5px solid {C['primary']}; }}
QComboBox::drop-down {{ border:0; width:26px; }}
QComboBox::down-arrow {{ image: url("{ASSETS}/chevron-combo.svg"); width:14px; height:14px; }}
QComboBox QAbstractItemView {{ background:{C['card']}; border:1px solid {C['border2']}; selection-background-color:{C['select']};
  selection-color:{C['text']}; outline:0; padding:4px; }}
QCheckBox {{ spacing:7px; color:{C['text2']}; }}
QPlainTextEdit {{ background:{C['input']}; border:1px solid {C['border']}; border-radius:8px; padding:8px; }}

/* Table */
QTableView, QTableWidget {{ background:{C['card']}; alternate-background-color:{C['row_alt']}; border:0; border-top:1px solid {C['border']};
  gridline-color:transparent; selection-background-color:{C['select']}; selection-color:{C['text']}; outline:0; }}
QTableView::item, QTableWidget::item {{ padding:0 8px; border-bottom:1px solid {C['divider']}; }}
QTableView::item:selected, QTableWidget::item:selected {{ background:{C['select']}; color:{C['text']}; }}
QHeaderView {{ background:{C['card']}; }}
QHeaderView::section {{ background:{C['head_bg']}; color:{C['muted']}; font-weight:700; font-size:9pt; padding:9px 8px;
  border:0; border-bottom:1px solid {C['border']}; border-left:1px solid {C['divider']}; }}
QTableCornerButton::section {{ background:{C['head_bg']}; border:0; }}

QTreeWidget {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:10px; outline:0; padding:4px; }}
QTreeWidget::item {{ min-height:30px; }}
QTreeWidget::item:selected {{ background:{C['select']}; color:{C['text']}; }}

/* Tabs */
QTabWidget::pane {{ border:0; background:transparent; top:-1px; }}
QTabBar::tab {{ background:transparent; color:{C['muted']}; padding:9px 16px; margin-left:4px; font-weight:600;
  border:0; border-bottom:2px solid transparent; }}
QTabBar::tab:selected {{ color:{C['primary']}; border-bottom:2px solid {C['primary']}; }}
QTabBar::tab:hover {{ color:{C['text']}; }}

/* Scroll */
QScrollArea {{ border:0; background:transparent; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:11px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{C['scroll']}; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{C['scroll_hover']}; }}
QScrollBar:horizontal {{ background:transparent; height:11px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{C['scroll']}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

/* Banner / notes */
QFrame#Banner {{ border-radius:10px; border:1px solid; }}
QFrame#Banner QLabel {{ background:transparent; }}
QFrame#Banner[kind="info"] {{ background:{C['primary_soft']}; border-color:{C['primary_border']}; }}
QFrame#Banner[kind="success"] {{ background:{C['green_soft']}; border-color:{C['green_border']}; }}
QFrame#Banner[kind="warn"] {{ background:{C['amber_soft']}; border-color:{C['amber_border']}; }}
QFrame#Banner[kind="error"] {{ background:{C['red_soft']}; border-color:{C['red_border']}; }}

/* Section inside detail */
QFrame#Section {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:10px; }}
QFrame#Section QLabel {{ background:transparent; }}
QLabel#SectionTitle {{ font-weight:700; color:{C['text2']}; font-size:9.5pt; }}
QLabel#FieldLabel {{ color:{C['muted']}; font-size:9pt; }}
QLabel#FieldValue {{ color:{C['text']}; font-weight:600; }}
QFrame#StepRow {{ background:transparent; border:1px solid transparent; border-radius:12px; }}
QFrame#StepRow[state="current"] {{ background:{C['primary_soft']}; border:1.5px solid {C['primary']}; }}
QLabel#StepNum {{ border-radius:14px; background:{C['track']}; color:{C['muted']}; font-weight:700; }}
QLabel#StepNum[state="current"] {{ background:{C['primary']}; color:#fff; }}
QLabel#StepNum[state="done"] {{ background:{C['green_soft']}; color:{C['green']}; }}
QLabel#StepTitle {{ font-weight:700; color:{C['faint']}; background:transparent; }}
QLabel#StepTitle[state="current"], QLabel#StepTitle[state="done"] {{ color:{C['text']}; }}
QLabel#StepSub {{ color:{C['muted']}; font-size:9pt; background:transparent; }}
QLabel#StepBanner {{ background:{C['track']}; color:{C['text2']}; border-radius:10px; padding:10px 14px; font-weight:600; }}
QLabel#StatusPill {{ border-radius:8px; padding:3px 10px; font-weight:600; background:{C['track']}; color:{C['muted']}; }}
QLabel#StatusPill[tone="pay"] {{ background:{C['amber_soft']}; color:{C['amber']}; }}
QLabel#StatusPill[tone="prepare"] {{ background:{C['primary_soft']}; color:{C['primary']}; }}
QLabel#StatusPill[tone="site"] {{ background:{C['teal_soft']}; color:{C['teal']}; }}
QLabel#StatusPill[tone="edition"] {{ background:{C['violet_soft']}; color:{C['violet']}; }}
QLabel#PageTitle {{ font-size:15pt; font-weight:800; color:{C['text']}; background:transparent; }}
QToolButton#StarBtn {{ border:1px solid {C['border']}; border-radius:9px; background:{C['card']}; }}
QToolButton#StarBtn:hover {{ background:{C['hover']}; }}
QFrame#Card QLabel#Chip, QLabel#Chip {{ background:{C['primary_soft']}; color:{C['primary']}; border-radius:8px; padding:3px 10px; font-weight:700; }}
QFrame#Card QLabel#ChipGreen, QLabel#ChipGreen {{ background:{C['green_soft']}; color:{C['green']}; border-radius:8px; padding:3px 10px; font-weight:600; }}
QFrame#Card QLabel#ChipAmber, QLabel#ChipAmber {{ background:{C['amber_soft']}; color:{C['amber']}; border-radius:8px; padding:3px 10px; font-weight:600; }}
QLabel#DetailTitle {{ font-size:12.5pt; font-weight:700; color:{C['text']}; }}

QProgressBar {{ background:{C['track']}; border:0; border-radius:3px; max-height:6px; min-height:6px; }}
QProgressBar::chunk {{ background:{C['primary']}; border-radius:3px; }}
QStatusBar {{ background:{C['card']}; border-top:1px solid {C['border']}; color:{C['muted']}; }}
QStatusBar QLabel {{ color:{C['text2']}; }}
QStatusBar::item {{ border:none; }}
QLineEdit#DirEdit {{ background:{C['hover']}; color:{C['text2']}; }}
QPushButton#PrimGhost {{ background:transparent; border:1px solid transparent; color:{C["primary"]}; padding:7px 10px; font-weight:600; }}
QPushButton#PrimGhost:hover {{ background:{C['primary_soft']}; }}
QSplitter::handle {{ background:transparent; }}
QMenu {{ background:{C['card']}; border:1px solid {C['border2']}; border-radius:8px; padding:5px; }}
QMenu::item {{ padding:7px 18px; border-radius:6px; }}
QMenu::item:selected {{ background:{C['select']}; color:{C['text']}; }}
QMessageBox QLabel {{ min-width:340px; }}

/* v0.3 additions */
QPushButton[kind="chip"] {{ background:{C['card']}; border:1px solid {C['border2']}; border-radius:15px; padding:4px 13px; font-weight:600; color:{C['text2']}; }}
QPushButton[kind="chip"]:hover {{ border-color:{C['btn_hover_border']}; background:{C['hover']}; }}
QPushButton[kind="chip"]:checked {{ background:{C['primary_soft']}; border:1px solid {C['primary']}; color:{C['primary']}; }}
QPushButton#Connect {{ background:{C['primary']}; border:0; border-radius:12px; padding:6px 22px; color:#fff; font-weight:700; font-size:10.5pt; min-height:26px; max-height:26px; }}
QPushButton#Connect:hover {{ background:{C['primary_hover']}; }}
QPushButton#Connect[state="on"] {{ background:{C['green']}; }}
QPushButton#Connect[state="wait"] {{ background:{C['amber']}; }}
QPushButton#Connect:disabled {{ background:{C['scroll']}; color:{C['card']}; }}
QFrame#BatchBar {{ background:{C['navy']}; border-radius:10px; }}
QFrame#BatchBar QLabel {{ background:transparent; color:#fff; font-weight:600; }}
QFrame#BatchBar QPushButton {{ background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.22); color:#fff; padding:5px 12px; }}
QFrame#BatchBar QPushButton:hover {{ background:rgba(255,255,255,0.22); }}
QFrame#InfoTable {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:8px; }}
QLabel#InfoLabel {{ background:{C['info_label_bg']}; color:{C['muted']}; font-size:9pt; border-bottom:1px solid {C['divider']}; border-left:1px solid {C['divider']}; }}
QLabel#InfoValue {{ background:{C['card']}; color:{C['text']}; font-weight:600; border-bottom:1px solid {C['divider']}; border-left:1px solid {C['divider']}; }}
QLabel#InfoHead {{ background:transparent; color:{C['primary']}; font-weight:700; font-size:10pt; padding:2px 0; }}
QPushButton[kind="stage"] {{ background:{C['card']}; border:1px solid {C['border2']}; border-radius:10px; padding:6px 12px; color:{C['muted']}; font-weight:600; }}
QPushButton[kind="stage"][state="done"] {{ background:{C['green_soft']}; border-color:{C['green_border']}; color:{C['green']}; }}
QPushButton[kind="stage"][state="current"] {{ background:{C['primary']}; border-color:{C['primary']}; color:#fff; }}
QPushButton[kind="stage"][state="hint"] {{ border:1.5px dashed {C['primary']}; color:{C['primary']}; }}
QLabel#Badge {{ border-radius:9px; padding:2px 9px; font-weight:700; font-size:8.5pt; }}
QTabBar::tab:!selected:hover {{ background:{C['hover']}; border-radius:6px; }}
QSpinBox, QDoubleSpinBox, QDateEdit {{ background:{C['input']}; border:1px solid {C['border2']}; border-radius:8px; padding:5px 8px; min-height:22px; }}
QListWidget {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:8px; outline:0; }}
QListWidget::item {{ padding:8px; border-bottom:1px solid {C['divider']}; }}
QListWidget::item:selected {{ background:{C['select']}; color:{C['text']}; }}
'''


QSS = _qss()
