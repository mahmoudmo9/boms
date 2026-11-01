"""Persian RTL desktop frontend. No web interaction runs on the UI thread."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSettings, QUrl, QSize, QTimer, QRectF, QRect, QPoint
from PySide6.QtGui import QColor, QDesktopServices, QFont, QAction, QShortcut, QKeySequence, QPainter, QFontMetrics, QPen, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QTableView, QHeaderView, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QMessageBox, QProgressBar, QFrame, QCheckBox, QStatusBar, QAbstractItemView, QScrollArea, QMenu,
    QStackedWidget, QSizePolicy, QPlainTextEdit, QDialog, QPushButton, QToolButton, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem)
from .compact_box import CompactBox
try:
    from multipick import MultiCombo
except ImportError:  # standalone tender app
    from inquiries.multipick import MultiCombo
from . import __version__
from .db import Database
from .paths import app_data_dir
from .worker import Worker
from .parsers import raw_fields, FIELD_LABELS, site_title, group_pairs, technical_fields
from .dates import days_left as _days_left
from . import lifecycle as LC
from .icons import icon, pixmap
from .theme import C, make_qss
from .widgets import (FlowLayout, busy_btn, done_btn, button, card, shadow, StepButton, StatCard, Banner, FieldGrid, Section, EmptyState,
                      fa_num, fa_digits, jalali_from_iso, repolish, InfoTable)
from .dialogs import DuplicatesDialog, SyncReportDialog, SettingsDialog
from .workspace_ui import WorkspaceDialog, CompanyDocsDialog
from .steps_ui import StepsPanel

# (key, tender field used to look up the site's own Persian title)  — titles come from the site grid headers
COLUMNS=[
 ('selected',''),('star',''),('row',''),('number','number'),('title','title'),('days_left',''),('stage_label',''),('organization','organization'),('price_text','price'),
 ('province','province'),('city','city'),('type_name','type_name'),('published','published'),
 ('documents_deadline','documents_deadline'),('inquiry_deadline',''),('proposal_deadline','proposal_deadline'),
 ('docs',''),('in_my_calls','')]
FIXED_TITLES={'row':'ردیف','days_left':'مهلت مؤثر','stage_label':'وضعیت','star':'★','inquiry_deadline':'مهلت ارزیابی کیفی','docs':'اسناد','in_my_calls':'فراخوان‌های من'}
CENTER={'row','star','stage_label','inquiry_deadline','number','province','city','type_name','days_left','published','documents_deadline','proposal_deadline','price_text','docs','in_my_calls'}
SORT_ROLE=Qt.UserRole+5
ALL='همه'


class TenderModel(QAbstractTableModel):
    """v0.9.12: `all` = every tender (classified once at load); `rows` = only the CURRENT PAGE shown in the table.
    Filtering, sorting and paging happen in MainWindow with plain Python, so Qt never walks thousands of rows."""
    def __init__(self,db):
        super().__init__();self.db=db;self.rows=[];self.all=[];self.offset=0;self.ui=None;self.status_map={}
        self.bold=QFont();self.bold.setWeight(QFont.DemiBold)
        self.titles={}

    def load(self):
        rows=self.db.list_tenders()
        self.status_map=self.db.meta('status_map') or {}
        self.titles=self.db.meta('column_labels') or {}
        for r in rows:
            st=LC.classify(r,self.status_map)
            if r.get('waived'):st=dict(st,actionable=False,label='صرف‌نظرشده')
            r['lc']=st;r['days_left']=st['days'];r['stage_label']=st['label']
            try:r['price_num']=float(r.get('price')) if r.get('price') not in (None,'') else None
            except ValueError:r['price_num']=None
            pn=r['price_num']
            r['price_text']='' if pn is None else ('رایگان' if pn==0 else fa_num(int(pn))+' ریال')
        for i,r in enumerate(rows):r['_pos']=i      # v0.9.16: position in the full list (the «ردیف» column and its sort)
        self.all=rows

    def set_page(self,rows,offset=0):
        self.beginResetModel();self.rows=list(rows);self.offset=offset;self.endResetModel()

    def refresh_page(self):
        if self.rows:self.dataChanged.emit(self.index(0,0),self.index(len(self.rows)-1,len(COLUMNS)-1))

    def sort(self,column,order=Qt.AscendingOrder):
        if self.ui is not None:self.ui._sort_changed(column,order)

    @staticmethod
    def days_text(n):
        if n is None:return ''
        if n<0:return 'پایان‌یافته'
        if n==0:return 'امروز'
        return fa_num(n)+' روز'

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if orientation==Qt.Horizontal and role==Qt.DisplayRole:
            key,field=COLUMNS[section]
            return FIXED_TITLES.get(key) or site_title(field,self.titles) if key!='selected' else ''
        if orientation==Qt.Horizontal and role==Qt.TextAlignmentRole:return int(Qt.AlignCenter)
        return None

    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or index.row()>=len(self.rows):return None
        r=self.rows[index.row()];key=COLUMNS[index.column()][0]
        if key=='selected':
            if role==Qt.CheckStateRole:return Qt.Checked if r.get('selected') else Qt.Unchecked
            return None
        if role in (Qt.DisplayRole,Qt.ToolTipRole):
            if key=='in_my_calls':return '✓ ثبت‌شده' if r.get('in_my_calls') else '—'
            if key=='star':
                if role==Qt.ToolTipRole:return 'برداشتن ستاره' if r.get('starred') else 'ستاره‌دار کردن (فقط در برنامه)'
                return '★' if r.get('starred') else '☆'
            if key=='row':return fa_digits(str(self.offset+index.row()+1))
            if key=='stage_label':return r.get('stage_label') or '—'
            if key=='title':
                ed=str(r.get('edition_no') or '').strip()
                t=str(r.get('title') or '')
                if ed and ed not in ('0',''):
                    tag=f'اصلاحیه {fa_num(ed)}'
                    return f'[{tag}]  {t}' if role==Qt.DisplayRole else f'{t}\n{tag} — {r.get("last_edition_date") or ""}'
                return t
            if key=='days_left':
                lc=r.get('lc') or {}
                n=r.get('days_left')
                if n is None or n<0:return ''
                kind=LC.deadline_kind_text(lc.get('kind',''),lc.get('stage',''))
                txt=self.days_text(n)
                if role==Qt.ToolTipRole:return f'{kind}: {lc.get("date","")}'
                return f'● {txt} · {"اسناد" if lc.get("kind")=="docs" else "ارسال"}'
            if key=='price_text':return r.get('price_text') or '—'
            if key=='docs':
                n=r.get('file_count') or 0;d=r.get('downloaded_count') or 0
                return '' if not d else 'کامل' if d>=n else f'ناقص {fa_num(d)} از {fa_num(n)}'
            return fa_digits(r.get(key) or '')
        if role==Qt.TextAlignmentRole:
            return int(Qt.AlignCenter) if key in CENTER else int(Qt.AlignLeading|Qt.AlignVCenter)
        if role==Qt.ForegroundRole:
            if key=='number':return QColor(C['primary'])
            if key=='row':return QColor(C['muted'])
            if key=='star':return QColor(C['amber'] if r.get('starred') else C['faint'])
            if key=='stage_label':
                stg=(r.get('lc') or {}).get('stage')
                return QColor({'pay':C['amber'],'prepare':C['primary'],'missed':C['faint'],'browse':C['muted'] if 'muted' in C else C['faint'],
                               'site':C['teal']}.get(stg,C['faint']))
            if key=='in_my_calls' and r.get('in_my_calls'):return QColor(C['green'])
            if key=='docs':return QColor(C['green'] if (r.get('downloaded_count') or 0)>=(r.get('file_count') or 0) else C['amber'])
            if key=='in_my_calls':return QColor(C['faint'])
            if key=='days_left':
                n=r.get('days_left')
                if n is None or n<0:return QColor(C['faint'])
                return QColor(C['red'] if n<=3 else (C['amber'] if n<=7 else C['green']))
            if key=='price_text':
                pn=r.get('price_num')
                if pn is None:return QColor(C['faint'])
                return QColor(C['green'] if pn==0 else C['amber'])
        if role==Qt.FontRole and key in ('number','title','days_left'):return self.bold
        if role==SORT_ROLE:return sort_value(r,key)
        if role==Qt.UserRole:return r.get(key)
        if role==ROW_ROLE:return r
        return None

    def flags(self,index):
        if not index.isValid():return Qt.NoItemFlags
        base=Qt.ItemIsEnabled|Qt.ItemIsSelectable
        if index.column()==0:base|=Qt.ItemIsUserCheckable
        return base

    def setData(self,index,value,role=Qt.EditRole):
        if not index.isValid() or index.column()!=0 or role!=Qt.CheckStateRole:return False
        row=self.rows[index.row()];checked=int(getattr(value,'value',value))==2
        self.db.select_many([row['id']],checked)
        row['selected']=1 if checked else 0
        self.dataChanged.emit(index,index,[Qt.CheckStateRole]);return True

    def check_ids(self,ids,checked):
        if not ids:return
        ids=set(ids);self.db.select_many(ids,checked)
        for row in self.all:                       # every tender, not only the current page
            if row['id'] in ids:row['selected']=int(checked)
        if self.rows:self.dataChanged.emit(self.index(0,0),self.index(len(self.rows)-1,0),[Qt.CheckStateRole])


_SEARCH_TR=str.maketrans('۰۱۲۳۴۵۶۷۸۹يك','0123456789یک')


def sort_value(r,key):
    """Sort key of one row for one column (what SORT_ROLE used to answer for the proxy), cached in the row."""
    c=r.setdefault('_sk',{})
    if key in c:return c[key]
    if key=='days_left':v=r['days_left'] if r.get('days_left') is not None else 10**6
    elif key=='price_text':v=r['price_num'] if r.get('price_num') is not None else -1
    elif key=='docs':
        _d=r.get('downloaded_count') or 0;_n=r.get('file_count') or 0;v=0 if not _d else (2 if _d>=_n else 1)
    elif key=='in_my_calls':v=int(bool(r.get('in_my_calls')))
    elif key=='star':v=int(bool(r.get('starred')))
    elif key=='row':v=r.get('_pos',0)
    elif key in ('published','documents_deadline','proposal_deadline','inquiry_deadline'):
        from .dates import parse_jalali
        d=parse_jalali(r.get(key) or '');v=d.isoformat()+str(r.get(key) or '')[-5:] if d else '9999'
    else:v=str(r.get(key) or '')
    if key not in ('selected','star'):c[key]=v      # selection and star change while the app runs
    return v


DEFAULT_HIDDEN={'row','price_text','in_my_calls','organization','province','city','type_name','published','documents_deadline','inquiry_deadline','proposal_deadline','docs'}
ROW_ROLE=Qt.UserRole+9


class RowDelegate(QStyledItemDelegate):
    """Two-line title, deadline chip + second date, and the site-status pill (v0.8 list design)."""
    def __init__(self,parent=None):
        super().__init__(parent)

    def paint(self,painter,option,index):
        key=COLUMNS[index.column()][0]
        if key=='star':
            o=QStyleOptionViewItem(option);self.initStyleOption(o,index);txt=o.text;o.text=''
            o.widget.style().drawControl(QStyle.CE_ItemViewItem,o,painter,o.widget)
            painter.save();painter.setPen(QColor('#F79009' if txt=='★' else C['faint']));painter.setFont(o.font)
            painter.drawText(option.rect,Qt.AlignCenter,txt);painter.restore();return
        if key=='number':
            o=QStyleOptionViewItem(option);self.initStyleOption(o,index);txt=o.text;o.text=''
            o.widget.style().drawControl(QStyle.CE_ItemViewItem,o,painter,o.widget)
            painter.save();painter.setPen(QColor(C['primary']));painter.setFont(o.font)
            painter.drawText(option.rect,Qt.AlignCenter,txt);painter.restore();return
        if key not in ('title','days_left','stage_label','docs'):
            return super().paint(painter,option,index)
        r=index.data(ROW_ROLE) or {}
        opt=QStyleOptionViewItem(option);self.initStyleOption(opt,index);opt.text=''
        opt.widget.style().drawControl(QStyle.CE_ItemViewItem,opt,painter,opt.widget)
        painter.save();painter.setRenderHint(QPainter.Antialiasing)
        rect=option.rect.adjusted(10,6,-10,-6)
        f=QFont(option.font);small=QFont(f);small.setPointSizeF(max(7.5,f.pointSizeF()-1.4))
        bold=QFont(f);bold.setWeight(QFont.DemiBold)
        faded=(r.get('lc') or {}).get('stage')=='missed' or r.get('waived')
        if key=='title':
            title=str(r.get('title') or '');ed=str(r.get('edition_no') or '').strip()
            sub=' • '.join(x for x in (r.get('organization'),r.get('province')) if x)
            top=QRect(rect.left(),rect.top(),rect.width(),rect.height()//2)
            painter.setFont(bold);painter.setPen(QColor(C['faint'] if faded else C['text']))
            painter.drawText(top,Qt.AlignLeading|Qt.AlignVCenter,QFontMetrics(bold).elidedText(fa_digits(title),Qt.ElideRight,top.width()))
            bot=QRect(rect.left(),rect.top()+rect.height()//2,rect.width(),rect.height()//2)
            right=bot.right()
            if ed and ed!='0':
                tag=f'اصلاحیه {fa_num(ed)}';painter.setFont(small)
                tw=QFontMetrics(small).horizontalAdvance(tag)+14
                chip=QRectF(right-tw,bot.center().y()-9,tw,18)
                painter.setPen(Qt.NoPen);painter.setBrush(QColor(C['violet_soft']));painter.drawRoundedRect(chip,6,6)
                painter.setPen(QColor(C['violet']));painter.drawText(chip,Qt.AlignCenter,tag)
                right-=tw+8
            painter.setFont(small);painter.setPen(QColor(C['muted']))
            area=QRect(bot.left(),bot.top(),right-bot.left(),bot.height())
            painter.drawText(area,Qt.AlignLeading|Qt.AlignVCenter,QFontMetrics(small).elidedText(fa_digits(sub),Qt.ElideRight,area.width()))
        elif key=='days_left':
            lc=r.get('lc') or {};n=lc.get('days')
            if lc.get('stage')=='missed' or n is None or n<0:
                text='اسناد گذشته' if lc.get('kind')!='send' or lc.get('stage')=='missed' and not r.get('in_my_calls') else 'مهلت گذشته'
                if lc.get('stage') not in ('missed',) and n is None:text=''
                fg,bg=C['muted'],C['track']
            else:
                kind='اسناد' if lc.get('kind')=='docs' else 'ارسال'
                text=f"{kind} {'امروز' if n==0 else fa_num(n)+' روز'}"
                fg,bg=(C['red'],C['red_soft']) if n<=2 else (C['amber'],C['amber_soft']) if n<=7 else (C['green'],C['green_soft'])
            top=QRect(rect.left(),rect.top(),rect.width(),rect.height()//2)
            if text:
                painter.setFont(bold);tw=QFontMetrics(bold).horizontalAdvance(text)+16
                chip=QRectF(top.right()-tw,top.center().y()-10,tw,20)
                painter.setPen(Qt.NoPen);painter.setBrush(QColor(bg));painter.drawRoundedRect(chip,7,7)
                painter.setPen(QColor(fg));painter.drawText(chip,Qt.AlignCenter,text)
            # second line: the next date that matters
            if lc.get('kind')=='docs' or not r.get('in_my_calls'):
                second=('پیشنهاد ' if not LC.is_quality(r) else 'ارسال ')+str(LC.send_deadline(r) or '')
            else:
                second=('بازگشایی '+str(r.get('opening_date'))) if r.get('opening_date') else ''
            bot=QRect(rect.left(),rect.top()+rect.height()//2,rect.width(),rect.height()//2)
            painter.setFont(small);painter.setPen(QColor(C['faint']))
            painter.drawText(bot,Qt.AlignLeading|Qt.AlignVCenter,fa_digits(second.strip()))
        elif key=='docs':
            n=r.get('file_count') or 0;d=r.get('downloaded_count') or 0
            if d and d>=n:
                painter.setFont(bold);tw=QFontMetrics(bold).horizontalAdvance('کامل')+18
                chip=QRectF(option.rect.center().x()-tw/2,option.rect.center().y()-11,tw,22)
                painter.setPen(Qt.NoPen);painter.setBrush(QColor(C['green_soft']));painter.drawRoundedRect(chip,7,7)
                painter.setPen(QColor(C['green']));painter.drawText(chip,Qt.AlignCenter,'کامل')
            elif d:
                painter.setFont(bold);tw=QFontMetrics(bold).horizontalAdvance('ناقص')+18
                chip=QRectF(option.rect.center().x()-tw/2,option.rect.center().y()-19,tw,20)
                painter.setPen(Qt.NoPen);painter.setBrush(QColor(C['amber_soft']));painter.drawRoundedRect(chip,7,7)
                painter.setPen(QColor(C['amber']));painter.drawText(chip,Qt.AlignCenter,'ناقص')
                painter.setFont(small);painter.setPen(QColor(C['muted']))
                painter.drawText(QRectF(option.rect.left(),option.rect.center().y()+3,option.rect.width(),16),Qt.AlignCenter,f'{fa_num(d)} از {fa_num(n)}')
        else:   # site status pill
            lc=r.get('lc') or {}
            text,tone={'browse':('افزوده‌نشده','browse'),'pay':('پرداخت لازم','pay'),'prepare':('منتظر ارسال پاکت','prepare'),
                       'missed':('از دست رفته','missed')}.get(lc.get('stage'),(lc.get('label') or '','site'))
            if lc.get('stage')=='pay' and lc.get('free'):text='دریافت اسناد'     # v0.9.2: free docs need no payment
            if r.get('waived'):text,tone='صرف‌نظرشده','missed'
            fg,bg,dashed={'browse':(C['muted'],C['card'],True),'pay':(C['amber'],C['amber_soft'],False),
                          'prepare':(C['primary'],C['primary_soft'],False),'missed':(C['faint'],C['track'],False),
                          'site':(C['teal'],C['teal_soft'],False)}[tone]
            painter.setFont(small if tone!='pay' else bold)
            fm=QFontMetrics(painter.font());text=fm.elidedText(text,Qt.ElideRight,rect.width()-10)
            tw=fm.horizontalAdvance(text)+20
            chip=QRectF(rect.center().x()-tw/2,rect.center().y()-12,tw,24)
            if dashed:
                pen=QPen(QColor(C['border2']));pen.setStyle(Qt.DashLine);painter.setPen(pen);painter.setBrush(Qt.NoBrush)
            else:
                painter.setPen(Qt.NoPen);painter.setBrush(QColor(bg))
            painter.drawRoundedRect(chip,7,7)
            painter.setPen(QColor(fg));painter.drawText(chip,Qt.AlignCenter,text)
        painter.restore()


class TenderFilter:
    """The list filters (was a QSortFilterProxyModel: Qt called Python for every row on every change)."""
    def __init__(self):
        self.search='';self.province=ALL;self.org=frozenset();self.type=ALL
        self.only_selected=False;self.only_docs=False;self.only_dl=False;self.ids=None
        self.only_open=False;self.soon=False;self.price_mode=None;self.only_mycalls=False
        self.actionable=False;self.starred=False

    def accepts(self,r):
        if self.ids is not None and r['id'] not in self.ids:return False
        if self.province!=ALL and r['province']!=self.province:return False
        if self.org and r['organization'] not in self.org:return False
        if self.type!=ALL and r['type_name']!=self.type:return False
        if self.only_selected and not r['selected']:return False
        if self.only_docs and not r.get('file_count'):return False
        if self.only_dl and not r.get('downloaded_count'):return False
        if self.only_mycalls and not r.get('in_my_calls'):return False
        n=r.get('days_left')
        if self.actionable and not (r.get('lc') or {}).get('actionable'):return False
        if self.starred and not r.get('starred'):return False
        if self.only_open and (n is None or n<0):return False
        if self.soon and (n is None or n<0 or n>7):return False
        pn=r.get('price_num')
        if self.price_mode=='free' and pn!=0:return False
        if self.price_mode=='paid' and not (pn and pn>0):return False
        if self.search:
            hay=r.get('_hay')
            if hay is None:        # built on first use: only a search needs it
                hay=r['_hay']=' '.join(str(r.get(k) or '') for k in ('number','title','organization','province','city','category','description')).casefold().translate(_SEARCH_TR)
            for needle in self.search.casefold().translate(_SEARCH_TR).split():
                if needle not in hay:return False
        return True

    def set_filter(self,**kwargs):
        for k,v in kwargs.items():setattr(self,k,v)


class MainWindow(QMainWindow):
    def __init__(self,embedded=False):
        super().__init__()
        self.embedded=embedded
        self.setWindowTitle(f'مدیریت مناقصات ستاد ایران — نسخه {__version__}')
        self.resize(1560,920);self.setMinimumSize(1180,760)
        self.setLayoutDirection(Qt.RightToLeft)
        self.base=app_data_dir()
        self.db=Database(self.base/'tenders.sqlite3')
        self.model=TenderModel(self.db);self.model.ui=self;self.flt=TenderFilter()
        self.visible=[];self.page=0;self.page_size=200;self._sort=(-1,Qt.AscendingOrder);self._ready=False
        _ps=QSettings('SetadSuite','tenders').value('page_size',200,type=int)
        if _ps in (100,200,500,1000):self.page_size=_ps
        self.worker=Worker(self.base)
        self.worker.message.connect(self.set_message)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.handle_result)
        _submit=self.worker.submit
        def _submit_fb(cmd,**kw):
            self._fb_start(cmd);return _submit(cmd,**kw)
        self.worker.submit=_submit_fb
        self.worker.failed.connect(self.handle_error)
        self.worker.busy.connect(self.on_busy)
        self.worker.start()
        self.online=False;self.browser_open=False;self.active_id=None;self.running=set();self._auto_dl=set()
        self.settings=QSettings('Blue Alvand Industry','Setad Tender Manager')
        self.download_path=Path(self.settings.value('download_path',str(Path.home()/'Documents'/'Setad-Tenders')))
        if embedded:self.setStyleSheet(make_qss())
        else:QApplication.instance().setStyleSheet(make_qss())
        self._build()
        self._ready=True
        self.refresh()
        self._update_steps()
        QShortcut(QKeySequence('Ctrl+K'),self,activated=lambda:(self.search.setFocus(),self.search.selectAll()))
        QShortcut(QKeySequence('F5'),self,activated=self.refresh)
        QShortcut(QKeySequence('Ctrl+L'),self,activated=self.connect_site)

    # ================================================================ layout
    def _build(self):
        root=QWidget();root.setObjectName('Root');self.setCentralWidget(root)
        outer=QVBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        self.header_frame=self._header();outer.addWidget(self.header_frame)
        if self.embedded:self.header_frame.hide()
        body=QWidget();bl=QVBoxLayout(body);bl.setContentsMargins(20,14,20,10);bl.setSpacing(10 if self.embedded else 11)
        th=QHBoxLayout();th.setSpacing(10)
        self.page_title=QLabel('فراخوان‌های مناقصه');self.page_title.setObjectName('PageTitle')
        self.page_count=QLabel('');self.page_count.setObjectName('Muted')
        th.addWidget(self.page_title);th.addWidget(self.page_count);th.addStretch()
        bl.addLayout(th)
        if self.embedded:self._toolbar(th)          # v0.9: same single row as the purchase page (title + buttons)
        else:bl.addLayout(self._toolbar())
        self.banner=Banner();bl.addWidget(self.banner)
        self.stats_row=QWidget();self.stats_row.setLayout(self._stats());self.stats_row.hide()
        bl.addWidget(self.stats_row)
        self.kpi=None
        if self.embedded:
            try:
                from suite.kpi import KpiStrip
                self.kpi=KpiStrip(['کل فراخوان‌ها','قابل‌اقدام','مهلت نزدیک','در فراخوان‌های من']);bl.addWidget(self.kpi)
            except Exception:self.kpi=None
        prog=QHBoxLayout();prog.setSpacing(10)
        self.progress_label=QLabel('');self.progress_label.setObjectName('Muted')
        self.progress=QProgressBar();self.progress.setTextVisible(False);self.progress.setRange(0,100)
        prog.addWidget(self.progress_label);prog.addWidget(self.progress,1)
        self.progress_row=QWidget();self.progress_row.setLayout(prog);self.progress_row.hide()
        bl.addWidget(self.progress_row)
        split=QSplitter(Qt.Horizontal);split.setChildrenCollapsible(False);split.setHandleWidth(14)
        split.addWidget(self._list_card());split.addWidget(self._detail_card())
        split.setStretchFactor(0,3);split.setStretchFactor(1,2);split.setSizes([980,560])
        if self.embedded:split.setContentsMargins(0,1,0,0)     # v0.9.13: title→tiles 10 px, tiles→cards 11 px, as in the purchase page
        bl.addWidget(split,1)
        outer.addWidget(body,1)
        sb=QStatusBar();self.setStatusBar(sb)
        self.status_text=QLabel('آماده — داده‌های ذخیره‌شده بدون اتصال هم قابل مشاهده‌اند.');sb.addWidget(self.status_text,1)
        self.db_label=QLabel(str(self.base));self.db_label.hide()
        if self.embedded:    # v0.9.13: same size/look as the purchase page's status bar (margins 14/2/14/4, 38 px ghost button)
            sb.setSizeGripEnabled(False);sb.setContentsMargins(14,2,14,4)
            self.btn_log=button('گزارش عملیات','ghost','file-text',icon_color=C['primary'],tooltip='آخرین عملیات و نتیجهٔ آن‌ها')
            self.btn_log.setObjectName('PrimGhost')
        else:
            self.btn_log=button('گزارش عملیات','link','file-text',tooltip='آخرین عملیات و نتیجهٔ آن‌ها')
        self.btn_log.clicked.connect(self.show_actions_log);sb.addPermanentWidget(self.btn_log)

    def _header(self):
        h=QFrame();h.setObjectName('Header');h.setFixedHeight(68)
        lay=QHBoxLayout(h);lay.setContentsMargins(22,10,22,10);lay.setSpacing(14)
        logo=QLabel('س');logo.setObjectName('Logo');logo.setFixedSize(42,42);logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        col=QVBoxLayout();col.setSpacing(0)
        t=QLabel('مدیریت مناقصات ستاد ایران');t.setObjectName('AppTitle')
        s=QLabel('فراخوان‌های etend.setadiran.ir  •  جست‌وجو، جزئیات و دریافت اسناد');s.setObjectName('AppSubtitle')
        col.addWidget(t);col.addWidget(s);lay.addLayout(col);lay.addStretch()
        self.pill=QLabel();self.pill.setObjectName('Pill');lay.addWidget(self.pill)
        v=QLabel('نسخه '+__version__);v.setObjectName('Version');lay.addWidget(v)
        self._set_pill('off','●  مرورگر بسته است')
        return h

    def _toolbar(self,row=None):
        row=row if row is not None else QHBoxLayout()
        row.setSpacing(10)
        self.b_connect=QPushButton('  اتصال به ستاد');self.b_connect.setObjectName('Connect');self.b_connect.setCursor(Qt.PointingHandCursor)
        self.b_connect.setIcon(icon('plug-zap','#ffffff',20));self.b_connect.setIconSize(QSize(20,20))
        self.b_connect.setToolTip('مرورگر اختصاصی را باز می‌کند، ورود شما را تشخیص می‌دهد، «فراخوان‌ها» را باز و بررسی می‌کند و مرورگر را کوچک می‌کند.')
        self.b_connect.clicked.connect(self.connect_site)
        self.b_sync=button('دریافت همه فراخوان‌ها','primary','cloud-download',tooltip='دریافت کل فهرست فراخوان‌های سایت در دیتابیس محلی')
        self.b_sync.clicked.connect(self.start_sync)
        self.b_mycalls=button('همگام‌سازی فراخوان‌های من','default','refresh-cw',tooltip='نشان «در فراخوان‌های من» را از فهرست خود سایت به‌روز می‌کند')
        self.b_mycalls.clicked.connect(lambda:self._run('my_calls'))
        self.b_showbrowser=button('نمایش مرورگر','ghost','external-link');self.b_showbrowser.clicked.connect(lambda:self._run('show_browser'))
        self.b_stop=button('توقف','danger','square');self.b_stop.clicked.connect(self.worker.cancel);self.b_stop.hide()
        if self.embedded:
            for w in (self.b_connect,self.b_showbrowser):row.addWidget(w);w.hide()    # the single «اتصال به ستاد» lives in the app header
            for w in (self.b_sync,self.b_mycalls,self.b_stop):row.addWidget(w)
        else:
            for w in (self.b_connect,self.b_sync,self.b_mycalls,self.b_showbrowser,self.b_stop):row.addWidget(w)
            row.addStretch()
        self.b_dups=button('تکراری‌ها','ghost','files',tooltip='فهرست شناسه‌های تکراری و بازیابی‌شده آخرین دریافت‌ها')
        self.b_dups.clicked.connect(self.open_duplicates)
        self.b_export=button('خروجی Excel','default','file-spreadsheet','#1d7a46',tooltip='خروجی ردیف‌های فیلترشده (CSV قابل باز شدن در Excel)')
        self.b_export.clicked.connect(lambda:self.export())
        self.b_folder=button('پوشه اسناد','ghost','folder-open');self.b_folder.clicked.connect(self.open_download_folder)
        self.b_company=button('مدارک شرکت','ghost','building-2',tooltip='کتابخانه مدارک تکراری شرکت با تاریخ انقضا');self.b_company.clicked.connect(self.open_company_docs)
        self.b_more=button('بیشتر','ghost','info')
        menu=QMenu(self)
        menu.addAction(icon('settings',C['text2']),'تنظیمات…',self.open_settings)
        menu.addAction(icon('plug-zap',C['text2']),'بررسی دوباره اتصال',lambda:self._run('check'))
        menu.addAction(icon('folder'),'تغییر محل ذخیره اسناد…',self.choose_folder)
        self.act_record=menu.addAction(icon('scan-search'),'ضبط روند دریافت اسناد در سایت…',self.toggle_recording)
        menu.addAction(icon('bug'),'ذخیره گزارش عیب‌یابی اتصال',lambda:self._run('diagnose',version=__version__))
        menu.addAction(icon('inbox'),'باز کردن پوشه داده‌های برنامه',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.base))))
        self.b_more.setMenu(menu)
        if self.embedded:
            # v0.9.1: two work buttons + Excel + «⋯» (duplicates); settings / recording / diagnostics live in the app header
            self.b_dots=button('','default','ellipsis',tooltip='بیشتر');self.b_dots.setFixedWidth(38)
            self.b_dots.clicked.connect(self._dots_menu)
            for b in (self.b_export,self.b_dots):row.addWidget(b)
            for b in (self.b_sync,self.b_mycalls,self.b_stop,self.b_export,self.b_dots):b.setFixedHeight(38)
            for b in (self.b_dups,self.b_folder,self.b_company,self.b_more):row.addWidget(b);b.hide()
        else:
            for b in (self.b_dups,self.b_export,self.b_folder,self.b_company,self.b_more):row.addWidget(b)
        return row

    def _stats(self):
        row=QHBoxLayout();row.setSpacing(12)
        self.st_total=StatCard('فراخوان‌های ذخیره‌شده','inbox',C['primary'],C['primary_soft'])
        self.st_selected=StatCard('انتخاب‌شده','square-check',C['teal'],C['teal_soft'])
        self.st_docs=StatCard('دارای فهرست اسناد','file-text','#7c3aed','#f1ebfd')
        self.st_sync=StatCard('آخرین دریافت','refresh-cw',C['green'],C['green_soft'])
        self.st_dups=StatCard('شناسه‌های تکراری','files',C['amber'],C['amber_soft'],clickable=True)
        self.st_dups.clicked.connect(self.open_duplicates)
        for w in (self.st_total,self.st_selected,self.st_docs,self.st_sync,self.st_dups):row.addWidget(w,1)
        return row

    def _list_card(self):
        c=card();shadow(c,16,12,1)
        lay=QVBoxLayout(c);lay.setContentsMargins(0,14,0,0);lay.setSpacing(10)
        if self.embedded:lay.setContentsMargins(0,12,0,0);lay.setSpacing(8)    # v0.9.13: same rhythm as the purchase card
        f=QHBoxLayout();f.setContentsMargins(*((14,0,14,0) if self.embedded else (16,0,16,0)));f.setSpacing(8)
        self.search=QLineEdit();self.search.setPlaceholderText('جست‌وجو (Ctrl+K): شماره فراخوان، عنوان، شرح، دستگاه…')
        self.search.addAction(icon('search',C['faint'],16),QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.province=QComboBox();self.org=MultiCombo('همه دستگاه‌ها','دستگاه','دستگاه‌ها',200);self.type=QComboBox()
        self.province.setMinimumWidth(130);self.org.setMinimumWidth(200);self.type.setMinimumWidth(130)
        f.addWidget(self.search,3);f.addWidget(self.province,1);f.addWidget(self.org,2);f.addWidget(self.type,1)
        lay.addLayout(f)
        f2=QHBoxLayout();f2.setContentsMargins(*((14,0,14,0) if self.embedded else (16,0,16,0)));f2.setSpacing(6)
        chip_box=QWidget();chip_flow=FlowLayout(chip_box,6);chip_box.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
        self.chips={}
        for key,label in (('actionable','قابل‌اقدام'),('soon','مهلت نزدیک (≤ ۷ روز)'),('starred','ستاره‌دار'),('free','رایگان'),('paid','پولی'),
                          ('mycalls','در فراخوان‌های من'),('selected','انتخاب‌شده'),('docs','دارای اسناد'),('downloaded','دانلودشده')):
            b=button(label,'chip');b.setCheckable(True);b.toggled.connect(lambda on,k=key:self._chip_toggled(k,on))
            self.chips[key]=b
            if self.embedded and key in ('free','paid','selected','docs','mycalls','downloaded'):b.setParent(chip_box);b.hide();continue   # live in «فیلترهای بیشتر»
            chip_flow.addWidget(b)
        self.chips['soon'].setToolTip('مهلت ۷ روز آینده یا کمتر')
        if self.embedded:
            self.b_morefilters=button('فیلترهای بیشتر','chip','filter');self.b_morefilters.clicked.connect(self._more_filters_menu)
            chip_flow.addWidget(self.b_morefilters)
        f2.addWidget(chip_box,1,Qt.AlignVCenter if self.embedded else Qt.Alignment())
        self.b_cols=button('ستون‌ها' if self.embedded else '','chip','layers',tooltip='انتخاب ستون‌های جدول')
        if not self.embedded:self.b_cols.setFixedWidth(40)
        self.b_cols.clicked.connect(lambda:self.columns_menu())
        if not self.embedded:f2.addWidget(self.b_cols,0,Qt.AlignTop)
        self.chips['actionable'].blockSignals(True)
        self.chips['actionable'].setChecked(QSettings('SetadSuite','tenders').value('chip_actionable',True,type=bool))
        self.chips['actionable'].blockSignals(False)
        f2.addSpacing(8)
        self.b_sel_all=button('انتخاب نتایج','link');self.b_sel_none=button('لغو انتخاب','link')
        if self.embedded:                               # v0.9: selection actions live in the bar that appears with a selection
            for w in (self.b_sel_all,self.b_sel_none):w.setParent(c);w.hide()
        else:
            f2.addWidget(self.b_sel_all);f2.addWidget(self.b_sel_none)
        self.id_chip=button('','amber','x');self.id_chip.hide();self.id_chip.clicked.connect(self.clear_id_filter)
        f2.addWidget(self.id_chip)
        f2.addStretch()
        self.count_label=QLabel('');self.count_label.setObjectName('Muted')
        if self.embedded:
            self.b_clear_filters=button('حذف فیلترها','ghost','filter-off',icon_color=C['primary']);self.b_clear_filters.setObjectName('PrimGhost');self.b_clear_filters.clicked.connect(self.clear_filters);f2.addWidget(self.b_clear_filters)
            f2.addWidget(self.b_cols,0,Qt.AlignVCenter)
            self.count_label.hide()
        else:f2.addWidget(self.count_label)
        lay.addLayout(f2)
        # batch bar (appears when rows are ticked)
        self.batch_bar=QFrame();self.batch_bar.setObjectName('BatchBar')
        bl=QHBoxLayout(self.batch_bar);bl.setContentsMargins(14,8,12,8);bl.setSpacing(8)
        self.batch_label=QLabel('');bl.addWidget(self.batch_label);bl.addStretch()
        for text,fn in (('انتخاب همهٔ نتایج',lambda:self.select_visible(True)),('افزودن همه به فراخوان‌های من',self.batch_favorite),('دریافت فهرست اسناد همه',self.batch_documents),
                        ('خروجی انتخاب‌شده‌ها',lambda:self.export(only_selected=True)),('لغو انتخاب',lambda:self._clear_selection())):
            b=QPushButton(text);b.setCursor(Qt.PointingHandCursor);b.clicked.connect(fn);bl.addWidget(b)
        wrap=QHBoxLayout();wrap.setContentsMargins(16,0,16,0);wrap.addWidget(self.batch_bar);lay.addLayout(wrap)
        self.batch_bar.hide()
        self.table=QTableView();self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True);self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(54);self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegate(RowDelegate(self.table))
        if self.embedded:self.table.setStyleSheet('QTableView{border:0;} QHeaderView::section{font-weight:600;border-left:0;}')   # v0.9.13: same table frame/header as the purchase page
        self.table.setShowGrid(False);self.table.setWordWrap(False)
        hh=self.table.horizontalHeader();hh.setSectionsMovable(True);hh.setHighlightSections(False)
        hh.setStretchLastSection(False);hh.setMinimumSectionSize(40)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        for i,w in enumerate([42,34,56,165,340,130,150,210,140,90,90,115,120,150,150,150,95,115]):self.table.setColumnWidth(i,w)
        hh.setSortIndicator(-1,Qt.AscendingOrder)
        hh.setSectionResizeMode(COLUMNS.index(('title','title')),QHeaderView.Stretch)
        self.table.setColumnWidth(COLUMNS.index(('days_left','')),150);self.table.setColumnWidth(COLUMNS.index(('stage_label','')),150)
        self.table.setColumnWidth(COLUMNS.index(('number','number')),160)
        hidden=QSettings('SetadSuite','tenders').value('hidden_cols',None)
        hidden=set(json.loads(hidden)) if hidden else set(DEFAULT_HIDDEN)
        for i,(k,_) in enumerate(COLUMNS):self.table.setColumnHidden(i,k in hidden)
        hh.setContextMenuPolicy(Qt.CustomContextMenu);hh.customContextMenuRequested.connect(lambda pos:self.columns_menu(hh.mapToGlobal(pos)))
        hh.setSortIndicatorShown(True)
        _st=QSettings('SetadSuite','tenders')
        _sc=_st.value('sort_col',COLUMNS.index(('days_left','')),type=int);_so=_st.value('sort_order',0,type=int)
        if _st.value('cols_ver',0,type=int)<16:      # v0.9.16: a column was inserted at index 2 → shift the saved sort column
            if _st.contains('sort_col') and _sc>=2:_sc+=1;_st.setValue('sort_col',_sc)
            _st.setValue('cols_ver',16)
        if 0<=_sc<len(COLUMNS):self.table.sortByColumn(_sc,Qt.SortOrder(_so))
        hh.sortIndicatorChanged.connect(lambda c,o:(QSettings('SetadSuite','tenders').setValue('sort_col',c),
                                                    QSettings('SetadSuite','tenders').setValue('sort_order',int(getattr(o,'value',o)))))
        self.table.selectionModel().currentRowChanged.connect(self.row_changed)
        self.table.clicked.connect(self._cell_clicked)
        self.table.doubleClicked.connect(lambda _:self.fetch_details())
        self.model.dataChanged.connect(lambda *_:self._update_batch())
        tl=QVBoxLayout();tl.setContentsMargins(0,0,0,0);tl.setSpacing(0)     # v0.9.13: table, pager and folder bar touch each other (as in the purchase card)
        lay.addLayout(tl,1)
        tl.addWidget(self.table,1)
        self.pager=self._build_pager();tl.addWidget(self.pager)
        if self.embedded:
            # v0.9.1: «پوشهٔ ذخیره» bar under the table, same anatomy as the purchase page
            sep=QFrame();sep.setFixedHeight(1);sep.setStyleSheet(f"background:{C['divider']};border:none;");tl.addWidget(sep)
            fw=QWidget();fl=QHBoxLayout(fw);fl.setContentsMargins(16,10,16,12);fl.setSpacing(8)
            fi=QLabel();fi.setPixmap(pixmap('folder',C['muted'],17));fl.addWidget(fi)
            fl_l=QLabel('پوشهٔ ذخیره:');fl_l.setObjectName('Muted');fl.addWidget(fl_l)
            self.dir_edit=QLineEdit(str(self.download_path));self.dir_edit.setReadOnly(True);self.dir_edit.setLayoutDirection(Qt.LeftToRight)
            self.dir_edit.setObjectName('DirEdit')   # v0.9.13: gray read-only field like the purchase page (style in theme.py)
            fl.addWidget(self.dir_edit,1)
            fb1=button('تغییر پوشه','default','folder-open');fb1.clicked.connect(self.choose_folder);fl.addWidget(fb1)
            fb2=button('باز کردن پوشه','default','folder');fb2.clicked.connect(self.open_download_folder);fl.addWidget(fb2)
            fb1.setFixedHeight(38);fb2.setFixedHeight(38)
            tl.addWidget(fw)
        self.search.textChanged.connect(lambda _:self._filter_timer.start(180))
        self._filter_timer=QTimer(self);self._filter_timer.setSingleShot(True);self._filter_timer.timeout.connect(self.filter_changed)
        for cb in (self.province,self.type):cb.currentTextChanged.connect(lambda _:self.filter_changed())
        self.org.selectionChanged.connect(lambda:self.filter_changed())
        self.b_sel_all.clicked.connect(lambda:self.select_visible(True))
        self.b_sel_none.clicked.connect(lambda:self.select_visible(False))
        return c

    def _fill_panel_v08(self,t):
        lc=LC.classify(t,self.db.meta('status_map') or {})
        ws=self.db.conn.execute('SELECT stage FROM workspace WHERE tender_id=?',(str(t['id']),)).fetchone()
        n=self.db.conn.execute("SELECT COUNT(*),SUM(CASE WHEN local_path<>'' THEN 1 ELSE 0 END) FROM files WHERE tender_id=?",(str(t['id']),)).fetchone()
        self.steps.set_tender(t,lc,ws[0] if ws else None,n[0] or 0,n[1] or 0)
        text={'browse':'افزوده‌نشده','pay':'پرداخت لازم','prepare':'منتظر ارسال پاکت','missed':'از دست رفته'}.get(lc['stage']) or lc['label'] or ''
        if lc['stage']=='pay' and lc.get('free'):text='دریافت اسناد'
        self.d_status.setText(text);self.d_status.setProperty('tone',lc['stage']);repolish(self.d_status);self.d_status.setVisible(bool(text))
        self.d_mycalls.hide()
        ed=str(t.get('edition_no') or '').strip()
        self.d_edition.setVisible(bool(ed) and ed!='0')
        self.d_edition.setText(f"اصلاحیه {fa_num(ed)} — {t.get('last_edition_date') or ''}".strip(' —'))
        self.b_star.setIcon(icon('star',C['amber'] if t.get('starred') else C['faint'],18))
        self.b_folder_t.setIcon(icon('folder-open',C['text2'],18));self.b_close.setIcon(icon('x',C['text2'],18))
        in_calls=bool(t.get('in_my_calls'));st=lc['stage'];ws_st=(ws[0] if ws else 0) or 0
        if st=='site' or ws_st>=5:key,text,ic,en='site','نمایش مرورگر','external-link',True
        elif not in_calls:key,text,ic,en='add','افزودن به فراخوان‌های من','bookmark-plus',st!='missed'
        elif st=='pay' and lc.get('free'):key,text,ic,en='getdocs','دریافت اسناد','download',True
        elif st=='pay':key,text,ic,en='pay','پرداخت و دریافت اسناد','wallet',True
        elif st=='missed':key,text,ic,en='workspace','از دست رفته','clock',False
        else:key,text,ic,en='workspace','آماده‌سازی پیشنهاد','clipboard-check',True
        self._main_key=key;self.b_main.setText('  '+text);self.b_main.setIcon(icon(ic,'#ffffff',18));self.b_main.setEnabled(en)
        sent=st=='site' or ws_st>=5
        if in_calls:               # one red button whose name is what it really does
            self._danger_key='remove'
            self.b_waive.setText(' حذف ');self.b_waive.setIcon(icon('trash-2',C['red'],16))
            self.b_waive.setEnabled(not sent)
            self.b_waive.setToolTip('پاکت در سایت بارگذاری/ارسال شده؛ حذف از «فراخوان‌های من» در سایت ممکن نیست.' if sent else
                                    'از «فراخوان‌های من» در سایت برداشته می‌شود. فایل‌ها و اطلاعات داخل برنامه می‌ماند.')
        else:
            self._danger_key='waive'
            self.b_waive.setText(' صرف‌نظر ');self.b_waive.setIcon(icon('x',C['red'],16));self.b_waive.setEnabled(True)
            self.b_waive.setToolTip('فقط داخل برنامه صرف‌نظر می‌شود؛ روی سایت تغییری نمی‌کند')
        self.b_waive.setProperty('_icon','trash-2' if in_calls else 'x')
        self.hist.clear()
        for h in self.db.history(t['id']):
            it=QListWidgetItem(f"{jalali_from_iso(h['at']) if h['at'] else ''}   {h['text']}")
            it.setIcon(icon('refresh-cw' if h['kind']=='site' else 'clipboard-check',C['teal'] if h['kind']=='site' else C['muted'],14))
            self.hist.addItem(it)
        if not self.hist.count():self.hist.addItem('هنوز رویدادی ثبت نشده است.')
        if self.tabs.currentIndex()<0:self.tabs.setCurrentIndex(0)

    def open_tender_folder(self):
        t=self.selected()
        if not t:return
        lp=next((f['local_path'] for f in self.db.files(t['id']) if f['local_path']),None)
        p=Path(lp).parent if lp else self.download_path
        try:                                    # climb to the tender's own folder (a direct child of the download folder)
            while p.parent!=self.download_path and p!=p.parent and self.download_path in p.parents:p=p.parent
        except Exception:pass
        if not p.exists():p=self.download_path;p.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def close_panel(self):
        self.active_id=None
        self.table.clearSelection();self.table.setCurrentIndex(self.table.model().index(-1,-1))
        self.detail_stack.setCurrentIndex(0)

    def toggle_star_current(self):
        t=self.selected()
        if not t:return
        self.db.set_star(t['id'],not t.get('starred'))
        for r in self.model.all:
            if r['id']==t['id']:r['starred']=int(not t.get('starred'))
        if self.flt.starred:self._rebuild_visible()
        else:self.model.refresh_page()
        self.show_tender(t['id'],reset_note=False)

    def _step_action(self,key):
        t=self.selected()
        if not t:return
        if key=='add':self.add_favorite()
        elif key=='pay':self.open_payment()
        elif key=='getdocs':
            if not self.online:
                self.banner.show_message('info','ابتدا «اتصال به ستاد» را بزنید.',timeout=8000)
            else:self._auto_docs(str(t['id']))
        elif key=='workspace':self.open_workspace()
        elif key=='site':self._run('show_browser')
        elif key=='remove':self.remove_favorite()
        elif key=='waive':
            self.db.set_waived([t['id']],True)
            self.note.show_message('info','در برنامه صرف‌نظر شد (روی سایت تغییری نکرد). از «کارهای من» یا فیلتر «همه» قابل دیدن است.',timeout=8000)
            self.refresh()

    def _dots_menu(self):
        m=QMenu(self);m.setLayoutDirection(Qt.RightToLeft)
        n=getattr(self,'_dup_count',0)
        m.addAction(icon('files',C['text2']),'تکراری‌ها'+(f' ({fa_num(n)})' if n else ''),self.open_duplicates)
        m.exec(self.b_dots.mapToGlobal(self.b_dots.rect().bottomRight())-QPoint(m.sizeHint().width(),0))

    def columns_menu(self,pos=None):
        m=QMenu(self);m.setLayoutDirection(Qt.RightToLeft)
        for i,(k,f) in enumerate(COLUMNS):
            if k in ('selected','title','number'):continue
            title=FIXED_TITLES.get(k) or site_title(f,self.model.titles) or k
            a=m.addAction(title);a.setCheckable(True);a.setChecked(not self.table.isColumnHidden(i))
            a.toggled.connect(lambda on,i=i:self._set_col(i,on))
        m.addSeparator();m.addAction('پیش‌فرض',self._reset_cols)
        from PySide6.QtGui import QCursor
        m.exec(pos or QCursor.pos())

    def _set_col(self,i,on):
        self.table.setColumnHidden(i,not on)
        QSettings('SetadSuite','tenders').setValue('hidden_cols',json.dumps([k for j,(k,_) in enumerate(COLUMNS) if self.table.isColumnHidden(j)]))

    def _reset_cols(self):
        for i,(k,_) in enumerate(COLUMNS):self.table.setColumnHidden(i,k in DEFAULT_HIDDEN)
        QSettings('SetadSuite','tenders').remove('hidden_cols')

    def _auto_docs(self,tid):
        """«دریافت خودکار اسناد»: read the file list, then download whatever is not in the folder yet."""
        if not self.online:return
        self._auto_dl.add(str(tid))
        t=self.db.tender(tid) or {}
        self.worker.submit('documents',id=str(tid),helper=bool(t.get('in_my_calls')) and self.settings.value('allow_helper',True,type=bool))

    def _cell_clicked(self,idx):
        if idx.isValid() and 0<=idx.row()<len(self.model.rows) and COLUMNS[idx.column()][0]=='star':
            r=self.model.rows[idx.row()];on=not r.get('starred')
            self.db.set_star(r['id'],on);r['starred']=int(on)
            self.model.dataChanged.emit(idx,idx)
            if self.flt.starred:self.filter_changed(keep_page=True)
        self.row_changed(idx,None)

    def _chip_toggled(self,key,on):
        if key=='actionable':QSettings('SetadSuite','tenders').setValue('chip_actionable',on)
        if on and key in ('free','paid'):
            other=self.chips['paid' if key=='free' else 'free']
            if other.isChecked():
                other.blockSignals(True);other.setChecked(False);other.blockSignals(False)
        self._sync_more();self.filter_changed()

    EXTRA_CHIPS=(('mycalls','در فراخوان‌های من'),('free','رایگان'),('paid','پولی'),('docs','دارای اسناد'),('downloaded','دانلودشده'),('selected','انتخاب‌شده'))

    def _sync_more(self):
        if not hasattr(self,'b_morefilters'):return
        n=sum(1 for k,_ in self.EXTRA_CHIPS if self.chips[k].isChecked())
        self.b_morefilters.setText(f'فیلترهای بیشتر ({fa_num(n)})' if n else 'فیلترهای بیشتر')
        self.b_morefilters.setProperty('active',bool(n));repolish(self.b_morefilters)

    def _more_filters_menu(self):
        m=QMenu(self);m.setLayoutDirection(Qt.RightToLeft)
        for k,t in self.EXTRA_CHIPS:
            a=m.addAction(t);a.setCheckable(True);a.setChecked(self.chips[k].isChecked())
            a.toggled.connect(lambda on,k=k:self.chips[k].setChecked(on))
        pos=self.b_morefilters.mapToGlobal(self.b_morefilters.rect().bottomRight())
        m.exec(pos-QPoint(m.sizeHint().width(),0))

    def clear_filters(self):
        for k,b in self.chips.items():
            b.blockSignals(True);b.setChecked(False);b.blockSignals(False)
        for cb in (self.province,self.type):
            cb.blockSignals(True);cb.setCurrentIndex(0);cb.blockSignals(False)
        self.org.clear_selection()
        self.search.clear()
        self.flt.set_filter(ids=None);self.id_chip.hide()
        QSettings('SetadSuite','tenders').setValue('chip_actionable',False)
        self.filter_changed()

    def _update_batch(self):
        n=sum(1 for r in self.model.all if r.get('selected'))
        self.batch_bar.setVisible(n>0)
        self.batch_label.setText(f'{fa_num(n)} فراخوان انتخاب شده')

    def _clear_selection(self):
        ids=[r['id'] for r in self.model.all if r.get('selected')]
        self.model.check_ids(ids,False);self.refresh()

    def _detail_card(self):
        c=card();shadow(c,16,12,1);c.setMinimumWidth(560)
        lay=QVBoxLayout(c);lay.setContentsMargins(0,0,0,0)
        self.detail_stack=QStackedWidget();lay.addWidget(self.detail_stack)
        empty=EmptyState('scan-search','یک ردیف را انتخاب کنید','مراحل، مشخصات و اسناد همان فراخوان اینجا دیده می‌شود.')
        self.detail_stack.addWidget(empty)
        page=QWidget();pl=QVBoxLayout(page);pl.setContentsMargins(18,16,18,14);pl.setSpacing(10)
        top=QHBoxLayout();top.setSpacing(8)
        self.d_number=QLabel();self.d_number.setObjectName('Chip');self.d_number.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.d_type=QLabel();self.d_type.setObjectName('ChipAmber')
        self.d_mycalls=QLabel('در فراخوان‌های من');self.d_mycalls.setObjectName('ChipGreen')
        self.d_status=QLabel();self.d_status.setObjectName('StatusPill')
        self.d_edition=QLabel();self.d_edition.setObjectName('StatusPill');self.d_edition.setProperty('tone','edition')
        self.b_star=QToolButton();self.b_star.setObjectName('StarBtn');self.b_star.setFixedSize(34,34);self.b_star.setCursor(Qt.PointingHandCursor)
        self.b_star.setToolTip('ستاره (فقط داخل برنامه)');self.b_star.clicked.connect(self.toggle_star_current)
        top.addWidget(self.d_number);top.addWidget(self.d_type);top.addWidget(self.d_mycalls);top.addWidget(self.d_status)
        self.b_folder_t=QToolButton();self.b_folder_t.setObjectName('StarBtn');self.b_folder_t.setFixedSize(34,34);self.b_folder_t.setCursor(Qt.PointingHandCursor)
        self.b_folder_t.setToolTip('پوشهٔ این فراخوان');self.b_folder_t.clicked.connect(self.open_tender_folder)
        self.b_close=QToolButton();self.b_close.setObjectName('StarBtn');self.b_close.setFixedSize(34,34);self.b_close.setCursor(Qt.PointingHandCursor)
        self.b_close.setToolTip('بستن پنل');self.b_close.clicked.connect(self.close_panel)
        top.addWidget(self.d_edition);top.addStretch();top.addWidget(self.b_star);top.addWidget(self.b_folder_t);top.addWidget(self.b_close)
        pl.addLayout(top)
        self.d_title=QLabel();self.d_title.setObjectName('DetailTitle');self.d_title.setWordWrap(True)
        self.d_title.setTextInteractionFlags(Qt.TextSelectableByMouse);pl.addWidget(self.d_title)
        self.d_meta=QLabel();self.d_meta.setObjectName('Muted');self.d_meta.setWordWrap(True);pl.addWidget(self.d_meta)
        acts=QHBoxLayout();acts.setSpacing(6)
        # v0.9: the same row as the purchase panel — one main button (the next step), «پرونده», refresh, «صرف‌نظر»
        self.b_main=button('آماده‌سازی پیشنهاد','primary','clipboard-check');self.b_main.clicked.connect(lambda:self._step_action(self._main_key))
        self._main_key='workspace'
        self.b_work=button('پرونده','default','folder-open',tooltip='پاکت‌ها، تضمین، استعلام و قیمت‌گذاری این مناقصه')
        self.b_details=button('','default','refresh-cw',tooltip='به‌روزرسانی جزئیات کامل این فراخوان از سامانه ستاد');self.b_details.setFixedWidth(38)
        self.b_waive=button('صرف‌نظر','danger','x',tooltip='فقط داخل برنامه صرف‌نظر می‌شود؛ روی سایت تغییری نمی‌کند')
        self.b_details.clicked.connect(self.fetch_details);self.b_work.clicked.connect(self.open_workspace)
        self._danger_key='waive'
        self.b_waive.clicked.connect(lambda:self._step_action(self._danger_key))
        # kept for the on_busy bookkeeping, never shown in the row
        self.b_docs=button('دریافت فهرست اسناد','primary','scan-search');self.b_docs.clicked.connect(self.fetch_documents)
        self.b_add=button('افزودن','amber','bookmark-plus');self.b_add.clicked.connect(self.add_favorite)
        self.b_remove=button('حذف','danger','square-x');self.b_remove.clicked.connect(self.remove_favorite)
        for b in (self.b_main,self.b_work,self.b_details,self.b_waive):
            b.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Fixed);acts.addWidget(b)
        self.b_main.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        for b in (self.b_docs,self.b_add,self.b_remove):acts.addWidget(b);b.hide()
        acts_w=QWidget();acts_w.setLayout(acts);acts.setContentsMargins(0,0,0,0);acts_w.setFixedHeight(38)
        pl.addWidget(acts_w)
        self.note=Banner(compact=True);pl.addWidget(self.note)
        self.tabs=QTabWidget();self.tabs.setDocumentMode(True);pl.addWidget(self.tabs,1)
        sc0=QScrollArea();sc0.setWidgetResizable(True);sc0.setFrameShape(QFrame.NoFrame)
        self.steps=StepsPanel();self.steps.action.connect(self._step_action);sc0.setWidget(self.steps)
        try:self.steps.setStyleSheet(make_qss())      # same local sheet as the purchase panel → numbered circles
        except Exception:pass
        try:self.tabs.setStyleSheet(make_qss())
        except Exception:pass
        self.tabs.addTab(sc0,icon('list-filter',C['muted'],15),'مراحل')
        # --- info tab
        sc=QScrollArea();sc.setWidgetResizable(True);sc.setFrameShape(QFrame.NoFrame)
        inner=QWidget();il=QVBoxLayout(inner);il.setContentsMargins(0,10,4,10);il.setSpacing(12)
        self.sec_main=Section('مشخصات فراخوان','building-2');self.f_main=InfoTable();self.sec_main.body.addWidget(self.f_main)
        self.sec_time=Section('زمان‌بندی','calendar-clock');self.f_time=InfoTable();self.sec_time.body.addWidget(self.f_time)
        self.sec_fin=Section('مالی','wallet');self.f_fin=InfoTable();self.sec_fin.body.addWidget(self.f_fin)
        self.site_box=QVBoxLayout();self.site_box.setSpacing(12)
        self.site_text=QPlainTextEdit();self.site_text.setReadOnly(True);self.site_text.setMinimumHeight(160);self.site_text.hide()
        self.site_hint=QLabel('جزئیات کامل سامانه هنوز دریافت نشده — «جزئیات کامل» را بزنید.');self.site_hint.setObjectName('Faint')
        self.sec_all=Section('سایر فیلدهای فهرست','layers')
        self.b_all_toggle=button('نمایش فیلدهای فنی','link');self.b_all_toggle.hide()  # v0.6: technical fields removed from the UI
        self.f_all=InfoTable();self.sec_all.body.addWidget(self.f_all)
        self.f_tech=InfoTable(single=True);self.f_tech.hide();self.sec_all.body.addWidget(self.f_tech)
        self.b_all_toggle.clicked.connect(self._toggle_all_fields)
        for w in (self.sec_main,self.sec_time,self.sec_fin):il.addWidget(w)
        il.addLayout(self.site_box);il.addWidget(self.site_text);il.addWidget(self.site_hint);il.addWidget(self.sec_all)
        il.addStretch();sc.setWidget(inner)
        self.tabs.addTab(sc,icon('file-text',C['muted'],15),'مشخصات')
        # --- documents tab
        docs=QWidget();dl=QVBoxLayout(docs);dl.setContentsMargins(0,10,0,0);dl.setSpacing(9)
        self.docs_info=QLabel('');self.docs_info.setObjectName('Muted');self.docs_info.setWordWrap(True);dl.addWidget(self.docs_info)
        self.docs_stack=QStackedWidget()
        self.docs_empty=EmptyState('folder-open','فهرست اسناد دریافت نشده',
            'برای دریافت اسناد، ابتدا فراخوان باید با «افزودن» در «فراخوان‌های من» ثبت شده باشد.')
        b=button('دریافت فهرست اسناد','primary','scan-search');b.clicked.connect(self.fetch_documents)
        self.docs_empty.actions.addWidget(b)
        self.docs_stack.addWidget(self.docs_empty)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['نام فایل','فرمت','حجم','وضعیت'])
        th=self.tree.header();th.setStretchLastSection(False);th.setSectionResizeMode(0,QHeaderView.Stretch)
        for i,wd in ((1,60),(2,80),(3,120)):th.setSectionResizeMode(i,QHeaderView.Fixed);self.tree.setColumnWidth(i,wd)
        self.tree.setRootIsDecorated(True);self.tree.setUniformRowHeights(True);self.tree.setAlternatingRowColors(False)
        self.tree.itemChanged.connect(self.tree_item_changed);self._tree_loading=False
        self.tree.itemDoubleClicked.connect(self._file_item_activated)
        self.docs_stack.addWidget(self.tree)
        dl.addWidget(self.docs_stack,1)
        drow=QHBoxLayout();drow.setSpacing(8)
        self.b_dl=button('دانلود انتخاب‌شده‌ها','primary','download')
        self.b_dl_all=button('انتخاب همه','link');self.b_dl_none=button('هیچ‌کدام','link')
        self.b_dl.clicked.connect(self.download_files)
        self.b_preview=button('پیش‌نمایش','default','eye',tooltip='اول یک فایل را در فهرست انتخاب کنید.');self.b_preview.setEnabled(False)   # v0.9.15: same as the purchase page
        self.b_preview.clicked.connect(self.preview_selected_file)
        self.tree.currentItemChanged.connect(lambda *_:self._sync_preview_btn())
        self.b_dl_all.clicked.connect(lambda:self.toggle_files(True));self.b_dl_none.clicked.connect(lambda:self.toggle_files(False))
        self.b_rmdl=button('حذف دانلودها','danger','trash-2',tooltip='فایل‌هایی که برنامه برای این فراخوان دانلود کرده پاک می‌شود و وضعیت به «دانلود نشده» برمی‌گردد.')   # v0.9.17
        self.b_rmdl.clicked.connect(self.delete_downloads)
        self.b_openf=button('باز کردن پوشه','default','folder-open',tooltip='پوشهٔ همین مناقصه را در ویندوز باز می‌کند (بعد از دانلود).')   # v0.9.20
        self.b_openf.clicked.connect(self.open_tender_folder)
        drow.addWidget(self.b_dl);drow.addWidget(self.b_preview);drow.addWidget(self.b_openf);drow.addStretch()
        drow2=QHBoxLayout();drow2.setSpacing(8)
        drow2.addWidget(self.b_rmdl);drow2.addStretch();drow2.addWidget(self.b_dl_all);drow2.addWidget(self.b_dl_none)
        self.b_trace=button('روش‌های امتحان‌شده','link');self.b_trace.clicked.connect(self._show_trace);self.b_trace.hide()
        if not self.embedded:drow.addWidget(self.b_trace)
        self.b_rec=button('ضبط روند سایت','link',tooltip='مراحل دریافت اسناد را یک‌بار دستی در مرورگر برنامه انجام دهید تا برنامه روند سایت را یاد بگیرد')
        self.b_rec.clicked.connect(self.toggle_recording)
        if self.embedded:self.b_rec.hide();self.b_rec.setParent(self)
        else:drow.addWidget(self.b_rec)
        dl.addLayout(drow);dl.addLayout(drow2)
        prow=QHBoxLayout();prow.setSpacing(6)
        pi=QLabel();pi.setPixmap(pixmap('folder',C['faint'],15));prow.addWidget(pi)
        self.path_label=QLabel();self.path_label.setObjectName('Faint');prow.addWidget(self.path_label,1)
        ch=button('تغییر','link');ch.clicked.connect(self.choose_folder);prow.addWidget(ch)
        dl.addLayout(prow)
        self.tabs.addTab(docs,icon('folder-open',C['muted'],15),'اسناد و دانلود')
        self.hist=QListWidget();self.hist.setObjectName('History');self.hist.setWordWrap(True)
        self.tabs.addTab(self.hist,icon('clock',C['muted'],15),'تاریخچه')
        self.detail_stack.addWidget(page)
        self._trace=[]
        return c

    # ================================================================ helpers
    def _set_pill(self,state,text):
        self.pill.setProperty('state',state);self.pill.setText(text);repolish(self.pill)

    def _run(self,cmd,**kw):
        self.worker.submit(cmd,**kw)

    def set_message(self,text):
        self.status_text.setText(text)
        if self.progress_row.isVisible():self.progress_label.setText(text[:120])

    def _update_steps(self):
        connecting='connect' in self.running
        if connecting:
            state,text='wait','  در حال اتصال… (برای توقف کلیک کنید)'
        elif self.online:
            state,text='on','  متصل به ستاد ✓'
        else:
            state,text='off','  اتصال به ستاد'
        self.b_connect.setProperty('state',state);self.b_connect.setText(text);repolish(self.b_connect)
        self.b_showbrowser.setVisible(self.browser_open and not self.embedded)

    def on_busy(self,cmd,running):
        if running:self.running.add(cmd)
        else:self.running.discard(cmd)
        long_ops={'sync','download','documents','connect','batch'}
        busy_long=bool(self.running & long_ops)
        self.b_stop.setVisible(busy_long)
        self.progress_row.setVisible(bool(self.running - {'browser'}))
        if running and cmd not in ('sync','download','batch'):self.progress.setRange(0,0)
        if running:
            self.progress_label.setText({'browser':'در حال باز کردن مرورگر…','check':'در حال بررسی اتصال…','sync':'در حال دریافت فهرست…',
                'detail':'در حال دریافت جزئیات از سامانه…','documents':'در حال خواندن فهرست اسناد…',
                'download':'در حال دانلود اسناد…','favorite':'در حال افزودن به فراخوان‌های من…','unfavorite':'در حال حذف از فراخوان‌های من…',
                'diagnose':'در حال تهیه گزارش عیب‌یابی…','connect':'در حال اتصال به ستاد…','batch':'در حال اجرای عملیات گروهی…',
                'my_calls':'در حال همگام‌سازی فراخوان‌های من…','payment':'در حال باز کردن صفحه پرداخت اسناد…'}.get(cmd,''))
        self.b_sync.setEnabled(not (self.running & {'sync','connect','batch'}))
        self.b_connect.setEnabled('sync' not in self.running)
        self.b_mycalls.setEnabled(not (self.running & {'sync','connect','batch'}))
        busy_detail=bool(self.running & {'detail','documents','download','favorite','unfavorite','sync','connect','batch'})
        for b in (self.b_details,self.b_docs,self.b_add,self.b_dl,self.b_remove):b.setEnabled(not busy_detail)
        self._update_steps()

    def on_progress(self,page,total,unique,reported):
        self.progress.setRange(0,100)
        self.progress.setValue(round(100*page/total) if total else 0)
        if 'sync' in self.running:
            self.progress_label.setText(f'صفحه {fa_num(page)} از {fa_num(total)}  •  یکتا {fa_num(unique)} از {fa_num(reported)}')
            if page%10==0:self.refresh(keep_detail=True)

    # ================================================================ data
    def refresh(self,keep_detail=True):
        current=self.active_id
        self.model.load()
        self._refresh_filter_choices()
        self.filter_changed(keep_page=True)
        st=self.db.stats()
        self.st_total.set(fa_num(st['total']),f"{fa_num(st['my_calls'])} در فراخوان‌های من" if st['my_calls'] else '')
        self.st_selected.set(fa_num(st['selected']),'')
        self.st_docs.set(fa_num(st['with_docs']),f"{fa_num(st['downloaded'])} فایل دانلودشده" if st['files'] else '')
        last=self.db.last_sync()
        if last:
            self.st_sync.set(last['status'] if last['status']!='کامل' else 'کامل ✓',
                             f"{fa_num(last['seen_unique'])} از {fa_num(last['reported_count'])} • {jalali_from_iso(last['started'])}")
            runs=self.db.sync_runs(1)
            dup=runs[0]['dup_ids'] if runs else 0
            self._dup_count=dup or 0
            if hasattr(self,'b_dots'):
                self.b_dots.setToolTip('بیشتر — تکراری‌ها: '+fa_num(dup) if dup else 'بیشتر')
            self.st_dups.set(fa_num(dup),'مشاهده و مقایسه با سایت ←' if dup else 'تکراری ثبت نشده')
        else:
            self.st_sync.set('—','هنوز دریافتی انجام نشده');self.st_dups.set('—','')
        self._update_batch()
        if current and keep_detail:
            self.active_id=current;self.show_tender(current,reset_note=False)
            self._reselect(current)

    def _reselect(self,tid):
        for i,r in enumerate(self.model.rows):          # only the current page has rows
            if r['id']==tid:
                self.table.selectionModel().blockSignals(True)
                self.table.selectRow(i)
                self.table.selectionModel().blockSignals(False)
                return

    def _refresh_filter_choices(self):
        self.org.set_values(sorted(set(str(r.get('organization') or '') for r in self.model.all)-{''}))
        for combo,first,key in ((self.province,'همه استان‌ها','province'),
                                (self.type,'همه انواع','type_name')):
            prev=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem(first,ALL)
            for v in sorted(set(str(r.get(key) or '') for r in self.model.all)-{''}):combo.addItem(v,v)
            i=combo.findData(prev)
            if i>=0:combo.setCurrentIndex(i)
            combo.blockSignals(False)

    # ---------------------------------------------------------------- v0.9.12: filter + sort + page (plain Python)
    def _sort_changed(self,column,order=Qt.AscendingOrder):
        self._sort=(column,order)
        if self._ready:
            self.page=0;self._rebuild_visible()

    def _rebuild_visible(self):
        accepts=self.flt.accepts
        vis=[r for r in self.model.all if accepts(r)]
        col,order=self._sort
        if 0<=col<len(COLUMNS):
            key=COLUMNS[col][0]
            vis.sort(key=lambda r:sort_value(r,key),reverse=(order==Qt.DescendingOrder))
        self.visible=vis
        self._show_page()

    def _page_count(self):
        return max(1,-(-len(self.visible)//self.page_size))

    def _show_page(self):
        self.page=min(max(self.page,0),self._page_count()-1)
        start=self.page*self.page_size
        chunk=self.visible[start:start+self.page_size]
        cur=self.model.rows
        same=(self.model.offset==start and len(cur)==len(chunk) and all(a is b for a,b in zip(cur,chunk)))
        if not same:
            sb=self.table.verticalScrollBar();keep=sb.value() if self.model.offset==start else 0
            self.model.set_page(chunk,start)
            if keep:sb.setValue(keep)
        self._update_pager()

    def _update_pager(self):
        pager=getattr(self,'pager',None)
        if pager is None:return
        pages=self._page_count();total=len(self.visible)
        pager.setVisible(total>0 and (pages>1 or self.page_size<total))
        start=self.page*self.page_size;end=min(total,start+self.page_size)
        self.pager_label.setText(f'صفحهٔ {fa_num(self.page+1)} از {fa_num(pages)}  ·  {fa_num(start+1)}–{fa_num(end)} از {fa_num(total)}')
        for b in (self.pager_first,self.pager_prev):b.setEnabled(self.page>0)
        for b in (self.pager_next,self.pager_last):b.setEnabled(self.page<pages-1)

    def _go_page(self,page):
        self.page=page;self._show_page();self.table.verticalScrollBar().setValue(0)

    def _page_size_changed(self,*_):
        try:size=int(self.pager_size.currentData())
        except (TypeError,ValueError):return
        if size==self.page_size:return
        first=self.page*self.page_size
        self.page_size=size;self.page=first//size
        QSettings('SetadSuite','tenders').setValue('page_size',size)
        self._show_page()

    def _build_pager(self):
        w=QWidget();hl=QHBoxLayout(w);hl.setContentsMargins(16,6,16,8);hl.setSpacing(6)
        self.pager_first=button('','default','chevron-right',tooltip='صفحهٔ اول')
        self.pager_prev=button('قبلی','default','chevron-right',tooltip='صفحهٔ قبل')
        self.pager_label=QLabel('');self.pager_label.setObjectName('Muted')
        self.pager_next=button('بعدی','default','chevron-left',tooltip='صفحهٔ بعد')
        self.pager_last=button('','default','chevron-left',tooltip='صفحهٔ آخر')
        self.pager_first.clicked.connect(lambda:self._go_page(0))
        self.pager_prev.clicked.connect(lambda:self._go_page(self.page-1))
        self.pager_next.clicked.connect(lambda:self._go_page(self.page+1))
        self.pager_last.clicked.connect(lambda:self._go_page(self._page_count()-1))
        if self.embedded:
            for b in (self.pager_first,self.pager_prev,self.pager_next,self.pager_last):b.setFixedHeight(38)    # v0.9.13: 38 px like the purchase page
        for b in (self.pager_first,self.pager_prev):hl.addWidget(b)
        hl.addWidget(self.pager_label)
        for b in (self.pager_next,self.pager_last):hl.addWidget(b)
        hl.addStretch(1)
        lab=QLabel('ردیف در هر صفحه:');lab.setObjectName('Muted');hl.addWidget(lab)
        self.pager_size=QComboBox()
        for n in (100,200,500,1000):self.pager_size.addItem(fa_num(n),n)
        self.pager_size.setCurrentIndex(max(0,self.pager_size.findData(self.page_size)))
        self.pager_size.currentIndexChanged.connect(self._page_size_changed)
        hl.addWidget(self.pager_size)
        w.hide();return w

    def filter_changed(self,keep_page=False):
        self.flt.set_filter(search=self.search.text().strip(),province=self.province.currentData() or ALL,
            org=frozenset(self.org.selected()),type=self.type.currentData() or ALL,
            only_selected=self.chips['selected'].isChecked(),only_docs=self.chips['docs'].isChecked(),only_dl=self.chips['downloaded'].isChecked(),
            actionable=self.chips['actionable'].isChecked(),soon=self.chips['soon'].isChecked(),
            starred=self.chips['starred'].isChecked(),
            only_mycalls=self.chips['mycalls'].isChecked(),
            price_mode='free' if self.chips['free'].isChecked() else ('paid' if self.chips['paid'].isChecked() else None))
        if not keep_page:self.page=0
        self._rebuild_visible()
        self.count_label.setText(f'{fa_num(len(self.visible))} از {fa_num(len(self.model.all))} فراخوان')
        self.page_count.setText(f'{fa_num(len(self.visible))} مورد')
        rows=self.model.all
        counts={'actionable':sum(1 for r in rows if (r.get('lc') or {}).get('actionable')),
                'soon':sum(1 for r in rows if r.get('days_left') is not None and 0<=r['days_left']<=7 and (r.get('lc') or {}).get('actionable')),
                'starred':sum(1 for r in rows if r.get('starred')),'mycalls':sum(1 for r in rows if r.get('in_my_calls')),
                'downloaded':sum(1 for r in rows if r.get('downloaded_count'))}
        base={'actionable':'قابل‌اقدام','soon':'مهلت نزدیک','starred':'ستاره‌دار','mycalls':'در فراخوان‌های من','downloaded':'دانلودشده'}
        for k,v in counts.items():
            if k in self.chips:self.chips[k].setText(f'{base[k]}  {fa_num(v)}')
        self._sync_more()
        if getattr(self,'kpi',None) is not None:
            self.kpi.set_values([len(rows),counts['actionable'],counts['soon'],counts['mycalls']])

    def set_id_filter(self,ids):
        self.flt.set_filter(ids=set(ids))
        self.id_chip.setText(f'فقط {fa_num(len(ids))} شناسه از فهرست تکراری‌ها');self.id_chip.show()
        self.filter_changed()

    def clear_id_filter(self):
        self.flt.set_filter(ids=None);self.id_chip.hide();self.filter_changed()

    def select_visible(self,checked):
        ids=[r['id'] for r in self.visible]            # every result, not only the current page
        self.model.check_ids(ids,checked);self.refresh()
        self.set_message(f'{fa_num(len(ids))} فراخوان {"انتخاب" if checked else "از انتخاب خارج"} شد.')

    def row_changed(self,current,previous):
        if not current.isValid():return
        idx=current
        if idx.isValid() and 0<=idx.row()<len(self.model.rows):
            tid=self.model.rows[idx.row()]['id']
            if tid!=self.active_id:
                self.active_id=tid;self.show_tender(tid)

    def selected(self):
        if not self.active_id:
            self.banner.show_message('info','ابتدا یک فراخوان را از جدول انتخاب کنید.',timeout=5000)
            return None
        return self.db.tender(self.active_id)

    # ================================================================ detail panel
    @staticmethod
    def _price_text(raw):
        try:
            v=float(raw)
            return 'رایگان' if v==0 else f'{fa_num(int(v))} ریال'
        except (TypeError,ValueError):
            return ''

    def show_tender(self,tid,reset_note=True):
        t=self.db.tender(tid)
        if not t:return
        learned=self.db.meta('column_labels') or {}
        T=lambda f:site_title(f,learned)
        self.detail_stack.setCurrentIndex(1)
        if reset_note:self.note.hide()
        _tt=fa_digits(t['title']);self.d_number.setText(fa_digits(t['number']));self.d_title.setToolTip(_tt)
        self.d_title.setText(_tt if len(_tt)<=140 else _tt[:140].rstrip()+'…')
        self.d_type.setText(t['type_name'] or '');self.d_type.setVisible(bool(t['type_name']))
        self.d_mycalls.setVisible(bool(t['in_my_calls']))
        loc=' / '.join(x for x in (t['province'],t['city']) if x)
        self.d_meta.setText(fa_digits('  •  '.join(x for x in (t['organization'],loc) if x)))
        self._fill_panel_v08(t)
        price=self._price_text(t['price'])
        site_state=(t.get('site_state_name') or '') if t['in_my_calls'] else ''
        lc=LC.classify(t,self.db.meta('status_map') or {})
        ed=str(t.get('edition_no') or '').strip()
        edition=(f"اصلاحیه {fa_num(ed)} — {t.get('last_edition_date') or ''}") if ed and ed!='0' else ''
        self.f_main.set_rows([(k,v) for k,v in ((T('number'),t['number']),(T('title'),t['title']),(T('type_name'),t['type_name']),
            ('وضعیت در سایت',site_state),('مرحله',lc['label']),('اصلاحیه',edition),
            (T('organization'),t['organization']),('محل اجرا',loc),(T('category'),t['category']),
            (T('description'),t['description'])) if v])
        n=lc['days'];left=''
        if n is not None:left='پایان‌یافته' if n<0 else ('امروز' if n==0 else f'{fa_num(n)} روز')
        kind=LC.deadline_kind_text(lc['kind'],lc['stage'])
        hist=self.db.status_history(t['id'])
        htxt='\n'.join(f"{h['at'][:16].replace('T',' ')}: {h['old_text'] or h['old_code'] or '—'} ← {h['new_text'] or h['new_code']}" for h in hist[:5])
        self.f_time.set_rows([(k,v) for k,v in ((T('published'),t['published']),(T('documents_deadline'),t['documents_deadline']),
            ('مهلت ارسال اسناد ارزیابی کیفی',t.get('inquiry_deadline') or ''),
            (T('proposal_deadline'),t['proposal_deadline']),(T('opening_date'),t['opening_date']),
            ((f'باقی‌مانده تا {kind}' if kind else 'باقی‌مانده'),left),('تاریخچهٔ وضعیت',htxt)) if v])
        self.f_fin.set_rows([(T('price'),price)] if price else [])
        self.sec_fin.setVisible(bool(price))
        # site details page → sections (titles exactly as the site prints them)
        while self.site_box.count():
            it=self.site_box.takeAt(0)
            wd=it.widget()
            if wd:
                wd.setParent(None);wd.deleteLater()
        pairs=[]
        try:pairs=json.loads(t.get('detail_json') or '[]')
        except ValueError:pass
        if pairs:
            self.site_text.hide()
            for title,rows in group_pairs(pairs):
                sec=Section(title+' (جزئیات سامانه)','shield-check');tb=InfoTable();tb.set_rows(rows);sec.body.addWidget(tb)
                self.site_box.addWidget(sec)
        elif t['detail_text']:
            self.site_text.setPlainText(t['detail_text']);self.site_text.show()
        else:
            self.site_text.hide()
        self.site_hint.setVisible(not pairs and not t['detail_text'])
        self.site_hint.setText('جزئیات کامل سامانه هنوز دریافت نشده — «جزئیات کامل» را بزنید.')
        fa_rows,tech_rows=technical_fields(t['raw_json'],learned)
        shown={x[0] for x in self.f_main_rows(t,T)}
        extra=[(k,v) for k,v in fa_rows if k not in shown][:80]
        self.f_all.set_rows(extra)
        self.f_tech.set_rows(tech_rows[:220])
        self.sec_all.findChild(QLabel,'SectionTitle').setText(f'سایر فیلدهای فهرست ({fa_num(len(extra))})')
        self.f_tech.hide()
        self.sec_all.setVisible(bool(extra))
        self.fill_doc_tree(tid)

    @staticmethod
    def f_main_rows(t,T):
        names=['number','title','type_name','organization','category','description','published','documents_deadline',
               'proposal_deadline','opening_date','price']
        return [(T(n),'') for n in names]

    def _toggle_all_fields(self):
        vis=not self.f_tech.isVisible();self.f_tech.setVisible(vis)
        n=len(self.f_tech.findChildren(QLabel,'InfoLabel'))
        self.b_all_toggle.setText('پنهان کردن فیلدهای فنی' if vis else f'نمایش فیلدهای فنی ({fa_num(n)})')

    def fill_doc_tree(self,tid):
        self._tree_loading=True
        self.tree.clear()
        groups=self.db.groups(tid);files=self.db.files(tid)
        gone=[(x['document_type'],x['appendix_id']) for x in files if x['local_path'] and not Path(x['local_path']).exists()]
        if gone:        # v0.9.17: the file was deleted by hand -> status goes back to «not downloaded»
            self.db.reset_file_downloads(tid,gone);files=self.db.files(tid)
            for r in self.model.all:
                if str(r.get('id'))==str(tid):r['downloaded_count']=sum(1 for x in files if x['local_path'])
            try:self.note.show_message('info',f"{fa_num(len(gone))} فایل دیگر روی رایانه پیدا نشد؛ وضعیتشان به «دانلود نشده» برگشت.",timeout=8000)
            except Exception:pass
        _has=any(x['local_path'] for x in files);self.b_rmdl.setEnabled(_has)
        self.b_openf.setEnabled(_has);self.b_openf.setToolTip('پوشهٔ همین مناقصه را در ویندوز باز می‌کند.' if _has else 'هنوز چیزی برای این مناقصه دانلود نشده است.')
        self.path_label.setText(str(self.download_path))
        if getattr(self,'dir_edit',None) is not None:self.dir_edit.setText(str(self.download_path))
        if not groups:
            self.docs_stack.setCurrentIndex(0);self.docs_info.setText('')
            for b in (self.b_dl,self.b_dl_all,self.b_dl_none,self.b_rmdl,self.b_openf):b.setVisible(False)
            self._tree_loading=False;return
        self.docs_stack.setCurrentIndex(1)
        for b in (self.b_dl,self.b_dl_all,self.b_dl_none,self.b_rmdl,self.b_openf):b.setVisible(True)
        method=groups[0].get('method') or ''
        for g in groups:
            related=[x for x in files if x['document_type']==g['document_type']]
            rep_n=g.get('reported_count')
            cnt=fa_num(len(related)) if not rep_n or rep_n==len(related) else f'{fa_num(len(related))} از {fa_num(rep_n)}'
            parent=QTreeWidgetItem([f"{g['title']}  ({cnt})",'',g['reported_size'] or '',''])
            if rep_n and rep_n>len(related):parent.setForeground(0,QColor(C['amber']));parent.setToolTip(0,f'سایت {rep_n} فایل اعلام کرده است')
            parent.setIcon(0,icon('folder',C['amber'],16))
            f=parent.font(0);f.setWeight(QFont.DemiBold);parent.setFont(0,f)
            parent.setFlags(parent.flags()|Qt.ItemIsUserCheckable|Qt.ItemIsAutoTristate)
            parent.setCheckState(0,Qt.Unchecked)
            self.tree.addTopLevelItem(parent)
            for x in related:
                state=x['state'];done=bool(x['local_path'])
                label=x['display_name']+('.'+x['extension'] if x['extension'] and not x['display_name'].lower().endswith('.'+x['extension'].lower()) else '')
                if x.get('comment') and x['comment']!=x['display_name']:label=f"{x['comment']}  —  {label}"
                item=QTreeWidgetItem([label,(x['extension'] or '').upper(),x['size'] or '',
                                      ('✓ ' if done else '')+state])
                item.setToolTip(0,label)
                item.setIcon(0,icon('file',C['primary'] if not done else C['green'],15))
                item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                item.setCheckState(0,Qt.Unchecked)
                item.setData(0,Qt.UserRole,(x['document_type'],x['appendix_id']))
                item.setData(0,Qt.UserRole+1,x['local_path'])
                if done:item.setForeground(3,QColor(C['green']));item.setToolTip(3,x['local_path']+'\n(دوبار کلیک: باز کردن فایل)')
                if x['error']:item.setForeground(3,QColor(C['red']));item.setToolTip(3,x['error'])
                parent.addChild(item)
            if not related:
                empty=QTreeWidgetItem(['فایلی در این دسته برنگشت','','',''])
                empty.setForeground(0,QColor(C['faint']));empty.setFlags(Qt.ItemIsEnabled);parent.addChild(empty)
            parent.setExpanded(True)
        dn=sum(1 for x in files if x['local_path'])
        self.docs_info.setText(f'{fa_num(len(groups))} دسته  •  {fa_num(len(files))} فایل  •  {fa_num(dn)} دانلودشده'
                               +(f'  •  منبع: {method}' if method else ''))
        self._tree_loading=False
        self._sync_preview_btn()

    def tree_item_changed(self,item,column):
        pass  # parent/child tri-state is handled by Qt.ItemIsAutoTristate

    def _file_item_path(self,item):
        path=item.data(0,Qt.UserRole+1) if item is not None else None
        return path if path and Path(path).exists() else None

    def delete_downloads(self):
        """«حذف فایل‌های دانلودشده»: deletes what the app downloaded for this tender (and then empty folders), resets the file
        states. Stars, workspace and history are untouched; other files a user put in the folder are left alone."""
        t=self.selected()
        if not t:return
        files=[f for f in self.db.files(t['id']) if f['local_path']]
        on_disk=[Path(f['local_path']) for f in files if Path(f['local_path']).is_file()]
        if not files:
            self.note.show_message('info','برای این فراخوان فایل دانلودشده‌ای نیست.',timeout=6000);return
        box=QMessageBox(self);box.setIcon(QMessageBox.Warning);box.setWindowTitle('حذف فایل‌های دانلودشده')
        box.setText(f"{fa_num(len(files))} فایل دانلودشدهٔ این فراخوان از روی رایانه حذف شود؟")
        box.setInformativeText('فقط فایل‌هایی که خود برنامه دانلود کرده پاک می‌شوند. ستاره، پرونده و تاریخچه دست نمی‌خورد و هر وقت خواستید دوباره دانلود می‌کنید.')
        yes=box.addButton('بله، حذف کن',QMessageBox.YesRole);box.addButton('انصراف',QMessageBox.NoRole);box.exec()
        if box.clickedButton() is not yes:return
        failed=[];ok_keys=[]
        for f in files:
            p=Path(f['local_path'])
            try:
                if p.exists():p.unlink()
                ok_keys.append((f['document_type'],f['appendix_id']))
            except OSError:failed.append(p.name)
        base=self.download_path
        for f in files:                      # remove folders that became empty, never above the download folder
            d=Path(f['local_path']).parent
            while d!=base and base in d.parents:
                try:d.rmdir()
                except OSError:break
                d=d.parent
        self.db.reset_file_downloads(t['id'],ok_keys)
        self.db.log_action(t['id'],'حذف فایل‌های دانلودشده','انجام شد',f'{len(ok_keys)} فایل'+(f'؛ {len(failed)} ناموفق' if failed else ''))
        self.refresh();self.show_tender(t['id'],reset_note=False)
        if failed:self.note.show_message('warn',f"{fa_num(len(ok_keys))} فایل حذف شد؛ {fa_num(len(failed))} فایل حذف نشد (شاید باز است).",timeout=9000)
        else:self.note.show_message('success',f"{fa_num(len(ok_keys))} فایل حذف شد و وضعیت به «دانلود نشده» برگشت.",timeout=8000)

    def _sync_preview_btn(self):
        if not hasattr(self,'b_preview'):return
        item=self.tree.currentItem()
        if item is None or item.parent() is None:
            self.b_preview.setEnabled(False);self.b_preview.setToolTip('اول یک فایل را در فهرست انتخاب کنید.');return
        ok=self._file_item_path(item) is not None
        self.b_preview.setEnabled(ok)
        self.b_preview.setToolTip('باز کردن پیش‌نمایش فایل انتخاب‌شده.' if ok else 'این فایل هنوز دانلود نشده؛ اول آن را تیک بزنید و «دانلود انتخاب‌شده‌ها» را بزنید.')

    def preview_selected_file(self,item=None):
        """v0.9.15: preview window over every downloaded file of this tender (any category folder), starting at the selected one."""
        item=item or self.tree.currentItem()
        cur=self._file_item_path(item)
        if cur is None:return False
        try:
            from ui_preview import open_files_preview
        except ImportError:
            return False
        t=self.selected()
        files=[];start=0
        for gi in range(self.tree.topLevelItemCount()):
            g=self.tree.topLevelItem(gi)
            gname=g.text(0).rsplit('  (',1)[0]
            for ci in range(g.childCount()):
                ch=g.child(ci);p=self._file_item_path(ch)
                if p is None:continue
                if ch is item:start=len(files)
                files.append((f"{gname} ‹ {ch.text(0)}",Path(p)))
        open_files_preview(self,f"t{t['id'] if t else 0}",files,start)
        return True

    def _file_item_activated(self,item,column):
        if item is None or item.parent() is None:return
        if not self.preview_selected_file(item):self._open_file_item(item,column)

    def _open_file_item(self,item,column):
        path=item.data(0,Qt.UserRole+1)
        if path and Path(path).exists():QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def toggle_files(self,checked):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0,Qt.Checked if checked else Qt.Unchecked)

    def toggle_recording(self):
        if getattr(self,'recording',False):
            self.worker.submit('record_stop',version=__version__);return
        self.worker.submit('record_start')      # the worker reports «مرورگر باز نیست» itself (also when connected from the purchase side)

    def _show_trace(self):
        QMessageBox.information(self,'روش‌های امتحان‌شده','\n'.join(self._trace[-25:]) or '—')

    # ================================================================ actions
    def fetch_details(self):
        t=self.selected()
        if not t:return
        if not self.online:
            self.note.show_message('warn','برای دریافت جزئیات کامل، ابتدا «اتصال به ستاد» را بزنید.');return
        self.worker.submit('detail',id=t['id'])

    def fetch_documents(self):
        t=self.selected()
        if not t:return
        if not self.online:
            self.note.show_message('warn','برای دریافت فهرست اسناد، ابتدا «اتصال به ستاد» را بزنید.');return
        self.tabs.setCurrentIndex(2)   # «اسناد و دانلود»
        helper=bool(t['in_my_calls']) and self.settings.value('allow_helper',True,type=bool)
        self.worker.submit('documents',id=t['id'],helper=helper)

    def connect_site(self):
        if 'connect' in self.running:
            self.worker.cancel();return
        self.worker.submit('connect',minimize=self.settings.value('auto_minimize',True,type=bool))

    def open_workspace(self):
        t=self.selected()
        if not t:return
        host=getattr(self,'window_host',None)
        if host is not None:                      # inside the suite: opens as an in-app tab
            host('ten',str(t['id']),f"مناقصه {t['number']}",lambda:WorkspaceDialog(self.db,t,self.download_path,None),self.refresh)
            return
        dlg=WorkspaceDialog(self.db,t,self.download_path,self)
        dlg.exec()
        self.refresh()

    def open_company_docs(self):
        CompanyDocsDialog(self.db,self).exec()

    def open_settings(self):
        dlg=SettingsDialog(self.settings,self,self.db)
        if dlg.exec()==QDialog.Accepted:
            dlg.apply_to(self.settings);self.refresh()
            self.banner.show_message('info','تنظیمات ذخیره شد.',timeout=6000)

    def _selected_ids(self,only_missing_calls=False):
        return [r['id'] for r in self.model.all if r.get('selected') and not (only_missing_calls and r.get('in_my_calls'))]

    def batch_favorite(self):
        if not self.online:
            self.banner.show_message('warn','ابتدا «اتصال به ستاد» را بزنید.',timeout=6000);return
        ids=self._selected_ids(True)
        if not ids:
            self.banner.show_message('info','همهٔ فراخوان‌های انتخاب‌شده قبلاً در «فراخوان‌های من» هستند.',timeout=6000);return
        box=CompactBox(self);box.setIcon(QMessageBox.Question);box.setWindowTitle('افزودن گروهی')
        box.setText(f'{fa_num(len(ids))} فراخوان به «فراخوان‌های من» در حساب ستاد اضافه شود؟')
        box.setInformativeText('این کار وضعیت حساب شما در سایت را تغییر می‌دهد. افزودن‌ها یکی‌یکی و با فاصله انجام می‌شود.')
        yes=box.addButton('بله، اضافه شود',QMessageBox.YesRole);box.addButton('انصراف',QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:return
        self.progress.setValue(0)
        self.worker.submit('batch',kind='favorite',ids=ids)

    def batch_documents(self):
        if not self.online:
            self.banner.show_message('warn','ابتدا «اتصال به ستاد» را بزنید.',timeout=6000);return
        ids=self._selected_ids()
        if not ids:return
        self.progress.setValue(0)
        self.worker.submit('batch',kind='documents',ids=ids,helper=self.settings.value('allow_helper',True,type=bool))

    def open_payment(self):
        t=self.selected()
        if not t:return
        if not self.online:
            self.banner.show_message('warn','ابتدا «اتصال به ستاد» را بزنید.',timeout=6000);return
        self.worker.submit('payment',id=t['id'])

    def download_files(self):
        t=self.selected()
        if not t:return
        keys=[]
        for i in range(self.tree.topLevelItemCount()):
            parent=self.tree.topLevelItem(i)
            for k in range(parent.childCount()):
                child=parent.child(k)
                key=child.data(0,Qt.UserRole)
                if key and child.checkState(0)==Qt.Checked:keys.append(list(key))
        if not keys:
            self.note.show_message('info','ابتدا فایل‌های موردنظر را تیک بزنید (یا «انتخاب همه»).',timeout=5000);return
        if not self.online:
            self.note.show_message('warn','برای دانلود، ابتدا «اتصال به ستاد» را بزنید.');return
        self.worker.submit('download',id=t['id'],file_keys=keys,dest=str(self.download_path))

    def add_favorite(self):
        t=self.selected()
        if not t:return
        if not self.online:
            self.note.show_message('warn','برای افزودن، ابتدا «اتصال به ستاد» را بزنید.');return
        box=CompactBox(self);box.setIcon(QMessageBox.Question);box.setWindowTitle('افزودن به فراخوان‌های من')
        box.setText(f'فراخوان {t["number"]} به «فراخوان‌های من» در حساب ستاد اضافه شود؟')
        box.setInformativeText(t['title'][:200]+'\n\nاین کار وضعیت حساب شما در سایت را تغییر می‌دهد.')
        yes=box.addButton('بله، اضافه شود',QMessageBox.YesRole);box.addButton('انصراف',QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:return
        self.worker.submit('favorite',id=t['id'],confirmed=True)

    def remove_favorite(self):
        t=self.selected()
        if not t:return
        if not self.online:
            self.note.show_message('warn','برای حذف از «فراخوان‌های من»، ابتدا «اتصال به ستاد» را بزنید.');return
        box=CompactBox(self);box.setIcon(QMessageBox.Warning);box.setWindowTitle('حذف از فراخوان‌های من')
        box.setText(f'فراخوان {t["number"]} از «فراخوان‌های من» در حساب ستاد حذف شود؟')
        box.setInformativeText(t['title'][:200]+'\n\nاین کار در سایت ستاد انجام می‌شود. اگر اسناد را خریده یا پاکت فرستاده باشید، '
                               'معمولاً سایت اجازهٔ حذف نمی‌دهد. فایل‌ها و اطلاعات داخل برنامه پاک نمی‌شوند.')
        yes=box.addButton('بله، حذف شود',QMessageBox.YesRole);box.addButton('انصراف',QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:return
        self.worker.submit('unfavorite',id=t['id'],confirmed=True)

    def start_sync(self):
        if not self.online:
            self.banner.show_message('info','ابتدا «اتصال به ستاد» را بزنید.',timeout=8000)
            return
        box=CompactBox(self);box.setIcon(QMessageBox.Question);box.setWindowTitle('دریافت همه فراخوان‌ها')
        box.setText('دریافت همه صفحات فهرست فعال سایت آغاز شود؟')
        box.setInformativeText('اگر فیلتری در سایت فعال باشد، فقط نتایج همان فیلتر دریافت می‌شود. '
                               'شناسه‌های تکراری و جاافتاده بعد از دریافت در بخش «تکراری‌ها» قابل مشاهده‌اند.')
        yes=box.addButton('شروع دریافت',QMessageBox.YesRole);box.addButton('انصراف',QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:return
        self.progress.setValue(0);self.worker.submit('sync',rows=50)

    def open_duplicates(self):
        d=DuplicatesDialog(self.db,self)
        d.show_in_table.connect(self.set_id_filter)
        d.exec()

    def show_actions_log(self):
        from PySide6.QtWidgets import QDialog,QListWidget,QListWidgetItem
        d=QDialog(self);d.setWindowTitle('گزارش عملیات');d.setLayoutDirection(Qt.RightToLeft);d.resize(720,460)
        lay=QVBoxLayout(d);lst=QListWidget();lay.addWidget(lst)
        try:rows=self.db.conn.execute('SELECT tender_id,action,at,result,message FROM actions ORDER BY id DESC LIMIT 300').fetchall()
        except Exception:rows=[]
        for r in rows:
            lst.addItem(QListWidgetItem(fa_digits(f"{r[2]}   {r[1]} ({r[0]}) — {r[3]}"+(f"   {r[4]}" if r[4] else ''))))
        if not rows:lst.addItem(QListWidgetItem('هنوز عملیاتی ثبت نشده است.'))
        d.exec()

    def choose_folder(self):
        name=QFileDialog.getExistingDirectory(self,'محل ذخیره اسناد',str(self.download_path))
        if name:
            self.download_path=Path(name);self.settings.setValue('download_path',name)
            self.worker.submit('set_download_dir',path=name)
            self.path_label.setText(name)
            if getattr(self,'dir_edit',None) is not None:self.dir_edit.setText(name)
            self.banner.show_message('success','محل ذخیره اسناد تغییر کرد: '+name,timeout=5000)

    def open_download_folder(self):
        self.download_path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.download_path)))

    def export(self,only_selected=False):
        if not self.visible and not only_selected:
            self.banner.show_message('info','ردیفی برای خروجی وجود ندارد.',timeout=4000);return
        dest,_=QFileDialog.getSaveFileName(self,'خروجی ردیف‌های فیلترشده',str(Path.home()/'Documents'/'Setad_Tenders.csv'),'CSV (*.csv)')
        if not dest:return
        cols=[(k,site_title(f,self.model.titles) if f else FIXED_TITLES.get(k,k)) for k,f in COLUMNS[1:] if k not in ('docs','days_left','star','row')]
        try:
            with open(dest,'w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f);w.writerow(['شناسه داخلی']+[x[1] for x in cols])
                rows=([r for r in self.model.all if r.get('selected')] if only_selected else list(self.visible))
                for r in rows:
                    w.writerow([r['id']]+[('بله' if r.get(k) else '') if k=='in_my_calls' else r.get(k,'') for k,_ in cols])
            self.banner.show_message('success',f'خروجی {fa_num(len(rows))} ردیف ذخیره شد.',
                                     'باز کردن',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(dest)),timeout=9000)
        except Exception as e:
            self.banner.show_message('error','خطا در ذخیره خروجی: '+str(e))

    # ================================================================ worker results
    FB_TEXT={'favorite':' در حال افزودن… ','unfavorite':' در حال حذف… ','documents':' در حال خواندن اسناد… ',
             'detail':' در حال دریافت… ','sync':' در حال دریافت… ','my_calls':' در حال همگام‌سازی… '}
    FB_DONE={'favorite':'افزوده شد','unfavorite':'حذف شد','documents':'اسناد خوانده شد','detail':'به‌روز شد','my_calls':'همگام شد'}

    def _fb_button(self,cmd):
        return {'favorite':getattr(self,'b_add',None),'unfavorite':getattr(self,'b_remove',None),'documents':getattr(self,'b_docs',None),
                'detail':getattr(self,'b_details',None),'sync':getattr(self,'b_sync',None),'my_calls':getattr(self,'b_mycalls',None)}.get(cmd)

    def _fb_start(self,cmd):
        b=self._fb_button(cmd)
        if b is not None:busy_btn(b,self.FB_TEXT.get(cmd))

    def handle_result(self,kind,payload):
        b=self._fb_button(kind)
        if b is not None:done_btn(b,True,self.FB_DONE.get(kind))
        if kind=='browser_closed':
            self.online=False;self.browser_open=False
            self._set_pill('off','●  مرورگر بسته است')
            self.banner.show_message('info','پنجره مرورگر ستاد بسته شد. برای ادامه «اتصال به ستاد» را بزنید.',timeout=12000)
            self._update_steps();return
        if kind=='role':
            if payload.get('role')=='ETEND' and self.browser_open:
                self.online=True;self._set_pill('on','●  متصل به ستاد (نقش مناقصه‌گر)')
            elif payload.get('role')=='EPROC':
                self._set_pill('wait','●  نقش فعلی ستاد: تامین‌کننده — با اولین کار مناقصه، خودکار عوض می‌شود')
            return
        if kind=='browser':
            self.browser_open=True
            if not self.online:self._set_pill('wait','●  مرورگر باز است — منتظر ورود')
            self.banner.show_message('info','در مرورگر برنامه وارد ستاد شوید و نقش «مناقصه‌گر» را انتخاب کنید؛ برنامه خودش «فراخوان‌ها» را باز و اتصال را کامل می‌کند.',timeout=20000)
        elif kind=='check':
            self.online=True;self.browser_open=True
            self._set_pill('on',f"●  متصل به ستاد — {fa_num(payload.get('records'))} فراخوان در سایت")
            self.refresh()
            filters=payload.get('filters') or {}
            mc=payload.get('my_calls')
            extra=f" • {fa_num(mc)} فراخوان در «فراخوان‌های من» (از سایت)" if mc else ''
            if filters:
                self.banner.show_message('warn','اتصال برقرار است، اما فیلتر در فهرست سایت فعال است؛ دریافت فقط شامل نتایج همین فیلتر می‌شود:\n'+
                    '  '.join(f'{k.split(".")[-1]}={v}' for k,v in filters.items())[:400])
            else:
                tail=' مرورگر کوچک شد؛ با «نمایش مرورگر» برمی‌گردد.' if payload.get('minimized') else ''
                self.banner.show_message('success',f"به ستاد وصل شد. تعداد فراخوان‌های سایت: {fa_num(payload.get('records'))}{extra}.{tail}",timeout=9000)
        elif kind=='connect_cancel':
            self.banner.show_message('info','اتصال متوقف شد.',timeout=4000)
        elif kind=='refresh':
            self.refresh()
        elif kind=='my_calls':
            self.refresh()
            n=payload.get('count')
            if payload.get('quiet'):
                if self.active_id:self.show_tender(self.active_id,reset_note=False)
            elif n is None:
                self.banner.show_message('warn','فهرست «فراخوان‌های من» از سایت خوانده نشد؛ نشان‌ها بدون تغییر ماند. (می‌توانید «افزودن» را برای هر فراخوان بزنید.)',timeout=9000)
            else:
                self.banner.show_message('success',f'{fa_num(n)} فراخوان به‌عنوان «در فراخوان‌های من» نشان شد.',timeout=7000)
        elif kind=='status_changes':
            ch=payload.get('changes') or []
            self.refresh()
            if self.settings.value('auto_docs',True,type=bool):
                for c in ch:
                    if c.get('code')==LC.ST_WAIT_PACKETS:self._auto_docs(c['id'])   # docs were just obtained (paid) on the site
            lines=[f"{fa_num(c['number'])}: {c['old'] or '—'} ← {c['new']}" for c in ch[:5]]
            self.banner.show_message('info',f'وضعیت {fa_num(len(ch))} فراخوان در سایت تغییر کرد:\n'+'\n'.join(lines),timeout=20000)
            try:QApplication.alert(self.window(),4000)
            except Exception:pass
        elif kind=='payment':
            self.note.show_message('info','صفحهٔ دریافت/پرداخت اسناد در مرورگر برنامه باز شد. پرداخت را خودتان انجام دهید؛ سپس «دریافت فهرست اسناد» را دوباره بزنید.',timeout=15000)
        elif kind=='batch':
            self.refresh()
            lbl={'favorite':'افزودن','documents':'دریافت فهرست اسناد'}.get(payload['kind'],'')
            msg=f"{lbl}: {fa_num(payload['ok'])} از {fa_num(payload['total'])} انجام شد"+(' (متوقف‌شده)' if payload['cancelled'] else '')+'.'
            if payload.get('empty'):msg+=f"\nبدون فایل (نیازمند افزودن یا خرید): {fa_num(len(payload['empty']))} مورد"
            if payload['errors']:msg+='\n'+'\n'.join(payload['errors'][:4])
            self.banner.show_message('warn' if (payload['errors'] or payload.get('empty')) else 'success',msg)
        elif kind=='sync':
            self.refresh()
            d=SyncReportDialog(payload,self);d.exec()
            if d.want_duplicates:self.open_duplicates()
        elif kind=='detail':
            self.refresh()
            self.note.show_message('success',f"جزئیات کامل دریافت شد.",timeout=6000)
        elif kind=='documents':
            self.refresh();self.tabs.setCurrentIndex(2)
            pid=str(payload.get('id') or '')
            if pid in self._auto_dl:
                self._auto_dl.discard(pid)
                keys=[[f['document_type'],f['appendix_id']] for f in self.db.files(pid) if not f.get('local_path')]
                if keys and not payload.get('all_empty'):
                    self.worker.submit('download',id=pid,file_keys=keys,dest=str(self.download_path))
            self._trace=payload.get('trace') or [];self.b_trace.setVisible(bool(self._trace) and not self.embedded)
            warnings=payload.get('warnings') or []
            t=self.db.tender(payload['id']) or {}
            if payload.get('all_empty'):
                try:paid=float(t.get('price') or 0)>0
                except ValueError:paid=False
                paid=paid or bool(payload.get('paid'))
                if payload.get('not_added') or not t.get('in_my_calls'):
                    self.note.show_message('warn','برای دریافت اسناد، ابتدا «افزودن» را بزنید.','افزودن',self.add_favorite)
                elif paid:
                    self.note.show_message('warn',f"اسناد این فراخوان پولی است ({self._price_text(t.get('price'))}). پس از پرداخت در سامانه، دوباره «دریافت فهرست اسناد» را بزنید.",
                                           'باز کردن صفحه پرداخت',self.open_payment)
                else:
                    self.note.show_message('warn','فهرست اسنادی از سایت برنگشت. چند لحظه بعد دوباره امتحان کنید؛ اگر تکرار شد «ضبط روند سایت» را بزنید.',
                                           'ضبط روند سایت',self.toggle_recording)
            elif warnings:
                self.note.show_message('warn',f"{fa_num(payload['count'])} فایل فهرست شد؛ برخی دسته‌ها کامل نبودند:\n"+'\n'.join(warnings[:4]))
            else:
                tail='  (برای این بار از تب کمکی استفاده شد)' if payload.get('helper_used') else ''
                self.note.show_message('success',f"{fa_num(payload['count'])} فایل فهرست شد. فایل‌ها را تیک بزنید و «دانلود» را بزنید.{tail}",timeout=8000)
        elif kind=='download':
            self.refresh()
            n=payload['success'];bad=payload['errors']
            try:        # v0.9.2: a free tender's docs were just obtained -> re-read its status from the site (quietly)
                t0=self.db.tender(payload.get('id')) or {}
                if n and self.online and t0.get('in_my_calls') and LC.is_free(t0) and LC.classify(t0,self.db.meta('status_map') or {})['stage']=='pay':
                    self.worker.submit('my_calls',quiet=True)
            except Exception:pass
            folder=payload.get('folder')
            opener=(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(folder))) if folder else None
            if bad:
                self.note.show_message('warn' if n else 'error',f"{fa_num(n)} فایل دریافت شد؛ {fa_num(len(bad))} ناموفق:\n"+'\n'.join(bad[:4]),
                                       'باز کردن پوشه' if folder else '',opener)
            else:
                self.note.show_message('success',f"{fa_num(n)} فایل دریافت شد"+(' (متوقف‌شده)' if payload['cancelled'] else '')+'.',
                                       'باز کردن پوشه' if folder else '',opener)
        elif kind=='unfavorite':
            self.refresh()
            self.note.show_message('success','از «فراخوان‌های من» در سایت حذف شد. اطلاعات و فایل‌های داخل برنامه دست‌نخورده ماند.',timeout=9000)
        elif kind=='favorite':
            self.refresh()
            if self.settings.value('auto_docs',True,type=bool) and payload.get('id'):
                tt=self.db.tender(payload['id']) or {}
                try:free=float(tt.get('price') or 0)==0
                except ValueError:free=False
                if free:self._auto_docs(str(payload['id']))      # paid ones: after payment (status change on the site)
            self.note.show_message('success','افزوده شد. حالا «دریافت فهرست اسناد» را بزنید.',
                                   'دریافت فهرست اسناد',self.fetch_documents)
        elif kind=='record_start':
            self.recording=True;self.b_rec.setText(' پایان ضبط ');self.act_record.setText('پایان ضبط و ذخیره')
            self.banner.show_message('warn','در حال ضبط روند سایت. در مرورگر برنامه همان کاری را بکنید که برای گرفتن اسناد انجام می‌دهید: '
                'فراخوان را باز کنید ← روی دسته اسناد کلیک کنید تا فهرست فایل‌ها بیاید ← یک فایل را دانلود کنید. سپس «پایان ضبط» را بزنید.\n'
                'رمز، Cookie و توکن ضبط نمی‌شود.','پایان ضبط',self.toggle_recording)
        elif kind=='record_stop':
            self.recording=False;self.b_rec.setText(' ضبط روند سایت ');self.act_record.setText('ضبط روند دریافت اسناد در سایت…')
            path=payload['path'];learned=payload.get('learned') or []
            what=[]
            if 'list' in learned:what.append('فهرست فایل‌ها')
            if 'download' in learned:what.append('دانلود فایل')
            msg=(f"ضبط ذخیره شد: {fa_num(payload['requests'])} درخواست، {fa_num(payload['downloads'])} دانلود. "+
                 (f"الگوی {' و '.join(what)} از سایت یاد گرفته شد؛ حالا «دریافت فهرست اسناد» را دوباره بزنید." if what else
                  'الگویی شناسایی نشد؛ فایل ضبط را برای بررسی بفرستید.'))
            self.banner.show_message('success' if what else 'warn',msg,'باز کردن پوشه',
                                     lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent))))
        elif kind=='manual_download':
            paths=payload.get('paths') or []
            if paths:
                folder=str(Path(paths[-1]).parent)
                self.banner.show_message('success',f'{fa_num(len(paths))} فایل از مرورگر برنامه ذخیره شد: '+Path(paths[-1]).name,
                                         'باز کردن پوشه',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(folder)),timeout=12000)
            return
        elif kind=='diagnose':
            path=payload['path']
            self.banner.show_message('success','گزارش عیب‌یابی ذخیره شد (بدون Cookie، رمز یا توکن). این فایل را برای بررسی بفرستید.',
                'باز کردن پوشه',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent))))
        self._update_steps()

    def handle_error(self,kind,error):
        b=self._fb_button(kind)
        if b is not None:done_btn(b,False,'ناموفق',3200)
        if kind in ('browser','check','connect'):
            self.online=False
            self._set_pill('err' if self.browser_open else 'off','●  اتصال برقرار نیست' if self.browser_open else '●  مرورگر بسته است')
        if kind in ('detail','documents','download','favorite','unfavorite','payment'):
            self.note.show_message('error',str(error)[:1400])
        else:
            title={'browser':'بازکردن مرورگر','check':'بررسی اتصال','connect':'اتصال به ستاد','batch':'عملیات گروهی','payment':'صفحه پرداخت','my_calls':'همگام‌سازی فراخوان‌های من','unfavorite':'حذف از فراخوان‌های من','sync':'دریافت فهرست','diagnose':'گزارش عیب‌یابی',
                   'record_start':'شروع ضبط','record_stop':'پایان ضبط'}.get(kind,kind)
            self.banner.show_message('error',f'{title}: {str(error)[:1400]}')
        self.status_text.setText(f'خطا در {kind}')
        self._update_steps()

    def closeEvent(self,event):
        self.worker.shutdown()
        if not self.worker.wait(12000):
            QMessageBox.warning(self,'در حال بستن','ارتباط مرورگر هنوز در حال بسته‌شدن است. چند لحظه دیگر دوباره تلاش کنید.')
            event.ignore();return
        self.db.close()
        super().closeEvent(event)
