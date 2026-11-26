"""v0.10.1 section 5: a showcase dataset for the review screenshots, in its own database ``boms_demo`` only.

``python -m app.cli demo-seed`` builds it through the application's own API (in process, as the app user), so every
record passes the same rules as real use; a few facts that only time produces (a deal closed last quarter, the hour
an offer arrived) are then set on the demo database directly. Persian, realistic and clearly fictional: every
company name is invented and marked «نمونه» / «Demo». BOMS shows «دادهٔ نمایشی» in the top bar while it runs on it.

What it holds (section 5): 9 deals across all stages; a sea import CNSHA → AEJEA (transshipment) → IRBND with a
4-day delay; an air shipment PVG → IKA; payment milestones in IRR, USD and EUR over the next 90 days with one week
below zero; deals closed this and last quarter with real profit; RFQs, offers, response times and inspections
enough for every party KPI tile on two suppliers; a tender with envelopes and missing documents; Setad listings that
match keywords today; an AI draft awaiting review; tasks and follow-ups for today (some done), overdue and untimed,
enough to show the 8-row caps and «همه (n)».
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

DEMO_PREFIX = "boms_demo"
CSRF = "demo-seed-csrf"


class DemoError(RuntimeError):
    pass


def is_demo_database(name: str) -> bool:
    return name == DEMO_PREFIX or name.startswith(DEMO_PREFIX + "_")


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def at(days: int, hour: int = 10, minute: int = 0) -> str:
    local = datetime.combine(date.today() + timedelta(days=days), time(hour, minute)).astimezone()
    return local.astimezone(timezone.utc).isoformat()


def demo_eml(sender: str, subject: str, body: str) -> bytes:
    """A fictional supplier e-mail with a small PDF datasheet attached (made here, never sent)."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = f"Li Wen <{sender}>", "purchase@kimia-demo.example.invalid", subject
    msg.set_content(body)
    msg.add_attachment(b"%PDF-1.4\n% ATEX datasheet (demo)\n%%EOF\n", maintype="application", subtype="pdf",
                       filename="ATEX-datasheet-demo.pdf")
    return msg.as_bytes()


class Api:
    """The app's HTTP API in process, signed in as the app user (no network, no browser)."""

    def __init__(self, user_id: uuid.UUID):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.modules.system.auth import current_user

        def demo_user():
            from app.core.db import new_session
            from app.modules.system.models import AppUser

            with new_session() as s:
                user = s.get(AppUser, user_id)
                s.expunge(user)
                return user

        app.dependency_overrides[current_user] = demo_user
        self.app = app
        from app.core.config import get_config

        # the app checks the Host header against its own port (BOMS_HTTP_PORT), so the client says the same port
        self.client = TestClient(app, base_url=f"http://127.0.0.1:{get_config().http_port}")
        self.client.cookies.set("boms_csrf", CSRF)

    def close(self) -> None:
        from app.modules.system.auth import current_user

        self.app.dependency_overrides.pop(current_user, None)

    def __call__(self, method: str, path: str, body=None, ok=(200, 201, 204), **kw):
        r = self.client.request(method, path, json=body, headers={"X-CSRF-Token": CSRF}, **kw)
        if r.status_code not in ok:
            raise DemoError(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None

    def get(self, path, **params):
        return self("GET", path, params=params)

    def post(self, path, body=None, **kw):
        return self("POST", path, body if body is not None else {}, **kw)

    def patch(self, path, body):
        return self("PATCH", path, body)

    def put(self, path, body):
        return self("PUT", path, body)

    def upload(self, filename: str, data: bytes, mime: str) -> dict:
        """A file into the document store (an e-mail saved as .eml, a datasheet)."""
        r = self.client.post("/api/documents", files={"file": (filename, data, mime)}, headers={"X-CSRF-Token": CSRF})
        if r.status_code == 409:
            return {"id": r.json()["error"]["details"]["id"]}
        if r.status_code != 201:
            raise DemoError(f"upload {filename} -> {r.status_code}: {r.text[:400]}")
        return r.json()


class Demo:
    def __init__(self, api: Api, log=print):
        self.api, self.log = api, log
        self.p: dict[str, dict] = {}                # parties by key
        self.loc: dict[str, dict] = {}
        self.cases: dict[str, dict] = {}

    # ---- base -----------------------------------------------------------------------------------------------------
    def company(self) -> None:
        self.api.patch("/api/settings", {
            "company.name_fa": "بازرگانی آرین‌تجارت (نمونه)", "company.name_en": "Arian Trade Demo Co.",
            "company.national_id": "10100000001", "company.economic_code": "411000000001",
            "company.address": {"fa": "تهران، خیابان نمونه، پلاک ۱۲", "en": "No. 12, Sample St., Tehran"},
            "company.phone": "+98 21 0000 0000", "company.email": "info@arian-demo.example",
            "company.bank_details": {"fa": "بانک نمونه، شبا IR00 0000 0000", "en": "Demo Bank, IBAN IR00 0000 0000"},
            "company.footer": {"fa": "دادهٔ نمایشی — همهٔ نام‌ها ساختگی است", "en": "Demo data — every name is fictional"},
            "finance.vat_default_domestic": {"mode": "apply"},
            "setad.warn_keywords": ["پمپ", "شیر", "لوله", "الکتروموتور"],
        })
        self.api.patch("/api/me", {"language": "fa", "calendar": "jalali"})

    def party(self, key, roles, name_fa, name_en, country, **extra) -> dict:
        body = {"name_fa": name_fa, "name_en": name_en, "roles": roles, "country_iso2": country, "confirm_duplicate": True, **extra}
        out = self.api.post("/api/parties", body)
        party = out.get("party", out)
        self.p[key] = party
        return party

    def contact(self, party, name_fa, name_en, job_title="مدیر خرید", **extra):
        return self.api.post("/api/contacts", {"party_id": party["id"], "name_fa": name_fa, "name_en": name_en,
                                               "is_primary": True, "job_title": job_title, **extra})

    def parties(self) -> None:
        p = self.party
        p("petro", ["buyer"], "پتروپالایش خلیج نمونه", "Gulf Petro Refining Demo", "IR", national_id="14000000101",
          economic_code="411000000101")
        p("steel", ["buyer"], "فولاد کویر نمونه", "Kavir Steel Demo", "IR", national_id="14000000102", economic_code="411000000102")
        p("water", ["buyer"], "آب‌وفاضلاب البرز نمونه", "Alborz Water Demo", "IR", national_id="14000000103",
          economic_code="411000000103")
        p("gulf", ["buyer"], "پیمانکاری خلیج نمونه", "Gulf Demo Contracting LLC", "AE")
        # v0.10.1 (0.4.2): a factory and a distributor; both have the history for every KPI tile
        p("ningbo", ["manufacturer"], "شیرآلات نینگبو نمونه", "Ningbo Demo Valves Co.", "CN", supplier_type="manufacturer")
        p("hamburg", ["supplier"], "پمپ هامبورگ نمونه", "Hamburg Demo Pumps GmbH", "DE", supplier_type="distributor")
        p("istanbul", ["supplier"], "لوله استانبول نمونه", "Istanbul Demo Pipes A.S.", "TR")
        p("shanghai", ["supplier"], "الکتروموتور شانگهای نمونه", "Shanghai Demo Motors Ltd.", "CN")
        p("caspian", ["carrier"], "کشتیرانی خزر نمونه", "Caspian Demo Lines", "IR",
          tracking_url_template="https://tracking.example.invalid/track?bl={number}")
        p("skyline", ["carrier"], "هوایی اسکای‌لاین نمونه", "Skyline Demo Air Cargo", "AE")
        p("forwarder", ["forwarder"], "ترابری پارس نمونه", "Pars Demo Logistics", "IR")
        p("inspector", ["other"], "بازرسی کیفیت آریا نمونه", "Arya Demo Inspection", "IR")
        self.contact(self.p["petro"], "مهندس رحیمی", "Eng. Rahimi")
        self.contact(self.p["steel"], "خانم کریمی", "Ms. Karimi")
        self.contact(self.p["water"], "آقای نادری", "Mr. Naderi")
        self.contact(self.p["gulf"], "Mr. Haddad", "Mr. Haddad", job_title="Sales manager")
        self.contact(self.p["ningbo"], "Ms. Li Wen", "Ms. Li Wen", job_title="Sales manager")
        self.contact(self.p["hamburg"], "Herr Becker", "Mr. Becker", job_title="Export manager")
        self.contact(self.p["istanbul"], "Mr. Kaya", "Mr. Kaya", job_title="Sales manager")
        self.contact(self.p["shanghai"], "Mr. Zhao", "Mr. Zhao", job_title="Sales manager")

    def locations(self) -> None:
        for code in ("CNSHA", "AEJEA", "IRBND", "CNPVG", "IRIKA", "DEHAM", "TRIST"):
            rows = self.api.get("/api/reference/locations", q=code)
            exact = [r for r in rows if (r.get("code") or "").replace(" ", "") == code] or rows
            if exact:
                self.loc[code] = exact[0]

    # ---- a deal from inquiry to purchase orders ----------------------------------------------------------------------
    def case(self, key, title, buyer, items) -> tuple[dict, list[dict]]:
        case = self.api.post("/api/cases", {"title": title, "party_id": self.p[buyer]["id"]})
        rows = self.api.post("/api/line-items/bulk", {"case_id": case["id"], "items": items})["items"]
        self.cases[key] = case
        return case, rows

    def rfq(self, case, items, suppliers, respond_days=5):
        rfq = self.api.post("/api/rfqs", {"case_id": case["id"], "respond_by": day(respond_days),
                                          "items": [{"line_item_id": i["id"]} for i in items],
                                          "recipients": [{"party_id": self.p[s]["id"]} for s in suppliers]})
        for rec in rfq["recipients"]:
            self.api.post(f"/api/rfqs/recipients/{rec['id']}/mark-sent", {})
        return rfq

    def offer(self, case, supplier, rows, currency, valid=30, rfq=None, **extra):
        if rfq is not None:     # v0.10.1 (0.4.6): the priced reply answers its RFQ recipient (and closes its chase)
            extra["rfq_recipient_id"] = next(r["id"] for r in rfq["recipients"] if r["party_id"] == self.p[supplier]["id"])
        body = {"case_id": case["id"], "party_id": self.p[supplier]["id"], "channel": "email", "currency": currency,
                "valid_until": day(valid), "items": rows, "no_followup_reason": "مقایسهٔ پیشنهادها", "incoterm": "CFR",
                "lead_time_days": 35, **extra}
        return self.api.post("/api/offers", body)

    def select(self, offer):
        for row in offer["items"]:
            self.api.post(f"/api/line-items/{row['line_item_id']}/select", {"offer_item_id": row["id"]})

    def sheet(self, case, rates: dict[str, str], freight="180000000", duty="240000000", margin="18"):
        sheet = self.api.post("/api/cost-sheets", {"case_id": case["id"], "deal_type": "import", "pricing_currency": "IRR"})
        sid = sheet["id"]
        for cur, rate in rates.items():
            self.api.put(f"/api/cost-sheets/{sid}/fx", {"from_currency": cur, "to_currency": "IRR", "rate": rate,
                                                        "rate_kind": "free market", "source_note": "صرافی نمونه", "as_of": day(0)})
        for line in sheet["lines"]:
            if line["kind"] == "purchase":
                continue
            body = {"freight_international": {"amount": freight, "currency": "IRR"},
                    "customs_duty": {"basis": "total", "amount": duty, "currency": "IRR"}}.get(line["kind"])
            if body is None:
                body = {"percent": "1", "tax_parameter_id": None} if line["basis"].startswith("percent") else {"amount": "15000000", "currency": "IRR"}
            self.api.patch(f"/api/cost-sheets/lines/{line['id']}", body)
        self.api.patch(f"/api/cost-sheets/{sid}", {"pricing_method": "margin", "target_percent": margin,
                                                   "annual_cost_of_money_percent": "30"})
        return self.api.post(f"/api/cost-sheets/{sid}/finalize")

    def quote(self, case, sent=True, outcome: str | None = None):
        quote = self.api.post("/api/quotes", {"case_id": case["id"]})
        if sent:
            self.api.post(f"/api/quotes/{quote['id']}/approve")
            quote = self.api.post(f"/api/quotes/{quote['id']}/mark-sent", {})
        if outcome:
            rows = [{"quote_item_id": i["id"], "outcome": outcome, **({"outcome_reason": "price"} if outcome == "rejected" else {})}
                    for i in quote["items"]]
            quote = self.api.put(f"/api/quotes/{quote['id']}/outcomes", {"items": rows})
        return quote

    def order(self, quote, delivery_in: int | None = None):
        so = self.api.post("/api/sales-orders/from-quote", {"quote_id": quote["id"]})
        if delivery_in is not None:
            self.api.patch(f"/api/sales-orders/{so['id']}", {"delivery_due_on": day(delivery_in)})
        return self.api.post(f"/api/sales-orders/{so['id']}/confirm", {"no_document_reason": "قرارداد کاغذی در بایگانی"})

    def purchase_orders(self, so, ready_in=20, send=True):
        pos = self.api.post(f"/api/sales-orders/{so['id']}/purchase-orders")["created"]
        out = {}
        for po in pos:
            if send:
                self.api.post(f"/api/purchase-orders/{po['id']}/approve")
                self.api.post(f"/api/purchase-orders/{po['id']}/mark-sent", {})
                po = self.api.post(f"/api/purchase-orders/{po['id']}/confirm", {"confirmed_ready_on": day(ready_in)})
            out[po["currency"]] = po
        return out

    def document(self, name: str, text_line: str) -> dict:
        import pymupdf

        pdf = pymupdf.open()
        pdf.new_page().insert_text((72, 90), text_line + f"  {uuid.uuid4().hex[:8]}", fontsize=11)
        data = pdf.tobytes()
        pdf.close()
        r = self.api.client.post("/api/documents", files={"file": (name, data, "application/pdf")}, headers={"X-CSRF-Token": CSRF})
        if r.status_code not in (200, 201):
            raise DemoError(f"upload {name} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def complete_steps(self, case: dict, upto: int, start_days: int = -30, current_due: int = 1) -> None:
        """The deal's checklist done through position ``upto`` (with a file where one is required); the next step is
        in progress and due in ``current_due`` days."""
        ex = self.api.get(f"/api/cases/{case['id']}/execution")
        for proc in ex.get("processes", []):
            for i, step in enumerate(sorted(proc["steps"], key=lambda x: x["position"])):
                if step["position"] <= upto:
                    body = {"status": "done", "done_on": day(start_days + 3 * i), "started_on": day(start_days + 3 * i - 1)}
                    if step["requires_document"]:
                        body["document_id"] = self.document(f"{step['label_fa']}.pdf", step["label_en"])["id"]
                    if step.get("reference_label"):
                        body["reference"] = f"DEMO-{step['code'].upper()[:6]}-{i + 1:03d}"
                    self.api.patch(f"/api/process-steps/{step['id']}", body)
                elif step["position"] == upto + 1:
                    self.api.patch(f"/api/process-steps/{step['id']}", {"status": "in_progress", "started_on": day(-1), "due_on": day(current_due)})

    def milestone(self, ref: dict, direction: str, amount: str, currency: str, due: int, kind="balance", label=None, party=None):
        body = {"kind": kind, "amount": amount, "amount_currency": currency, "due_on": day(due)}
        if direction == "in":
            body["sales_order_id"] = ref["id"]
        else:
            body["purchase_order_id"] = ref["id"]
        if label:
            body["label"] = label
        return self.api.post("/api/payment-milestones", body)

    def pay(self, ms, amount, on: int, **extra):
        return self.api.post(f"/api/payment-milestones/{ms['id']}/payments", {"amount": amount, "paid_on": day(on), **extra})

    # ---- scenarios ------------------------------------------------------------------------------------------------------
    def sea_import(self) -> None:
        """Deal 1: pumps and valves for the refinery, by sea CNSHA → AEJEA → IRBND, 4 days late, in transit."""
        case, items = self.case("sea", "پمپ و شیرآلات واحد تقطیر — پتروپالایش", "petro", [
            {"name": "پمپ سانتریفیوژ ۷۵ کیلووات", "quantity": "4", "unit_code": "pc"},
            {"name": "شیر کشویی ۸ اینچ کلاس ۳۰۰", "quantity": "24", "unit_code": "pc"}])
        self.rfq(case, items, ["ningbo", "hamburg", "shanghai"])
        o1 = self.offer(case, "hamburg", [{"line_item_id": items[0]["id"], "unit_price": "18500"}], "EUR")
        o2 = self.offer(case, "ningbo", [{"line_item_id": items[1]["id"], "unit_price": "1240"},
                                         {"line_item_id": items[0]["id"], "unit_price": "21000"}], "USD")
        self.offer(case, "shanghai", [{"line_item_id": items[1]["id"], "unit_price": "1390"}], "USD")
        self.select({"items": [o1["items"][0]]})
        self.select({"items": [r for r in o2["items"] if r["line_item_id"] == items[1]["id"]]})
        self.sheet(case, {"USD": "820000", "EUR": "890000"})
        quote = self.quote(case, outcome="accepted")
        so = self.order(quote, delivery_in=25)
        pos = self.purchase_orders(so, ready_in=-12)
        usd, eur = pos["USD"], pos["EUR"]
        self.api.post(f"/api/purchase-orders/{usd['id']}/status", {"status": "ready", "on_date": day(-10)})
        self.api.post(f"/api/purchase-orders/{eur['id']}/status", {"status": "ready", "on_date": day(-14)})
        self.api.post("/api/inspections", {"purchase_order_id": usd["id"], "kind": "pre_shipment", "inspector_party_id": self.p["inspector"]["id"],
                                           "done_on": day(-11), "result": "pass"})
        self.api.post("/api/inspections", {"purchase_order_id": eur["id"], "kind": "pre_shipment", "inspector_party_id": self.p["inspector"]["id"],
                                           "done_on": day(-15), "result": "conditional", "notes": "برچسب پلاک نصب نشده بود؛ اصلاح شد"})
        sh = self.api.post("/api/shipments", {
            "purchase_order_id": usd["id"], "mode": "sea", "carrier_party_id": self.p["caspian"]["id"],
            "forwarder_party_id": self.p["forwarder"]["id"], "transport_doc_kind": "bl", "transport_doc_no": "CSLDEMO240917",
            "tracking_number": "CSLDEMO240917", "vessel_or_flight": "MV Caspian Pearl (نمونه)", "incoterm": "CFR",
            "origin_location_id": self.loc.get("CNSHA", {}).get("id"), "destination_location_id": self.loc.get("IRBND", {}).get("id"),
            "etd": day(-9), "eta": day(8), "container_units": [{"number": "MSCU1234566", "container_type": "45G1"},
                                                             {"number": "TGHU7654320", "container_type": "45G1"}],
            "items": [{"purchase_order_item_id": i["id"], "quantity": i["quantity"]} for i in usd["items"]]})
        sid = sh["id"]
        self.api.patch(f"/api/shipments/{sid}", {"atd": day(-8)})
        self.api.post(f"/api/shipments/{sid}/events", {"kind": "loaded", "at": at(-9, 16), "location_id": self.loc.get("CNSHA", {}).get("id")})
        self.api.post(f"/api/shipments/{sid}/events", {"kind": "transshipment", "at": at(-2, 7), "location_id": self.loc.get("AEJEA", {}).get("id"),
                                                       "note": "انتقال به کشتی فیدر"})
        self.api.patch(f"/api/shipments/{sid}", {"eta": day(12)})            # the 4-day delay
        for kind, number, name in (("bl", "CSLDEMO240917", "بارنامه-CSLDEMO240917.pdf"),
                                   ("commercial_invoice", "NDV-CI-0917", "فاکتور-تجاری-نینگبو.pdf")):
            doc = self.document(name, f"{kind} {number} (demo)")
            self.api.post(f"/api/shipments/{sid}/documents", {"kind": kind, "document_id": doc["id"], "number": number, "issued_on": day(-8)})
        # money: prepayments done, balances over the next weeks
        self.pay(self.milestone(so, "in", "6000000000", "IRR", -20, kind="prepayment"), "6000000000", -18)
        self.pay(self.milestone(usd, "out", "8900", "USD", -15, kind="prepayment"), "8900", -15, fx_rate_to_base="815000")
        self.pay(self.milestone(eur, "out", "22200", "EUR", -16, kind="prepayment"), "22200", -16, fx_rate_to_base="885000")
        self.milestone(usd, "out", "20860", "USD", 6)
        self.milestone(eur, "out", "51800", "EUR", 9)
        self.milestone(so, "in", "38000000000", "IRR", 21)
        self.complete_steps(case, 6, start_days=-34, current_due=1)
        self.cases["sea_so"], self.cases["sea_usd"] = so, usd

    def air_import(self) -> None:
        """Deal 2: motor spare parts by air PVG → IKA, arrived, at customs."""
        case, items = self.case("air", "قطعات یدکی الکتروموتور — فولاد کویر", "steel", [
            {"name": "بلبرینگ الکتروموتور ۶۳۱۶", "quantity": "60", "unit_code": "pc"},
            {"name": "سیم‌پیچ استاتور ۱۳۲ کیلووات", "quantity": "6", "unit_code": "pc"}])
        self.rfq(case, items, ["shanghai", "ningbo"])
        o = self.offer(case, "shanghai", [{"line_item_id": items[0]["id"], "unit_price": "95"},
                                          {"line_item_id": items[1]["id"], "unit_price": "2300"}], "USD")
        self.offer(case, "ningbo", [{"line_item_id": items[0]["id"], "unit_price": "110"},
                                    {"line_item_id": items[1]["id"], "unit_price": "2150"}], "USD")
        self.select(o)
        self.sheet(case, {"USD": "820000"}, freight="95000000", duty="60000000")
        so = self.order(self.quote(case, outcome="accepted"), delivery_in=10)
        po = self.purchase_orders(so, ready_in=-6)["USD"]
        self.api.post(f"/api/purchase-orders/{po['id']}/status", {"status": "ready", "on_date": day(-8)})
        self.api.post("/api/inspections", {"purchase_order_id": po["id"], "kind": "pre_shipment", "done_on": day(-7), "result": "pass"})
        sh = self.api.post("/api/shipments", {
            "purchase_order_id": po["id"], "mode": "air", "carrier_party_id": self.p["skyline"]["id"], "transport_doc_kind": "awb",
            "transport_doc_no": "176-12345675", "vessel_or_flight": "SL 718", "origin_location_id": self.loc.get("CNPVG", {}).get("id"),
            "destination_location_id": self.loc.get("IRIKA", {}).get("id"), "etd": day(-5), "eta": day(-3),
            "items": [{"purchase_order_item_id": i["id"], "quantity": i["quantity"]} for i in po["items"]]})
        self.api.patch(f"/api/shipments/{sh['id']}", {"atd": day(-5), "ata": day(-3)})
        self.api.patch(f"/api/shipments/{sh['id']}", {"status": "at_customs"})
        self.pay(self.milestone(po, "out", "6000", "USD", -10, kind="prepayment"), "6000", -10, fx_rate_to_base="818000")
        self.milestone(po, "out", "13500", "USD", 4)
        self.milestone(so, "in", "21500000000", "IRR", 30)
        self.complete_steps(case, 8, start_days=-30, current_due=2)

    def closed_deal(self, key: str, title: str, buyer: str, supplier: str, item: str, qty: str, price: str, rate: str,
                    closed_days_ago: int) -> None:
        """Deals 3 and 4: delivered, invoiced, paid both ways and closed — with real profit."""
        case, items = self.case(key, title, buyer, [{"name": item, "quantity": qty, "unit_code": "pc"}])
        self.rfq(case, items, [supplier, "istanbul"])
        o = self.offer(case, supplier, [{"line_item_id": items[0]["id"], "unit_price": price}], "USD")
        self.offer(case, "istanbul", [{"line_item_id": items[0]["id"], "unit_price": str(Decimal(price) * Decimal("1.12"))}], "USD")
        self.select(o)
        self.sheet(case, {"USD": rate}, freight="60000000", duty="45000000", margin="16")
        so = self.order(self.quote(case, outcome="accepted"))
        po = self.purchase_orders(so, ready_in=-40)["USD"]
        self.api.post(f"/api/purchase-orders/{po['id']}/status", {"status": "ready", "on_date": day(-41)})
        self.api.post("/api/inspections", {"purchase_order_id": po["id"], "kind": "on_arrival", "done_on": day(-30),
                                           "result": "pass" if supplier == "ningbo" else "fail", "notes": "بازرسی ورود کالا"})
        self.api.post("/api/receipts", {"purchase_order_id": po["id"], "received_on": day(-30),
                                        "items": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": qty}]})
        self.api.post("/api/deliveries", {"sales_order_id": so["id"], "delivered_on": day(-25),
                                          "items": [{"sales_order_item_id": i["id"], "quantity": i["quantity"]} for i in so["items"]]})
        inv = self.api.post("/api/sales-invoices", {"sales_order_id": so["id"]})
        inv = self.api.post(f"/api/sales-invoices/{inv['id']}/issue")
        self.api.post(f"/api/sales-invoices/{inv['id']}/moadian", {"moadian_status": "accepted", "moadian_tax_id": f"TXDEMO{key.upper()}"})
        ms_in = self.milestone(so, "in", inv["total"], "IRR", -20)
        self.pay(ms_in, inv["total"], -20, reference=f"DEMO-IN-{key}")
        pi = self.api.post("/api/purchase-invoices", {"purchase_order_id": po["id"], "supplier_invoice_no": f"INV-DEMO-{key}",
                                                      "invoice_date": day(-35)})
        self.api.post(f"/api/purchase-invoices/{pi['id']}/approve")
        ms_out = self.milestone(po, "out", po["total"], "USD", -33)
        self.pay(ms_out, po["total"], -33, fx_rate_to_base=rate)
        for rec in self.api.get(f"/api/cases/{case['id']}/finance")["payments"]:
            target = {"sales_invoice_id": inv["id"]} if rec["direction"] == "in" else {"purchase_invoice_id": pi["id"]}
            self.api.post(f"/api/payment-records/{rec['id']}/allocations", {"allocations": [{**target, "amount": rec["amount"]}]})
        check = self.api.get(f"/api/cases/{case['id']}/close-checklist")
        reasons = {p["code"]: "بررسی شد (دادهٔ نمایشی)" for p in check["problems"]}
        self.api.post(f"/api/cases/{case['id']}/close", {"reasons": reasons, "confirm_cancel_open": True})
        self.api.post(f"/api/cases/{case['id']}/ratings", {"party_id": self.p[supplier]["id"], "role": "supplier",
                                                          "quality": 4 if supplier == "ningbo" else 3, "timeliness": 5, "communication": 4, "price": 4})
        self.cases[key + "_closed_days"] = {"days": closed_days_ago, "id": case["id"]}

    def quoted(self) -> None:
        """Deal 5: quote sent, waiting for the buyer (expires soon)."""
        case, items = self.case("quoted", "لولهٔ پلی‌اتیلن خط انتقال — آب‌وفاضلاب البرز", "water", [
            {"name": "لوله پلی‌اتیلن ۱۱۰ میلی‌متر PN16", "quantity": "1200", "unit_code": "m"}])
        self.rfq(case, items, ["istanbul", "ningbo"])
        o = self.offer(case, "istanbul", [{"line_item_id": items[0]["id"], "unit_price": "6.4"}], "EUR", valid=20)
        self.offer(case, "ningbo", [{"line_item_id": items[0]["id"], "unit_price": "7.1"}], "USD", valid=20)
        self.select(o)
        self.sheet(case, {"EUR": "890000", "USD": "820000"}, freight="70000000", duty="40000000")
        self.quote(case)

    def rfq_stage(self) -> None:
        """Deal 6: RFQs out, two offers in, comparing (one supplier has not answered)."""
        case, items = self.case("rfq", "الکتروموتور ضدانفجار — پیمانکاری خلیج", "gulf", [
            {"name": "الکتروموتور ضدانفجار ۵۵ کیلووات", "quantity": "8", "unit_code": "pc"},
            {"name": "تابلو راه‌انداز نرم", "quantity": "8", "unit_code": "pc"}])
        rfq = self.rfq(case, items, ["shanghai", "hamburg", "ningbo"])
        self.offer(case, "shanghai", [{"line_item_id": items[0]["id"], "unit_price": "4100"},
                                      {"line_item_id": items[1]["id"], "unit_price": "1300"}], "USD", rfq=rfq)
        self.offer(case, "hamburg", [{"line_item_id": items[0]["id"], "unit_price": "4650"}], "EUR", rfq=rfq)
        self.correspondence(rfq)

    def correspondence(self, rfq) -> None:
        """v0.10.1 (0.4.6): the factory replies without a price (saved from its mail client as .eml, with a datasheet):
        it asks a question; then one chase. Two priced replies came in above."""
        ningbo = next(r for r in rfq["recipients"] if r["party_id"] == self.p["ningbo"]["id"])
        address = "li.wen@ningbo-valves.example.invalid"
        self.api.post("/api/contacts", {"party_id": self.p["ningbo"]["id"], "name_en": "Ms. Li Wen (sales)",
                                        "methods": [{"type": "email", "value": address}]})
        doc = self.api.upload("Re-RFQ-motor.eml", demo_eml(address, f"Re: [{rfq['code']}] Request for Quotation",
                                                           "Dear Sir,\nBefore we quote: is the motor for zone 1 or zone 2?\n"
                                                           "Our ATEX datasheet is attached.\nBest regards,\nLi Wen"),
                              "message/rfc822")
        self.api.post(f"/api/rfqs/recipients/{ningbo['id']}/reply", {
            "kind": "question", "body": "Before we quote: is the motor for zone 1 or zone 2? Our ATEX datasheet is attached.",
            "subject": f"Re: [{rfq['code']}] Request for Quotation", "raw_document_id": doc["id"], "next_due_on": day(2)})
        self.api.post(f"/api/rfqs/recipients/{ningbo['id']}/chase", {
            "subject": f"[{rfq['code']}] Zone 1 — please quote", "body": "Dear Ms. Li Wen,\nThe motors are for zone 1. Please send your price.",
            "next_due_on": day(3)})

    def inquiry(self) -> None:
        """Deal 7: a fresh inquiry, items only."""
        self.case("inquiry", "شیرآلات ایمنی مخازن — پتروپالایش", "petro", [
            {"name": "شیر اطمینان ۲ اینچ", "quantity": "16", "unit_code": "pc"},
            {"name": "شیر یک‌طرفه ۴ اینچ", "quantity": "10", "unit_code": "pc"}])

    def lost(self) -> None:
        """Deal 8: a quote the buyer turned down (price)."""
        case, items = self.case("lost", "پمپ آتش‌نشانی — فولاد کویر", "steel", [
            {"name": "پمپ آتش‌نشانی ۵۰۰ گالن", "quantity": "2", "unit_code": "pc"}])
        self.rfq(case, items, ["hamburg", "ningbo", "istanbul"])
        o = self.offer(case, "hamburg", [{"line_item_id": items[0]["id"], "unit_price": "26000"}], "EUR")
        self.offer(case, "ningbo", [{"line_item_id": items[0]["id"], "unit_price": "24500"}], "USD")
        self.offer(case, "istanbul", [{"line_item_id": items[0]["id"], "unit_price": "27400"}], "EUR")
        self.select(o)
        self.sheet(case, {"EUR": "890000", "USD": "820000"})
        self.quote(case, outcome="rejected")

    def tender(self) -> None:
        """Deal 9: a public tender with envelopes, two documents missing, deadline in 4 days."""
        case, items = self.case("tender", "مناقصهٔ تأمین پمپ ایستگاه‌های پمپاژ — آب‌وفاضلاب البرز", "water", [
            {"name": "پمپ شناور ۴۵ کیلووات", "quantity": "6", "unit_code": "pc"}])
        self.rfq(case, items, ["hamburg", "shanghai", "istanbul"])
        o = self.offer(case, "hamburg", [{"line_item_id": items[0]["id"], "unit_price": "9800"}], "EUR")
        self.offer(case, "shanghai", [{"line_item_id": items[0]["id"], "unit_price": "8700"}], "USD")
        self.offer(case, "istanbul", [{"line_item_id": items[0]["id"], "unit_price": "9650"}], "EUR")
        self.select(o)
        self.sheet(case, {"EUR": "890000", "USD": "820000"})
        t = self.api.post(f"/api/cases/{case['id']}/tender")
        self.api.patch(f"/api/tenders/{t['id']}", {"tender_no": "2005-DEMO-0418", "organizer_party_id": self.p["water"]["id"],
                                                   "tender_type": "public", "participation": "yes",
                                                   "document_price": "1500000", "document_price_currency": "IRR"})
        for kind, days in (("documents_deadline", 1), ("proposal_deadline", 4), ("opening", 6)):
            self.api.post(f"/api/tenders/{t['id']}/dates", {"kind": kind, "at": at(days, 14)})
        for e, rows in (("a", [("ضمانت‌نامهٔ شرکت در مناقصه", "bid_bond", "in_progress"), ("فیش خرید اسناد", "document", "ready")]),
                        ("b", [("اساسنامه و آگهی تغییرات", "document", "ready"), ("گواهی صلاحیت پیمانکاری", "document", "not_ready"),
                               ("رزومهٔ کاری", "document", "needs_signature")]),
                        ("c", [("پیشنهاد قیمت امضاشده", "price_form", "not_ready")])):
            for title, kind, status in rows:
                body = {"envelope": e.upper(), "title": title, "kind": kind, "status": status}
                if status == "ready":
                    body["document_id"] = self.document(f"{title}.pdf", title)["id"]
                self.api.post(f"/api/tenders/{t['id']}/envelope-items", body)
        self.api.post("/api/guarantees", {"case_id": case["id"], "tender_id": t["id"], "purpose": "bid", "amount": "1500000000",
                                          "amount_currency": "IRR"}, ok=(200, 201, 422))

    def payments_plan(self) -> None:
        """Milestones in IRR, USD and EUR over the next 90 days; the week of day 6-12 goes below zero (payables first)."""
        usd = self.cases.get("sea_usd")
        if usd:
            self.milestone(usd, "out", "4200", "USD", 45, kind="other", label="حمل داخلی و ترخیص")
        so = self.cases.get("sea_so")
        if so:
            self.milestone(so, "in", "4500000000", "IRR", 60, kind="other", label="تسویهٔ نهایی")
            # customs duty and clearance before the buyer's balance: the IRR line dips below zero in week two
            self.api.post("/api/payment-milestones", {"case_id": so["case_id"], "direction": "out", "party_id": self.p["forwarder"]["id"],
                                                      "kind": "other", "label": "حقوق گمرکی و ترخیص", "amount": "9500000000",
                                                      "amount_currency": "IRR", "due_on": day(10)})

    def listings(self) -> None:
        from app.core.db import new_session
        from app.connectors.setad.rows import SOURCE_TENDER
        from app.modules.listings.store import ListingStore

        store = ListingStore(new_session)
        store.start_run(SOURCE_TENDER, "full")
        rows = []
        titles = ["خرید پمپ سانتریفیوژ ایستگاه پمپاژ شمارهٔ ۲", "تأمین شیرآلات کشویی خط انتقال", "خرید لولهٔ پلی‌اتیلن ۲۵۰ میلی‌متر",
                  "تعمیر و بازسازی الکتروموتورهای ایستگاه", "خرید تابلو برق فشار ضعیف", "تأمین مواد شیمیایی تصفیه‌خانه",
                  "خرید شیر پروانه‌ای ۱۲ اینچ", "خرید پمپ کفکش و اتصالات"]
        today_j = _jalali(date.today())
        for i, title in enumerate(titles):
            rows.append({"id": f"DEMO{i}", "number": f"20050000004{i:02d}", "title": title, "typeName": "مناقصه عمومی",
                         "operationProvinceName": "البرز", "operationCityName": "کرج",
                         "organization": {"id": 9000 + i, "name": "شرکت آب‌وفاضلاب نمونه"},
                         "publicNotificationDate": f"{today_j} 09:00:00", "documentsDeadlineDate": _jalali(date.today() + timedelta(days=3 + i)) + " 12:00:00",
                         "proposalDeadlineDate": _jalali(date.today() + timedelta(days=6 + i)) + " 14:00:00",
                         "tenderDocumentsPrice": 1500000.0, "recCount": 100 + i})
        store.add_tenders(rows)
        store.finish_run("done")

    def ai_draft(self) -> None:
        """An extraction draft from a scanned proforma, waiting for review, with several low-confidence fields."""
        from app.core.db import new_session
        from app.modules.ai import drafts

        case = self.cases.get("rfq")
        pdf = _proforma_pdf()
        doc = self.api.client.post("/api/documents", files={"file": ("پیش‌فاکتور-اسکن‌شده-شانگهای.pdf", pdf, "application/pdf")},
                                   headers={"X-CSRF-Token": CSRF}).json()
        with new_session() as db:
            d = drafts.create(db, task="extraction", target_type="offer", case_id=uuid.UUID(case["id"]) if case else None,
                              sources=[{"document_id": doc.get("id"), "title": doc.get("title")}], source="ui", actor="admin")
            box = lambda y: {"document_id": doc.get("id"), "page": 1, "bbox": [72, y, 400, y + 14]}   # noqa: E731
            drafts.fill(db, d, [
                {"path": "party.name", "label": "تأمین‌کننده", "proposed": "Shanghai Demo Motors Ltd.", "confidence": "high", "source": box(80)},
                {"path": "offer.currency", "label": "ارز", "proposed": "USD", "confidence": "high", "source": box(110)},
                {"path": "offer.valid_until", "label": "اعتبار تا", "proposed": day(25), "confidence": "low", "source": box(130)},
                {"path": "offer.incoterm", "label": "اینکوترمز", "proposed": "CIF", "confidence": "medium", "source": box(150)},
                {"path": "items[0].unit_price", "label": "قیمت واحد ردیف ۱", "proposed": "4050", "confidence": "low", "source": box(200)},
                {"path": "items[0].quantity", "label": "مقدار ردیف ۱", "proposed": "8", "confidence": "high", "source": box(200)},
                {"path": "items[1].unit_price", "label": "قیمت واحد ردیف ۲", "proposed": "1280", "confidence": "low", "source": box(220)},
                {"path": "offer.lead_time_days", "label": "زمان تحویل (روز)", "proposed": 45, "confidence": "medium", "source": box(260)},
            ])
            db.commit()

    def tasks_and_followups(self) -> None:
        """Enough to show the caps: 11 tasks today (3 done), 10 overdue, 4 tomorrow; follow-ups overdue and today."""
        cases = [c for k, c in self.cases.items() if isinstance(c, dict) and "title" in c]
        titles_today = ["تماس با گمرک بندرعباس دربارهٔ ارزش‌گذاری", "ارسال پیش‌نویس قرارداد به پتروپالایش", "پیگیری ثبت سفارش در سامانهٔ جامع تجارت",
                        "هماهنگی بازرسی پیش از حمل", "تمدید بیمه‌نامهٔ باربری", "ارسال اسناد حمل به بانک", "بررسی پیشنهاد هامبورگ",
                        "آماده‌سازی پاکت ب مناقصه", "تسویهٔ هزینهٔ انبارداری", "پاسخ به پرسش فنی فولاد کویر", "رزرو حمل داخلی از بندر"]
        made = []
        for i, title in enumerate(titles_today):
            due_at = at(0, 9 + i % 8, 30) if i % 3 else None
            made.append(self.api.post("/api/tasks", {"title": title, "due_on": day(0), "due_at": due_at,
                                                     "priority": "high" if i in (0, 7) else "normal",
                                                     "case_id": cases[i % len(cases)]["id"] if cases else None}))
        for t in made[:3]:
            self.api.post(f"/api/tasks/{t['id']}/done", {"note": "انجام شد"})
        for i in range(10):
            self.api.post("/api/tasks", {"title": f"پیگیری مدارک ترخیص — مرحلهٔ {_fa(i + 1)}", "due_on": day(-1 - i),
                                         "case_id": cases[(i + 2) % len(cases)]["id"] if cases else None})
        for i in range(4):
            self.api.post("/api/tasks", {"title": f"آماده‌سازی گزارش هفتگی {_fa(i + 1)}", "due_on": day(1)})
        for key, days, action in (("petro", -3, "پیگیری پاسخ به پیش‌فاکتور"), ("steel", -2, "هماهنگی زمان تحویل"),
                                  ("water", -1, "ارسال رزومه برای ارزیابی"), ("gulf", 0, "تماس دربارهٔ مشخصات فنی"),
                                  ("ningbo", 0, "پیگیری زمان آماده‌شدن"), ("hamburg", 0, "درخواست گواهی مبدأ"),
                                  ("istanbul", 2, "بررسی پیشنهاد جدید"), ("shanghai", 3, "پیگیری بارنامه")):
            self.api.post("/api/followups", {"party_id": self.p[key]["id"], "due_on": day(days), "action": action})

    # ---- facts only time produces ------------------------------------------------------------------------------------------
    def backdate(self, db) -> None:
        """On the demo database only: a deal closed last quarter, offers that took hours or days to arrive."""
        for key in ("closed_this", "closed_last"):
            info = self.cases.get(key + "_closed_days")
            if not info:
                continue
            when = datetime.now(timezone.utc) - timedelta(days=info["days"])
            db.execute(text("UPDATE ops.deal_result SET computed_at = :w, created_at = :w WHERE case_id = :c"), {"w": when, "c": info["id"]})
            db.execute(text("UPDATE ops.case SET updated_at = :w WHERE id = :c"), {"w": when, "c": info["id"]})
        # response times: RFQs sent days before, offers received hours to days later (per supplier)
        hours = {"ningbo": 20, "hamburg": 54, "shanghai": 30, "istanbul": 70}
        for key, h in hours.items():
            db.execute(text("""UPDATE ops.rfq_recipient SET sent_at = now() - interval '9 days' WHERE party_id = :p"""), {"p": self.p[key]["id"]})
            db.execute(text("""UPDATE ops.supplier_offer o SET received_at = rr.sent_at + make_interval(hours => :h)
                               FROM ops.rfq_recipient rr WHERE rr.id = o.rfq_recipient_id AND o.party_id = :p"""),
                       {"p": self.p[key]["id"], "h": h})

    def run(self, db_factory) -> dict:
        steps = [("company", self.company), ("parties", self.parties), ("locations", self.locations),
                 ("sea import", self.sea_import), ("air import", self.air_import),
                 ("closed this quarter", lambda: self.closed_deal("closed_this", "شیرآلات کشویی — پتروپالایش (بسته‌شده)", "petro",
                                                                 "ningbo", "شیر کشویی ۶ اینچ", "40", "820", "805000", 12)),
                 ("closed last quarter", lambda: self.closed_deal("closed_last", "پمپ تزریق مواد — آب‌وفاضلاب (بسته‌شده)", "water",
                                                                 "hamburg", "پمپ دوزینگ", "12", "2100", "780000", _last_quarter_days())),
                 ("quoted", self.quoted), ("rfq", self.rfq_stage), ("inquiry", self.inquiry), ("lost", self.lost),
                 ("tender", self.tender), ("payments", self.payments_plan), ("listings", self.listings),
                 ("ai draft", self.ai_draft), ("tasks", self.tasks_and_followups)]
        for name, fn in steps:
            self.log(f"demo: {name}")
            fn()
        with db_factory() as db:
            self.backdate(db)
            db.commit()
        return {"cases": len([c for c in self.cases.values() if isinstance(c, dict) and "title" in c]), "parties": len(self.p)}


EVENT_BACKDATE_SQL = """
    WITH ranked AS (
        SELECT id, row_number() OVER (PARTITION BY entity_id ORDER BY id) AS i, count(*) OVER (PARTITION BY entity_id) AS n
        FROM core.event WHERE entity_type = 'case')
    UPDATE core.event e SET occurred_at = now() - make_interval(days => (36 * (r.n - r.i) / greatest(r.n, 1))::int + 1)
                                           - make_interval(hours => ((r.i * 3) % 9)::int)
    FROM ranked r WHERE r.id = e.id"""


def backdate_events(superuser_conninfo: dict, dbname: str) -> None:
    """Each case's story spread over the weeks before today, in the order it happened. The event log is append-only
    for the app's role, so this runs as the PostgreSQL superuser — on the demo database only."""
    import psycopg

    if not is_demo_database(dbname):
        raise DemoError(f"refusing to rewrite events outside the demo database ({dbname})")
    with psycopg.connect(**superuser_conninfo, dbname=dbname) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")   # the append-only trigger, for this statement only
        conn.execute(EVENT_BACKDATE_SQL)
        conn.commit()


def _fa(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _jalali(d: date) -> str:
    from app.modules.sourcing.jalali import to_jalali

    y, m, dd = to_jalali(d)
    return f"{y}/{m:02d}/{dd:02d}"


def _last_quarter_days() -> int:
    """Days back to the middle of the previous Jalali season (the profit tile counts by the user's calendar)."""
    from app.modules.sourcing.jalali import to_jalali

    season = lambda d: (to_jalali(d)[0], (to_jalali(d)[1] - 1) // 3)   # noqa: E731
    today, n = date.today(), 0
    while season(today - timedelta(days=n)) == season(today):
        n += 1
    return n + 40


def _proforma_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    lines = ["SHANGHAI DEMO MOTORS LTD.  (fictional)", "PROFORMA INVOICE No. SDM-PI-0917", "Currency: USD    Valid until: see below",
             "Incoterm: CIF Bandar Abbas", "", "1. Explosion-proof motor 55 kW   8 pcs   4,050.00", "2. Soft starter panel          8 pcs   1,280.00",
             "", "Lead time: 45 days after deposit"]
    for i, line in enumerate(lines):
        page.insert_text((72, 90 + i * 20), line, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data
