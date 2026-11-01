"""Read-only adapters: turn the two apps' live data into one list of «work items».

Inquiries come from the embedded inquiries window (ManagerUI.board_items), tenders from the
tenders database. Nothing here writes to either database."""
from __future__ import annotations

from setad_tender.dates import days_left as _days_left
from setad_tender import lifecycle as LC
from setad_tender.parsers import SENT_STATES

# the five shared columns of «کارهای من»
COLUMNS = ['بررسی', 'دریافت اسناد', 'آماده‌سازی', 'ارسال', 'نتیجه']
COLUMN_COLORS = ['#667085', '#7a5af8', '#1f5fbf', '#0e9384', '#067647']

INQ_STAGE_COL = {'starred': 0, 'review': 0, 'rfq_ready': 1, 'rfq': 1, 'final': 2, 'submitted': 3, 'result': 4}
# tender workspace stages: بررسی، اسناد، استعلام، تضمین، پاکت‌ها، ارسال، نتیجه
TENDER_STAGE_COL = {0: 0, 1: 0, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4}
TENDER_STAGE_NAMES = ['بررسی', 'اسناد', 'استعلام', 'تضمین', 'پاکت‌ها', 'ارسال', 'نتیجه']
# moving a card to a column → the stage it gets
INQ_COL_STAGE = {0: 'review', 1: 'rfq', 2: 'final', 3: 'submitted', 4: 'result'}
TENDER_COL_STAGE = {0: 0, 1: 2, 2: 4, 3: 5, 4: 6}

FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa(x) -> str:
    return str(x).translate(FA)


def days_text(days: float | None) -> str:
    if days is None:
        return ''
    if days < 0:
        return 'مهلت گذشته'
    d = int(days)
    if d == 0:
        return 'امروز'
    return fa(d) + ' روز'


def inquiry_items(ui) -> list[dict]:
    """Open cases of the inquiries app (everything on its follow-up board)."""
    out = []
    if ui is None:
        return out
    try:
        items = ui.board_items()
    except Exception:
        return out
    try:
        import pipeline as P
        titles = P.STAGE_TITLE
    except Exception:
        titles = {}
    for it in items:
        need = it['need']
        case = it['case']
        stage = case.get('stage')
        hours = it.get('hours')
        days = None if hours is None else hours / 24.0
        out.append({
            'kind': 'inq', 'id': need.need_no, 'number': need.need_no,
            'title': (need.description or '').strip(), 'org': need.organization or '',
            'col': INQ_STAGE_COL.get(stage, 0), 'stage': titles.get(stage, stage or ''),
            'stage_key': stage, 'days': days, 'remaining': fa(it.get('remaining') or '') or days_text(days),
            'meta': fa(it.get('meta') or ''), 'open': stage in ('starred', 'review', 'rfq_ready', 'rfq', 'final'),
            'result': (case.get('data') or {}).get('result'),
            'starred': True, 'locked': False, 'gone': False,
        })
    return out


def tender_rows(db) -> list[dict]:
    try:
        rows = db.list_tenders()
        smap = db.meta('status_map') or {}
    except Exception:
        return []
    for r in rows:
        lc = LC.classify(r, smap)
        r['lc'] = lc
        r['days_left'] = lc['days']
    return rows


def tender_locked(r) -> bool:
    """Packets already uploaded/sent on the site → removing it from «فراخوان‌های من» is not allowed there."""
    return str(r.get('site_state') or '') in SENT_STATES or int(r.get('stage') or 0) >= 5


def tender_items(db, rows=None, waived=False) -> list[dict]:
    """Tenders that are in «فراخوان‌های من» or have a workspace (waived=True → only the «صرف‌نظرشده» ones)."""
    out = []
    for r in (rows if rows is not None else tender_rows(db)):
        stage = r.get('stage')
        if bool(r.get('waived')) != waived:
            continue
        if not r.get('in_my_calls') and stage is None and not r.get('was_in_calls'):
            continue
        st = int(stage or 0)
        lc = r.get('lc') or {}
        days = r.get('days_left')
        gone = bool(r.get('was_in_calls')) and not r.get('in_my_calls')
        meta = (f"اسناد: {fa(r.get('downloaded_count') or 0)} از {fa(r.get('file_count') or 0)}" if r.get('file_count')
                else 'اسناد هنوز دریافت نشده')
        out.append({
            'kind': 'tender', 'id': str(r['id']), 'number': r.get('number') or str(r['id']),
            'title': (r.get('title') or '').strip(), 'org': r.get('organization') or '',
            'col': TENDER_STAGE_COL.get(st, 0), 'stage': TENDER_STAGE_NAMES[st] if 0 <= st < 7 else '',
            'stage_key': st, 'days': days, 'remaining': days_text(days),
            'deadline_kind': 'اسناد' if lc.get('kind') == 'docs' else ('ارسال' if lc.get('kind') == 'send' else ''),
            'site': lc.get('label') or '', 'lc_stage': lc.get('stage'),
            'meta': meta, 'open': st < 5 and lc.get('stage') != 'missed', 'result': None,
            'starred': bool(r.get('starred')), 'locked': tender_locked(r), 'gone': gone,
            'in_calls': bool(r.get('in_my_calls')), 'edition': str(r.get('edition_no') or ''),
        })
    return out


def all_items(ui, db) -> list[dict]:
    items = inquiry_items(ui) + tender_items(db)
    items.sort(key=lambda x: (x['days'] is None, x['days'] if x['days'] is not None else 0))
    return items


def search(ui, db, text: str, limit: int = 40) -> list[dict]:
    """Search both lists (number / title / organisation)."""
    q = (text or '').strip()
    if len(q) < 2:
        return []
    norm = lambda s: str(s or '').replace('ي', 'ی').replace('ك', 'ک').replace('‌', ' ').lower()
    qq = norm(q.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')))
    res = []
    if ui is not None:
        try:
            needs = list(ui.model.needs)
        except Exception:
            needs = []
        stages = getattr(ui, 'stages', {}) or {}
        for n in needs:
            if qq in norm(n.need_no) or qq in norm(n.description) or qq in norm(n.organization):
                res.append({'kind': 'inq', 'id': n.need_no, 'number': n.need_no, 'title': n.description,
                            'org': n.organization, 'in_case': n.need_no in stages})
                if len(res) >= limit:
                    break
    for r in tender_rows(db):
        if len(res) >= limit * 2:
            break
        if qq in norm(r.get('number')) or qq in norm(r.get('title')) or qq in norm(r.get('organization')):
            res.append({'kind': 'tender', 'id': str(r['id']), 'number': r.get('number'), 'title': r.get('title'),
                        'org': r.get('organization'), 'in_case': bool(r.get('in_my_calls'))})
    return res


def stats(ui, db) -> dict:
    inq = inquiry_items(ui)
    rows = tender_rows(db)
    ten = tender_items(db, rows)
    items = inq + ten
    urgent = [x for x in items if x['open'] and x['days'] is not None and 0 <= x['days'] < 2]
    try:
        needs_total = len(ui.model.needs) if ui is not None else 0
        needs_new = len(getattr(ui, 'new_needs', ()) or ())
    except Exception:
        needs_total = needs_new = 0
    open_tenders = [r for r in rows if (r.get('lc') or {}).get('actionable')]
    soon_tenders = [r for r in open_tenders if r['days_left'] <= 3]
    return {
        'active': len([x for x in items if x['open']]),
        'active_inq': len([x for x in inq if x['open']]),
        'active_ten': len([x for x in ten if x['open']]),
        'urgent': len(urgent),
        'submitted': len([x for x in items if x['col'] == 3]),
        'won': len([x for x in items if x.get('result') == 'won']),
        'results': len([x for x in items if x['col'] == 4]),
        'needs_total': needs_total, 'needs_new': needs_new,
        'tenders_total': len(rows), 'tenders_open': len(open_tenders), 'tenders_soon': len(soon_tenders),
        'my_calls': len([r for r in rows if r.get('in_my_calls')]),
        'tenders_actionable': len([r for r in rows if (r.get('lc') or {}).get('actionable')]),
        'tenders_starred': len([r for r in rows if r.get('starred')]),
        'inq_rejected': len([1 for v in (getattr(ui, 'stages', {}) or {}).values() if v == 'rejected']) if ui is not None else 0,
        'items': items,
        'urgent_blocks': urgent_blocks(ui, db, rows),
    }


def urgent_blocks(ui, db, rows=None) -> dict:
    """The four «اقدام فوری» blocks of the dashboard."""
    out = {'docs': [], 'send': [], 'edition': [], 'status': []}
    if db is None:
        return out
    rows = rows if rows is not None else tender_rows(db)
    seen_ed = db.meta('seen_editions')
    if seen_ed is None:      # first run: today's editions count as already seen; only new ones show up later
        seen_ed = {str(r['id']): str(r.get('edition_no') or '').strip() for r in rows if str(r.get('edition_no') or '').strip()}
        try:
            db.set_meta('seen_editions', seen_ed)
        except Exception:
            pass
    for r in rows:
        if r.get('waived'):
            continue
        lc = r.get('lc') or {}
        n = lc.get('days')
        mine = r.get('starred') or r.get('in_my_calls') or r.get('stage') is not None
        base = {'kind': 'tender', 'id': str(r['id']), 'number': r.get('number') or '', 'title': (r.get('title') or '').strip(),
                'days': n, 'starred': bool(r.get('starred'))}
        if mine and lc.get('stage') in ('browse', 'pay') and n is not None and 0 <= n <= 3:
            out['docs'].append(dict(base, tag='اسناد'))
        if lc.get('stage') == 'prepare' and n is not None and 0 <= n <= 7:
            out['send'].append(dict(base, tag='پیشنهاد'))
        ed = str(r.get('edition_no') or '').strip()
        if mine and ed and ed != '0' and str(seen_ed.get(str(r['id']), '')) != ed:
            out['edition'].append(dict(base, tag=f'اصلاحیه {fa(ed)}', edition=ed, date=r.get('last_edition_date') or ''))
    for x in inquiry_items(ui):
        if x['open'] and x['days'] is not None and 0 <= x['days'] < 2 and x.get('stage_key') in ('rfq', 'final', 'rfq_ready', 'review'):
            out['send'].append({'kind': 'inq', 'id': x['id'], 'number': x['number'], 'title': x['title'], 'days': x['days'],
                                'tag': 'پاسخ', 'remaining': x.get('remaining')})
    seen_at = db.meta('status_seen_at')
    if not seen_at:
        from datetime import datetime, timedelta, timezone
        seen_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec='seconds')
    try:
        hist = db.conn.execute("SELECT h.tender_id, h.at, h.new_text, h.new_code, t.title, t.number FROM status_history h "
                               "LEFT JOIN tenders t ON t.id=h.tender_id WHERE h.at>? ORDER BY h.id DESC LIMIT 20", (seen_at,)).fetchall()
    except Exception:
        hist = []
    done = set()
    for h in hist:
        if h['tender_id'] in done:
            continue
        done.add(h['tender_id'])
        out['status'].append({'kind': 'tender', 'id': str(h['tender_id']), 'number': h['number'] or '', 'title': h['title'] or '',
                              'tag': (h['new_text'] or h['new_code'] or '')[:22], 'at': h['at']})
    for k in ('docs', 'send'):
        out[k].sort(key=lambda x: x['days'] if x['days'] is not None else 99)
    return out
