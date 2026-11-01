"""Reusable UI building blocks."""
from __future__ import annotations
from datetime import datetime, timezone
from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (QFrame, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QGridLayout, QWidget,
                               QSizePolicy, QGraphicsDropShadowEffect)
from PySide6.QtGui import QColor
from .icons import icon, pixmap
from .theme import C


def repolish(w):
    w.style().unpolish(w);w.style().polish(w);w.update()


def button(text, kind='default', icon_name=None, icon_color=None, tooltip=''):
    b=QPushButton(f' {text} ' if icon_name and text else text);b.setCursor(Qt.PointingHandCursor);b.setProperty('kind',kind)
    if icon_name:
        color=icon_color or {'primary':'#ffffff','danger':C['red'],'amber':C['amber'],'link':C['primary']}.get(kind,C['text2'])
        b.setIcon(icon(icon_name,color,16));b.setIconSize(QSize(16,16))
        b.setProperty('_icon',icon_name);b.setProperty('_icon_fixed',icon_color or '')
    if tooltip:b.setToolTip(tooltip)
    if kind=='chip':b.setFixedHeight(32)
    elif kind not in ('link','stage'):
        b.setFixedHeight(38)                     # one height for every normal button
        if icon_name and not text:b.setFixedWidth(38)
    return b


def shadow(w, blur=18, alpha=18, dy=2):
    eff=QGraphicsDropShadowEffect(w);eff.setBlurRadius(blur);eff.setOffset(0,dy)
    eff.setColor(QColor(15,39,68,alpha));w.setGraphicsEffect(eff)


def card(object_name='Card'):
    f=QFrame();f.setObjectName(object_name)
    return f


FA=str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹')


def fa_digits(value) -> str:
    """Display only: Latin digits → Persian digits (text otherwise untouched)."""
    return str(value if value is not None else '').translate(FA)


def fa_num(value) -> str:
    try:
        return f'{int(value or 0):,}'.translate(FA).replace(',','٬')
    except (TypeError,ValueError):
        return str(value or '')


def g2j(gy,gm,gd):
    g_d_m=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+(365*gy)+((gy2+3)//4)-((gy2+99)//100)+((gy2+399)//400)+gd+g_d_m[gm-1]
    jy=-1595+(33*(days//12053));days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:
        jy+=(days-1)//365;days=(days-1)%365
    if days<186:jm=1+days//31;jd=1+days%31
    else:jm=7+(days-186)//30;jd=1+(days-186)%30
    return jy,jm,jd


def jalali_from_iso(iso: str, with_time=True) -> str:
    """UTC ISO timestamp stored by the app -> local Jalali text."""
    if not iso:return ''
    try:
        dt=datetime.fromisoformat(iso)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        dt=dt.astimezone()
    except ValueError:
        return iso
    y,m,d=g2j(dt.year,dt.month,dt.day)
    s=f'{y}/{m:02d}/{d:02d}'+(f' — {dt:%H:%M}' if with_time else '')
    return s.translate(FA)


class StepButton(QPushButton):
    def __init__(self, number, title, hint):
        super().__init__()
        self.setObjectName('Step');self.setCursor(Qt.PointingHandCursor)
        self.number=number;self.title=title;self.hint=hint
        self.setToolTip(hint)
        self.set_state('idle')

    def set_state(self, state):
        self.setProperty('state',state)
        mark='✓' if state=='done' else str(self.number).translate(FA)
        self.setText(f'  {mark}   {self.title}')
        color={'done':C['green'],'current':C['primary']}.get(state,C['muted'])
        repolish(self)


class StatCard(QFrame):
    clicked=Signal()

    def __init__(self, label, icon_name, tint, soft, clickable=False):
        super().__init__();self.setObjectName('Stat')
        self.setProperty('clickable','true' if clickable else 'false')
        if clickable:self.setCursor(Qt.PointingHandCursor)
        lay=QHBoxLayout(self);lay.setContentsMargins(14,9,14,9);lay.setSpacing(12)
        ic=QLabel();ic.setObjectName('StatIcon');ic.setFixedSize(38,38);ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f'background:{soft};border-radius:11px;')
        ic.setPixmap(pixmap(icon_name,tint,19))
        col=QVBoxLayout();col.setSpacing(0)
        self.label=QLabel(label);self.label.setObjectName('StatLabel')
        self.value=QLabel('۰');self.value.setObjectName('StatValue')
        self.sub=QLabel('');self.sub.setObjectName('StatSub')
        col.addWidget(self.label);col.addWidget(self.value);col.addWidget(self.sub)
        lay.addWidget(ic,0,Qt.AlignTop);lay.addLayout(col,1)
        shadow(self,14,12,1)

    def set(self, value, sub=''):
        self.value.setText(value);self.sub.setText(sub or ' ')

    def mousePressEvent(self, e):
        if self.property('clickable')=='true':self.clicked.emit()
        super().mousePressEvent(e)


class Banner(QFrame):
    """Inline notification instead of blocking pop-ups."""
    ICONS={'info':('info',C['primary']),'success':('circle-check',C['green']),
           'warn':('triangle-alert',C['amber']),'error':('circle-alert',C['red'])}

    def __init__(self, parent=None, compact=False):
        super().__init__(parent);self.setObjectName('Banner');self.setProperty('kind','info')
        lay=QHBoxLayout(self);m=8 if compact else 11
        lay.setContentsMargins(12,m,10,m);lay.setSpacing(10)
        self.ic=QLabel();self.ic.setFixedSize(20,20);lay.addWidget(self.ic,0,Qt.AlignTop)
        self.text=QLabel();self.text.setWordWrap(True);self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        lay.addWidget(self.text,1)
        self.action=button('', 'link');self.action.hide();lay.addWidget(self.action,0,Qt.AlignTop)
        self.close_btn=QPushButton();self.close_btn.setProperty('kind','ghost');self.close_btn.setIcon(icon('x',C['muted'],14))
        self.close_btn.setFixedSize(26,26);self.close_btn.setCursor(Qt.PointingHandCursor);self.close_btn.clicked.connect(self.hide)
        lay.addWidget(self.close_btn,0,Qt.AlignTop)
        self._cb=None;self.action.clicked.connect(self._run)
        self._timer=QTimer(self);self._timer.setSingleShot(True);self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, kind, text, action_text='', action=None, timeout=0):
        self.setProperty('kind',kind);repolish(self)
        name,color=self.ICONS.get(kind,self.ICONS['info'])
        self.ic.setPixmap(pixmap(name,color,19))
        self.text.setText(text)
        self._cb=action
        self.action.setText(action_text);self.action.setVisible(bool(action_text and action))
        self.show()
        self._timer.stop()
        if timeout:self._timer.start(timeout)

    def _run(self):
        if self._cb:self._cb()


class FieldGrid(QWidget):
    """Label/value rows, wrapping, selectable."""
    def __init__(self):
        super().__init__()
        self.grid=QGridLayout(self);self.grid.setContentsMargins(0,0,0,0)
        self.grid.setHorizontalSpacing(14);self.grid.setVerticalSpacing(9)
        self.grid.setColumnStretch(1,1)

    def set_rows(self, rows):
        while self.grid.count():
            it=self.grid.takeAt(0)
            wd=it.widget()
            if wd:
                wd.setParent(None);wd.deleteLater()
        for i,(label,value) in enumerate(rows):
            l=QLabel(label);l.setObjectName('FieldLabel');l.setMinimumWidth(110);l.setAlignment(Qt.AlignLeading|Qt.AlignTop)
            v=QLabel(str(value));v.setObjectName('FieldValue');v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(l,i,0);self.grid.addWidget(v,i,1)


class Section(QFrame):
    def __init__(self, title, icon_name=None):
        super().__init__();self.setObjectName('Section')
        lay=QVBoxLayout(self);lay.setContentsMargins(14,12,14,13);lay.setSpacing(10)
        head=QHBoxLayout();head.setSpacing(7)
        if icon_name:
            ic=QLabel();ic.setPixmap(pixmap(icon_name,C['muted'],15));head.addWidget(ic)
        t=QLabel(title);t.setObjectName('SectionTitle');head.addWidget(t);head.addStretch()
        self.head=head
        lay.addLayout(head)
        self.body=QVBoxLayout();self.body.setSpacing(8);lay.addLayout(self.body)


class EmptyState(QWidget):
    def __init__(self, icon_name, title, text):
        super().__init__()
        lay=QVBoxLayout(self);lay.setAlignment(Qt.AlignCenter);lay.setSpacing(8)
        ic=QLabel();ic.setAlignment(Qt.AlignCenter)
        ic.setFixedSize(64,64);ic.setStyleSheet(f'background:{C["primary_soft"]};border-radius:32px;')
        ic.setPixmap(pixmap(icon_name,C['primary'],28))
        box=QHBoxLayout();box.addStretch();box.addWidget(ic);box.addStretch();lay.addLayout(box)
        self.title=QLabel(title);self.title.setAlignment(Qt.AlignCenter);self.title.setObjectName('CardTitle')
        self.text=QLabel(text);self.text.setAlignment(Qt.AlignCenter);self.text.setObjectName('Muted');self.text.setWordWrap(True)
        lay.addWidget(self.title);lay.addWidget(self.text)
        self.actions=QHBoxLayout();self.actions.setAlignment(Qt.AlignCenter);lay.addLayout(self.actions)


class InfoTable(QFrame):
    """Neat bordered label/value table: two label-value pairs per row; long values take a full row."""
    SHORT = 24

    def __init__(self, single=False):
        super().__init__();self.setObjectName('InfoTable');self.single = single
        self.grid = QGridLayout(self);self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.grid.setColumnStretch(1, 1);self.grid.setColumnStretch(3, 1)
        self.grid.setColumnMinimumWidth(0, 118);self.grid.setColumnMinimumWidth(2, 118)

    def _cell(self, text, kind):
        l = QLabel(str(text));l.setObjectName(kind);l.setWordWrap(True)
        if kind == 'InfoValue':
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        else:
            l.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        l.setContentsMargins(10, 8, 10, 8);l.setMinimumHeight(34)
        l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return l

    def set_rows(self, rows):
        while self.grid.count():
            it = self.grid.takeAt(0)
            wd=it.widget()
            if wd:
                wd.setParent(None);wd.deleteLater()
        r = 0;pending = None
        for label, value in rows:
            value = str(value)
            long_ = self.single or len(value) > self.SHORT or '\n' in value or len(str(label)) > 20
            if long_:
                if pending:
                    self.grid.addWidget(self._cell(pending[0], 'InfoLabel'), r, 0)
                    self.grid.addWidget(self._cell(pending[1], 'InfoValue'), r, 1, 1, 3);r += 1;pending = None
                self.grid.addWidget(self._cell(label, 'InfoLabel'), r, 0)
                self.grid.addWidget(self._cell(value, 'InfoValue'), r, 1, 1, 3);r += 1
            elif pending is None:
                pending = (label, value)
            else:
                self.grid.addWidget(self._cell(pending[0], 'InfoLabel'), r, 0)
                self.grid.addWidget(self._cell(pending[1], 'InfoValue'), r, 1)
                self.grid.addWidget(self._cell(label, 'InfoLabel'), r, 2)
                self.grid.addWidget(self._cell(value, 'InfoValue'), r, 3);r += 1;pending = None
        if pending:
            self.grid.addWidget(self._cell(pending[0], 'InfoLabel'), r, 0)
            self.grid.addWidget(self._cell(pending[1], 'InfoValue'), r, 1, 1, 3)
        self.setVisible(bool(rows))


class StageBar(QWidget):
    """Seven clickable stage chips. states: done / current / hint / idle."""
    picked = Signal(int)

    def __init__(self, stages):
        super().__init__()
        lay = QHBoxLayout(self);lay.setContentsMargins(0, 0, 0, 0);lay.setSpacing(6)
        self.btns = []
        for i, name in enumerate(stages):
            b = QPushButton(f'{str(i + 1).translate(FA)}  {name}');b.setProperty('kind', 'stage');b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=i: self.picked.emit(k))
            lay.addWidget(b);self.btns.append(b)

    def set_stage(self, current, hint=None):
        for i, b in enumerate(self.btns):
            st = 'done' if i < current else ('current' if i == current else ('hint' if hint is not None and i == hint else 'idle'))
            b.setProperty('state', st);repolish(b)


def badge(text, color, soft):
    l = QLabel(text);l.setObjectName('Badge')
    l.setStyleSheet(f'background:{soft};color:{color};')
    return l


def recolor_icons(root):
    """Re-draw button icons after a theme switch (colors follow the current tokens)."""
    for b in root.findChildren(QPushButton):
        name=b.property('_icon')
        if not name:continue
        kind=b.property('kind') or 'default'
        color=b.property('_icon_fixed') or {'primary':'#ffffff','danger':C['red'],'amber':C['amber'],'link':C['primary']}.get(kind,C['text2'])
        try:b.setIcon(icon(name,color,16))
        except Exception:pass


from PySide6.QtWidgets import QLayout
from PySide6.QtCore import QRect, QPoint


class FlowLayout(QLayout):
    """Lays widgets out in rows and wraps to the next row when space runs out (RTL aware)."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent);self._items=[];self._sp=spacing;self.setContentsMargins(0,0,0,0)
    def addItem(self,item):self._items.append(item)
    def count(self):return len(self._items)
    def itemAt(self,i):return self._items[i] if 0<=i<len(self._items) else None
    def takeAt(self,i):return self._items.pop(i) if 0<=i<len(self._items) else None
    def expandingDirections(self):return Qt.Orientations(0)
    def hasHeightForWidth(self):return True
    def heightForWidth(self,w):return self._do(QRect(0,0,w,0),True)
    def setGeometry(self,rect):super().setGeometry(rect);self._do(rect,False)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):
        from PySide6.QtCore import QSize as _S
        s=_S()
        for it in self._items:s=s.expandedTo(it.minimumSize())
        return s
    def _do(self,rect,test):
        rtl=self.parentWidget() is not None and self.parentWidget().layoutDirection()==Qt.RightToLeft
        x=rect.x();y=rect.y();line=0
        rows=[];row=[]
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():continue
            sz=it.sizeHint()
            if row and x+sz.width()>rect.right()+1:
                rows.append(row);row=[];x=rect.x();y+=line+self._sp;line=0
            row.append((it,x,y,sz));x+=sz.width()+self._sp;line=max(line,sz.height())
        if row:rows.append(row)
        if not test:
            for r in rows:
                for it,xx,yy,sz in r:
                    if rtl:xx=rect.right()-(xx-rect.x())-sz.width()+1
                    it.setGeometry(QRect(QPoint(xx,yy),sz))
        return y+line-rect.y()


# ---------------------------------------------------------------- in-button feedback (shared by the suite)
def busy_btn(btn, text=None):
    """«در حال…» inside the button itself; done_btn() restores it with ✓ / ✕."""
    if btn is None or btn.property('_fb_text') is not None:return
    btn.setProperty('_fb_text',btn.text());btn.setProperty('state','busy')
    if text:btn.setText(text)
    repolish(btn)


def done_btn(btn, ok=True, text=None, ms=2200):
    from PySide6.QtCore import QTimer
    if btn is None:return
    orig=btn.property('_fb_text')
    if orig is None:return
    btn.setProperty('state','ok' if ok else 'err');btn.setText(('✓ ' if ok else '✕ ')+(text or orig.strip()))
    repolish(btn)
    def back():
        try:
            btn.setText(orig);btn.setProperty('state','');btn.setProperty('_fb_text',None);repolish(btn)
        except RuntimeError:pass
    QTimer.singleShot(ms,back)
