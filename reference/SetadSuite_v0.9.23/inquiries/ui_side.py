"""Side panel for «فراخوان‌های خرید» (v0.9): the same anatomy as the tender panel —
tags + ☆/پوشه/✕ → title → one main action → tabs (مراحل / مشخصات / اسناد و دانلود / تاریخچه)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QTabWidget,
                               QVBoxLayout, QWidget)

import jalali
import pipeline as P
from ui_detail import DetailCard
from ui_kit import C, button, fa, label, rtl

# the five steps are shared with the tender panel; only names and the rule that finishes each one differ
STEP_TITLES = ["بررسی نیاز", "دریافت پیوست‌ها", "استعلام و مقایسهٔ قیمت", "ارسال پیشنهاد در سایت", "نتیجه"]
STEP_SUBS = ["شرح و پیوست‌ها را ببینید", "پیوست‌های نیاز", "تأمین‌کنندگان و قیمت‌ها", "با خودتان، در خود سایت", ""]


def current_step(stage: str | None, has_files: bool) -> int:
    """1..5 (6 = everything done). Stage is the pipeline stage the user moved the case to."""
    if stage in (None, "starred", "review"):
        return 1
    if stage == "rfq_ready":
        return 3 if has_files else 2
    if stage == "rfq":
        return 3
    if stage == "final":
        return 4
    if stage == "submitted":
        return 5
    return 6          # result


try:
    from setad_tender.widgets import fa_digits
except Exception:
    def fa_digits(v):
        return str(v)


class NeedSidePanel(QFrame):
    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.need_no = None
        self.setObjectName("card")
        self.setMinimumWidth(400)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        # --- tags + icons
        top = QHBoxLayout()
        top.setSpacing(6)
        self.t_no = QLabel()
        self.t_cat = QLabel()
        self.t_stage = QLabel()
        for t in (self.t_no, self.t_cat, self.t_stage):
            t.setTextInteractionFlags(Qt.TextSelectableByMouse)
            top.addWidget(t)
        top.addStretch()
        self.b_star = button("", "star", None, "ستاره‌دار / برداشتن")
        self.b_folder = button("", "folder", None, "پوشهٔ این نیاز")
        self.b_close = button("", "x", None, "بستن پنل")
        for b in (self.b_star, self.b_folder, self.b_close):
            b.setFixedWidth(38)
            top.addWidget(b)
        self.b_star.clicked.connect(lambda: self.need_no and (self.ui.toggle_star(self.need_no), self.show_need(self.need_no)))
        self.b_folder.clicked.connect(lambda: self.need_no and self.ui._open_directory(str(self.ui.need_folder(self.need_no))))
        self.b_close.clicked.connect(self.clear)
        v.addLayout(top)
        # --- title
        self.title = label("", "detailTitle", wrap=True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sub = label("", "muted", wrap=True)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        # --- actions: one main button (the next step), «پرونده», refresh, «صرف‌نظر»
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.b_main = button("شروع بررسی نیاز", "send", "primary")
        self.b_case = button("پرونده", "folder")
        self.b_refresh = button("", "refresh", None, "به‌روزرسانی جزئیات از سایت")
        self.b_refresh.setFixedWidth(38)
        self.b_waive = button("صرف‌نظر", "x", "danger")
        self.b_main.clicked.connect(self._main_action)
        self.b_case.clicked.connect(lambda: self.need_no and self.ui.open_case(self.need_no))
        self.b_refresh.clicked.connect(lambda: self.need_no and self.ui.request_detail(self.need_no, force=True))
        self.b_waive.clicked.connect(lambda: self.need_no and (self.ui.reject_need(self.need_no), self.show_need(self.need_no)))
        bar.addWidget(self.b_main, 1)
        for b in (self.b_case, self.b_refresh, self.b_waive):
            bar.addWidget(b)
        v.addLayout(bar)
        # --- tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setObjectName("sideTabs")
        v.addWidget(self.tabs, 1)
        self._steps_host = None
        self._restyle_tabs()
        self.clear()

    # ------------------------------------------------------------------ styling
    def _restyle_tabs(self):
        try:
            from setad_tender.theme import make_qss
            self.tabs.setStyleSheet(make_qss())
        except Exception:
            pass

    def restyle(self):
        self._restyle_tabs()
        if self.need_no:
            self.show_need(self.need_no)

    @staticmethod
    def _tag(lbl: QLabel, text: str, fg: str, bg: str):
        lbl.setText(rtl(text))
        lbl.setVisible(bool(text))
        lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:8px; padding:3px 10px; font-weight:600;")

    # ------------------------------------------------------------------ states
    def _clear_tabs(self):
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if w is not None:
                w.deleteLater()

    def clear(self):
        self.need_no = None
        self._clear_tabs()
        empty = QWidget()
        l = QVBoxLayout(empty)
        l.setContentsMargins(0, 0, 0, 0)
        try:
            from setad_tender.widgets import EmptyState
            l.addWidget(EmptyState("scan-search", "یک ردیف را انتخاب کنید", "مراحل، مشخصات و اسناد همان فراخوان اینجا دیده می‌شود."))
        except Exception:
            l.addStretch()
            t = label("یک ردیف را انتخاب کنید", "sectionTitle")
            t.setAlignment(Qt.AlignCenter)
            d = label("مراحل، مشخصات و اسناد همان فراخوان اینجا دیده می‌شود.", "muted", wrap=True)
            d.setAlignment(Qt.AlignCenter)
            l.addWidget(t)
            l.addWidget(d)
            l.addStretch()
        self.tabs.addTab(empty, "")
        self.tabs.tabBar().hide()
        for t in (self.t_no, self.t_cat, self.t_stage):
            t.hide()
        self.title.setText("")
        self.sub.setText("")
        for b in (self.b_main, self.b_case, self.b_refresh, self.b_waive, self.b_star, self.b_folder, self.b_close):
            b.setEnabled(False)
            b.setVisible(False)

    def _files_count(self, need_no: str) -> int:
        try:
            p = Path(self.ui.output_dir) / need_no
            return sum(1 for f in p.rglob("*") if f.is_file()) if p.exists() else 0
        except Exception:
            return 0

    def _main_action(self):
        if not self.need_no:
            return
        stage = self.ui.stages.get(self.need_no)
        step = current_step(stage, self._files_count(self.need_no) > 0)
        if step == 2:
            need = self.ui.need_obj(self.need_no)
            if need is not None:
                self.ui.download_needs([need])
                return
        self.ui.open_case(self.need_no)

    def show_need(self, need_no: str):
        need = self.ui.need_obj(need_no)
        if need is None:
            self.clear()
            return
        self.need_no = need_no
        if hasattr(self.ui, "sync_download_status"):
            self.ui.sync_download_status(need_no)      # v0.9.17: folder removed by hand → status back to «not downloaded»
        stage = self.ui.stages.get(need_no)
        payload = None if need_no in self.ui.detail_pending else self.ui.detail_payload(need_no)
        info = (payload or {}).get("info") or {}
        self._tag(self.t_no, fa_digits(need_no), C["primary"], C["primary_soft"])
        self.t_no.setLayoutDirection(Qt.LeftToRight)
        self._tag(self.t_cat, need.category or "", C["info"], C["info_soft"])
        stage_text = P.STAGE_TITLE.get(stage, "") if stage else "جدید" if need_no in self.ui.new_needs else ""
        self._tag(self.t_stage, stage_text, C["neutral"], C["neutral_soft"])
        _t = fa_digits(fa(info.get("description")) or need.description or "بدون شرح")
        self.title.setToolTip(rtl(_t))
        self.title.setText(rtl(_t if len(_t) <= 140 else _t[:140].rstrip() + "…"))   # two lines at most, full text in the tooltip
        self.sub.setText(rtl(fa_digits(" • ".join(x for x in (need.organization, need.province) if x))))
        files = self._files_count(need_no)
        step = current_step(stage, files > 0)
        self.b_main.setText({1: " شروع بررسی نیاز", 2: " دریافت پیوست‌ها"}.get(step, " باز کردن پرونده"))
        self.b_star.setToolTip("برداشتن از پیگیری" if stage not in (None, P.REJECTED) else "ستاره‌دار کردن")
        for b in (self.b_main, self.b_case, self.b_refresh, self.b_star, self.b_folder, self.b_close, self.b_waive):
            b.setVisible(True)
        for b in (self.b_main, self.b_case, self.b_refresh, self.b_star, self.b_folder, self.b_close):
            b.setEnabled(True)
        self.b_waive.setEnabled(stage != P.REJECTED)       # v0.9.17: also for a need that is not added yet

        cur = self.tabs.currentIndex() if self.tabs.count() == 4 else 0
        self._clear_tabs()
        self.tabs.tabBar().show()
        self.tabs.addTab(self._steps_tab(need, stage, step, files), "مراحل")
        self.tabs.addTab(self._scroll(DetailCard(self.ui, need, payload, embedded=True, part="info")), "مشخصات")
        self.tabs.addTab(self._scroll(DetailCard(self.ui, need, payload, embedded=True, part="files")), "اسناد و دانلود")
        self.tabs.addTab(self._history_tab(need_no), "تاریخچه")
        try:
            from setad_tender.icons import icon as _tic
            from setad_tender.theme import C as _TC
            for i, n in enumerate(("list-filter", "file-text", "folder-open", "clock")):
                self.tabs.setTabIcon(i, _tic(n, _TC["muted"], 15))
        except Exception:
            pass
        self.tabs.setCurrentIndex(max(0, min(cur, 3)))

    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.NoFrame)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setWidget(w)
        return s

    # ------------------------------------------------------------------ tabs
    def _steps_tab(self, need, stage, step: int, files: int) -> QWidget:
        from setad_tender.steps_ui import StepRow, Timeline
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(8)
        tl = Timeline()
        hours = self.ui.remaining_hours_for(need.need_no)
        rem = self.ui.remaining_for(need.need_no)
        overdue = hours is not None and hours <= 0
        sent = step >= 5
        nodes = [("انتشار", fa(need.published_date or ""), "done", "")]
        if sent:
            nodes.append(("مهلت ارسال پیشنهاد", fa(need.response_deadline or ""), "done", ""))
        else:
            nodes.append(("مهلت ارسال پیشنهاد", fa(need.response_deadline or ""), "missed" if overdue else "current",
                          "گذشته" if overdue else (rem or "")))
        nodes.append(("بازگشایی", "اعلام نشده", "todo", ""))
        tl.set_nodes(nodes)
        lay.addWidget(tl)
        if overdue and not sent and stage not in (None, P.REJECTED):
            b = QLabel(rtl(f"مهلت ارسال ({fa(need.response_deadline or '')}) گذشته است."))
            b.setObjectName("StepBanner")
            b.setWordWrap(True)
            lay.addWidget(b)
        subs = list(STEP_SUBS)
        subs[1] = f"{fa(files)} فایل در پوشهٔ برنامه" if files else "هنوز دریافت نشده"
        for i in range(5):
            state = "done" if i + 1 < step else "current" if i + 1 == step else "todo"
            lay.addWidget(StepRow(i + 1, STEP_TITLES[i], subs[i] if state != "done" or i == 1 else "", state, None))
        lay.addStretch(1)
        return self._scroll(host)

    def _history_tab(self, need_no: str) -> QWidget:
        lst = QListWidget()
        lst.setFrameShape(QFrame.NoFrame)
        try:
            events = self.ui.store.events(need_no)
        except Exception:
            events = []
        for e in events:
            lst.addItem(QListWidgetItem(rtl(f"{jalali.fmt_stamp(e['at'])}   {e['text']}")))
        if not lst.count():
            lst.addItem(QListWidgetItem(rtl("هنوز رویدادی ثبت نشده است.")))
        return lst
