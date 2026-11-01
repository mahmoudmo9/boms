"""Dashboard and «کارهای من» pages of the shell."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal, QSize, QMimeData, QTimer
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget, QButtonGroup)

from setad_tender.icons import icon, pixmap
from setad_tender.dates import jalali_of

from . import data as D
from .style import P

WEEKDAYS = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']
MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


def today_text() -> str:
    d = date.today()
    try:
        y, m, dd = (int(x) for x in jalali_of(d).replace('-', '/').split('/'))
        return f'{WEEKDAYS[d.weekday()]} {D.fa(dd)} {MONTHS[m - 1]} {D.fa(y)}'
    except Exception:
        return WEEKDAYS[d.weekday()]


def lab(text='', name=None, wrap=False) -> QLabel:
    l = QLabel(str(text))
    if name:
        l.setObjectName(name)
    if wrap:
        l.setWordWrap(True)
    return l


def tag(text, fg, bg) -> QLabel:
    t = QLabel(text)
    t.setObjectName('STag')
    t.setStyleSheet(f'color:{fg}; background:{bg};')
    t.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    t.setAlignment(Qt.AlignCenter)
    return t


def kind_tag(kind) -> QLabel:
    if kind == 'inq':
        return tag('استعلام', P['inq'], P['inq_soft'])
    return tag('مناقصه', P['ten'], P['ten_soft'])


def days_tag(item) -> QLabel | None:
    d = item.get('days')
    if d is None or not item.get('open'):
        return None
    txt = item.get('remaining') or D.days_text(d)
    if item.get('deadline_kind') and d >= 0:
        txt = f"{item['deadline_kind']} {txt}"
    if d < 0:
        return tag('مهلت گذشته', P['muted'], P['track'])
    if d < 2:
        return tag(txt, P['red'], P['red_soft'])
    if d < 5:
        return tag(txt, P['amber'], P['amber_soft'])
    return tag(txt, P['muted'], P['track'])


def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear(it.layout())


class Clickable(QFrame):
    clicked = Signal()

    def __init__(self, name='SItem'):
        super().__init__()
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class Kpi(QFrame):
    def __init__(self, title, icon_name, color, soft):
        super().__init__()
        self.setObjectName('SKpi')
        self.setMinimumHeight(98)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(14)
        ic = QLabel()
        ic.setObjectName('SKpiIcon')
        ic.setFixedSize(46, 46)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f'background:{soft}; border-radius:12px;')
        ic.setPixmap(pixmap(icon_name, color, 22))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.t = lab(title, 'SKpiTitle')
        self.v = lab('—', 'SKpiValue')
        self.s = lab('', 'SFaint')
        col.addWidget(self.t)
        col.addWidget(self.v)
        col.addWidget(self.s)
        lay.addWidget(ic, 0, Qt.AlignTop)
        lay.addLayout(col, 1)

    def set(self, value, sub=''):
        self.v.setText(D.fa(value))
        self.s.setText(sub)


class WorkCard(Clickable):
    def __init__(self, item, compact=False):
        super().__init__('SItem')
        self.item = item
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(kind_tag(item['kind']))
        num = lab(item['number'], 'SNum')
        top.addWidget(num)
        top.addStretch()
        dt = days_tag(item)
        if dt:
            top.addWidget(dt)
        lay.addLayout(top)
        title = lab(item['title'] or '—', 'SItemTitle', wrap=True)
        title.setMaximumHeight(46 if compact else 64)
        lay.addWidget(title)
        if item.get('org'):
            o = lab(item['org'], 'SFaint', wrap=True)
            o.setMaximumHeight(36)
            lay.addWidget(o)
        meta = ' • '.join(x for x in (item.get('stage'), item.get('meta')) if x)
        if meta:
            lay.addWidget(lab(meta, 'SMuted', wrap=True))


class ScrollList(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setObjectName('SScroll')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.box = QVBoxLayout(self.inner)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)
        self.setWidget(self.inner)


# ===================================================================== dashboard
class UrgentCard(QFrame):
    """One «اقدام فوری» block: icon + title + count, up to three rows, a footer line."""

    def __init__(self, key, title, icon_name, color, foot, page):
        super().__init__()
        self.setObjectName('SCard')
        self.key, self.page, self.color = key, page, color
        self.setMinimumHeight(196)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(8)
        h = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(pixmap(icon_name, P['text2'], 18))
        h.addWidget(ic)
        h.addWidget(lab(title, 'SH2'))
        h.addStretch()
        self.count = lab('۰', 'SKpiValue')
        self.count.setStyleSheet(f'color:{color}; font-size:17pt;')
        h.addWidget(self.count)
        v.addLayout(h)
        self.box = QVBoxLayout()
        self.box.setSpacing(6)
        v.addLayout(self.box)
        v.addStretch()
        fl = QHBoxLayout()
        self.foot = lab(foot, 'SFaint', wrap=True)
        fl.addWidget(self.foot, 1)
        self.ack = QPushButton('دیدم')
        self.ack.setObjectName('SToastBtn')
        self.ack.setStyleSheet(f'color:{P["primary"]};')
        self.ack.setCursor(Qt.PointingHandCursor)
        self.ack.clicked.connect(lambda: self.page.ack.emit(self.key))
        self.ack.setVisible(key in ('edition', 'status'))
        fl.addWidget(self.ack)
        v.addLayout(fl)

    def set_items(self, items):
        clear(self.box)
        self.count.setText(D.fa(len(items)))
        self.ack.setEnabled(bool(items))
        if not items:
            e = lab('موردی نیست', 'SFaint')
            self.box.addWidget(e)
            return
        for it in items[:3]:
            row = Clickable('SUrgentRow')
            row.setStyleSheet(f'QFrame#SUrgentRow {{ background:{P["hover"]}; border-radius:10px; }}'
                              f'QFrame#SUrgentRow:hover {{ background:{P["primary_soft"]}; }}')
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 7, 10, 7)
            rl.setSpacing(8)
            d = it.get('days')
            if self.key in ('docs', 'send') and d is not None:
                txt = (it.get('remaining') or D.days_text(d)) if it['kind'] == 'inq' else D.days_text(d)
                fg, bg = (P['red'], P['red_soft']) if d < 2 else (P['amber'], P['amber_soft']) if d < 5 else (P['green'], P['green_soft'])
                rl.addWidget(tag(f"{it.get('tag', '')} {txt}".strip(), fg, bg))
            else:
                rl.addWidget(tag(it.get('tag', ''), P['muted'], P['track']))
            t = lab(it['title'] or it['number'], 'SItemTitle')
            t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            t.setToolTip(f"{it['number']}\n{it['title']}")
            rl.addWidget(t, 1)
            if it.get('starred'):
                st = QLabel()
                st.setPixmap(pixmap('star', P['amber'], 15))
                rl.addWidget(st)
            row.clicked.connect(lambda it=it: self.page.open_urgent(self.key, it))
            self.box.addWidget(row)
        if len(items) > 3:
            self.box.addWidget(lab(f'و {D.fa(len(items) - 3)} مورد دیگر…', 'SFaint'))


class DashboardPage(QWidget):
    open_item = Signal(dict)
    action = Signal(str)
    goto = Signal(str)
    ack = Signal(str)                 # 'edition' | 'status' | ('edition:<id>')

    def __init__(self):
        super().__init__()
        self.setObjectName('SPage')
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(16)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(lab('داشبورد', 'SH1'))
        self.date = lab(today_text() + '  •  نمای کلی استعلام‌ها و مناقصه‌ها', 'SMuted')
        col.addWidget(self.date)
        head.addLayout(col)
        head.addStretch()
        root.addLayout(head)

        ur = QHBoxLayout()
        ur.setSpacing(14)
        self.urgent = {
            'docs': UrgentCard('docs', 'مهلت دریافت اسناد نزدیک است', 'clock', P['red'], 'ستاره‌دار یا افزوده‌شده، اسناد هنوز گرفته نشده (≤ ۳ روز)', self),
            'send': UrgentCard('send', 'مهلت ارسال در حال نزدیک شدن', 'send', P['amber'], 'مناقصه‌های منتظر ارسال پاکت (≤ ۷ روز) و استعلام‌های زیر ۲ روز', self),
            'edition': UrgentCard('edition', 'اصلاحیهٔ جدید', 'refresh-cw', P['ten'], 'اسناد را دوباره بررسی کنید', self),
            'status': UrgentCard('status', 'تغییر وضعیت در سایت', 'triangle-alert', P['primary'], 'از همگام‌سازی «فراخوان‌های من»', self),
        }
        for k in ('docs', 'send', 'edition', 'status'):
            ur.addWidget(self.urgent[k], 1)
        root.addLayout(ur)

        grid = QHBoxLayout()
        grid.setSpacing(14)
        self.k_active = Kpi('کارهای در جریان', 'square-kanban', P['primary'], P['primary_soft'])
        self.k_urgent = Kpi('مهلت زیر ۲ روز', 'clock', P['red'], P['red_soft'])
        self.k_new = Kpi('نیازهای جدید ستاد', 'shopping-cart', P['inq'], P['inq_soft'])
        self.k_tenders = Kpi('فراخوان‌های باز', 'gavel', P['ten'], P['ten_soft'])
        self.k_sent = Kpi('ارسال‌شده', 'send', P['green'], P['green_soft'])
        for k in (self.k_active, self.k_urgent, self.k_new, self.k_tenders, self.k_sent):
            grid.addWidget(k, 1)
        root.addLayout(grid)

        body = QHBoxLayout()
        body.setSpacing(16)
        # deadlines
        dl = QFrame()
        dl.setObjectName('SCard')
        dv = QVBoxLayout(dl)
        dv.setContentsMargins(18, 16, 18, 12)
        dv.setSpacing(10)
        h = QHBoxLayout()
        h.addWidget(lab('نزدیک‌ترین مهلت‌ها', 'SH2'))
        h.addStretch()
        b = QPushButton('همه کارها')
        b.setObjectName('SChip')
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self.action.emit('mywork'))
        h.addWidget(b)
        dv.addLayout(h)
        self.dl_list = ScrollList()
        self.dl_list.box.setSpacing(0)
        dv.addWidget(self.dl_list, 1)
        body.addWidget(dl, 3)

        # quick actions + funnel
        side = QVBoxLayout()
        side.setSpacing(16)
        qa = QFrame()
        qa.setObjectName('SCard')
        qv = QVBoxLayout(qa)
        qv.setContentsMargins(18, 16, 18, 16)
        qv.setSpacing(8)
        qv.addWidget(lab('شروع سریع', 'SH2'))
        for key, ic, text in (('inq_refresh', 'shopping-cart', 'استعلام‌ها: باز کردن مرورگر و دریافت نیازها'),
                              ('ten_connect', 'plug-zap', 'مناقصه‌ها: اتصال به ستاد'),
                              ('ten_sync', 'refresh-cw', 'مناقصه‌ها: دریافت فهرست فراخوان‌ها'),
                              ('company_docs', 'shield-check', 'مدارک شرکت (برای پاکت‌ها)'),
                              ('suppliers', 'users', 'تأمین‌کنندگان')):
            btn = QPushButton('  ' + text)
            btn.setObjectName('SAction')
            btn.setIcon(icon(ic, P['primary'], 18))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            qv.addWidget(btn)
        side.addWidget(qa)

        fn = QFrame()
        fn.setObjectName('SCard')
        self.fn_box = QVBoxLayout(fn)
        self.fn_box.setContentsMargins(18, 16, 18, 16)
        self.fn_box.setSpacing(9)
        side.addWidget(fn)
        side.addStretch()
        body.addLayout(side, 2)
        root.addLayout(body, 1)

    def open_urgent(self, key, it):
        if key == 'edition':
            self.ack.emit(f"edition:{it['id']}:{it.get('edition', '')}")
        self.open_item.emit(it)

    def update_data(self, st: dict):
        self.date.setText(today_text() + '  •  نمای کلی استعلام‌ها و مناقصه‌ها')
        u = st.get('urgent_blocks') or {}
        for k, card in self.urgent.items():
            card.set_items(u.get(k) or [])
        self.k_active.set(st['active'], f"{D.fa(st['active_inq'])} استعلام • {D.fa(st['active_ten'])} مناقصه")
        self.k_urgent.set(st['urgent'], 'نیاز به اقدام فوری' if st['urgent'] else 'مهلت فوری ندارید')
        self.k_new.set(st['needs_new'], f"از {D.fa(st['needs_total'])} نیاز آخرین دریافت")
        self.k_tenders.set(st['tenders_open'], f"{D.fa(st['tenders_soon'])} با مهلت ≤ ۳ روز • {D.fa(st['my_calls'])} در فراخوان‌های من")
        self.k_sent.set(st['submitted'], f"{D.fa(st['results'])} نتیجه • {D.fa(st['won'])} برنده")

        clear(self.dl_list.box)
        items = [x for x in st['items'] if x['open'] and x['days'] is not None and x['days'] >= 0][:14]
        if not items:
            e = lab('هنوز کاری با مهلت باز ندارید. نیازها را ستاره‌دار کنید یا فراخوانی را به «فراخوان‌های من» بیفزایید.', 'SMuted', wrap=True)
            e.setAlignment(Qt.AlignCenter)
            e.setMinimumHeight(120)
            self.dl_list.box.addWidget(e)
        for it in items:
            row = Clickable('SRow')
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 10, 6, 10)
            rl.setSpacing(10)
            rl.addWidget(kind_tag(it['kind']))
            t = lab(it['title'] or it['number'], 'SItemTitle')
            t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            t.setToolTip(f"{it['number']}\n{it['title']}\n{it.get('org', '')}")
            rl.addWidget(t, 1)
            rl.addWidget(lab(it['stage'], 'SFaint'))
            dt = days_tag(it)
            if dt:
                rl.addWidget(dt)
            row.clicked.connect(lambda it=it: self.open_item.emit(it))
            self.dl_list.box.addWidget(row)
        self.dl_list.box.addStretch()

        clear(self.fn_box)
        self.fn_box.addWidget(lab('جریان کار', 'SH2'))
        counts = [0] * 5
        for x in st['items']:
            counts[x['col']] += 1
        top = max(counts) or 1
        for i, name in enumerate(D.COLUMNS):
            r = QHBoxLayout()
            r.setSpacing(8)
            n = lab(name, 'SMuted')
            n.setFixedWidth(190)
            r.addWidget(n)
            bar = QFrame()
            bar.setObjectName('SBar')
            bar.setFixedHeight(8)
            bl = QHBoxLayout(bar)
            bl.setContentsMargins(0, 0, 0, 0)
            fill = QFrame()
            fill.setStyleSheet(f'background:{D.COLUMN_COLORS[i]}; border-radius:4px;')
            bl.addWidget(fill, counts[i])
            bl.addStretch(top - counts[i] if counts[i] else top)
            if not counts[i]:
                fill.hide()
            r.addWidget(bar, 1)
            r.addWidget(lab(D.fa(counts[i]), 'SNum'))
            self.fn_box.addLayout(r)


# ===================================================================== my work (kanban)
MIME = 'application/x-setad-cards'


class IconBtn(QToolButton):
    def __init__(self, name, tip, color=None, tone=None):
        super().__init__()
        self.setObjectName('SIconBtn')
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(icon(name, color or P['text2'], 17))
        self.setIconSize(QSize(17, 17))
        self.setFixedSize(30, 30)
        self.setToolTip(tip)
        if tone:
            self.setProperty('tone', tone)


class ClampLabel(QLabel):
    """Wrapped label limited to N lines; the last line ends with … (never a half-cut line). Full text in the tooltip."""

    def __init__(self, text, name, lines=2):
        super().__init__()
        self.setObjectName(name)
        self._full = text or ''
        self._lines = lines
        self._w = -1
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(self._full)
        self.setText(self._full)
        self.setMinimumHeight(self.fontMetrics().lineSpacing() + 2)

    def _fit(self):
        w = self.width()
        if w <= 20 or w == self._w:
            return
        self._w = w
        fm = self.fontMetrics()
        flags = Qt.TextWordWrap | Qt.AlignRight
        full = self._full
        limit = fm.lineSpacing() * self._lines + 2
        if fm.boundingRect(0, 0, w, 10000, flags, full).height() <= limit:
            txt = full
        else:
            lo, hi = 0, len(full)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fm.boundingRect(0, 0, w, 10000, flags, full[:mid].rstrip() + '…').height() <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            txt = full[:lo].rstrip() + '…'
        self.setText(txt)
        h = fm.boundingRect(0, 0, w, 10000, flags, txt).height() + 4
        self.setFixedHeight(max(h, fm.lineSpacing() + 2))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()


class WorkCard(QFrame):
    """A kanban card: click = open, Ctrl+click = select, drag = move, right-click = menu, hover = quick bar."""

    def __init__(self, item, page):
        super().__init__()
        self.setObjectName('SItem')
        self.setCursor(Qt.PointingHandCursor)
        self.item = item
        self.page = page
        self._press = None
        self.setProperty('gone', bool(item.get('gone')))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(kind_tag(item['kind']))
        num = lab(item['number'], 'SNum')
        num.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        num.setMinimumWidth(40)
        num.setToolTip(item['number'])
        top.addWidget(num, 1)
        if item.get('locked'):
            lk = QLabel()
            lk.setPixmap(pixmap('lock', P['faint'], 15))
            lk.setToolTip('پاکت در سایت بارگذاری/ارسال شده؛ حذف از «فراخوان‌های من» در سایت ممکن نیست.')
            top.addWidget(lk)
        dt = days_tag(item)
        if dt:
            top.addWidget(dt)
        lay.addLayout(top)
        title = ClampLabel(item['title'] or '—', 'SItemTitle', 2)
        lay.addWidget(title)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if item.get('org'):
            lay.addWidget(ClampLabel(item['org'], 'SFaint', 1))
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        meta = ' • '.join(x for x in (item.get('stage'), item.get('meta')) if x)
        if meta:
            bottom.addWidget(ClampLabel(meta, 'SMuted', 2), 1)
        if item.get('gone'):
            bottom.addWidget(tag('در سایت حذف شده', P['red'], P['red_soft']))
        elif item.get('edition') and item['edition'] not in ('0', ''):
            bottom.addWidget(tag(f"اصلاحیه {D.fa(item['edition'])}", P['ten'], P['ten_soft']))
        lay.addLayout(bottom)
        # quick bar (shown on hover, floats over the top row)
        self.bar = QFrame(self)
        self.bar.setObjectName('SHover')
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(3, 3, 3, 3)
        bl.setSpacing(2)
        acts = [('open', 'arrow-left', 'باز کردن پرونده', P['primary'], 'primary'),
                ('docs', 'download', 'دریافت اسناد / پیوست‌ها', None, None)]
        if item['kind'] == 'tender':
            acts.append(('star', 'star', 'برداشتن ستاره' if item.get('starred') else 'ستاره‌دار کردن',
                         P['amber'] if item.get('starred') else None, None))
        acts += [('folder', 'folder-open', 'پوشه اسناد', None, None),
                 ('waive', 'x', 'صرف‌نظر (Delete)', P['red'], None)]
        for key, ic, tip, color, tone in acts:
            b = IconBtn(ic, tip, color, tone)
            b.clicked.connect(lambda _=False, k=key: self.page.act(k, [self.item]))
            bl.addWidget(b)
        self.bar.adjustSize()
        self.bar.hide()

    def set_selected(self, on):
        self.setProperty('sel', bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, e):
        self.page.hovered = self
        self.bar.adjustSize()
        self.bar.move(8, 6)
        self.bar.raise_()
        self.bar.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.page.hovered is self:
            self.page.hovered = None
        self.bar.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() > 12:
            self._press = None
            self.page.start_drag(self)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None and self.rect().contains(e.position().toPoint()):
            self._press = None
            if e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                self.page.toggle_select(self)
            else:
                self.page.clear_selection()
                self.page.act('open', [self.item])
        self._press = None
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.page.context_menu(self, e.globalPos())


class KanbanColumn(QFrame):
    def __init__(self, page, index, name, color):
        super().__init__()
        self.setObjectName('SCol')
        self.setAcceptDrops(True)
        self.page = page
        self.index = index
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 12, 10, 10)
        v.setSpacing(8)
        h = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f'background:{color}; border-radius:4px;')
        h.addWidget(dot)
        h.addWidget(lab(name, 'SH2'))
        h.addStretch()
        self.cnt = lab('۰', 'SCount')
        h.addWidget(self.cnt)
        v.addLayout(h)
        self.list = ScrollList()
        v.addWidget(self.list, 1)

    def _drop(self, on):
        self.setProperty('drop', bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self._drop(True)

    def dragLeaveEvent(self, e):
        self._drop(False)

    def dropEvent(self, e):
        self._drop(False)
        self.page.dropped(self.index)
        e.acceptProposedAction()


class DropZone(QFrame):
    def __init__(self, page):
        super().__init__()
        self.setObjectName('SDrop')
        self.setAcceptDrops(True)
        self.page = page
        self.setFixedHeight(54)
        l = QHBoxLayout(self)
        ic = QLabel()
        ic.setPixmap(pixmap('x', P['red'], 18))
        l.addStretch()
        l.addWidget(ic)
        l.addWidget(lab('برای «صرف‌نظر» اینجا رها کنید  •  برای حذف کامل Shift را نگه دارید', 'SMuted'))
        l.addStretch()
        self.hide()

    def _drop(self, on):
        self.setProperty('drop', bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self._drop(True)

    def dragLeaveEvent(self, e):
        self._drop(False)

    def dropEvent(self, e):
        self._drop(False)
        shift = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
        self.page.act('delete' if shift else 'waive', self.page.drag_items)
        e.acceptProposedAction()


class MyWorkPage(QWidget):
    open_item = Signal(dict)
    request = Signal(dict)     # {'action': ..., 'items': [...], 'col': int}

    def __init__(self):
        super().__init__()
        self.setObjectName('SPage')
        self.setFocusPolicy(Qt.StrongFocus)
        self.filter = 'all'
        self._items = []
        self.cards = []
        self.selected = set()        # (kind, id)
        self.hovered = None
        self.drag_items = []
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(14)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(lab('کارهای من', 'SH1'))
        col.addWidget(lab('نشانگر را روی کارت ببرید تا کارهای سریع ظاهر شود • Ctrl+کلیک برای انتخاب چندتایی • '
                          'کارت را بکشید تا مرحله عوض شود • Delete = صرف‌نظر', 'SMuted'))
        head.addLayout(col)
        head.addStretch()
        self.group = QButtonGroup(self)
        for key, text, ic in (('all', 'همه', None), ('inq', 'خرید', 'shopping-cart'), ('tender', 'مناقصه', 'gavel')):
            b = QPushButton(text)
            b.setObjectName('SChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if ic:
                b.setIcon(icon(ic, P['text2'], 15))
            b.setChecked(key == 'all')
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.group.addButton(b)
            head.addWidget(b)
        root.addLayout(head)
        board = QHBoxLayout()
        board.setSpacing(12)
        self.cols = []
        for i, name in enumerate(D.COLUMNS):
            c = KanbanColumn(self, i, name, D.COLUMN_COLORS[i])
            board.addWidget(c, 1)
            self.cols.append(c)
        root.addLayout(board, 1)
        self.drop = DropZone(self)
        root.addWidget(self.drop)
        # selection bar + undo toast float above the board
        self.selbar = QFrame(self)
        self.selbar.setObjectName('SSelBar')
        sl = QHBoxLayout(self.selbar)
        sl.setContentsMargins(14, 8, 10, 8)
        sl.setSpacing(8)
        self.sel_label = lab('', 'SH2')
        sl.addWidget(self.sel_label)
        self.b_move = self._sel_btn('انتقال به…', 'arrow-left', lambda: self._move_menu(self.b_move))
        self.b_docs = self._sel_btn('دریافت اسناد', 'download', lambda: self.act('docs', self.selected_items()))
        self.b_waive = self._sel_btn('صرف‌نظر', 'x', lambda: self.act('waive', self.selected_items()), 'danger')
        for b in (self.b_move, self.b_docs, self.b_waive):
            sl.addWidget(b)
        x = IconBtn('x', 'لغو انتخاب (Esc)')
        x.clicked.connect(self.clear_selection)
        sl.addWidget(x)
        self.selbar.hide()
        self.toast = QFrame(self)
        self.toast.setObjectName('SToast')
        tl = QHBoxLayout(self.toast)
        tl.setContentsMargins(14, 8, 8, 8)
        tl.setSpacing(10)
        ok = QLabel()
        ok.setPixmap(pixmap('check', '#4ccf80', 17))
        tl.addWidget(ok)
        self.toast_text = QLabel('')
        tl.addWidget(self.toast_text)
        self.toast_undo = QPushButton('برگرداندن')
        self.toast_undo.setObjectName('SToastBtn')
        self.toast_undo.setIcon(icon('undo-2', '#84adff', 15))
        self.toast_undo.setCursor(Qt.PointingHandCursor)
        self.toast_undo.clicked.connect(self._undo)
        tl.addWidget(self.toast_undo)
        self.toast.hide()
        self._undo_fn = None
        self.toast_timer = QTimer(self, singleShot=True, interval=9000)
        self.toast_timer.timeout.connect(self.toast.hide)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=lambda: self._key_remove(False), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence('Shift+Delete'), self, activated=lambda: self._key_remove(True), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.clear_selection, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence.SelectAll, self, activated=self.select_all, context=Qt.WidgetWithChildrenShortcut)

    def _sel_btn(self, text, ic, fn, tone=None):
        b = QPushButton(' ' + text)
        b.setObjectName('SSelBtn')
        b.setCursor(Qt.PointingHandCursor)
        b.setIcon(icon(ic, P['red'] if tone == 'danger' else P['text2'], 16))
        if tone:
            b.setProperty('tone', tone)
        b.clicked.connect(fn)
        return b

    # ---------------------------------------------------------------- data
    def _set_filter(self, k):
        self.filter = k
        self.clear_selection()
        self._render()

    def update_data(self, items):
        self._items = items
        keys = {(x['kind'], x['id']) for x in items}
        self.selected &= keys
        self._render()

    def _render(self):
        self.cards = []
        self.hovered = None
        for i, c in enumerate(self.cols):
            clear(c.list.box)
            items = [x for x in self._items if x['col'] == i and (self.filter == 'all' or x['kind'] == self.filter)]
            c.cnt.setText(D.fa(len(items)))
            for it in items:
                card = WorkCard(it, self)
                card.set_selected((it['kind'], it['id']) in self.selected)
                c.list.box.addWidget(card)
                self.cards.append(card)
            if not items:
                e = lab('—', 'SFaint')
                e.setAlignment(Qt.AlignCenter)
                c.list.box.addWidget(e)
            c.list.box.addStretch()
        self._update_selbar()

    # ---------------------------------------------------------------- selection
    def selected_items(self):
        return [x for x in self._items if (x['kind'], x['id']) in self.selected]

    def toggle_select(self, card):
        k = (card.item['kind'], card.item['id'])
        if k in self.selected:
            self.selected.discard(k)
        else:
            self.selected.add(k)
        card.set_selected(k in self.selected)
        self._update_selbar()
        self.setFocus()

    def select_all(self):
        for card in self.cards:
            self.selected.add((card.item['kind'], card.item['id']))
            card.set_selected(True)
        self._update_selbar()

    def clear_selection(self):
        if not self.selected:
            return
        self.selected.clear()
        for card in self.cards:
            card.set_selected(False)
        self._update_selbar()

    def _update_selbar(self):
        n = len(self.selected)
        if not n:
            self.selbar.hide()
            return
        self.sel_label.setText(f'{D.fa(n)} مورد انتخاب شده')
        self.selbar.adjustSize()
        self._place_floats()
        self.selbar.show()
        self.selbar.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_floats()

    def _place_floats(self):
        sb = self.selbar.sizeHint()
        self.selbar.setGeometry((self.width() - sb.width()) // 2, self.height() - sb.height() - 18, sb.width(), sb.height())
        th = self.toast.sizeHint()
        self.toast.setGeometry(26, self.height() - th.height() - 18, th.width(), th.height())

    # ---------------------------------------------------------------- actions
    def act(self, action, items):
        items = [x for x in items if x]
        if not items:
            return
        if action == 'open':
            self.open_item.emit(items[0])
            return
        self.request.emit({'action': action, 'items': items})

    def _key_remove(self, full):
        items = self.selected_items() or ([self.hovered.item] if self.hovered is not None else [])
        if items:
            self.act('delete' if full else 'waive', items)

    def _move_menu(self, anchor, items=None):
        items = items or self.selected_items()
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        for i, name in enumerate(D.COLUMNS):
            a = m.addAction(name)
            a.triggered.connect(lambda _=False, c=i: self.request.emit({'action': 'move', 'items': items, 'col': c}))
        m.exec(anchor.mapToGlobal(anchor.rect().topLeft()) if isinstance(anchor, QWidget) else anchor)

    def context_menu(self, card, pos):
        items = self.selected_items() if (card.item['kind'], card.item['id']) in self.selected else [card.item]
        it = items[0]
        m = QMenu(self)
        m.setLayoutDirection(Qt.RightToLeft)
        if len(items) == 1:
            m.addAction(icon('arrow-left', P['primary'], 16), 'باز کردن پرونده', lambda: self.act('open', items))
        mv = m.addMenu(icon('arrow-right-left', P['text2'], 16), 'انتقال به')
        for i, name in enumerate(D.COLUMNS):
            a = mv.addAction(name)
            a.setEnabled(not (len(items) == 1 and it['col'] == i))
            a.triggered.connect(lambda _=False, c=i: self.request.emit({'action': 'move', 'items': items, 'col': c}))
        m.addAction(icon('download', P['text2'], 16), 'دریافت اسناد / پیوست‌ها', lambda: self.act('docs', items))
        if len(items) == 1:
            m.addAction(icon('folder-open', P['text2'], 16), 'باز کردن پوشه', lambda: self.act('folder', items))
        if any(x['kind'] == 'tender' for x in items):
            m.addAction(icon('star', P['amber'], 16), 'ستاره روشن/خاموش', lambda: self.act('star', items))
        m.addSeparator()
        m.addAction(icon('x', P['red'], 16), 'صرف‌نظر\tDelete', lambda: self.act('waive', items))
        m.addAction(icon('trash-2', P['red'], 16), 'حذف کامل…\tShift+Delete', lambda: self.act('delete', items))
        m.exec(pos)

    # ---------------------------------------------------------------- drag & drop
    def start_drag(self, card):
        k = (card.item['kind'], card.item['id'])
        self.drag_items = self.selected_items() if k in self.selected else [card.item]
        md = QMimeData()
        md.setData(MIME, b'1')
        drag = QDrag(card)
        drag.setMimeData(md)
        drag.setPixmap(card.grab().scaledToWidth(min(260, card.width()), Qt.SmoothTransformation))
        card.bar.hide()
        self.drop.show()
        drag.exec(Qt.MoveAction)
        self.drop.hide()

    def dropped(self, col):
        items = [x for x in self.drag_items if x['col'] != col]
        if items:
            self.request.emit({'action': 'move', 'items': items, 'col': col})

    # ---------------------------------------------------------------- undo toast
    def show_toast(self, text, undo=None):
        self.toast_text.setText(text)
        self._undo_fn = undo
        self.toast_undo.setVisible(undo is not None)
        self.toast.adjustSize()
        self._place_floats()
        self.toast.show()
        self.toast.raise_()
        self.toast_timer.start()

    def _undo(self):
        fn, self._undo_fn = self._undo_fn, None
        self.toast.hide()
        if fn:
            fn()
