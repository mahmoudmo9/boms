"""Tender workspace (stages, quotes/pricing, guarantee, envelopes) and the company-documents library."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractSpinBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QLineEdit, QPlainTextEdit, QDoubleSpinBox, QFileDialog, QFormLayout,
    QMessageBox, QInputDialog, QFrame, QScrollArea, QSizePolicy)
from .db import Database
from .dates import days_left
from .icons import icon
from .parsers import latin_digits, group_pairs
from .theme import C
from .widgets import button, fa_num, card, Banner, InfoTable, StageBar, Section
from . import workspace as W


def _num(text, default=0.0):
    s = latin_digits(str(text or '')).replace(',', '').replace('٬', '').strip()
    try:
        return float(s)
    except ValueError:
        return default


def _fmt(v):
    return fa_num(round(v)) if v == int(v) or abs(v) > 1000 else fa_num(round(v, 2))


def _open_path(path):
    if path and Path(path).exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return True
    return False


class WorkspaceDialog(QDialog):
    def __init__(self, db: Database, tender: dict, download_dir: Path, parent=None):
        super().__init__(parent)
        self.db = db;self.t = tender;self.tid = str(tender['id']);self.download_dir = Path(download_dir)
        self.setWindowTitle(f'فضای کار مناقصه — {tender["number"]}')
        self.resize(1180, 800);self.setLayoutDirection(Qt.RightToLeft)
        self._loading = False
        self.db.env_seed(self.tid, W.DEFAULT_TEMPLATE)
        root = QVBoxLayout(self);root.setContentsMargins(20, 16, 20, 14);root.setSpacing(10)
        # header
        head = QHBoxLayout()
        col = QVBoxLayout();col.setSpacing(2)
        num = QLabel(tender['number']);num.setObjectName('Chip');num.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title = QLabel(tender['title']);title.setObjectName('DetailTitle');title.setWordWrap(True)
        meta = QLabel('  •  '.join(x for x in (tender.get('organization'), tender.get('province')) if x));meta.setObjectName('Muted')
        row0 = QHBoxLayout();row0.addWidget(num);row0.addStretch();col.addLayout(row0);col.addWidget(title);col.addWidget(meta)
        head.addLayout(col, 1)
        side = QVBoxLayout()
        self.deadline = QLabel();self.deadline.setObjectName('Muted')
        n = days_left(tender.get('proposal_deadline') or '')
        txt = '' if n is None else ('مهلت پیشنهاد: پایان‌یافته' if n < 0 else f'مهلت پیشنهاد: {fa_num(n)} روز دیگر ({tender["proposal_deadline"]})')
        self.deadline.setText(txt)
        self.decision = QComboBox()
        for d in W.DECISIONS:self.decision.addItem(d or 'تصمیم: مشخص نشده', d)
        side.addWidget(self.deadline);side.addWidget(self.decision)
        head.addLayout(side)
        root.addLayout(head)
        self.stagebar = StageBar(W.STAGES);self.stagebar.picked.connect(self._stage_picked)
        root.addWidget(self.stagebar)
        self.note = Banner(compact=True);root.addWidget(self.note)
        self.tabs = QTabWidget();root.addWidget(self.tabs, 1)
        self._build_summary();self._build_pricing();self._build_guarantee();self._build_envelopes()
        foot = QHBoxLayout();foot.addStretch()
        close = button('بستن', 'primary');close.clicked.connect(self.accept);foot.addWidget(close)
        root.addLayout(foot)
        ws = self.db.ws(self.tid)
        self.decision.setCurrentIndex(max(0, self.decision.findData(ws['decision'])))
        self.decision.currentIndexChanged.connect(lambda _: self.db.ws_save(self.tid, decision=self.decision.currentData() or ''))
        self._refresh_all()

    # ---------------------------------------------------------------- common
    def _stage_picked(self, i):
        self.db.ws_save(self.tid, stage=i);self._refresh_stage()

    def _refresh_stage(self):
        ws = self.db.ws(self.tid)
        files = self.db.files(self.tid)
        hint = W.stage_hint(ws, self.db.env_items(self.tid), self.db.guarantee(self.tid), bool(files), self.db.quotes(self.tid))
        self.stagebar.set_stage(ws['stage'], hint if hint != ws['stage'] else None)

    def _refresh_all(self):
        self._refresh_stage();self._refresh_summary();self._refresh_calc();self._refresh_env_titles()

    # ---------------------------------------------------------------- summary tab
    def _build_summary(self):
        w = QWidget();lay = QVBoxLayout(w);lay.setContentsMargins(0, 12, 0, 0);lay.setSpacing(12)
        self.sum_table = InfoTable(single=True);lay.addWidget(self.sum_table)
        self.block_box = Section('موارد مانع از ارسال', 'triangle-alert');self.block_label = QLabel();self.block_label.setWordWrap(True)
        self.block_box.body.addWidget(self.block_label);lay.addWidget(self.block_box)
        nb = Section('یادداشت', 'file-text');self.note_edit = QPlainTextEdit();self.note_edit.setMinimumHeight(110)
        self.note_edit.setPlainText(self.db.ws(self.tid)['note']);nb.body.addWidget(self.note_edit)
        self.note_edit.textChanged.connect(lambda: self.db.ws_save(self.tid, note=self.note_edit.toPlainText()))
        lay.addWidget(nb);lay.addStretch()
        self.tabs.addTab(w, icon('layout-dashboard', C['muted'], 15), 'خلاصه')

    def _refresh_summary(self):
        items = self.db.env_items(self.tid);g = self.db.guarantee(self.tid)
        prog = W.envelope_progress(items)
        rows = [('شماره فراخوان', self.t['number']), ('دستگاه', self.t.get('organization') or '—'),
                ('مهلت پیشنهاد', self.t.get('proposal_deadline') or '—'), ('زمان بازگشایی', self.t.get('opening_date') or '—')]
        for e in W.ENVELOPES:
            d, n = prog[e];rows.append((f'پاکت {e}', f'{fa_num(d)} از {fa_num(n)} آماده'))
        rows.append(('تضمین', g['status'] + (f' — {g["kind"]}' if g['kind'] else '')))
        calc = W.calc_offer(self.db.quotes(self.tid), *self._params())
        if calc['lines']:rows.append(('پیشنهاد قیمت محاسبه‌شده', _fmt(calc['total']) + ' ریال'))
        self.sum_table.set_rows(rows)
        bl = W.blockers(items, g, proposal_deadline=self.t.get('proposal_deadline') or '')
        self.block_label.setText('\n'.join('• ' + b for b in bl) if bl else '✓ همه موارد آماده است؛ می‌توانید ارسال را انجام دهید.')
        self.block_label.setStyleSheet(f'color:{C["amber"] if bl else C["green"]};font-weight:600;background:transparent;')

    # ---------------------------------------------------------------- pricing tab
    def _params(self):
        ws = self.db.ws(self.tid)
        return ws['margin_pct'], ws['vat_pct'], ws['other_costs']

    def _build_pricing(self):
        w = QWidget();lay = QHBoxLayout(w);lay.setContentsMargins(0, 12, 0, 0);lay.setSpacing(14)
        left = QVBoxLayout()
        info = QLabel('فرم پیشنهاد قیمت (پاکت ج) را خود کارفرما در اسناد گذاشته است؛ این بخش فقط قیمت تأمین‌کننده‌ها را مقایسه و عدد پیشنهادی را برای '
                      'وارد کردن در آن فرم آماده می‌کند. هر قلم با تیک «انتخاب» تأمین‌کننده‌اش را مشخص می‌کنید؛ بدون تیک، ارزان‌ترین در نظر گرفته می‌شود.')
        info.setWordWrap(True);info.setObjectName('Muted');left.addWidget(info)
        self.qt = QTableWidget(0, 5)
        self.qt.setHorizontalHeaderLabels(['قلم / شرح', 'تأمین‌کننده', 'تعداد', 'قیمت واحد (ریال)', 'انتخاب'])
        self.qt.verticalHeader().setVisible(False);self.qt.setAlternatingRowColors(True)
        self.qt.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.qt.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.qt.verticalHeader().setDefaultSectionSize(38)
        self.qt.itemChanged.connect(self._quote_changed)
        left.addWidget(self.qt, 1)
        bar = QHBoxLayout()
        a = button('افزودن ردیف قیمت', 'primary', 'plus');a.clicked.connect(self._quote_add)
        d = button('حذف ردیف', 'danger', 'trash-2');d.clicked.connect(self._quote_del)
        bar.addWidget(a);bar.addWidget(d);bar.addStretch();left.addLayout(bar)
        lay.addLayout(left, 3)
        right = card();rl = QVBoxLayout(right);rl.setContentsMargins(16, 14, 16, 14);rl.setSpacing(10)
        t = QLabel('محاسبهٔ پیشنهاد');t.setObjectName('CardTitle');rl.addWidget(t)
        form = QFormLayout();form.setLabelAlignment(Qt.AlignLeading)
        ws = self.db.ws(self.tid)
        self.sp_margin = QDoubleSpinBox();self.sp_margin.setRange(0, 500);self.sp_margin.setSuffix(' ٪');self.sp_margin.setValue(ws['margin_pct'])
        self.sp_vat = QDoubleSpinBox();self.sp_vat.setRange(0, 100);self.sp_vat.setSuffix(' ٪');self.sp_vat.setValue(ws['vat_pct'])
        self.sp_other = QDoubleSpinBox();self.sp_other.setRange(0, 1e13);self.sp_other.setDecimals(0);self.sp_other.setGroupSeparatorShown(True)
        self.sp_other.setValue(ws['other_costs'])
        for sp in (self.sp_margin, self.sp_vat, self.sp_other):sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
        form.addRow('سود', self.sp_margin);form.addRow('مالیات بر ارزش افزوده', self.sp_vat);form.addRow('سایر هزینه‌ها (ریال)', self.sp_other)
        rl.addLayout(form)
        self.calc_table = InfoTable(single=True);rl.addWidget(self.calc_table)
        self.calc_total = QLabel();self.calc_total.setStyleSheet(f'font-size:15pt;font-weight:800;color:{C["primary"]};background:transparent;')
        rl.addWidget(self.calc_total)
        b1 = button('کپی قیمت پیشنهادی', 'default', 'copy');b1.clicked.connect(self._copy_total)
        b2 = button('خروجی محاسبه (CSV)', 'default', 'file-spreadsheet');b2.clicked.connect(self._export_calc)
        rl.addWidget(b1);rl.addWidget(b2);rl.addStretch()
        lay.addWidget(right, 2)
        for sp in (self.sp_margin, self.sp_vat, self.sp_other):sp.valueChanged.connect(self._params_changed)
        self.tabs.addTab(w, icon('calculator', C['muted'], 15), 'استعلام و قیمت‌گذاری')
        self._load_quotes()

    def _load_quotes(self):
        self._loading = True
        qs = self.db.quotes(self.tid)
        self.qt.setRowCount(len(qs))
        for r, q in enumerate(qs):
            it0 = QTableWidgetItem(q['item']);it0.setData(Qt.UserRole, q['id'])
            self.qt.setItem(r, 0, it0);self.qt.setItem(r, 1, QTableWidgetItem(q['supplier']))
            self.qt.setItem(r, 2, QTableWidgetItem(_fmt(q['qty'])));self.qt.setItem(r, 3, QTableWidgetItem(_fmt(q['unit_price'])))
            ck = QTableWidgetItem();ck.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            ck.setCheckState(Qt.Checked if q['chosen'] else Qt.Unchecked);self.qt.setItem(r, 4, ck)
        self._loading = False

    def _quote_changed(self, _item):
        if self._loading:return
        self._save_quote_rows();self._refresh_calc();self._refresh_summary();self._refresh_stage()

    def _save_quote_rows(self):
        for r in range(self.qt.rowCount()):
            qid = self.qt.item(r, 0).data(Qt.UserRole)
            self.db.quote_save(self.tid, qid, self.qt.item(r, 1).text(), self.qt.item(r, 0).text(),
                               _num(self.qt.item(r, 2).text(), 1.0), _num(self.qt.item(r, 3).text()),
                               1 if self.qt.item(r, 4).checkState() == Qt.Checked else 0)

    def _quote_add(self):
        self.db.quote_save(self.tid, None, '', 'قلم جدید', 1, 0, 0)
        self._load_quotes();self._refresh_calc();self._refresh_stage()

    def _quote_del(self):
        r = self.qt.currentRow()
        if r < 0:return
        self.db.quote_delete(self.qt.item(r, 0).data(Qt.UserRole))
        self._load_quotes();self._refresh_calc();self._refresh_summary()

    def _params_changed(self, *_):
        self.db.ws_save(self.tid, margin_pct=self.sp_margin.value(), vat_pct=self.sp_vat.value(), other_costs=self.sp_other.value())
        self._refresh_calc();self._refresh_summary()

    def _refresh_calc(self):
        c = W.calc_offer(self.db.quotes(self.tid), self.sp_margin.value(), self.sp_vat.value(), self.sp_other.value())
        self.last_calc = c
        rows = [('جمع بهای تمام‌شده', _fmt(c['cost']) + ' ریال'), ('سود', _fmt(c['profit']) + ' ریال'),
                ('جمع قبل از مالیات', _fmt(c['before_vat']) + ' ریال'), ('مالیات بر ارزش افزوده', _fmt(c['vat']) + ' ریال')]
        self.calc_table.set_rows(rows)
        self.calc_total.setText('قیمت پیشنهادی: ' + _fmt(c['total']) + ' ریال')

    def _copy_total(self):
        QGuiApplication.clipboard().setText(str(round(self.last_calc['total'])))
        self.note.show_message('success', 'عدد قیمت پیشنهادی (بدون جداکننده) کپی شد.', timeout=4000)

    def _export_calc(self):
        dest, _ = QFileDialog.getSaveFileName(self, 'خروجی محاسبه', str(self.download_dir / f'محاسبه-{self.t["number"]}.csv'), 'CSV (*.csv)')
        if not dest:return
        c = self.last_calc
        with open(dest, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f);w.writerow(['قلم', 'تأمین‌کننده', 'تعداد', 'قیمت واحد', 'جمع'])
            for l in c['lines']:w.writerow([l['item'], l['supplier'], l['qty'], l['unit_price'], l['total']])
            w.writerow([]);w.writerow(['جمع بهای تمام‌شده', '', '', '', c['cost']]);w.writerow(['سود', '', '', '', c['profit']])
            w.writerow(['مالیات', '', '', '', c['vat']]);w.writerow(['قیمت پیشنهادی', '', '', '', c['total']])
        self.note.show_message('success', 'محاسبه ذخیره شد.', 'باز کردن', lambda: _open_path(dest), timeout=8000)

    # ---------------------------------------------------------------- guarantee tab
    def _build_guarantee(self):
        w = QWidget();lay = QHBoxLayout(w);lay.setContentsMargins(0, 12, 0, 0);lay.setSpacing(14)
        form_card = card();fl = QVBoxLayout(form_card);fl.setContentsMargins(16, 14, 16, 14)
        t = QLabel('مشخصات تضمین');t.setObjectName('CardTitle');fl.addWidget(t)
        form = QFormLayout();form.setLabelAlignment(Qt.AlignLeading);fl.addLayout(form)
        self.g_kind = QComboBox()
        for k in W.GUARANTEE_KINDS:self.g_kind.addItem(k or 'انتخاب نوع…', k)
        self.g_status = QComboBox()
        for k in W.GUARANTEE_STATUSES:self.g_status.addItem(k, k)
        self.g_amount = QLineEdit();self.g_bank = QLineEdit();self.g_number = QLineEdit()
        self.g_issued = QLineEdit();self.g_issued.setPlaceholderText('۱۴۰۵/۰۸/۰۱')
        self.g_valid = QLineEdit();self.g_valid.setPlaceholderText('۱۴۰۵/۱۱/۳۰')
        self.g_file = QLineEdit();self.g_file.setReadOnly(True)
        pick = button('انتخاب اسکن…', 'default', 'paperclip');pick.clicked.connect(self._g_pick)
        openb = button('باز کردن', 'ghost', 'external-link');openb.clicked.connect(lambda: _open_path(self.g_file.text()))
        fr = QHBoxLayout();fr.addWidget(self.g_file, 1);fr.addWidget(pick);fr.addWidget(openb)
        self.g_note = QLineEdit()
        for lab, wd in (('نوع تضمین', self.g_kind), ('وضعیت', self.g_status), ('مبلغ (ریال)', self.g_amount), ('بانک', self.g_bank),
                        ('شماره چک / ضمانت‌نامه', self.g_number), ('تاریخ صدور', self.g_issued), ('معتبر تا', self.g_valid)):
            form.addRow(lab, wd)
        form.addRow('فایل اسکن', fr);form.addRow('یادداشت', self.g_note)
        self.g_warn = QLabel();self.g_warn.setWordWrap(True);fl.addWidget(self.g_warn);fl.addStretch()
        lay.addWidget(form_card, 3)
        hint_card = card();hl = QVBoxLayout(hint_card);hl.setContentsMargins(16, 14, 16, 14)
        ht = QLabel('آنچه سایت دربارهٔ تضمین نوشته');ht.setObjectName('CardTitle');hl.addWidget(ht)
        try:pairs = json.loads(self.t.get('detail_json') or '[]')
        except ValueError:pairs = []
        self.hint_table = InfoTable();hints = W.guarantee_hints(pairs)
        if not pairs:
            hl.addWidget(self._muted('جزئیات کامل این فراخوان هنوز دریافت نشده؛ در پنل جزئیات «جزئیات کامل» را بزنید.'))
        elif not hints:
            hl.addWidget(self._muted('در جزئیات سامانه فیلدی دربارهٔ تضمین پیدا نشد؛ اسناد مناقصه را بررسی کنید.'))
        else:
            self.hint_table.set_rows(hints);hl.addWidget(self.hint_table)
            for k, v in hints:
                if 'مبلغ' in k and not self.db.guarantee(self.tid)['amount']:
                    self._hint_amount = v
        hl.addStretch();lay.addWidget(hint_card, 2)
        g = self.db.guarantee(self.tid)
        self.g_kind.setCurrentIndex(max(0, self.g_kind.findData(g['kind'])));self.g_status.setCurrentIndex(max(0, self.g_status.findData(g['status'])))
        self.g_amount.setText(g['amount'] or getattr(self, '_hint_amount', ''));self.g_bank.setText(g['bank']);self.g_number.setText(g['number'])
        self.g_issued.setText(g['issued']);self.g_valid.setText(g['valid_until']);self.g_file.setText(g['file_path']);self.g_note.setText(g['note'])
        for wd in (self.g_amount, self.g_bank, self.g_number, self.g_issued, self.g_valid, self.g_note):wd.editingFinished.connect(self._g_save)
        self.g_kind.currentIndexChanged.connect(self._g_save);self.g_status.currentIndexChanged.connect(self._g_save)
        self.tabs.addTab(w, icon('landmark', C['muted'], 15), 'تضمین')
        self._g_check()

    @staticmethod
    def _muted(text):
        l = QLabel(text);l.setObjectName('Muted');l.setWordWrap(True);return l

    def _g_pick(self):
        name, _ = QFileDialog.getOpenFileName(self, 'اسکن تضمین', str(self.download_dir))
        if name:
            self.g_file.setText(name);self._g_save()

    def _g_save(self, *_):
        self.db.guarantee_save(self.tid, kind=self.g_kind.currentData() or '', status=self.g_status.currentData(),
                               amount=self.g_amount.text(), bank=self.g_bank.text(), number=self.g_number.text(),
                               issued=self.g_issued.text(), valid_until=self.g_valid.text(), file_path=self.g_file.text(), note=self.g_note.text())
        self._g_check();self._refresh_summary();self._refresh_stage()

    def _g_check(self):
        v = self.g_valid.text().strip()
        msg = '';color = C['muted']
        if v:
            a = days_left(v);b = days_left(self.t.get('proposal_deadline') or '')
            if a is None:msg = 'تاریخ اعتبار قابل فهم نیست (نمونه: ۱۴۰۵/۱۱/۳۰).';color = C['amber']
            elif a < 0:msg = 'اعتبار این تضمین تمام شده است.';color = C['red']
            elif b is not None and a < b:msg = 'اعتبار تضمین قبل از مهلت پیشنهاد تمام می‌شود.';color = C['red']
            else:msg = f'اعتبار تضمین: {fa_num(a)} روز دیگر.';color = C['green']
        self.g_warn.setText(msg);self.g_warn.setStyleSheet(f'color:{color};font-weight:600;background:transparent;')

    # ---------------------------------------------------------------- envelopes tab
    def _build_envelopes(self):
        w = QWidget();lay = QVBoxLayout(w);lay.setContentsMargins(0, 12, 0, 0);lay.setSpacing(8)
        info = QLabel('برای هر پاکت، وضعیت هر مدرک را مشخص کنید و فایل آماده را پیوست کنید. چک‌لیست اولیه برای پاکت‌های الف، ب و ج ساخته شده؛ '
                      'می‌توانید مورد اضافه یا حذف کنید (اقلام را با اسناد همین مناقصه تطبیق دهید). آپلود نهایی در سامانهٔ ستاد انجام می‌شود.')
        info.setWordWrap(True);info.setObjectName('Muted');lay.addWidget(info)
        self.env_tabs = QTabWidget();lay.addWidget(self.env_tabs, 1)
        self.env_tables = {}
        for e in W.ENVELOPES:
            page = QWidget();pl = QVBoxLayout(page);pl.setContentsMargins(0, 8, 0, 0)
            tb = QTableWidget(0, 4)
            tb.setHorizontalHeaderLabels(['مدرک', 'وضعیت', 'فایل', 'یادداشت'])
            tb.verticalHeader().setVisible(False);tb.setAlternatingRowColors(True);tb.verticalHeader().setDefaultSectionSize(40)
            tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch);tb.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            tb.setColumnWidth(1, 170);tb.setColumnWidth(2, 200)
            tb.setSelectionBehavior(QAbstractItemView.SelectRows)
            tb.itemChanged.connect(lambda item, env=e: self._env_text_changed(env, item))
            pl.addWidget(tb, 1)
            bar = QHBoxLayout()
            for text, ic, fn, kind in (('افزودن مورد', 'plus', lambda _=False, env=e: self._env_add(env), 'primary'),
                                       ('پیوست فایل…', 'paperclip', lambda _=False, env=e: self._env_attach(env), 'default'),
                                       ('پیوند به مدرک شرکت…', 'building-2', lambda _=False, env=e: self._env_link(env), 'default'),
                                       ('باز کردن فایل', 'external-link', lambda _=False, env=e: self._env_open(env), 'ghost'),
                                       ('حذف مورد', 'trash-2', lambda _=False, env=e: self._env_del(env), 'danger')):
                b = button(text, kind, ic);b.clicked.connect(fn);bar.addWidget(b)
            bar.addStretch();pl.addLayout(bar)
            self.env_tabs.addTab(page, '');self.env_tables[e] = tb
        self.tabs.addTab(w, icon('clipboard-check', C['muted'], 15), 'پاکت‌ها')
        self._load_env()

    def _load_env(self):
        self._loading = True
        items = self.db.env_items(self.tid)
        companies = {d['id']: d for d in self.db.company_docs()}
        for e, tb in self.env_tables.items():
            rows = [i for i in items if i['envelope'] == e]
            tb.setRowCount(len(rows))
            for r, it in enumerate(rows):
                a = QTableWidgetItem(it['title']);a.setData(Qt.UserRole, it['id']);tb.setItem(r, 0, a)
                cb = QComboBox()
                for st in W.ITEM_STATUSES:cb.addItem(st, st)
                cb.setCurrentIndex(max(0, cb.findData(it['status'])))
                cb.currentIndexChanged.connect(lambda _=0, iid=it['id'], c=cb: self._env_status(iid, c))
                tb.setCellWidget(r, 1, cb)
                path = it['file_path']
                cd = companies.get(it['company_doc_id']) if it['company_doc_id'] else None
                label = Path(path).name if path else (f'مدرک شرکت: {cd["title"]}' if cd else '—')
                f = QTableWidgetItem(label);f.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable);f.setToolTip(path or '')
                if cd:
                    st, n = W.doc_expiry(cd['expires'])
                    if st == 'expired':f.setForeground(QColor(C['red']));f.setToolTip('مدرک شرکت منقضی شده است')
                    elif st == 'soon':f.setForeground(QColor(C['amber']));f.setToolTip(f'{n} روز تا انقضا')
                tb.setItem(r, 2, f)
                tb.setItem(r, 3, QTableWidgetItem(it['note']))
        self._loading = False
        self._refresh_env_titles()

    def _refresh_env_titles(self):
        prog = W.envelope_progress(self.db.env_items(self.tid))
        for i, e in enumerate(W.ENVELOPES):
            d, n = prog[e]
            self.env_tabs.setTabText(i, f'پاکت {e}  ({fa_num(d)}/{fa_num(n)})')

    def _env_selected(self, env):
        tb = self.env_tables[env];r = tb.currentRow()
        if r < 0 or tb.item(r, 0) is None:
            self.note.show_message('info', 'ابتدا یک ردیف را انتخاب کنید.', timeout=3500);return None
        return tb.item(r, 0).data(Qt.UserRole)

    def _env_item(self, iid):
        return next((i for i in self.db.env_items(self.tid) if i['id'] == iid), None)

    def _env_status(self, iid, combo):
        if self._loading:return
        self.db.env_update(iid, status=combo.currentData());self._refresh_env_titles();self._refresh_summary();self._refresh_stage()

    def _env_text_changed(self, env, item):
        if self._loading:return
        tb = self.env_tables[env];iid = tb.item(item.row(), 0).data(Qt.UserRole)
        if item.column() == 0:self.db.env_update(iid, title=item.text())
        elif item.column() == 3:self.db.env_update(iid, note=item.text())

    def _env_add(self, env):
        title, ok = QInputDialog.getText(self, 'مورد جدید', f'عنوان مدرک پاکت {env}:')
        if ok and title.strip():
            self.db.env_add(self.tid, env, title.strip());self._load_env();self._refresh_summary()

    def _env_del(self, env):
        iid = self._env_selected(env)
        if iid:
            self.db.env_delete(iid);self._load_env();self._refresh_summary()

    def _env_attach(self, env):
        iid = self._env_selected(env)
        if not iid:return
        name, _ = QFileDialog.getOpenFileName(self, 'فایل مدرک', str(self.download_dir))
        if name:
            it = self._env_item(iid);status = it['status']
            if status in ('آماده نیست', 'در حال تهیه'):status = 'آماده'
            self.db.env_update(iid, file_path=name, company_doc_id=None, status=status)
            self._load_env();self._refresh_summary();self._refresh_stage()

    def _env_link(self, env):
        iid = self._env_selected(env)
        if not iid:return
        docs = self.db.company_docs()
        if not docs:
            self.note.show_message('info', 'کتابخانهٔ مدارک شرکت خالی است. از دکمهٔ «مدارک شرکت» در صفحهٔ اصلی مدارک را اضافه کنید.', timeout=6000);return
        names = [d['title'] + ('  — منقضی' if W.doc_expiry(d['expires'])[0] == 'expired' else '') for d in docs]
        pick, ok = QInputDialog.getItem(self, 'مدرک شرکت', 'کدام مدرک؟', names, 0, False)
        if ok:
            d = docs[names.index(pick)]
            status = 'آماده' if W.doc_expiry(d['expires'])[0] != 'expired' else 'در حال تهیه'
            self.db.env_update(iid, company_doc_id=d['id'], file_path=d['file_path'], status=status)
            if status != 'آماده':self.note.show_message('warn', 'این مدرک منقضی شده؛ وضعیت «در حال تهیه» ماند.', timeout=6000)
            self._load_env();self._refresh_summary();self._refresh_stage()

    def _env_open(self, env):
        iid = self._env_selected(env)
        if iid:
            it = self._env_item(iid)
            if not _open_path(it['file_path']):
                self.note.show_message('info', 'فایلی پیوست نشده است.', timeout=3500)


class CompanyDocsDialog(QDialog):
    COLS = ['مدرک', 'دسته', 'تاریخ انقضا', 'وضعیت', 'فایل']

    def __init__(self, db: Database, parent=None):
        super().__init__(parent);self.db = db
        self.setWindowTitle('مدارک شرکت');self.resize(980, 620);self.setLayoutDirection(Qt.RightToLeft)
        root = QVBoxLayout(self);root.setContentsMargins(20, 16, 20, 14);root.setSpacing(10)
        t = QLabel('کتابخانهٔ مدارک شرکت');t.setObjectName('DetailTitle');root.addWidget(t)
        info = QLabel('مدارک تکراری شرکت را یک بار اینجا ثبت کنید (با فایل اسکن و تاریخ انقضا) تا در چک‌لیست پاکت هر مناقصه با یک کلیک پیوند بخورند. '
                      'برنامه مدارک منقضی یا نزدیک به انقضا را هشدار می‌دهد.')
        info.setWordWrap(True);info.setObjectName('Muted');root.addWidget(info)
        self.tb = QTableWidget(0, len(self.COLS));self.tb.setHorizontalHeaderLabels(self.COLS)
        self.tb.verticalHeader().setVisible(False);self.tb.setAlternatingRowColors(True);self.tb.verticalHeader().setDefaultSectionSize(38)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers);self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch);self.tb.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tb.setColumnWidth(1, 120);self.tb.setColumnWidth(2, 130);self.tb.setColumnWidth(3, 190)
        self.tb.doubleClicked.connect(lambda _: self._edit())
        root.addWidget(self.tb, 1)
        bar = QHBoxLayout()
        for text, ic, fn, kind in (('افزودن مدرک', 'plus', self._add, 'primary'), ('ویرایش', 'file-text', self._edit, 'default'),
                                   ('باز کردن فایل', 'external-link', self._open, 'ghost'),
                                   ('افزودن مدارک پیشنهادی', 'layers', self._suggest, 'default'), ('حذف', 'trash-2', self._delete, 'danger')):
            b = button(text, kind, ic);b.clicked.connect(fn);bar.addWidget(b)
        bar.addStretch();close = button('بستن', 'ghost');close.clicked.connect(self.accept);bar.addWidget(close)
        root.addLayout(bar)
        self._load()

    def _load(self):
        docs = self.db.company_docs()
        self.tb.setRowCount(len(docs))
        names = {'ok': 'معتبر', 'soon': 'نزدیک انقضا', 'expired': 'منقضی', 'none': 'بدون تاریخ'}
        colors = {'ok': C['green'], 'soon': C['amber'], 'expired': C['red'], 'none': C['faint']}
        for r, d in enumerate(docs):
            st, n = W.doc_expiry(d['expires'])
            vals = [d['title'], d['category'], d['expires'] or '—', names[st] + (f' ({fa_num(n)} روز)' if n is not None and st != 'expired' else ''),
                    Path(d['file_path']).name if d['file_path'] else '—']
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:it.setData(Qt.UserRole, d['id'])
                if c == 3:it.setForeground(QColor(colors[st]))
                self.tb.setItem(r, c, it)

    def _current(self):
        r = self.tb.currentRow()
        if r < 0:return None
        did = self.tb.item(r, 0).data(Qt.UserRole)
        return next((d for d in self.db.company_docs() if d['id'] == did), None)

    def _form(self, d=None):
        dlg = QDialog(self);dlg.setWindowTitle('مدرک شرکت');dlg.setLayoutDirection(Qt.RightToLeft);dlg.resize(520, 300)
        lay = QVBoxLayout(dlg);form = QFormLayout();form.setLabelAlignment(Qt.AlignLeading);lay.addLayout(form)
        title = QLineEdit(d['title'] if d else '');cat = QLineEdit(d['category'] if d else '')
        exp = QLineEdit(d['expires'] if d else '');exp.setPlaceholderText('۱۴۰۵/۱۲/۲۹ (اختیاری)')
        fpath = QLineEdit(d['file_path'] if d else '');fpath.setReadOnly(True)
        pick = button('انتخاب فایل…', 'default', 'paperclip')
        pick.clicked.connect(lambda: fpath.setText(QFileDialog.getOpenFileName(dlg, 'فایل مدرک')[0] or fpath.text()))
        fr = QHBoxLayout();fr.addWidget(fpath, 1);fr.addWidget(pick)
        note = QLineEdit(d['note'] if d else '')
        form.addRow('عنوان', title);form.addRow('دسته', cat);form.addRow('تاریخ انقضا', exp);form.addRow('فایل', fr);form.addRow('یادداشت', note)
        bar = QHBoxLayout();ok = button('ذخیره', 'primary');cancel = button('انصراف', 'ghost')
        ok.clicked.connect(dlg.accept);cancel.clicked.connect(dlg.reject);bar.addStretch();bar.addWidget(cancel);bar.addWidget(ok);lay.addLayout(bar)
        if dlg.exec() == QDialog.Accepted and title.text().strip():
            self.db.company_doc_save(d['id'] if d else None, title.text().strip(), cat.text().strip(), fpath.text(), exp.text().strip(), note.text().strip())
            self._load()

    def _add(self):self._form()

    def _edit(self):
        d = self._current()
        if d:self._form(d)

    def _open(self):
        d = self._current()
        if d and not _open_path(d['file_path']):
            QMessageBox.information(self, 'مدارک شرکت', 'فایلی برای این مدرک ثبت نشده است.')

    def _delete(self):
        d = self._current()
        if d and QMessageBox.question(self, 'حذف', f'«{d["title"]}» حذف شود؟ (پیوندهای آن در چک‌لیست‌ها برداشته می‌شود.)') == QMessageBox.Yes:
            self.db.company_doc_delete(d['id']);self._load()

    def _suggest(self):
        have = {d['title'] for d in self.db.company_docs()}
        n = 0
        for title, cat in W.COMPANY_DOC_SUGGESTIONS:
            if title not in have:
                self.db.company_doc_save(None, title, cat);n += 1
        self._load()
        QMessageBox.information(self, 'مدارک شرکت', f'{fa_num(n)} مدرک پیشنهادی اضافه شد. فایل و تاریخ انقضا را برای هرکدام تکمیل کنید.' if n else 'همهٔ مدارک پیشنهادی از قبل وجود دارند.')
