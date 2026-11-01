"""Business logic of the tender workspace: stages, envelope checklists, guarantee hints, price calculation.
Pure Python (no Qt) so it is unit-testable."""
from __future__ import annotations
from .dates import days_left

STAGES = ['بررسی', 'اسناد', 'استعلام', 'تضمین', 'پاکت‌ها', 'ارسال', 'نتیجه']
ENVELOPES = ['الف', 'ب', 'ج']
ENVELOPE_TITLES = {'الف': 'پاکت الف — تضمین شرکت در مناقصه',
                   'ب': 'پاکت ب — مدارک و پیشنهاد فنی',
                   'ج': 'پاکت ج — پیشنهاد قیمت'}
ITEM_STATUSES = ['آماده نیست', 'در حال تهیه', 'نیاز به امضا و مهر', 'آماده', 'تحویل/آپلود شد']
DONE_STATUSES = ('آماده', 'تحویل/آپلود شد')
GUARANTEE_STATUSES = ['درخواست نشده', 'درخواست شد', 'صادر شد', 'اسکن و آماده آپلود', 'آپلود شد', 'مسترد شد']
GUARANTEE_KINDS = ['', 'چک تضمین', 'ضمانت‌نامه بانکی', 'ضمانت‌نامه الکترونیکی', 'فیش/سپرده نقدی', 'سایر']
DECISIONS = ['', 'شرکت می‌کنیم', 'بررسی بیشتر', 'شرکت نمی‌کنیم']

DEFAULT_TEMPLATE = {
    'الف': ['ضمانت‌نامه / چک تضمین شرکت در مناقصه'],
    'ب': ['تعهدنامه‌ها و برگه‌های اسناد مناقصه (مهر و امضا)', 'آگهی تأسیس و آخرین تغییرات (روزنامه رسمی)',
          'اساسنامه', 'گواهی ثبت‌نام ارزش افزوده', 'گواهی رتبه / صلاحیت (در صورت درخواست)',
          'مدارک هویتی و وکالت امضاکنندگان', 'فهرست سوابق کاری و تأییدیه‌ها', 'گواهینامه‌ها (ISO / ایمنی)',
          'مفاصا حساب بیمه / فهرست بیمه', 'گواهی یا اظهارنامه مالیاتی', 'مشخصات و کاتالوگ فنی / روش اجرا'],
    'ج': ['فرم پیشنهاد قیمت کارفرما (تکمیل، مهر و امضا)', 'برگه‌های ریز قیمت (در صورت وجود)'],
}

COMPANY_DOC_SUGGESTIONS = [
    ('آگهی تأسیس و آخرین تغییرات (روزنامه رسمی)', 'ثبتی'), ('اساسنامه', 'ثبتی'),
    ('گواهی ثبت‌نام ارزش افزوده', 'مالیاتی'), ('گواهی یا اظهارنامه مالیاتی', 'مالیاتی'),
    ('مفاصا حساب بیمه / فهرست بیمه', 'بیمه'), ('گواهینامه‌ها (ISO / ایمنی)', 'گواهینامه'),
    ('فهرست سوابق کاری و تأییدیه‌ها', 'سوابق'), ('گواهی رتبه / صلاحیت (در صورت درخواست)', 'صلاحیت'),
]


def doc_expiry(expires: str, today=None):
    """-> (state, days). state in ok / soon / expired / none."""
    n = days_left(expires, today) if expires else None
    if n is None:
        return 'none', None
    if n < 0:
        return 'expired', n
    if n <= 30:
        return 'soon', n
    return 'ok', n


def envelope_progress(items):
    """-> {envelope: (done, total)} plus 'all'."""
    out = {e: [0, 0] for e in ENVELOPES}
    for it in items:
        e = it['envelope'] if it['envelope'] in out else None
        if e is None:
            continue
        out[e][1] += 1
        if it['status'] in DONE_STATUSES:
            out[e][0] += 1
    total = [sum(v[0] for v in out.values()), sum(v[1] for v in out.values())]
    res = {k: tuple(v) for k, v in out.items()}
    res['all'] = tuple(total)
    return res


def blockers(items, guarantee, today=None, proposal_deadline=''):
    """Human-readable reasons why the tender is not ready to submit."""
    out = []
    for e in ENVELOPES:
        left = [i for i in items if i['envelope'] == e and i['status'] not in DONE_STATUSES]
        if left:
            out.append(f'پاکت {e}: {len(left)} مورد ناتمام' + (' — ' + '، '.join(i['title'] for i in left[:2]) if len(left) <= 2 else ''))
    if not items:
        out.append('چک‌لیست پاکت‌ها هنوز ساخته نشده')
    if guarantee and guarantee.get('status') in ('درخواست نشده', 'درخواست شد'):
        out.append('تضمین هنوز صادر نشده')
    if guarantee and guarantee.get('valid_until') and proposal_deadline:
        a = days_left(guarantee['valid_until'], today)
        b = days_left(proposal_deadline, today)
        if a is not None and b is not None and a < b:
            out.append('اعتبار تضمین قبل از مهلت پیشنهاد تمام می‌شود')
    return out


def guarantee_hints(pairs):
    """Label/value pairs read from the site's details page that concern the guarantee."""
    out = []
    for k, v in pairs or []:
        if any(w in k for w in ('تضمین', 'ضمانت', 'سپرده')):
            out.append((k, v))
    return out


def stage_hint(ws, items, guarantee, has_files, quotes):
    """Suggest the furthest sensible stage from the data (shown as a hint, user can override)."""
    prog = envelope_progress(items)['all']
    if ws.get('stage', 0) >= 5:
        return ws['stage']
    if prog[1] and prog[0] == prog[1]:
        return 5
    if items:
        return 4
    if guarantee and guarantee.get('status') not in ('', 'درخواست نشده'):
        return 3
    if quotes:
        return 2
    return 1 if has_files else 0


def calc_offer(quotes, margin_pct=10.0, vat_pct=10.0, other_costs=0.0):
    """Price build-up from the chosen supplier quotes (or the cheapest per item if none is chosen)."""
    by_item = {}
    for q in quotes:
        by_item.setdefault(q['item'] or '—', []).append(q)
    lines = []
    for item, qs in by_item.items():
        chosen = [q for q in qs if q['chosen']] or [min(qs, key=lambda q: q['unit_price'])]
        q = chosen[0]
        lines.append({'item': item, 'supplier': q['supplier'], 'qty': q['qty'], 'unit_price': q['unit_price'],
                      'total': q['qty'] * q['unit_price'], 'auto': not q['chosen']})
    cost = sum(l['total'] for l in lines) + float(other_costs or 0)
    profit = cost * float(margin_pct or 0) / 100.0
    before_vat = cost + profit
    vat = before_vat * float(vat_pct or 0) / 100.0
    return {'lines': lines, 'cost': cost, 'profit': profit, 'before_vat': before_vat, 'vat': vat, 'total': before_vat + vat}


def money(value) -> str:
    try:
        return f'{round(float(value)):,}'
    except (TypeError, ValueError):
        return str(value or '')
