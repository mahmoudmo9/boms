"""Effective deadline + stage of a tender, derived from the site's own dates/status (no guessing of unseen states).

Stages (key -> label):
  pay      «نیاز به دریافت/پرداخت اسناد»  (not obtained yet, docs deadline still open)
  prepare  «در انتظار ارسال پاکت»          (docs obtained, send deadline still open)
  missed   «مهلت گذشته»                   (could not obtain docs / send deadline passed without sending)
  browse   «در فهرست»                     (not added, docs deadline still open)
  site     any other status → shown verbatim from the site (sent / opening / evaluation / result …)
"""
from __future__ import annotations
from .dates import days_left

AR2FA = str.maketrans({'ي': 'ی', 'ك': 'ک', '‌': ' '})
QUALITY_TYPES = {'QUALITY_EVALUATION_TENDER', 'QUALITY_EVALUATION'}

# participationTender.state values observed on the real site
ST_NEED_PAY = 'ADD_TO_MY_FAVORITE'
ST_WAIT_PACKETS = 'IN_WATING_SENDING_PACKETS'
ST_DOCS_MISSED = 'DEADLINE'

STAGE_LABELS = {'pay': 'نیاز به دریافت اسناد', 'prepare': 'در انتظار ارسال پاکت', 'missed': 'مهلت گذشته',
                'browse': 'در فهرست', 'site': ''}
ACTIONABLE = {'pay', 'prepare', 'browse'}


def norm(s: str) -> str:
    return str(s or '').translate(AR2FA).strip()


def is_quality(row: dict) -> bool:
    t = str(row.get('site_type') or row.get('type_code') or '')
    return t in QUALITY_TYPES or 'ارزیابی کیفی' in norm(row.get('type_name'))


def is_free(row: dict) -> bool:
    """v0.9.2: documents price is known and zero (unknown price is NOT treated as free)."""
    p = row.get('price')
    if p in (None, ''):
        return False
    try:
        return float(p) == 0
    except (TypeError, ValueError):
        return False


def send_deadline(row: dict) -> str:
    """The last date to send (packets / quality-evaluation docs). Quality evaluation has no proposal deadline."""
    if is_quality(row):
        return row.get('inquiry_deadline') or row.get('proposal_deadline') or ''
    return row.get('proposal_deadline') or row.get('inquiry_deadline') or ''


def classify(row: dict, mapping: dict | None = None, today=None) -> dict:
    """-> {stage, label, date, kind, days, actionable}.  `mapping` = user's {site_state_code_or_text: stage}."""
    code = str(row.get('site_state') or '')
    text = norm(row.get('site_state_name'))
    in_calls = bool(row.get('in_my_calls'))
    docs_dl, send_dl = row.get('documents_deadline') or '', send_deadline(row)
    d_docs, d_send = days_left(docs_dl, today), days_left(send_dl, today)
    stage = None
    if mapping:
        stage = mapping.get(code) or mapping.get(text)
    if not stage and in_calls:
        if code == ST_NEED_PAY:stage = 'pay'
        elif code == ST_WAIT_PACKETS:stage = 'prepare'
        elif code == ST_DOCS_MISSED:stage = 'missed'
        elif code or text:stage = 'site'
        else:stage = 'pay'
    if not stage:
        stage = 'browse' if (d_docs is None or d_docs >= 0) else 'missed'
    if stage == 'pay':
        date, days, kind = docs_dl, d_docs, 'docs'
        if d_docs is not None and d_docs < 0:stage = 'missed'
    elif stage in ('prepare', 'browse'):
        date, days, kind = (send_dl, d_send, 'send') if stage == 'prepare' else (docs_dl, d_docs, 'docs')
        if stage == 'prepare' and d_send is not None and d_send < 0:stage = 'missed'
        if stage == 'browse' and d_docs is not None and d_docs < 0:stage = 'missed'
    else:
        date, days, kind = '', None, ''
    label = STAGE_LABELS.get(stage) or (row.get('site_state_name') or '')
    if stage == 'missed' and not label:label = 'مهلت گذشته'
    return {'stage': stage, 'label': label, 'date': date, 'kind': kind, 'days': days, 'free': is_free(row),
            'actionable': stage in ACTIONABLE and days is not None and days >= 0}


def deadline_kind_text(kind: str, stage: str) -> str:
    return {'docs': 'مهلت دریافت اسناد', 'send': 'مهلت ارسال'}.get(kind, '')
