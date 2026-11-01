"""An offline fake of the three Setad hosts for the agent tests and the browser check.

``install(context)`` routes every request of the agent's browser: *.setadiran.ir is answered here from generated
data, anything else is aborted (the context also has a dead proxy). Nothing ever reaches the real site.

Behaviour reproduced from what the ported code expects (and from SetadSuite's own recordings):
- sso2: a login page (password field) that "logs in" by itself after BOMS_SETAD_FAKE_LOGIN_MS, then Setad's role
  page (system radios EPROC/ETEND, role radios, «شروع»); the role decides which system is served.
- eproc: needBoardInfo-load.do, needAdvancedSearch.do (form; result pages of 30 rows, 12 cells, pagebanner and
  d-146909-p links; ``needDateFrom`` filters a quick update), ONE captcha on the first visit of result page 2 that
  "is solved" after BOMS_SETAD_FAKE_CAPTCHA_MS (the owner typing it), purchaseNeedView.do detail forms,
  anonymousAppendixDocument.do attachment lists and appendixDocument.do?method=viewFile downloads.
- etend: indexPage.action with a jqGrid stand-in (#tendersGrid, getGridParam), the grid JSON, favoriteForm /
  callMainPageCartable-add.action, reloadCsrfToken, myCallsCartable-execute/-search/-delete, and (v0.6.0)
  tenderDetails-execute.action: a #tenderDetailsForm of label/value rows; tenders without a guarantee in the list
  carry it there as «مبلغ تضمین».
State lives in this process (FAKE).
"""
from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import parse_qs, urlparse

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ORGS = ["بیمارستان امام خمینی", "شرکت آب و فاضلاب استان یزد", "دانشگاه علوم پزشکی شیراز", "شهرداری تفت",
        "شركت ملی گاز ایران"]   # Arabic kaf in the last one: normalized search must find it as «شرکت»
PROVINCES = [("یزد", "تفت"), ("فارس", "شیراز"), ("تهران", "تهران"), ("البرز", "کرج")]
ITEMS = ["کارتریج پلاسما", "لوله پلی‌اتیلن ۱۱۰", "شیر فلکه برنجی", "کالای مصرفی آزمایشگاه", "پمپ سانتریفیوژ"]


def _jalali(day_offset: int) -> str:
    from datetime import date, timedelta

    from app.connectors.setad.dates import jalali_of
    return jalali_of(date.today() + timedelta(days=day_offset))


class Fake:
    def __init__(self, needs: int = 75, tenders: int = 120):
        self.logged_in = False
        self.role = None
        self.captcha_pending = True          # one captcha, on the first visit of result page 2
        self.captchas_shown = 0
        self.my_calls: set[str] = set()
        self.add_requests: list[dict] = []
        self.delete_requests: list[str] = []
        self.waf_files: set[str] = set()     # v0.6.0: attachments answered with an HTML block page (a failing file)
        self.needs = [self._need(i) for i in range(needs)]
        self.tenders = [self._tender(i) for i in range(tenders)]

    def _need(self, i: int) -> dict:
        province, city = PROVINCES[i % len(PROVINCES)]
        return {"no": str(1105090000000100 + i), "request_id": str(8800000 + i),
                "title": f"{ITEMS[i % len(ITEMS)]} - نیاز {i + 1}", "org": ORGS[i % len(ORGS)],
                "province": province, "city": city, "published": _jalali(-(i % 10)),
                "days_left": 2 + i % 9, "files": [(str(9100000 + i * 10 + k), f"مشخصات فنی {k + 1}.pdf") for k in range(2)]}

    def _tender(self, i: int) -> dict:
        province, city = PROVINCES[i % len(PROVINCES)]
        return {"id": 700000 + i, "number": str(2005000000000100 + i), "title": f"مناقصه {ITEMS[i % len(ITEMS)]} {i + 1}",
                "typeName": "مناقصه عمومی یک مرحله ای", "type": "ONE_STAGE_TENDER",
                "operationProvinceName": province, "operationCityName": city,
                "organization": {"id": 4000 + i % 5, "name": ORGS[i % len(ORGS)]},
                "domainsDescription": "تأمین و اجرا", "publicNotificationDate": _jalali(-(i % 10)) + " 10:00:00",
                "documentsDeadlineDate": _jalali(3 + i % 12) + " 12:00:00",
                "proposalDeadlineDate": _jalali(10 + i % 12) + " 12:00:00",
                "tenderDocumentsPrice": 0.0 if i % 3 == 0 else 1500000.0, "favoriteCount": None,
                "recCount": len(self.tenders) if hasattr(self, "tenders") else 0, "remainingTime": "0",
                "tenderTypeId": 4, "setupCode": 2,
                # v0.6.0: the key names of the owner's real data (every 4th tender has no guarantee in the list)
                "guarantyPrice": None if i % 4 == 1 else float((i % 7 + 1) * 50_000_000),
                "guarantyPriceCurrency": "ریال", "guarantyDescription": "ضمانت‌نامه بانکی یا واریز وجه نقد",
                "financialEstimatePrice": float((i % 7 + 1) * 1_000_000_000), "financialEstimatePriceCurrencyStr": "ریال",
                "renewalAppendixCount": 0, "priceAppendixCount": 0, "cancelAppendixCount": 0}


FAKE = Fake(int(os.environ.get("BOMS_SETAD_FAKE_NEEDS", "75")), int(os.environ.get("BOMS_SETAD_FAKE_TENDERS", "120")))
LOGIN_MS = int(os.environ.get("BOMS_SETAD_FAKE_LOGIN_MS", "1500"))
CAPTCHA_MS = int(os.environ.get("BOMS_SETAD_FAKE_CAPTCHA_MS", "4000"))
PER_PAGE = 30


def install(context) -> None:
    context.route("**/*", _route)


def _page(body: str, title: str = "ستاد") -> str:
    return f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>{title}</title></head><body>{body}</body></html>'


def _route(route, request):
    url = urlparse(request.url)
    host = url.hostname or ""
    if not host.endswith("setadiran.ir"):
        return route.abort()
    form = parse_qs(request.post_data or "", keep_blank_values=True) if request.method == "POST" else {}
    q = {**parse_qs(url.query, keep_blank_values=True), **form}
    one = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731
    try:
        if host == "sso2.setadiran.ir":
            return _sso(route, url, one)
        system = "EPROC" if host == "eproc.setadiran.ir" else "ETEND"
        if not FAKE.logged_in:
            return _redirect(route, "https://sso2.setadiran.ir/login")
        if FAKE.role != system:
            return _redirect(route, f"https://sso2.setadiran.ir/role?want={system}")
        if system == "EPROC":
            return _eproc(route, url, one, request)
        return _etend(route, url, one, request)
    except Exception as exc:  # pragma: no cover - debugging aid
        return route.fulfill(status=500, body=f"fake error: {exc}")


def _redirect(route, location: str):
    """A page that navigates on: a fulfilled HTTP redirect would be followed outside the route handler (to the
    dead proxy), a script navigation is an ordinary routed request."""
    return _html(route, _page(f"<p>...</p><script>location.replace({json.dumps(location)})</script>"))


def _html(route, body: str, status: int = 200):
    return route.fulfill(status=status, content_type="text/html; charset=utf-8", body=body)


def _json(route, data):
    return route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(data, ensure_ascii=False))


# ---- sso2: login and role page -------------------------------------------------------------------------------

def _sso(route, url, one):
    if url.path == "/login-done":
        FAKE.logged_in = True
        return _json(route, {"ok": True})
    if url.path == "/login" or not FAKE.logged_in:
        return _html(route, _page(f"""
            <form id="login"><input name="username" value="owner"><input type="password" name="password"></form>
            <p>ورود به سامانه ستاد (نمونهٔ آزمایشی)</p>
            <script>setTimeout(()=>fetch('/login-done').then(()=>location.href='/role'), {LOGIN_MS});</script>"""))
    if url.path == "/choose":
        FAKE.role = one("system")
        target = ("https://eproc.setadiran.ir/eproc/needBoardInfo-load.do" if FAKE.role == "EPROC"
                  else "https://etend.setadiran.ir/etend/indexPage.action")
        return _redirect(route, target)
    return _html(route, _page("""
        <form id="roles" action="/choose">
          <input type="hidden" name="appType" value="1">
          <input type="radio" name="system" id="EPROC" value="EPROC"><label for="EPROC">تدارکات الکترونیکی</label>
          <input type="radio" name="system" id="ETEND" value="ETEND"><label for="ETEND">مناقصات</label>
          <div id="roles-list">
            <input type="radio" name="role" id="r1" value="supplier"><label for="r1">تامین کننده</label>
            <input type="radio" name="role" id="r2" value="bidder"><label for="r2">مناقصه گر</label>
          </div>
          <button type="button" id="start-button" onclick="
            const s=document.querySelector('input[name=system]:checked'); if(!s) return;
            location.href='/choose?system='+s.value;">شروع</button>
        </form>"""))


# ---- eproc: purchase calls ---------------------------------------------------------------------------------------

def _row(i: int, n: dict) -> str:
    link = (f'<a class="hyperlink" href="javascript:void(0)" onclick="javascript:postLink(&quot;purchaseNeedView.do?'
            f'method=showNeedDetailInfo&amp;requestId={n["request_id"]}&amp;taskId=null&quot;)">{n["no"].translate(FA)}</a>')
    cells = [str(i).translate(FA), link, html.escape(n["title"]), html.escape(n["org"]), n["province"], n["city"],
             "استعلام بها", "کالا", "تجهیزات", "", n["published"].translate(FA), f"{n['days_left']} روز و ۲ ساعت"]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _results(needs: list[dict], page: int) -> str:
    total = len(needs)
    pages = max(1, -(-total // PER_PAGE))
    chunk = needs[(page - 1) * PER_PAGE: page * PER_PAGE]
    start = (page - 1) * PER_PAGE + 1
    links = "".join(f'<a class="pagelinks" href="/eproc/needAdvancedSearch.do?pager=true&amp;d-146909-p={p}">{p}</a> '
                    for p in range(1, pages + 1) if p != page)
    rows = "".join(_row(start + k, n) for k, n in enumerate(chunk))
    return _page(f"""<span class="pagebanner"> {total} مورد یافت شد, نمایش {start} تا {start + len(chunk) - 1}. </span>
        <span class="pagelinks">{links}</span><table id="resultTable"><thead><tr><th>ردیف</th></tr></thead>
        <tbody>{rows}</tbody></table>""")


def _search_form(since: str = "") -> str:
    return _page(f"""<form name="NeedAdvancedSearchForm" method="post" action="/eproc/needAdvancedSearch.do">
        <input name="purchaseNeedDto.needNo" value=""><input name="currentDate" type="hidden" value="{_jalali(0)}">
        <input name="responseDateFrom" value=""><input name="needDateFrom" value="{since}">
        <input type="hidden" name="checkCaptcha" value="true"></form>""")


def _eproc(route, url, one, request):
    path = url.path
    if path.endswith("needBoardInfo-load.do"):
        return _html(route, _page('<table id="aList"><tbody></tbody></table>'))
    if path.endswith("needAdvancedSearch.do"):
        since = one("needDateFrom")
        needs = [n for n in FAKE.needs if not since or n["published"] >= since.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))]
        if request.method == "POST" and one("method") == "doSearch":
            FAKE.last_since = since
            return _html(route, _results(needs, 1))
        page = one("d-146909-p")
        if page:
            needs = [n for n in FAKE.needs if not getattr(FAKE, "last_since", "") or n["published"] >= FAKE.last_since]
            if page == "2" and FAKE.captcha_pending and one("captchaSolved") != "1":
                FAKE.captchas_shown += 1
                return _html(route, _page(f"""<img id="captchaImage" src="/eproc/captcha.jpg">
                    <input type="text" name="captchaText"><p>کد امنیتی را وارد کنید</p>
                    <script>setTimeout(()=>{{location.href=location.href+'&captchaSolved=1'}}, {CAPTCHA_MS});</script>"""))
            if page == "2":
                FAKE.captcha_pending = False
            return _html(route, _results(needs, int(page)))
        return _html(route, _search_form())
    if path.endswith("purchaseNeedView.do"):
        n = next((x for x in FAKE.needs if x["request_id"] == one("requestId")), None)
        if n is None:
            return _html(route, _page("<p>یافت نشد</p>"), 404)
        return _html(route, _detail(n))
    if path.endswith("anonymousAppendixDocument.do"):
        n = next((x for x in FAKE.needs if x["no"] == one("docNo")), None)
        rows = "".join(f'<tr><td>{k + 1}</td><td><input type="radio" name="sel" id="r{fid}" '
                       f'onclick="document.getElementsByName(\'fileId\')[0].value=\'{fid}\'"></td><td>{html.escape(name)}</td></tr>'
                       for k, (fid, name) in enumerate(n["files"] if n else []))
        return _html(route, _page(f"""<form><input type="hidden" name="fileId" value="">
            <input type="hidden" name="viewBySupplier" value="2"><table><tbody>{rows}</tbody></table></form>"""))
    if path.endswith("appendixDocument.do") and one("method") == "viewFile":
        fid = one("fileId")
        name = next((f for n in FAKE.needs for f_id, f in n["files"] if f_id == fid), "file.pdf")
        body = b"%PDF-1.4\n% fake Setad attachment " + fid.encode() + b"\n" + b"0" * 2048 + b"\n%%EOF\n"
        if fid in FAKE.waf_files:
            body = b"<html><body>Request blocked</body></html>"
        from urllib.parse import quote
        return route.fulfill(status=200, headers={"Content-Type": "application/pdf",
                                                  "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
                             body=body)
    if path.endswith("captcha.jpg"):
        return route.fulfill(status=200, content_type="image/gif", body=b"GIF89a")
    return _html(route, _page("<p>صفحهٔ آزمایشی</p>"))


def _detail(n: dict) -> str:
    deadline = _jalali(n["days_left"])
    valid = _jalali(n["days_left"] + 30)
    def field(name, value):
        return f'<tr><td>label</td><td><input type="text" name="{name}" value="{html.escape(value)}" readonly></td></tr>'
    rows = f"""<tr><td>1</td><td>--</td><td>{html.escape(n['title'].split(' - ')[0])}</td><td>عدد</td>
               <td>تجهیزات</td><td>{(10 + int(n['request_id']) % 40)}</td><td>{deadline}</td></tr>"""
    return _page(f"""<form name="PurchaseNeedViewForm" action="purchaseNeedView.do"><table>
        {field('purchaseNeedDto.needNo', n['no'])}
        {field('sendDate', n['published'] + ' - 09:00')}
        {field('purchaseNeedDto.purchaseRequestDto.organization.name', n['org'])}
        {field('deadlineDurationDateStr', deadline)}{field('deadlineDurationTimeStr', '14:00')}
        {field('purchaseNeedDto.priceValidDurationDate', valid)}{field('purchaseNeedDto.priceValidDurationTime', '11:00')}
        {field('purchaseNeedDto.purchaseRequestDto.deliveryLocation.parentLocation.name', n['province'])}
        {field('purchaseNeedDto.purchaseRequestDto.deliveryLocation.name', n['city'])}
        <tr><td>شرح</td><td><textarea name="purchaseNeedDto.needName">{html.escape(n['title'])}</textarea></td></tr>
        <tr><td>توضیحات</td><td><textarea name="purchaseNeedDto.description">پیش فاکتور با مهر و امضا؛ تسویه سه ماهه. تلفن واحد تدارکات ۰۳۵۳۱۲۳۴۵۶۷</textarea></td></tr>
        <tr><td>اطلاعات کالاهای مورد نیاز</td></tr></table>
        <table id="aList"><thead><tr><th>ردیف</th><th>کد کالا</th><th>نام کالا</th><th>واحد شمارش</th><th>گروه</th>
          <th>تعداد / مقدار</th><th>تاریخ نیاز</th></tr></thead><tbody>{rows}</tbody></table>
        <input type="button" value="مشاهده مدارک پیوستی ({len(n['files'])})">
        </form>
        <script>
        function anonymousShowAppendix()
        {{
            openUniquedWindow('anonymousAppendixDocument.do?method=checkCaptcha' +
                '&docId={n['request_id']}' +
                '&docNo={n['no']}' +
                '&docState=1' +
                '&docType=327', 'appendixDocument', 700, 450);
        }}
        </script>""")


# ---- etend: tenders --------------------------------------------------------------------------------------------

GRID_JS = """
<script>
window.__grid={url:'/etend/afterLoginCallMainPageCartable-search.action',postData:{},rowNum:50,records:%(records)d,
  lastpage:%(pages)d,colNames:['شماره فراخوان','عنوان'],colModel:[{name:'number'},{name:'title'}]};
window.jQuery=function(sel){ if(sel==='#tendersGrid'&&document.querySelector('#tendersGrid'))
  return {length:1,jqGrid:(cmd,k)=>window.__grid[k]}; return {length:0}; };
window.getCsrfTokenParamNameAndValue=()=>'&struts.token.name=csrf_token&csrf_token='+document.getElementsByName('csrf_token')[0].value;
window.navigateBody=(u,p)=>{location.href=u+'?'+p};
window.favoriteForm=function(id,price,org,type,setup){
  const b=new URLSearchParams({tenderId:id,tenderDocumentsPrice:price,organizationId:org,tenderTypeId:type,allSetupType:setup});
  b.set('csrf_token',document.getElementsByName('csrf_token')[0].value);
  return fetch('/etend/callMainPageCartable-add.action',{method:'POST',body:b});
};
</script>"""


def _etend(route, url, one, request):
    path = url.path
    token = '<input type="hidden" name="struts.token.name" value="csrf_token"><input type="hidden" name="csrf_token" value="tok-0">'
    if path.endswith("indexPage.action") or path.endswith("afterLoginCallMainPageCartable-execute.action"):
        pages = -(-len(FAKE.tenders) // 50)
        return _html(route, _page(token + '<a id="callMainPageCartableExecuteMenuLink" href="#">فراخوان ها</a>'
                                  '<a href="/etend/myCallsCartable-execute.action">فراخوان‌های من</a>'
                                  '<div id="tendersGrid"></div>' + GRID_JS % {"records": len(FAKE.tenders), "pages": pages}))
    if path.endswith("afterLoginCallMainPageCartable-search.action"):
        rows = int(one("rows", "50") or 50)
        page = int(one("page", "1") or 1)
        data = FAKE.tenders[(page - 1) * rows: page * rows]
        for t in data:
            t["favoriteCount"] = 1 if str(t["id"]) in FAKE.my_calls else None
        return _json(route, {"page": page, "records": len(FAKE.tenders), "total": -(-len(FAKE.tenders) // rows),
                             "gridModel": data})
    if path.endswith("callMainPageCartable-add.action"):
        FAKE.add_requests.append({k: one(k) for k in ("tenderId", "tenderDocumentsPrice", "organizationId")})
        FAKE.my_calls.add(one("tenderId"))
        return _json(route, {"errorMessage": "", "newCsrfTokenValue": "tok-1"})
    if path.endswith("reloadCsrfToken"):
        return _json(route, {"newCsrfTokenValue": "tok-2"})
    if path.endswith("myCallsCartable-execute.action"):
        return _html(route, _page(token + """<input type="hidden" name="myCallsCartableAction_conversation" value="7">
            <script>window.navigateBody=(u,p)=>{location.href=u+'?'+p};
            window.deleteAction=function(id){ const b=new URLSearchParams({selectedTenderId:id});
              return fetch('/etend/myCallsCartable-delete.action?myCallsCartableAction_conversation=7',{method:'POST',body:b}); };
            </script><p>فراخوان‌های من</p>"""))
    if path.endswith("myCallsCartable-search.action"):
        rows = [{"id": None, "entity": {"participationTender": {
            "state": "ADD_TO_MY_FAVORITE", "stateName": "در انتظار پرداخت",
            "tender": {"id": int(i), "type": "ONE_STAGE_TENDER"}}}} for i in sorted(FAKE.my_calls)]
        return _json(route, {"total": 1, "gridModel": rows})
    if path.endswith("myCallsCartable-delete.action"):
        tid = one("selectedTenderId")
        FAKE.delete_requests.append(tid)
        FAKE.my_calls.discard(tid)
        return _json(route, {"errorMessage": "", "selectedTenderId": tid})
    if path.endswith("tenderDetails-execute.action"):
        tid = one("tenderId")
        t = next((x for x in FAKE.tenders if str(x["id"]) == str(tid)), None)
        if t is None:
            return _html(route, _page(token + "<p>صفحهٔ آزمایشی</p>"))
        i = t["id"] - 700000
        rows = [("شماره فراخوان", t["number"]), ("عنوان", t["title"]), ("نوع فراخوان", t["typeName"]),
                ("دستگاه مناقصه‌گزار", t["organization"]["name"]), ("مهلت دریافت اسناد", t["documentsDeadlineDate"]),
                ("مهلت ارسال پیشنهاد", t["proposalDeadlineDate"]), ("نوع تضمین", t["guarantyDescription"])]
        if t["guarantyPrice"] is None:
            rows.append(("مبلغ تضمین شرکت در فرآیند", f"{(i % 5 + 2) * 40_000_000:,} ریال"))
        body = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(str(b))}</td></tr>" for a, b in rows)
        return _html(route, _page(token + f'<form id="tenderDetailsForm"><h3>مشخصات فراخوان</h3><table>{body}</table></form>'))
    return _html(route, _page(token + "<p>صفحهٔ آزمایشی</p>"))


_ = re
