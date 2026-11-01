"""Main window: top bar + sidebar + pages (dashboard, my work, inquiries app, tenders app)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QUrl, QEvent, QPoint, QSettings, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)
from setad_tender.compact_box import CompactBox

from setad_tender.icons import icon

from . import __version__, APP_TITLE, COMPANY
from . import data as D
from . import design
from .pages import DashboardPage, MyWorkPage
from .style import P, qss

PAGE_DASH, PAGE_WORK, PAGE_INQ, PAGE_TEN, PAGE_DOCS = range(5)

# sidebar keys that belong to each section page
INQ_KEYS = ('inq', 'inq_open', 'inq_star', 'inq_all', 'inq_arch', 'inq_board', 'inq_sup')
TEN_KEYS = ('ten', 'ten_act', 'ten_star', 'ten_mine', 'ten_all')
INQ_TAB = {'inq': 0, 'inq_open': 0, 'inq_star': 0, 'inq_all': 0, 'inq_board': 1, 'inq_sup': 2, 'inq_arch': 3}


class NavButton(QPushButton):
    """Sidebar entry: icon + text on the right, badge on the left (built from labels so RTL is exact).
    sub=True → an indented sub-item; expandable=True → shows a chevron for its sub-menu."""

    arrow_clicked = Signal()

    def __init__(self, text, icon_name, sub=False, expandable=False):
        super().__init__()
        self._arrow_press = False
        self.setObjectName('SNav')
        self.setProperty('sub', bool(sub))
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34 if sub else 40)
        self.icon_name = icon_name
        self.text_value = text
        self.sub = sub
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)
        self.ic = QLabel()
        self.ic.setFixedSize(20, 20)
        self.ic.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.tx = QLabel(text)
        self.tx.setObjectName('SNavText')
        self.tx.setProperty('sub', bool(sub))
        self.tx.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.arrow = QLabel('')
        self.arrow.setObjectName('SArrow')
        self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.arrow.setVisible(expandable)
        self.badge = QLabel()
        self.badge.setObjectName('SBadge')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(20)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.hide()
        if not sub:
            lay.addWidget(self.ic)
        else:
            self.ic.hide()
        lay.addWidget(self.tx)
        lay.addStretch()
        lay.addWidget(self.badge)
        lay.addWidget(self.arrow)
        self._badge_n = 0
        self.collapsed = False
        self.toggled.connect(self._paint)
        self._paint(False)

    def mousePressEvent(self, e):
        self._arrow_press = False
        if self.arrow.isVisible() and e.button() == Qt.LeftButton:
            r = self.arrow.geometry().adjusted(-14, -10, 14, 10)
            if r.contains(e.position().toPoint()):
                self._arrow_press = True
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._arrow_press:
            self._arrow_press = False
            if self.arrow.geometry().adjusted(-14, -10, 14, 10).contains(e.position().toPoint()):
                self.arrow_clicked.emit()
            return
        super().mouseReleaseEvent(e)

    def set_open(self, on):
        self.arrow.setText('▾' if on else '‹')

    def _paint(self, on):
        if not self.sub:
            self.ic.setPixmap(icon(self.icon_name, P['primary'] if on else P['text2'], 19).pixmap(19, 19))
        self.tx.setProperty('on', bool(on))
        self.tx.style().unpolish(self.tx)
        self.tx.style().polish(self.tx)

    def set_collapsed(self, on):
        self.collapsed = on
        self.tx.setVisible(not on)
        self.arrow.setVisible(not on and self.arrow.text() != '')
        self.badge.setVisible(bool(self._badge_n) and not on)
        self.setToolTip(self.text_value if on else '')
        self.layout().setContentsMargins(22 if on else 12, 0, 12, 0)

    def set_badge(self, n, tone=None):
        self._badge_n = n or 0
        if not n:
            self.badge.hide()
            return
        self.badge.setText(D.fa(n))
        self.badge.setProperty('tone', tone or '')
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.badge.setVisible(not self.collapsed)


class Shell(QMainWindow):
    def __init__(self, inquiries_factory=None, tenders_factory=None):
        super().__init__()
        self.setWindowTitle(f'{APP_TITLE} — نسخه {__version__}')
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1600, 960)
        self.setMinimumSize(1240, 760)
        self._closing = False
        self._font = QApplication.instance().font().family()
        self.settings = QSettings('Blue Alvand Industry', 'Setad Suite')

        root = QWidget()
        root.setObjectName('SRoot')
        root.setStyleSheet(qss(self._font))
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._top())
        outer.addWidget(self._doc_strip())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._side())
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        # pages
        self.dash = DashboardPage()
        self.work = MyWorkPage()
        self.stack.addWidget(self.dash)
        self.stack.addWidget(self.work)
        self.ten = self._make(tenders_factory, 'مناقصه‌ها')
        self.inq = self._make((lambda: inquiries_factory(self.ten)) if inquiries_factory else None, 'استعلام‌ها')
        self.stack.addWidget(self.inq)
        self.stack.addWidget(self.ten)
        self.docs = QTabWidget()
        self.docs.setObjectName('SDocTabs')
        self.docs.setTabsClosable(True)
        self.docs.setDocumentMode(True)
        self.docs.tabBar().hide()            # the strip under the header is the tab bar
        self.docs.tabCloseRequested.connect(self._close_doc)
        self.docs.currentChanged.connect(lambda *_: (self._sync_nav(), self._rebuild_strip()))
        self.stack.addWidget(self.docs)
        self._docs = {}                      # (kind, id) -> widget
        # shared menus live only in the shell: the embedded sections hide their own tab bars
        tabs = getattr(self.inq, 'tabs', None)
        if tabs is not None:
            tabs.tabBar().hide()
            tabs.currentChanged.connect(lambda *_: self._sync_nav())
        for sec in (self.inq, self.ten):
            try:
                sec.window_host = self.host_doc
            except Exception:
                pass
        self._role = None
        tw = getattr(self.ten, 'worker', None)
        if tw is not None:
            tw.result.connect(self._worker_result)
            tw.failed.connect(self._worker_failed)
        self._wire_pages()

        self._popup()
        self.go('dash')
        self.set_collapsed(self.settings.value('side_collapsed', False, type=bool))
        self.timer = QTimer(self, interval=1500)
        self.timer.timeout.connect(self._mirror_status)
        self.timer.start()
        self.data_timer = QTimer(self, interval=60_000)
        self.data_timer.timeout.connect(self.refresh_data)
        self.data_timer.start()
        QTimer.singleShot(300, self.refresh_data)
        QShortcut(QKeySequence('Ctrl+Shift+F'), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))

    def _wire_pages(self):
        self.dash.open_item.connect(self.open_item)
        self.work.open_item.connect(self.open_item)
        self.dash.action.connect(self.quick_action)
        self.work.request.connect(self.work_request)
        self.dash.goto.connect(self.go)
        self.dash.ack.connect(self.dash_ack)

    # ------------------------------------------------------------------ building
    def _make(self, factory, name):
        if factory is None:
            w = QLabel(f'بخش {name} بارگذاری نشد.')
            w.setAlignment(Qt.AlignCenter)
            return w
        try:
            return factory()
        except Exception as e:  # keep the other section usable
            w = QLabel(f'بخش {name} بارگذاری نشد:\n{e}')
            w.setAlignment(Qt.AlignCenter)
            w.setWordWrap(True)
            return w

    def _top(self):
        top = QFrame()
        top.setObjectName('STop')
        top.setFixedHeight(70)
        lay = QHBoxLayout(top)
        lay.setContentsMargins(22, 10, 22, 10)
        lay.setSpacing(14)
        logo = QLabel('س')
        logo.setObjectName('SLogo')
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(APP_TITLE)
        t.setObjectName('STitle')
        s = QLabel(COMPANY)
        s.setObjectName('SSub')
        col.addWidget(t)
        col.addWidget(s)
        lay.addLayout(col)
        lay.addSpacing(30)
        self.search = QLineEdit()
        self.search.setObjectName('SSearch')
        self.search.setPlaceholderText('جست‌وجو در استعلام‌ها و مناقصه‌ها (شماره، عنوان، دستگاه)…   Ctrl+Shift+F')
        self.search.setMaximumWidth(560)
        self.search.setMinimumWidth(340)
        self.search.addAction(icon('search', '#c6d3e3', 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._search_enter)
        self.search.installEventFilter(self)
        lay.addWidget(self.search, 1)
        lay.addStretch()
        self.pill_ten = QLabel()      # kept only as a hidden object for older code paths
        self.pill_ten.hide()
        self.b_connect = QPushButton('  اتصال به ستاد')
        self.b_connect.setObjectName('SConnect')
        self.b_connect.setCursor(Qt.PointingHandCursor)
        self.b_connect.setIcon(icon('plug-zap', '#ffffff', 18))
        self.b_connect.setProperty('state', 'off')
        self.b_connect.setToolTip('یک مرورگر مشترک برای هر دو بخش؛ ورود را خودتان انجام می‌دهید')
        self.b_connect.clicked.connect(self._connect_clicked)
        lay.addWidget(self.b_connect)
        self.pill_inq = self.b_connect
        self.b_role = QPushButton('نقش: —')
        self.b_role.setObjectName('SRole')
        self.b_role.setCursor(Qt.PointingHandCursor)
        self.b_role.setProperty('hint', False)
        self.b_role.setToolTip('نقش فعال ستاد در مرورگر مشترک — برای تعویض کلیک کنید (تعیین نقش: مناقصه‌گر / تامین‌کننده)')
        self.b_role.clicked.connect(self._role_clicked)
        lay.addWidget(self.b_role)
        self._switching = None
        self.b_tools = QPushButton()
        self.b_tools.setObjectName('SToolBtn')
        self.b_tools.setCursor(Qt.PointingHandCursor)
        self.b_tools.setIcon(icon('wrench', '#ffffff', 18))
        self.b_tools.setToolTip('ابزارهای اتصال: ضبط روند سایت، گزارش عیب‌یابی')
        self.b_tools.setProperty('rec', False)
        self.b_tools.clicked.connect(self._tools_menu)
        lay.addWidget(self.b_tools)
        return top

    # ---- open-case tab strip (v0.9): replaces the «پرونده‌های باز» menu item
    def _doc_strip(self):
        self.doc_strip = QFrame()
        self.doc_strip.setObjectName('SDocStrip')
        self.doc_strip_lay = QHBoxLayout(self.doc_strip)
        self.doc_strip_lay.setContentsMargins(18, 5, 18, 5)
        self.doc_strip_lay.setSpacing(6)
        self.doc_strip.hide()
        return self.doc_strip

    def _rebuild_strip(self):
        lay = self.doc_strip_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self._docs:
            self.doc_strip.hide()
            return
        cur = self.docs.currentWidget() if self.stack.currentIndex() == PAGE_DOCS else None
        lab = QLabel('پرونده‌های باز:')
        lab.setObjectName('SDocLabel')
        lay.addWidget(lab)
        for key, w in list(self._docs.items()):
            i = self.docs.indexOf(w)
            box = QFrame()
            box.setObjectName('SDocChip')
            box.setProperty('on', w is cur)
            h = QHBoxLayout(box)
            h.setContentsMargins(10, 2, 4, 2)
            h.setSpacing(4)
            b = QPushButton(self.docs.tabText(i))
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(self.docs.tabIcon(i))
            b.clicked.connect(lambda _=False, w=w: self._show_doc(w))
            x = QPushButton('✕')
            x.setFlat(True)
            x.setFixedWidth(22)
            x.setToolTip('بستن تب (چیزی حذف نمی‌شود)')
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(lambda _=False, w=w: self._close_doc(self.docs.indexOf(w)))
            h.addWidget(b)
            h.addWidget(x)
            lay.addWidget(box)
        lay.addStretch()
        self.doc_strip.show()

    def _show_doc(self, w):
        self.stack.setCurrentIndex(PAGE_DOCS)
        self.docs.setCurrentWidget(w)
        self._sync_nav('docs')
        self._rebuild_strip()

    def _tools_menu(self):
        ten = self.ten
        rec = bool(getattr(ten, 'recording', False))
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        a_rec = m.addAction(icon('scan-search', P['text2'], 16), 'پایان ضبط و ذخیره' if rec else 'ضبط روند سایت…')
        a_diag = m.addAction(icon('bug', P['text2'], 16), 'ذخیرهٔ گزارش عیب‌یابی اتصال')
        a_trace = m.addAction(icon('list', P['text2'], 16), 'روش‌های امتحان‌شدهٔ دریافت اسناد')
        m.addSeparator()
        a_dir = m.addAction(icon('folder-open', P['text2'], 16), 'باز کردن پوشهٔ گزارش‌ها')
        has = getattr(ten, 'worker', None) is not None
        for a in (a_rec, a_diag, a_trace):
            a.setEnabled(has)
        chosen = m.exec(self.b_tools.mapToGlobal(QPoint(self.b_tools.width(), self.b_tools.height())) - QPoint(m.sizeHint().width(), 0))
        if chosen is a_rec:
            self._call(ten, 'toggle_recording')
        elif chosen is a_diag:
            self._call(ten, '_run', 'diagnose', version=__version__)
        elif chosen is a_trace:
            self._call(ten, '_show_trace')
        elif chosen is a_dir:
            base = getattr(ten, 'base', None)
            if base is not None:
                d = Path(base) / 'diagnostics'
                d.mkdir(parents=True, exist_ok=True)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _connect_clicked(self):
        connected = (self.b_connect.property('state') or 'off') == 'on'
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        a_conn = m.addAction(icon('plug-zap', P['text2'], 16), 'اتصال دوباره / ورود' if connected else 'اتصال و ورود')
        a_show = m.addAction(icon('external-link', P['text2'], 16), 'نمایش مرورگر')
        a_chk = m.addAction(icon('refresh-cw', P['text2'], 16), 'بررسی وضعیت اتصال و نقش')
        chosen = m.exec(self.b_connect.mapToGlobal(QPoint(self.b_connect.width(), self.b_connect.height())) - QPoint(m.sizeHint().width(), 0))
        if chosen is a_conn:
            want = self._section_role()
            if want == 'EPROC' or getattr(self.ten, 'worker', None) is None:
                self._call(self.inq, '_launch')       # stays on the purchase page, role «تامین‌کننده»
            else:
                self._call(self.ten, 'connect_site')
        elif chosen is a_show:
            if getattr(self.ten, 'worker', None) is not None:
                self._call(self.ten, '_run', 'show_browser')
            else:
                self._call(self.inq, '_launch')
        elif chosen is a_chk:
            self._call(self.ten, '_run', 'check')

    def _section_role(self):
        """Role that fits the section the user is in; dashboard/other pages keep the last role."""
        idx = self.stack.currentIndex()
        if idx == PAGE_INQ:
            return 'EPROC'
        if idx == PAGE_TEN:
            return 'ETEND'
        return self._role if self._role in ('ETEND', 'EPROC') else 'ETEND'

    def _role_clicked(self):
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        acts = {}
        for code in ('ETEND', 'EPROC'):
            title = self.ROLE_TITLES[code] + ('  ✓' if self._role == code else '')
            acts[m.addAction(title)] = code
        chosen = m.exec(self.b_role.mapToGlobal(QPoint(self.b_role.width(), self.b_role.height())) - QPoint(m.sizeHint().width(), 0))
        code = acts.get(chosen)
        if code:
            self.set_role(code)

    def set_role(self, code):
        if code == self._role or self._switching:
            return
        worker = getattr(self.ten, 'worker', None)
        online = (self.b_connect.property('state') or 'off') == 'on'
        if worker is None or not online:
            QMessageBox.information(self, 'تعیین نقش', 'ابتدا «اتصال به ستاد» را بزنید و وارد شوید؛ بعد نقش را عوض کنید.')
            return
        self._switching = code
        QTimer.singleShot(120_000, self._switch_timeout)
        self._update_role_chip()
        self._call(self.ten, '_run', 'set_role', role=code)

    def _switch_timeout(self):
        if self._switching:
            self._switching = None
            self._update_role_chip()

    def _worker_failed(self, cmd, msg):
        if cmd in ('record_start', 'record_stop'):
            QMessageBox.warning(self, 'ضبط روند سایت', str(msg)[:600])
            return
        if cmd == 'set_role':
            self._switching = None
            self._update_role_chip()
            QMessageBox.warning(self, 'تعیین نقش', str(msg)[:600])

    def _update_role_chip(self):
        if self._switching:
            text, hint = f'در حال تعویض نقش به {self.ROLE_TITLES[self._switching]}…', False
        else:
            cur = self.ROLE_TITLES.get(self._role or '', '—')
            text = f'نقش: {cur}'
            idx = self.stack.currentIndex()
            need = 'EPROC' if idx == PAGE_INQ else 'ETEND' if idx == PAGE_TEN else None
            hint = bool(self._role and need and need != self._role)
            if hint:
                text += '  •  این بخش نقش دیگری می‌خواهد'
        if self.b_role.text() != text or bool(self.b_role.property('hint')) != hint:
            self.b_role.setText(text)
            self.b_role.setProperty('hint', hint)
            self.b_role.style().unpolish(self.b_role)
            self.b_role.style().polish(self.b_role)
            self.b_role.adjustSize()

    def _side(self):
        side = QFrame()
        side.setObjectName('SSide')
        side.setFixedWidth(250)
        self.side = side
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName('SScroll')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName('SSideInner')
        inner.setStyleSheet('QWidget#SSideInner { background:transparent; }')
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 8, 0, 8)
        v.setSpacing(0)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.nav = {}
        self.groups = []
        self.subs = {}

        def group(text):
            g = QLabel(text)
            g.setObjectName('SGroup')
            v.addWidget(g)
            self.groups.append(g)

        def item(key, text, ic, expandable=False, box=None, sub=False):
            b = NavButton(text, ic, sub=sub, expandable=expandable)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            if expandable:
                b.arrow_clicked.connect(lambda k=key: self._toggle_sub(k))
            (box or v).addWidget(b)
            self.nav[key] = b
            return b

        def submenu(parent_key, entries):
            f = QFrame()
            f.setObjectName('SSubRail')
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 2)
            fl.setSpacing(0)
            for k, t in entries:
                item(k, t, '', box=fl, sub=True)
            v.addWidget(f)
            self.subs[parent_key] = f
            f.hide()
            self.nav[parent_key].set_open(False)

        group('کار روزانه')
        item('dash', 'داشبورد', 'layout-dashboard')
        item('work', 'کارهای من', 'square-kanban')
        group('فراخوان‌ها')
        item('inq', 'فراخوان‌های خرید', 'shopping-cart', expandable=True)
        submenu('inq', [('inq_open', 'مهلت‌دار'), ('inq_star', 'ستاره‌دار'), ('inq_all', 'همه'), ('inq_arch', 'صرف‌نظرشده')])
        item('ten', 'فراخوان‌های مناقصه', 'gavel', expandable=True)
        submenu('ten', [('ten_act', 'قابل‌اقدام'), ('ten_star', 'ستاره‌دار'), ('ten_mine', 'در فراخوان‌های من'), ('ten_all', 'همه')])
        group('تأمین و فروش')
        item('inq_sup', 'تأمین‌کنندگان', 'users')
        group('مدارک و اسناد')
        item('ten_docs', 'مدارک شرکت', 'shield-check')
        item('folders', 'پوشه اسناد', 'folder-open')
        item('settings', 'تنظیمات', 'settings')
        v.addStretch()

        # bottom: theme switch + collapse + version
        self.theme_seg = QFrame()
        self.theme_seg.setObjectName('SThemeSeg')
        tl = QHBoxLayout(self.theme_seg)
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(4)
        self.b_light = QPushButton(' روشن')
        self.b_dark = QPushButton(' تیره')
        self.theme_group = QButtonGroup(self)
        for b, name in ((self.b_light, 'light'), (self.b_dark, 'dark')):
            b.setObjectName('SThemeBtn')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self.set_theme(n))
            self.theme_group.addButton(b)
            tl.addWidget(b, 1)
        outer.addWidget(self.theme_seg)
        self.b_collapse = QPushButton()
        self.b_collapse.setObjectName('SCollapse')
        self.b_collapse.setCursor(Qt.PointingHandCursor)
        self.b_collapse.setToolTip('جمع/باز کردن منو')
        self.b_collapse.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        outer.addWidget(self.b_collapse)
        self.foot = QLabel(f'نسخه {D.fa(__version__)}')
        self.foot.setObjectName('SFoot')
        self.foot.setWordWrap(True)
        outer.addWidget(self.foot)
        self._collapsed = False
        self._paint_side_controls()
        return side

    def _paint_side_controls(self):
        dark = design.current() == 'dark'
        self.b_light.setChecked(not dark)
        self.b_dark.setChecked(dark)
        self.b_light.setIcon(icon('sun', P['text'] if not dark else P['muted'], 16))
        self.b_dark.setIcon(icon('moon', P['text'] if dark else P['muted'], 16))
        self.b_collapse.setIcon(icon('chevron-right' if not self._collapsed else 'chevron-left', P['muted'], 18))
        for b in self.nav.values():
            b._paint(b.isChecked())

    def set_collapsed(self, on):
        self._collapsed = bool(on)
        self.settings.setValue('side_collapsed', self._collapsed)
        self.side.setFixedWidth(68 if on else 250)
        for g in self.groups:
            g.setVisible(not on)
        for k, b in self.nav.items():
            b.set_collapsed(on)
            if b.sub:
                b.setVisible(not on)
        for k, f in self.subs.items():
            f.setVisible(not on and f.property('open') is True)
        self.theme_seg.setVisible(not on)
        self.foot.setVisible(not on)
        self._paint_side_controls()

    def _toggle_sub(self, key):
        f = self.subs.get(key)
        if f is not None:
            self._open_sub(key, not bool(f.property('open')))

    def _open_sub(self, key, on=True):
        f = self.subs.get(key)
        if f is None:
            return
        if on:          # accordion: only the section you are in stays open
            for other in self.subs:
                if other != key:
                    self._open_sub(other, False)
        f.setProperty('open', bool(on))
        f.setVisible(bool(on) and not self._collapsed)
        self.nav[key].set_open(on)

    def _popup(self):
        self.pop = QFrame(self, Qt.Tool | Qt.FramelessWindowHint)
        self.pop.setObjectName('SPopup')
        self.pop.setStyleSheet(self.centralWidget().styleSheet())
        self.pop.setAttribute(Qt.WA_ShowWithoutActivating)
        pl = QVBoxLayout(self.pop)
        pl.setContentsMargins(4, 4, 4, 4)
        self.results = QListWidget()
        self.results.setObjectName('SResults')
        self.results.itemClicked.connect(self._result_clicked)
        pl.addWidget(self.results)
        self.pop.hide()

    # ------------------------------------------------------------------ theme
    def set_theme(self, name):
        design.set_theme(self, name)

    def restyle(self):
        """Re-apply every style sheet from the current tokens and rebuild what bakes colors."""
        css = qss(self._font)
        self.centralWidget().setStyleSheet(css)
        self.pop.setStyleSheet(css)
        try:
            from setad_tender.theme import make_qss
            from setad_tender.widgets import recolor_icons as ten_recolor
            if hasattr(self.ten, 'db'):
                self.ten.setStyleSheet(make_qss())
                ten_recolor(self.ten)
        except Exception:
            pass
        try:
            import ui_kit
            if hasattr(self.inq, 'model'):
                self.inq.setStyleSheet(ui_kit.build_stylesheet(self._inq_font()))
                ui_kit.recolor_icons(self.inq)
        except Exception:
            pass
        for (kind, _id), w in list(self._docs.items()):
            self._style_doc(kind, w)
        # pages whose colors are baked at construction are simply rebuilt
        cur = self.stack.currentIndex()
        for attr, idx, cls in (('dash', PAGE_DASH, DashboardPage), ('work', PAGE_WORK, MyWorkPage)):
            old = getattr(self, attr)
            new = cls()
            self.stack.insertWidget(idx, new)
            self.stack.removeWidget(old)
            old.deleteLater()
            setattr(self, attr, new)
        self._wire_pages()
        self.stack.setCurrentIndex(cur)
        self._paint_side_controls()
        for fn in (lambda: self.ten.refresh(), lambda: self.inq.refresh_views()):
            try:
                fn()
            except Exception:
                pass
        self.refresh_data()

    def _inq_font(self):
        try:
            import ui_kit
            if not hasattr(self, '_inq_font_cache'):
                self._inq_font_cache = ui_kit.load_fonts()
            return self._inq_font_cache
        except Exception:
            return self._font

    # ------------------------------------------------------------------ in-app tabs (cases / tender workspaces)
    def _style_doc(self, kind, w):
        try:
            if kind == 'ten':
                from setad_tender.theme import make_qss
                w.setStyleSheet(make_qss())
            elif hasattr(self.inq, 'styleSheet'):
                w.setStyleSheet(self.inq.styleSheet())
        except Exception:
            pass

    def host_doc(self, kind, item_id, title, factory, on_close=None):
        """Open a case / workspace as a tab inside the app (one tab per item)."""
        key = (kind, str(item_id))
        w = self._docs.get(key)
        if w is None:
            try:
                w = factory()
            except Exception as e:
                QMessageBox.warning(self, title, str(e)[:600])
                return
            w.setWindowFlags(Qt.Widget)
            self._style_doc(kind, w)
            w._doc_key = key
            w._doc_close = on_close
            if hasattr(w, 'finished'):
                w.finished.connect(lambda *_, k=key: self._doc_finished(k))
            ic = icon('shopping-cart' if kind == 'inq' else 'gavel', P['inq'] if kind == 'inq' else P['ten'], 16)
            self.docs.addTab(w, ic, title)
            self._docs[key] = w
            w.show()
        self.stack.setCurrentIndex(PAGE_DOCS)
        self.docs.setCurrentWidget(w)
        self._sync_nav('docs')
        self._rebuild_strip()

    def _close_doc(self, index):
        w = self.docs.widget(index)
        if w is None:
            return
        try:
            if hasattr(w, 'done'):
                w.done(0)      # a QDialog emits finished → _doc_finished (even while its tab is hidden)
            else:
                w.close()
        except Exception:
            pass
        if getattr(w, '_doc_key', None) in self._docs:
            self._doc_finished(w._doc_key)

    def _doc_finished(self, key):
        w = self._docs.pop(key, None)
        if w is None:
            return
        i = self.docs.indexOf(w)
        if i >= 0:
            self.docs.removeTab(i)
        cb = getattr(w, '_doc_close', None)
        w.deleteLater()
        if cb:
            try:
                cb()
            except Exception:
                pass
        self._rebuild_strip()
        if not self._docs and self.stack.currentIndex() == PAGE_DOCS:
            self.go('work')
        QTimer.singleShot(200, self.refresh_data)

    # ------------------------------------------------------------------ navigation
    def go(self, key):
        page = None
        if key == 'inq_board':
            key = 'work'
        if key == 'dash':
            page = PAGE_DASH
        elif key == 'work':
            page = PAGE_WORK
        elif key == 'docs':
            if not self._docs:
                self.go('work')
                return
            page = PAGE_DOCS
        elif key in INQ_KEYS:
            page = PAGE_INQ
            tabs = getattr(self.inq, 'tabs', None)
            if tabs is not None:
                tabs.setCurrentIndex(INQ_TAB[key])
            if key in ('inq', 'inq_open', 'inq_star', 'inq_all', 'inq_arch'):
                self._open_sub('inq', True)
            if key in ('inq_open', 'inq_star', 'inq_all'):
                self._inq_filter(key)
        elif key in TEN_KEYS:
            page = PAGE_TEN
            self._open_sub('ten', True)
            if key != 'ten':
                self._ten_filter(key)
        elif key == 'ten_docs':
            self._call(self.ten, 'open_company_docs')
            return self._sync_nav()
        elif key == 'folders':
            return self._folders_menu()
        elif key == 'settings':
            return self._settings_menu()
        if page is not None:
            self.stack.setCurrentIndex(page)
            if page in (PAGE_DASH, PAGE_WORK):
                self.refresh_data()
        self._sync_nav(key)
        self._rebuild_strip()

    def _inq_filter(self, key):
        star, opened = getattr(self.inq, 'only_star', None), getattr(self.inq, 'only_open', None)
        if star is None or opened is None:
            return
        star.setChecked(key == 'inq_star')
        opened.setChecked(key == 'inq_open')
        nw = getattr(self.inq, 'only_new', None)
        if nw is not None and key == 'inq_all':
            nw.setChecked(False)

    def _ten_filter(self, key):
        chips = getattr(self.ten, 'chips', None)
        if not chips:
            return
        want = {'ten_act': 'actionable', 'ten_star': 'starred', 'ten_mine': 'mycalls'}.get(key)
        for k in ('actionable', 'starred', 'mycalls', 'soon'):
            if k in chips:
                chips[k].blockSignals(True)
                chips[k].setChecked(k == want)
                chips[k].blockSignals(False)
        try:
            from PySide6.QtCore import QSettings as _S
            _S('SetadSuite', 'tenders').setValue('chip_actionable', want == 'actionable')
            self.ten.filter_changed()
        except Exception:
            pass

    def _sync_nav(self, key=None):
        page = self.stack.currentIndex()
        if hasattr(self, 'b_role') and hasattr(self, '_switching'):
            self._update_role_chip()
        if key is None or key in ('ten_docs', 'folders', 'settings'):
            if page == PAGE_INQ:
                tabs = getattr(self.inq, 'tabs', None)
                i = tabs.currentIndex() if tabs is not None else 0
                key = {0: self._last_inq_key(), 1: 'inq_board', 2: 'inq_sup', 3: 'inq_arch'}.get(i, 'inq')
            elif page == PAGE_TEN:
                key = self._last_ten_key()
            else:
                key = {PAGE_DASH: 'dash', PAGE_WORK: 'work', PAGE_DOCS: 'docs'}.get(page, 'dash')
        parent = 'inq' if key in ('inq_open', 'inq_star', 'inq_all', 'inq_arch') else 'ten' if key in TEN_KEYS[1:] else None
        for k, b in self.nav.items():
            on = k == key or k == parent
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
            b._paint(on)

    def _last_inq_key(self):
        star, opened = getattr(self.inq, 'only_star', None), getattr(self.inq, 'only_open', None)
        if star is not None and star.isChecked():
            return 'inq_star'
        if opened is not None and opened.isChecked():
            return 'inq_open'
        return 'inq_all'

    def _last_ten_key(self):
        chips = getattr(self.ten, 'chips', None) or {}
        for k, key in (('actionable', 'ten_act'), ('starred', 'ten_star'), ('mycalls', 'ten_mine')):
            if k in chips and chips[k].isChecked():
                return key
        return 'ten_all'

    def _menu_at(self, key):
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        return m, self.nav[key].mapToGlobal(QPoint(self.nav[key].width() // 2, self.nav[key].height()))

    def _folders_menu(self):
        m, pos = self._menu_at('folders')
        inq_dir = getattr(self.inq, 'output_dir', None)
        ten_dir = getattr(self.ten, 'download_path', None)
        a1 = m.addAction(icon('shopping-cart', P['text2'], 16), 'پوشه پیوست‌های استعلام')
        a2 = m.addAction(icon('gavel', P['text2'], 16), 'پوشه اسناد مناقصه')
        a1.setEnabled(bool(inq_dir))
        a2.setEnabled(bool(ten_dir))
        chosen = m.exec(pos)
        target = inq_dir if chosen is a1 else ten_dir if chosen is a2 else None
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        self._sync_nav()

    def _settings_menu(self):
        m, pos = self._menu_at('settings')
        a1 = m.addAction(icon('shopping-cart', P['text2'], 16), 'تنظیمات استعلام و پیش‌فاکتور')
        a2 = m.addAction(icon('gavel', P['text2'], 16), 'تنظیمات مناقصه‌ها (و نگاشت وضعیت سایت)')
        a3 = m.addAction(icon('folder-open', P['text2'], 16), 'محل ذخیرهٔ اسناد')
        chosen = m.exec(pos)
        if chosen is a3:
            from .storage import StorageDialog
            StorageDialog(self).exec()
        if chosen is a1:
            self._call(self.inq, '_open_settings')
        elif chosen is a2:
            self._call(self.ten, 'open_settings')
        self._sync_nav()

    @staticmethod
    def _call(obj, name, *args, **kw):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                return fn(*args, **kw)
            except Exception as e:
                QMessageBox.warning(obj if isinstance(obj, QWidget) else None, 'خطا', str(e)[:600])
        return None

    # ------------------------------------------------------------------ actions
    def quick_action(self, key):
        if key == 'mywork':
            self.go('work')
        elif key == 'inq_refresh':
            self.go('inq')
            if getattr(self.inq, 'browser_opened', False):
                self._call(self.inq, '_refresh')
            else:
                self._call(self.inq, '_launch')
        elif key == 'ten_connect':
            self.go('ten')
            self._call(self.ten, 'connect_site')
        elif key == 'ten_sync':
            self.go('ten')
            self._call(self.ten, 'start_sync')
        elif key == 'company_docs':
            self._call(self.ten, 'open_company_docs')
        elif key == 'suppliers':
            self.go('inq_sup')

    def dash_ack(self, key):
        db = getattr(self.ten, 'db', None)
        if db is None:
            return
        if key.startswith('edition:'):
            _, tid, ed = key.split(':', 2)
            seen = db.meta('seen_editions') or {}
            seen[tid] = ed
            db.set_meta('seen_editions', seen)
        elif key == 'edition':
            seen = db.meta('seen_editions') or {}
            for r in db.list_tenders():
                if str(r.get('edition_no') or '').strip():
                    seen[str(r['id'])] = str(r['edition_no']).strip()
            db.set_meta('seen_editions', seen)
        elif key == 'status':
            from setad_tender.db import now as _now
            db.set_meta('status_seen_at', _now())
        QTimer.singleShot(50, self.refresh_data)

    # ------------------------------------------------------------------ kanban requests
    def work_request(self, req):
        action, items = req.get('action'), req.get('items') or []
        inq = [x for x in items if x['kind'] == 'inq']
        ten = [x for x in items if x['kind'] == 'tender']
        db = getattr(self.ten, 'db', None)
        if action == 'move':
            col = req.get('col', 0)
            for x in inq:
                self._call(self.inq, 'move_stage', x['id'], D.INQ_COL_STAGE[col])
            if db is not None:
                for x in ten:
                    db.ws_save(x['id'], stage=D.TENDER_COL_STAGE[col])
            self.work.show_toast(f'{D.fa(len(items))} مورد به «{D.COLUMNS[col]}» رفت.')
        elif action == 'star' and db is not None:
            for x in ten:
                db.set_star(x['id'], not x.get('starred'))
        elif action == 'folder':
            x = items[0]
            base = getattr(self.inq, 'output_dir', None) if x['kind'] == 'inq' else getattr(self.ten, 'download_path', None)
            if base:
                folder = Path(base) / str(x['id']) if x['kind'] == 'inq' else Path(base)
                if x['kind'] == 'tender':
                    cand = [p for p in Path(base).glob(f"*{x['number']}*") if p.is_dir()] if Path(base).exists() else []
                    folder = cand[0] if cand else Path(base)
                folder.mkdir(parents=True, exist_ok=True)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif action == 'docs':
            needs = [n for n in (self._call(self.inq, 'need_obj', x['id']) for x in inq) if n]
            if needs:
                self._call(self.inq, 'download_needs', needs)
            if ten:
                if not getattr(self.ten, 'online', False):
                    self.work.show_toast('برای دریافت اسناد مناقصه، ابتدا در بخش مناقصه «اتصال به ستاد» را بزنید.')
                else:
                    self.ten.worker.submit('batch', kind='documents', ids=[x['id'] for x in ten],
                                           helper=self.ten.settings.value('allow_helper', True, type=bool))
            if needs or ten:
                self.work.show_toast(f'دریافت اسناد {D.fa(len(needs) + len(ten))} مورد شروع شد.')
        elif action == 'waive':
            undo = []
            for x in inq:
                prev = self._call(self.inq, 'quick_waive', x['id'])
                undo.append(('inq', x['id'], prev))
            if db is not None and ten:
                db.set_waived([x['id'] for x in ten], True)
                undo += [('ten', x['id'], None) for x in ten]
            self._call(self.inq, 'refresh_views')
            title = items[0]['title'][:40] if len(items) == 1 else f'{D.fa(len(items))} مورد'
            self.work.show_toast(f'«{title}» صرف‌نظر شد', lambda u=undo: self._undo_waive(u))
        elif action == 'delete':
            self._delete_items(inq, ten)
        QTimer.singleShot(50, self.refresh_data)
        self._call(self.ten, 'refresh')

    def _undo_waive(self, undo):
        db = getattr(self.ten, 'db', None)
        for kind, item_id, prev in undo:
            if kind == 'inq':
                self._call(self.inq, 'undo_waive', item_id, prev)
            elif db is not None:
                db.set_waived([item_id], False)
        self._call(self.ten, 'refresh')
        self.refresh_data()

    def _delete_items(self, inq, ten):
        n = len(inq) + len(ten)
        locked = [x for x in ten if x.get('locked')]
        on_site = [x for x in ten if x.get('in_calls') and not x.get('locked')]
        box = CompactBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle('حذف کامل')
        box.setText(f'{D.fa(n)} مورد به‌طور کامل از برنامه حذف شود؟')
        info = ['پرونده، استعلام‌ها، میز کار، پاکت‌ها و یادداشت‌ها پاک می‌شوند (فایل‌های داخل پوشه‌ها دست نمی‌خورند). این کار برگشت ندارد.']
        if locked:
            info.append(f'{D.fa(len(locked))} مناقصه پاکتش در سایت بارگذاری/ارسال شده؛ در سایت قفل است و فقط از برنامه حذف می‌شود.')
        box.setInformativeText('\n\n'.join(info))
        b_site = None
        if on_site:
            b_site = box.addButton(f'حذف + برداشتن از «فراخوان‌های من» سایت ({D.fa(len(on_site))})', QMessageBox.DestructiveRole)
        b_app = box.addButton('فقط از برنامه', QMessageBox.AcceptRole if not on_site else QMessageBox.DestructiveRole)
        box.addButton('انصراف', QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (b_app, b_site) or clicked is None:
            return
        for x in inq:
            self._call(self.inq, 'delete_case', x['id'])
        db = getattr(self.ten, 'db', None)
        if db is not None:
            for x in ten:
                db.delete_work(x['id'])
        if clicked is b_site and on_site:
            if not getattr(self.ten, 'online', False):
                QMessageBox.information(self, 'حذف از سایت', 'برای برداشتن از «فراخوان‌های من» سایت ابتدا «اتصال به ستاد» را بزنید؛ '
                                        'از داخل برنامه حذف شد.')
            else:
                for x in on_site:
                    self.ten.worker.submit('unfavorite', id=x['id'], confirmed=True)
        self.work.show_toast(f'{D.fa(n)} مورد حذف شد.')

    def open_item(self, item):
        if item['kind'] == 'inq':
            self._call(self.inq, 'open_case', item['id'])
        else:
            self.open_tender(item['id'])
        QTimer.singleShot(400, self.refresh_data)

    def open_tender(self, tid):
        ten = self.ten
        db = getattr(ten, 'db', None)
        if db is None:
            return
        t = db.tender(tid)
        if not t:
            return
        try:
            ten.show_tender(tid)
            ten._reselect(tid)
        except Exception:
            pass
        from setad_tender.workspace_ui import WorkspaceDialog
        self.host_doc('ten', str(tid), f"مناقصه {t.get('number') or tid}",
                      lambda: WorkspaceDialog(db, t, ten.download_path, None), lambda: self._call(ten, 'refresh'))

    # ------------------------------------------------------------------ search
    def _search_changed(self, text):
        res = D.search(self.inq if hasattr(self.inq, 'model') else None, getattr(self.ten, 'db', None), text) \
            if getattr(self.ten, 'db', None) is not None or hasattr(self.inq, 'model') else []
        self.results.clear()
        if not res:
            self.pop.hide()
            return
        for r in res[:60]:
            kind = 'استعلام' if r['kind'] == 'inq' else 'مناقصه'
            mark = '  ✓' if r.get('in_case') else ''
            it = QListWidgetItem(f"[{kind}]  {D.fa(r['number'] or '')}  —  {r['title'] or ''}{mark}")
            it.setToolTip(r.get('org') or '')
            it.setData(Qt.UserRole, r)
            it.setIcon(icon('shopping-cart' if r['kind'] == 'inq' else 'gavel', P['inq'] if r['kind'] == 'inq' else P['ten'], 16))
            self.results.addItem(it)
        w = max(self.search.width(), 520)
        h = min(420, 14 + 40 * self.results.count())
        pos = self.search.mapToGlobal(QPoint(self.search.width() - w if self.layoutDirection() == Qt.LeftToRight else 0,
                                             self.search.height() + 6))
        self.pop.setGeometry(pos.x(), pos.y(), w, h)
        self.pop.show()
        self.pop.raise_()

    def _search_enter(self):
        if self.results.count():
            self._result_clicked(self.results.currentItem() or self.results.item(0))

    def _result_clicked(self, it):
        if it is None:
            return
        r = it.data(Qt.UserRole)
        self.pop.hide()
        if r['kind'] == 'inq':
            self.go('inq')
            s = getattr(self.inq, 'search', None)
            if s is not None:
                s.setText(r['number'])
            if r.get('in_case'):
                self._call(self.inq, 'open_case', r['id'])
        else:
            self.go('ten')
            s = getattr(self.ten, 'search', None)
            if s is not None:
                s.setText(r['number'] or '')
            try:
                self.ten.show_tender(r['id'])
                self.ten._reselect(r['id'])
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        if obj is self.search:
            if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Down, Qt.Key_Up) and self.pop.isVisible():
                row = self.results.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
                self.results.setCurrentRow(max(0, min(self.results.count() - 1, row)))
                return True
            if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                self.pop.hide()
                self.search.clear()
                return True
            if ev.type() == QEvent.FocusOut:
                QTimer.singleShot(200, lambda: (not self.results.hasFocus()) and self.pop.hide())
        return super().eventFilter(obj, ev)

    def moveEvent(self, e):
        self.pop.hide()
        super().moveEvent(e)

    # ------------------------------------------------------------------ data
    def refresh_data(self):
        if self._closing:
            return
        db = getattr(self.ten, 'db', None)
        ui = self.inq if hasattr(self.inq, 'board_items') else None
        try:
            st = D.stats(ui, db)
        except Exception:
            return
        if self.stack.currentIndex() == PAGE_DASH:
            self.dash.update_data(st)
        if self.stack.currentIndex() == PAGE_WORK:
            self.work.update_data(st['items'])
        self.nav['work'].set_badge(st['active'], 'blue')
        self.nav['inq'].set_badge(st['needs_new'], 'green')
        self.nav['ten'].set_badge(st['tenders_soon'])
        self.nav['dash'].set_badge(st['urgent'])
        self.nav['ten_act'].set_badge(st.get('tenders_actionable'), 'muted')
        self.nav['ten_star'].set_badge(st.get('tenders_starred'), 'muted')
        self.nav['ten_mine'].set_badge(st.get('my_calls'), 'muted')
        self.nav['ten_all'].set_badge(st.get('tenders_total'), 'muted')
        self.nav['inq_arch'].set_badge(st.get('inq_rejected'), 'muted')
        self.nav['inq_all'].set_badge(st.get('needs_total'), 'muted')
        self._rebuild_strip()

    def _set_pill(self, pill, state, text):
        if pill.property('state') == state and pill.text() == text:
            return
        pill.setText('  ' + text if pill is self.b_connect else text)
        pill.setProperty('state', state)
        pill.style().unpolish(pill)
        pill.style().polish(pill)
        pill.adjustSize()
        pill.updateGeometry()

    ROLE_TITLES = {'ETEND': 'مناقصه‌گر', 'EPROC': 'تامین‌کننده'}

    def _worker_result(self, kind, payload):
        if kind == 'role':
            self._role = payload.get('role')
            if self._switching == self._role:
                self._switching = None
            self._mirror_status()
        elif kind == 'record_start':
            QMessageBox.information(self, 'ضبط روند سایت',
                'ضبط شروع شد (هر دو بخش مناقصه و خرید ضبط می‌شود).\n'
                'حالا در مرورگر برنامه مراحل را انجام دهید. رمز، Cookie و توکن ضبط نمی‌شود و هیچ پرداختی انجام ندهید.\n'
                'برای پایان: دکمهٔ آچار ← «پایان ضبط و ذخیره».')
        elif kind == 'record_stop':
            n = payload.get('requests')
            QMessageBox.information(self, 'ضبط روند سایت',
                f'ضبط ذخیره شد: {n} درخواست.\nپوشهٔ گزارش‌ها: آچار ← «باز کردن پوشهٔ گزارش‌ها».')
        elif kind == 'browser_closed':
            self._role = None
            self._switching = None
            self._mirror_status()

    def _mirror_status(self):
        """One status for the shared Setad browser: connected? which role is active?"""
        on = False
        src = getattr(self.ten, 'pill', None)
        if src is not None and (src.property('state') or '') == 'on':
            on = True
        src = getattr(self.inq, 'conn_pill', None)
        if src is not None and (src.property('state') or '') == 'on':
            on = True
        if getattr(self.inq, 'browser_opened', False):
            on = True
        if self._role:
            on = True
        if on:
            role = self.ROLE_TITLES.get(self._role or '', '')
            text = 'ستاد: متصل' + (f'  •  نقش فعلی: {role}' if role else '')
            self._set_pill(self.pill_inq, 'on', text)
        else:
            self._set_pill(self.pill_inq, 'off', 'اتصال به ستاد')
        self._update_role_chip()
        rec = bool(getattr(self.ten, 'recording', False))
        if bool(self.b_tools.property('rec')) != rec:
            self.b_tools.setProperty('rec', rec)
            self.b_tools.setToolTip('در حال ضبط روند سایت — برای پایان، همین‌جا بزنید' if rec else 'ابزارهای اتصال: ضبط روند سایت، گزارش عیب‌یابی')
            self.b_tools.style().unpolish(self.b_tools)
            self.b_tools.style().polish(self.b_tools)
        if self.stack.currentIndex() == PAGE_INQ:
            self._sync_nav()

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, event):
        if self._closing:
            event.ignore()
            return
        self._closing = True
        self.timer.stop()
        self.data_timer.stop()
        self.pop.hide()
        self.setEnabled(False)
        self.statusBar().showMessage('در حال بستن ایمن مرورگرها و برنامه…')
        QApplication.processEvents()
        # tenders: synchronous shutdown of its worker thread
        ten = self.ten
        if hasattr(ten, 'worker'):
            try:
                ten.worker.shutdown()
                ten.worker.wait(15000)
                ten.db.close()
            except Exception:
                pass
        # inquiries: its own close sequence (stops the engine, then quits the application)
        if hasattr(self.inq, 'worker') and hasattr(self.inq, 'closeEvent'):
            self.inq.close()
            event.ignore()
            self.hide()
            QTimer.singleShot(25000, QApplication.instance().quit)  # safety net
            return
        event.accept()
        QApplication.instance().quit()
