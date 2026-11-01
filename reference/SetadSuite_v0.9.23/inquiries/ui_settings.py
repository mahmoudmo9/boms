"""Settings dialog: seller identity, proforma template, pricing defaults, review lists."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

import pipeline as P
from ui_kit import button, label, rtl


class SettingsDialog(QDialog):
    def __init__(self, ui):
        super().__init__(ui)
        self.ui = ui
        self.setWindowTitle("تنظیمات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 620)
        s = ui.store.settings()
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)

        # seller
        w, f = self._form()
        self.seller_name = QLineEdit(s["seller_name"])
        self.national_id = QLineEdit(s["national_id"])
        self.economic_code = QLineEdit(s["economic_code"])
        self.signer = QLineEdit(s["signer"])
        self.signer.setPlaceholderText(rtl("مثلاً: علی رضایی، مدیرعامل"))
        f.addRow("نام فروشنده (روی پیش‌فاکتور):", self.seller_name)
        f.addRow("شناسه ملی:", self.national_id)
        f.addRow("کد اقتصادی:", self.economic_code)
        f.addRow("نام و سمت امضاکننده:", self.signer)
        tabs.addTab(w, "مشخصات فروشنده")

        # proforma
        w, f = self._form()
        row = QHBoxLayout()
        self.template = QLineEdit(s["proforma_template"])
        self.template.setPlaceholderText(rtl("قالب پیش‌فرض برنامه (سربرگ شرکت)"))
        self.template.setLayoutDirection(Qt.LeftToRight)
        pick = button("انتخاب…", "folder")
        pick.clicked.connect(self._pick_template)
        reset = button("قالب پیش‌فرض", "retry", "ghost")
        reset.clicked.connect(lambda: self.template.setText(""))
        row.addWidget(self.template, 1)
        row.addWidget(pick)
        row.addWidget(reset)
        f.addRow("فایل قالب Word:", row)
        self.addressee = QLineEdit(s["addressee"])
        self.delivery_text = QLineEdit(s["delivery_text"])
        self.payment_text = QLineEdit(s["payment_text"])
        self.shipping_text = QLineEdit(s["shipping_text"])
        f.addRow("خطاب پیش‌فرض:", self.addressee)
        f.addRow("", label("{خریدار} با نام دستگاه خریدار جایگزین می‌شود.", "muted"))
        f.addRow("متن زمان تحویل:", self.delivery_text)
        f.addRow("", label("{روز} با زمان تحویل تأمین‌کننده منتخب جایگزین می‌شود.", "muted"))
        f.addRow("نحوه پرداخت:", self.payment_text)
        f.addRow("هزینه حمل:", self.shipping_text)
        counters = s.get("proforma_counters") or {}
        f.addRow("", label("آخرین شماره‌های صادرشده: " + ("، ".join(f"{y}: {n}" for y, n in counters.items()) or "—"), "muted"))
        tabs.addTab(w, "پیش‌فاکتور")

        # pricing
        w, f = self._form()
        self.vat = self._dspin(s["vat_pct"], 0, 50, " ٪")
        self.margin = self._dspin(s["margin_pct"], 0, 500, " ٪")
        self.finance = self._dspin(s["finance_monthly_pct"], 0, 50, " ٪ در ماه")
        self.months = QSpinBox()
        self.months.setRange(0, 36)
        self.months.setValue(int(s["default_payment_months"]))
        self.months.setSuffix(" ماه")
        self.rounding = QSpinBox()
        self.rounding.setRange(1, 10_000_000)
        self.rounding.setSingleStep(1000)
        self.rounding.setValue(int(s["rounding"]))
        self.rounding.setSuffix(" ریال")
        f.addRow("نرخ مالیات بر ارزش افزوده:", self.vat)
        f.addRow("حاشیه سود پیش‌فرض:", self.margin)
        f.addRow("هزینه مالی پول (خواب سرمایه):", self.finance)
        f.addRow("مدت پیش‌فرض تسویه خریدار:", self.months)
        f.addRow("", label("اگر در توضیحات خریدار مدت تسویه (مثلاً «تسویه سه ماهه») آمده باشد، همان استفاده می‌شود.", "muted", wrap=True))
        f.addRow("گرد کردن فی فروش به بالا:", self.rounding)
        tabs.addTab(w, "قیمت‌گذاری")

        # review lists
        w = QWidget()
        lv = QVBoxLayout(w)
        self.checklist = self._lines(s["checklist"])
        self.keywords = self._lines(s["warn_keywords"])
        self.reasons = self._lines(s["reject_reasons"])
        lv.addWidget(label("چک‌لیست بررسی (هر مورد در یک خط):", "fieldLabel"))
        lv.addWidget(self.checklist)
        lv.addWidget(label("کلیدواژه‌های هشدار (هر مورد در یک خط) — شرط‌هایی که ندارید؛ در شرح و توضیحات خریدار علامت‌گذاری می‌شوند:", "fieldLabel", wrap=True))
        lv.addWidget(self.keywords)
        lv.addWidget(label("دلایل صرف‌نظر (هر مورد در یک خط):", "fieldLabel"))
        lv.addWidget(self.reasons)
        tabs.addTab(w, "بررسی")

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("ذخیره")
        box.button(QDialogButtonBox.Cancel).setText("انصراف")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        v.addWidget(box)

    @staticmethod
    def _form():
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        f.setVerticalSpacing(10)
        f.setContentsMargins(16, 16, 16, 16)
        return w, f

    @staticmethod
    def _dspin(value, lo, hi, suffix):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(1)
        sp.setValue(float(value))
        sp.setSuffix(suffix)
        return sp

    @staticmethod
    def _lines(values):
        ed = QPlainTextEdit("\n".join(values))
        ed.setMaximumHeight(120)
        return ed

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب قالب Word", str(Path.home()), "Word (*.docx)")
        if path:
            self.template.setText(path)

    def _save(self):
        lines = lambda ed: [x.strip() for x in ed.toPlainText().splitlines() if x.strip()]
        st = self.ui.store
        for key, value in {
            "seller_name": self.seller_name.text().strip(), "national_id": self.national_id.text().strip(),
            "economic_code": self.economic_code.text().strip(), "signer": self.signer.text().strip(),
            "proforma_template": self.template.text().strip(), "addressee": self.addressee.text().strip(),
            "delivery_text": self.delivery_text.text().strip(), "payment_text": self.payment_text.text().strip(),
            "shipping_text": self.shipping_text.text().strip(),
            "vat_pct": self.vat.value(), "margin_pct": self.margin.value(), "finance_monthly_pct": self.finance.value(),
            "default_payment_months": self.months.value(), "rounding": self.rounding.value(),
            "checklist": lines(self.checklist) or P.DEFAULT_SETTINGS["checklist"],
            "warn_keywords": lines(self.keywords),
            "reject_reasons": lines(self.reasons) or P.DEFAULT_SETTINGS["reject_reasons"],
        }.items():
            st.set(key, value)
        self.accept()
