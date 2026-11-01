"""«مراحل» tab of the tender panel: a dated timeline + the five steps with exactly one main button.

Everything shown comes from the site's own dates/status (lifecycle.classify); states we have not seen on
the site are shown verbatim, never guessed."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QSizePolicy, QPushButton

from .theme import C
from .widgets import button, fa_num, repolish
from .dates import days_left
from . import lifecycle as LC


def _left(n):
    if n is None:return ''
    if n < 0:return 'گذشته'
    if n == 0:return 'امروز'
    return f'{fa_num(n)} روز'


class Timeline(QWidget):
    """انتشار ── مهلت دریافت اسناد ── مهلت ارسال ── بازگشایی (RTL, drawn)."""

    def __init__(self):
        super().__init__()
        self.nodes = []      # (title, date, state, chip)   state: done|current|missed|todo
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_nodes(self, nodes):
        from .widgets import fa_digits
        self.nodes = [(t, fa_digits(d), st, fa_digits(c)) for (t, d, st, c) in nodes]
        self.update()

    def sizeHint(self):
        return QSize(420, 118)

    def paintEvent(self, e):
        if not self.nodes:return
        p = QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        n = len(self.nodes);w = self.width();r = 13;y = 22
        margin = 56
        xs = [w - margin - i * (w - 2 * margin) / max(1, n - 1) for i in range(n)]   # RTL: first node on the right
        # connecting lines
        for i in range(n - 1):
            done = self.nodes[i][2] in ('done',) and self.nodes[i + 1][2] in ('done', 'current', 'missed')
            p.setPen(QPen(QColor(C['green'] if done else C['border2']), 2))
            p.drawLine(QPointF(xs[i] - r, y), QPointF(xs[i + 1] + r, y))
        base = QFont(self.font());small = QFont(base);small.setPointSizeF(max(7.5, base.pointSizeF() - 1.3))
        bold = QFont(base);bold.setWeight(QFont.DemiBold)
        for i, (title, date, state, chip) in enumerate(self.nodes):
            x = xs[i]
            fill, ring, fg, mark = {
                'done': (C['green'], C['green'], '#ffffff', '✓'),
                'current': (C['primary'], C['primary_soft'], '#ffffff', fa_num(i + 1)),
                'missed': (C['muted'], C['muted'], '#ffffff', '✕'),
            }.get(state, (C['card'], C['border2'], C['muted'], fa_num(i + 1)))
            if state == 'current':
                p.setPen(Qt.NoPen);p.setBrush(QColor(C['primary_soft']));p.drawEllipse(QPointF(x, y), r + 4, r + 4)
            p.setPen(QPen(QColor(ring), 1.5));p.setBrush(QColor(fill));p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(QColor(fg));p.setFont(bold)
            p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, mark)
            p.setPen(QColor(C['text']));p.setFont(bold)
            p.drawText(QRectF(x - 70, y + r + 6, 140, 20), Qt.AlignCenter, title)
            p.setPen(QColor(C['muted']));p.setFont(small)
            p.drawText(QRectF(x - 70, y + r + 26, 140, 18), Qt.AlignCenter, date or 'اعلام نشده')
            if chip:
                fm = QFontMetrics(small);cw = fm.horizontalAdvance(chip) + 18
                rect = QRectF(x - cw / 2, y + r + 47, cw, 20)
                tone = (C['muted'], C['track']) if chip == 'گذشته' else (C['green'], C['green_soft'])
                p.setPen(Qt.NoPen);p.setBrush(QColor(tone[1]));p.drawRoundedRect(rect, 7, 7)
                p.setPen(QColor(tone[0]));p.drawText(rect, Qt.AlignCenter, chip)
        p.end()


class StepRow(QFrame):
    def __init__(self, num, title, sub, state, action=None):
        super().__init__()
        self.setObjectName('StepRow')
        self.setProperty('state', state)
        lay = QHBoxLayout(self);lay.setContentsMargins(12, 9, 12, 9);lay.setSpacing(12)
        badge = QLabel('✓' if state == 'done' else fa_num(num));badge.setObjectName('StepNum');badge.setProperty('state', state)
        badge.setFixedSize(28, 28);badge.setAlignment(Qt.AlignCenter)
        _bg, _fg = {'current': (C['primary'], '#ffffff'), 'done': (C['green_soft'], C['green'])}.get(state, (C['track'], C['muted']))
        badge.setStyleSheet(f"QLabel#StepNum {{ background:{_bg}; color:{_fg}; border-radius:14px; font-weight:700; }}")   # same circle in both lists, whatever page style wraps it
        col = QVBoxLayout();col.setSpacing(1)
        t = QLabel(title);t.setObjectName('StepTitle');t.setProperty('state', state)
        s = QLabel(sub);s.setObjectName('StepSub');s.setWordWrap(True)
        col.addWidget(t)
        if sub:col.addWidget(s)
        lay.addWidget(badge);lay.addLayout(col, 1)
        if action is not None:lay.addWidget(action)


class StepsPanel(QWidget):
    action = Signal(str)       # add | pay | docs | workspace | site | remove | waive

    def __init__(self):
        super().__init__()
        self.v = QVBoxLayout(self);self.v.setContentsMargins(0, 10, 0, 0);self.v.setSpacing(8)
        self.timeline = Timeline();self.v.addWidget(self.timeline)
        self.banner = QLabel();self.banner.setObjectName('StepBanner');self.banner.setWordWrap(True);self.banner.hide()
        self.v.addWidget(self.banner)
        self.rows = QVBoxLayout();self.rows.setSpacing(6);self.v.addLayout(self.rows)
        self.v.addStretch()

    def _btn(self, text, key, kind='primary', ic=None):
        b = button(text, kind, ic);b.clicked.connect(lambda: self.action.emit(key))
        return b

    def set_tender(self, t: dict, lc: dict, ws_stage: int | None, files: int = 0, downloaded: int = 0):
        while self.rows.count():
            it = self.rows.takeAt(0);w = it.widget()
            if w:w.setParent(None);w.deleteLater()
        quality = LC.is_quality(t)
        send_dl = LC.send_deadline(t)
        d_docs, d_send, d_open = days_left(t.get('documents_deadline') or ''), days_left(send_dl), days_left(t.get('opening_date') or '')
        stage = lc['stage'];in_calls = bool(t.get('in_my_calls'))
        obtained = in_calls and stage in ('prepare', 'site') or (stage == 'missed' and str(t.get('site_state')) == LC.ST_WAIT_PACKETS)
        sent = stage == 'site' or (ws_stage or 0) >= 5
        missed_docs = stage == 'missed' and not obtained
        # timeline
        def st(d, done_cond):
            if done_cond:return 'done'
            return 'todo'
        nodes = [('انتشار', t.get('published') or '', 'done', '')]
        if missed_docs:
            nodes.append(('دریافت اسناد', t.get('documents_deadline') or '', 'missed', 'گذشته'))
        elif obtained or sent:
            nodes.append(('دریافت اسناد', t.get('documents_deadline') or '', 'done', ''))
        else:
            nodes.append(('مهلت دریافت اسناد', t.get('documents_deadline') or '', 'current', _left(d_docs)))
        send_title = 'مهلت ارسال اسناد ارزیابی' if quality else 'مهلت ارسال پیشنهاد'
        if sent:
            nodes.append(('ارسال', send_dl, 'done', ''))
        elif obtained:
            nodes.append((send_title, send_dl, 'missed' if (d_send is not None and d_send < 0) else 'current',
                          'گذشته' if (d_send is not None and d_send < 0) else _left(d_send)))
        else:
            nodes.append((send_title, send_dl, 'todo', ''))
        if not quality or t.get('opening_date'):
            nodes.append(('بازگشایی', t.get('opening_date') or '', 'done' if (d_open is not None and d_open < 0 and sent) else
                          ('current' if sent else 'todo'), _left(d_open) if sent and d_open is not None and d_open >= 0 else ''))
        self.timeline.set_nodes(nodes)
        # banner for the lost state
        if missed_docs:
            self.banner.setText(f"مهلت دریافت اسناد ({t.get('documents_deadline') or '—'}) گذشته و اسناد گرفته نشده؛ امکان شرکت نیست.")
            self.banner.show()
        elif stage == 'missed' and obtained:
            self.banner.setText(f"مهلت ارسال ({send_dl or '—'}) گذشته است.")
            self.banner.show()
        else:
            self.banner.hide()
        # steps
        cur = 1 if not in_calls else 2 if stage == 'pay' else 3 if (stage == 'prepare' and (ws_stage or 0) < 5) else 4 if stage == 'prepare' else 5
        if missed_docs:cur = 0
        steps = [
            (1, 'افزودن به «فراخوان‌های من»', 'افزوده شد' if in_calls else (f'تا {_left(d_docs)} دیگر فرصت دارید' if d_docs is not None and d_docs >= 0 else ''),
             self._btn('افزودن', 'add', 'primary', 'bookmark-plus')),
            (2, 'دریافت اسناد' if lc.get('free') else 'پرداخت و دریافت اسناد', (f'{fa_num(downloaded)} از {fa_num(files)} فایل در پوشهٔ برنامه' if files else 'اسناد گرفته شد') if obtained or sent else 'بعد از افزودن',
             self._btn('صفحهٔ پرداخت/دریافت', 'pay', 'primary', 'wallet')),
            (3, 'آماده‌سازی پیشنهاد', 'پاکت‌ها، تضمین، قیمت', self._btn('فضای کار', 'workspace', 'primary', 'clipboard-check')),
            (4, 'ارسال در سایت', 'با خودتان، در خود سایت', self._btn('نمایش مرورگر', 'site', 'primary', 'external-link')),
            (5, 'نتیجه', t.get('site_state_name') or '' if stage == 'site' else '', None),
        ]
        for num, title, sub, btn in steps:
            state = 'done' if num < cur else 'current' if num == cur else 'todo'
            btn = None          # v0.9: the one main button lives in the panel header, not in each row
            self.rows.addWidget(StepRow(num, title, sub if state != 'todo' or num == 2 else sub, state, btn))
