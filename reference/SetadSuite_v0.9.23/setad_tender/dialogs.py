"""Duplicate-ID review and sync report dialogs."""
from __future__ import annotations
import csv
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QLineEdit, QApplication,
                               QFileDialog, QFrame, QGridLayout, QWidget)
from .widgets import button, fa_num, jalali_from_iso, card, Banner
from .icons import icon, pixmap
from .theme import C

COLS=[('number','شماره فراخوان'),('title','عنوان'),('organization','دستگاه مناقصه‌گزار'),
      ('province','استان'),('pages','صفحات مشاهده'),('occurrences','تعداد')]


def _metric(label, value, color=None):
    w=card('Section');l=QVBoxLayout(w);l.setContentsMargins(14,10,14,10);l.setSpacing(2)
    a=QLabel(label);a.setObjectName('FieldLabel')
    b=QLabel(value);b.setStyleSheet(f'font-size:15pt;font-weight:700;color:{color or C["text"]};background:transparent;')
    l.addWidget(a);l.addWidget(b)
    return w


class DuplicatesDialog(QDialog):
    show_in_table=Signal(list)

    def __init__(self, db, parent=None):
        super().__init__(parent);self.db=db
        self.setWindowTitle('شناسه‌های تکراری و بازیابی‌شده');self.resize(1080,680)
        self.setLayoutDirection(Qt.RightToLeft)
        root=QVBoxLayout(self);root.setContentsMargins(20,18,20,16);root.setSpacing(12)
        head=QHBoxLayout()
        t=QLabel('شناسه‌های تکراری دریافت');t.setObjectName('DetailTitle');head.addWidget(t);head.addStretch()
        head.addWidget(QLabel('دریافت:'))
        self.runs=QComboBox();self.runs.setMinimumWidth(380);head.addWidget(self.runs)
        root.addLayout(head)
        info=QLabel('«تکراری» یعنی همان فراخوان در بیش از یک صفحه از فهرست سایت برگشته است؛ معمولاً هم‌زمان یک فراخوان دیگر '
                    'جا می‌افتد (کسری). «بازیابی‌شده» فراخوان‌هایی است که در دور اول دیده نشدند و در دور بازبینی پیدا شدند. '
                    'شماره صفحه‌ها بر اساس صفحات ۵۰تایی برنامه است، نه صفحات ۵تایی سایت؛ برای بررسی، شماره فراخوان را در جست‌وجوی سایت وارد کنید.')
        info.setWordWrap(True);info.setObjectName('Muted');root.addWidget(info)
        self.metrics=QHBoxLayout();self.metrics.setSpacing(10);root.addLayout(self.metrics)
        tools=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('جست‌وجو در شماره، عنوان یا دستگاه...')
        self.search.addAction(icon('search',C['faint'],16),QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter);tools.addWidget(self.search,1)
        self.b_copy=button('کپی شماره‌ها','default','copy');self.b_copy.clicked.connect(self._copy)
        self.b_csv=button('خروجی Excel','default','file-spreadsheet');self.b_csv.clicked.connect(self._export)
        self.b_show=button('نمایش در جدول اصلی','primary','list-filter');self.b_show.clicked.connect(self._show)
        for b in (self.b_copy,self.b_csv,self.b_show):tools.addWidget(b)
        root.addLayout(tools)
        self.note=Banner(compact=True);root.addWidget(self.note)
        self.tabs=QTabWidget();root.addWidget(self.tabs,1)
        self.tables={}
        for kind,label in (('duplicate','تکراری بین صفحات'),('recovered','بازیابی‌شده در دور دوم')):
            tb=QTableWidget(0,len(COLS));tb.setHorizontalHeaderLabels([c[1] for c in COLS])
            tb.verticalHeader().setVisible(False);tb.setAlternatingRowColors(True)
            tb.setEditTriggers(QAbstractItemView.NoEditTriggers);tb.setSelectionBehavior(QAbstractItemView.SelectRows)
            tb.verticalHeader().setDefaultSectionSize(38);tb.setSortingEnabled(True)
            h=tb.horizontalHeader();h.setSectionResizeMode(1,QHeaderView.Stretch)
            for i,w in ((0,175),(2,240),(3,130),(4,130),(5,60)):tb.setColumnWidth(i,w)
            wrap=card();l=QVBoxLayout(wrap);l.setContentsMargins(0,0,0,0);l.addWidget(tb)
            self.tabs.addTab(wrap,label);self.tables[kind]=tb
        bottom=QHBoxLayout();bottom.addStretch()
        close=button('بستن');close.clicked.connect(self.accept);bottom.addWidget(close);root.addLayout(bottom)
        self._runs=db.sync_runs()
        for r in self._runs:
            self.runs.addItem(f"{jalali_from_iso(r['started'])}  •  {r['status']}  •  تکراری {fa_num(r['dup_ids'])}",r['id'])
        self.runs.currentIndexChanged.connect(self._load)
        self._load()

    def _current_run(self):
        i=self.runs.currentIndex()
        return self._runs[i] if 0<=i<len(self._runs) else None

    def _load(self):
        run=self._current_run()
        while self.metrics.count():
            it=self.metrics.takeAt(0)
            if it.widget():it.widget().deleteLater()
        for tb in self.tables.values():tb.setRowCount(0)
        if not run:
            self.note.show_message('info','هنوز دریافتی انجام نشده است.');return
        reported=run['reported_count'] or 0;unique=run['seen_unique'] or 0
        missing=max(0,reported-unique)
        self.metrics.addWidget(_metric('اعلامی سایت',fa_num(reported)))
        self.metrics.addWidget(_metric('شناسه یکتای دریافت‌شده',fa_num(unique),C['primary']))
        self.metrics.addWidget(_metric('کسری',fa_num(missing),C['red'] if missing else C['green']))
        self.metrics.addWidget(_metric('شناسه‌های تکراری',fa_num(run['dup_ids']),C['amber'] if run['dup_ids'] else None))
        self.metrics.addWidget(_metric('بازیابی‌شده در دور دوم',fa_num(run['rec_ids']),C['teal']))
        for kind,tb in self.tables.items():
            rows=self.db.sync_issues(run['id'],kind)
            tb.setSortingEnabled(False);tb.setRowCount(len(rows))
            for i,r in enumerate(rows):
                for j,(key,_) in enumerate(COLS):
                    val=r.get(key,'')
                    it=QTableWidgetItem(str(val));it.setData(Qt.UserRole,r['tender_id'])
                    if key in ('number','pages','occurrences','province'):it.setTextAlignment(Qt.AlignCenter)
                    if key=='number':it.setForeground(Qt.GlobalColor.darkBlue)
                    if not r.get('number') and key=='number':it.setText('شناسه '+r['tender_id'])
                    tb.setItem(i,j,it)
            tb.setSortingEnabled(True)
        self.tabs.setTabText(0,f'تکراری بین صفحات ({fa_num(run["dup_ids"])})')
        self.tabs.setTabText(1,f'بازیابی‌شده در دور دوم ({fa_num(run["rec_ids"])})')
        if run['dup_ids']==0 and run['rec_ids']==0:
            if (run['duplicates'] or 0)>0:
                self.note.show_message('warn',f'در این دریافت {fa_num(run["duplicates"])} تکرار شمارش شده، اما فهرست شناسه‌ها ثبت نشده است. '
                                       'ثبت فهرست شناسه‌های تکراری از نسخه ۰.۲ انجام می‌شود؛ یک دریافت جدید بگیرید.')
            else:
                self.note.show_message('success','در این دریافت شناسه تکراری یا بازیابی‌شده‌ای وجود ندارد.')
        else:self.note.hide()
        self._filter()

    def _visible_rows(self, tb):
        return [i for i in range(tb.rowCount()) if not tb.isRowHidden(i)]

    def _filter(self):
        needle=self.search.text().strip().casefold()
        for tb in self.tables.values():
            for i in range(tb.rowCount()):
                hay=' '.join(tb.item(i,j).text() for j in range(3) if tb.item(i,j)).casefold()
                tb.setRowHidden(i,bool(needle) and needle not in hay)

    def _active(self):
        return list(self.tables.values())[self.tabs.currentIndex()]

    def _copy(self):
        tb=self._active()
        nums=[tb.item(i,0).text() for i in self._visible_rows(tb)]
        QApplication.clipboard().setText('\n'.join(nums))
        self.note.show_message('success',f'{fa_num(len(nums))} شماره فراخوان در کلیپ‌بورد کپی شد.',timeout=5000)

    def _export(self):
        tb=self._active()
        dest,_=QFileDialog.getSaveFileName(self,'خروجی',str(Path.home()/'Documents'/'Setad_Duplicates.csv'),'CSV (*.csv)')
        if not dest:return
        with open(dest,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['شناسه داخلی']+[c[1] for c in COLS])
            for i in self._visible_rows(tb):
                w.writerow([tb.item(i,0).data(Qt.UserRole)]+[tb.item(i,j).text() for j in range(len(COLS))])
        self.note.show_message('success','خروجی ذخیره شد: '+dest,timeout=7000)

    def _show(self):
        tb=self._active()
        ids=[tb.item(i,0).data(Qt.UserRole) for i in self._visible_rows(tb)]
        if ids:
            self.show_in_table.emit(ids);self.accept()


class SyncReportDialog(QDialog):
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.setWindowTitle('گزارش دریافت فراخوان‌ها');self.setLayoutDirection(Qt.RightToLeft);self.resize(620,0)
        self.want_duplicates=False
        root=QVBoxLayout(self);root.setContentsMargins(22,20,22,18);root.setSpacing(14)
        status=payload['status'];ok=status=='کامل'
        head=QHBoxLayout();ic=QLabel()
        ic.setPixmap(pixmap('circle-check' if ok else 'triangle-alert',C['green'] if ok else C['amber'],30));head.addWidget(ic)
        col=QVBoxLayout();t=QLabel('دریافت فراخوان‌ها: '+status);t.setObjectName('DetailTitle');col.addWidget(t)
        s=QLabel('تعداد شناسه‌های یکتا با شمارش اعلامی سایت برابر است.' if ok else
                 'تعداد شناسه‌های یکتا با شمارش سایت برابر نیست؛ فهرست تکراری‌ها را با سایت مقایسه کنید.')
        s.setObjectName('Muted');s.setWordWrap(True);col.addWidget(s);head.addLayout(col,1);root.addLayout(head)
        grid=QGridLayout();grid.setSpacing(10)
        missing=max(0,payload['reported']-payload['unique'])
        items=[('اعلامی سایت',payload['reported'],None),('یکتای دریافت‌شده',payload['unique'],C['primary']),
               ('کسری',missing,C['red'] if missing else C['green']),('شناسه تکراری',payload.get('duplicate_ids',0),C['amber']),
               ('بازیابی در دور دوم',payload.get('recovered',0),C['teal']),('رکورد جدید / تغییرکرده',f"{fa_num(payload['new'])} / {fa_num(payload['updated'])}",None)]
        for i,(label,val,color) in enumerate(items):
            grid.addWidget(_metric(label,val if isinstance(val,str) else fa_num(val),color),i//3,i%3)
        root.addLayout(grid)
        if payload.get('errors'):
            e=QLabel('\n'.join(payload['errors'][:6]));e.setWordWrap(True);e.setObjectName('Muted')
            e.setTextInteractionFlags(Qt.TextSelectableByMouse);root.addWidget(e)
        row=QHBoxLayout();row.addStretch()
        if payload.get('duplicate_ids') or payload.get('recovered'):
            d=button('مشاهده شناسه‌های تکراری','primary','files')
            d.clicked.connect(self._dups);row.addWidget(d)
        c=button('بستن');c.clicked.connect(self.accept);row.addWidget(c);root.addLayout(row)

    def _dups(self):
        self.want_duplicates=True;self.accept()


class SettingsDialog(QDialog):
    """General options + the table that maps the site's status (code/text) to our stage."""
    STAGES=[('','خودکار (پیشنهاد برنامه)'),('pay','نیاز به دریافت اسناد'),('prepare','در انتظار ارسال پاکت'),
            ('site','ارسال‌شده / بعد از ارسال (نمایش متن سایت)'),('missed','مهلت گذشته / از دست رفته')]

    def __init__(self, settings, parent=None, db=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QFormLayout
        self.db=db
        self.setWindowTitle('تنظیمات مناقصه‌ها');self.setLayoutDirection(Qt.RightToLeft);self.resize(760, 560)
        lay = QVBoxLayout(self);lay.setContentsMargins(20, 18, 20, 16);lay.setSpacing(12)
        t = QLabel('تنظیمات مناقصه‌ها');t.setObjectName('DetailTitle');lay.addWidget(t)
        form = QFormLayout();form.setLabelAlignment(Qt.AlignLeading);lay.addLayout(form)
        self.theme = QComboBox();self.theme.addItem('روشن', 'light');self.theme.addItem('تیره', 'dark')
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.value('theme', 'light'))))
        self.minimize = QCheckBox('بعد از اتصال موفق، مرورگر برنامه کوچک شود')
        self.minimize.setChecked(settings.value('auto_minimize', True, type=bool))
        self.helper = QCheckBox('اگر دریافت مستقیم اسناد کامل نشد، تب کمکی باز شود')
        self.helper.setChecked(settings.value('allow_helper', True, type=bool))
        self.auto_docs = QCheckBox('بعد از «افزودن» و بعد از گرفتن اسناد در سایت (پرداخت)، فهرست اسناد خودکار خوانده و دانلود شود')
        self.auto_docs.setChecked(settings.value('auto_docs', True, type=bool))
        self.theme.hide();form.addRow('', self.minimize);form.addRow('', self.helper);form.addRow('', self.auto_docs)
        n = QLabel('حالت روشن/تیره از پایین منوی کناری، فوری عوض می‌شود. محل ذخیرهٔ اسناد: منوی «تنظیمات» ← «محل ذخیرهٔ اسناد».')
        n.setObjectName('Muted');n.setWordWrap(True);lay.addWidget(n)
        h = QLabel('نگاشت وضعیت سایت به مرحلهٔ برنامه');h.setObjectName('SectionTitle');lay.addWidget(h)
        m = QLabel('وضعیت‌هایی که تا حالا در «فراخوان‌های من» دیده شده‌اند. اگر برنامه وضعیتی را درست دسته‌بندی نکرد، اینجا مرحله‌اش را انتخاب کنید.')
        m.setObjectName('Muted');m.setWordWrap(True);lay.addWidget(m)
        self.table = QTableWidget(0, 4);self.table.setHorizontalHeaderLabels(['کد سایت', 'متن سایت', 'تعداد', 'مرحله در برنامه'])
        hh = self.table.horizontalHeader();hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for i, w in ((0, 210), (2, 60), (3, 230)):hh.setSectionResizeMode(i, QHeaderView.Fixed);self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setVisible(False);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self._combos = []
        if db is not None:
            mapping = db.meta('status_map') or {}
            rows = db.conn.execute("SELECT site_state, site_state_name, COUNT(*) n FROM tenders WHERE site_state<>'' OR site_state_name<>'' "
                                   "GROUP BY site_state, site_state_name ORDER BY n DESC").fetchall()
            hist = db.conn.execute("SELECT DISTINCT new_code, new_text FROM status_history").fetchall()
            seen = {(r[0], r[1]): r[2] for r in rows}
            for hrow in hist:seen.setdefault((hrow[0], hrow[1]), 0)
            for (code, text), cnt in seen.items():
                r = self.table.rowCount();self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(code or '—'));self.table.setItem(r, 1, QTableWidgetItem(text or '—'))
                self.table.setItem(r, 2, QTableWidgetItem(fa_num(cnt)))
                cb = QComboBox()
                for k, label in self.STAGES:cb.addItem(label, k)
                cur = mapping.get(code) or mapping.get(text) or ''
                cb.setCurrentIndex(max(0, cb.findData(cur)))
                self.table.setCellWidget(r, 3, cb);self._combos.append((code, text, cb))
            if not seen:
                self.table.insertRow(0);self.table.setItem(0, 1, QTableWidgetItem('هنوز وضعیتی از سایت خوانده نشده؛ بعد از «همگام‌سازی فراخوان‌های من» پر می‌شود.'))
        bar = QHBoxLayout();bar.addStretch()
        cancel = button('انصراف', 'ghost');ok = button('ذخیره', 'primary')
        cancel.clicked.connect(self.reject);ok.clicked.connect(self.accept);bar.addWidget(cancel);bar.addWidget(ok);lay.addLayout(bar)

    def apply_to(self, settings):
        settings.setValue('auto_minimize', self.minimize.isChecked())
        settings.setValue('allow_helper', self.helper.isChecked())
        settings.setValue('auto_docs', self.auto_docs.isChecked())
        if self.db is not None and self._combos:
            mapping = {}
            for code, text, cb in self._combos:
                if cb.currentData():mapping[code or text] = cb.currentData()
            self.db.set_meta('status_map', mapping)
