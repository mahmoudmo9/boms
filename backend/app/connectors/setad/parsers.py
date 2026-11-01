# Ported unchanged from SetadSuite v0.9.23 setad_tender/parsers.py.
"""Parsers for untrusted page/JSON contents. Python never executes HTML from Setad."""
from __future__ import annotations
from bs4 import BeautifulSoup
import html as html_lib
import json
import re

ALLOWED_HOST = 'etend.setadiran.ir'
DOCUMENT_FALLBACK = [
    {'document_type':'3192','title':'شرایط و ضوابط مناقصه','count':None,'size':''},
    {'document_type':'3193','title':'اسناد فنی','count':None,'size':''},
    {'document_type':'3194','title':'متن قرارداد و شرایط عمومی/خصوصی','count':None,'size':''},
    {'document_type':'7013','title':'اسناد ارزیابی کیفی','count':None,'size':''},
]
FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')


def text(value) -> str:
    return re.sub(r'\s+', ' ',str(value or '')).strip()


def latin_digits(value) -> str:
    return str(value or '').translate(FA_DIGITS)


# ---------------------------------------------------------------- details page
def looks_like_login(html: str) -> bool:
    low=(html or '').lower()
    return ('type="password"' in low or "type='password'" in low) and 'tenderdetails' not in low


def looks_like_details(html: str, tender_id='', number='') -> bool:
    if not html or looks_like_login(html):
        return False
    if 'tenderDetailsForm' in html or 'مشخصات مناقصه' in html or 'مشخصات فراخوان' in html:
        return True
    plain=latin_digits(html)
    if number and latin_digits(number) in plain:
        return True
    return bool(tender_id) and str(tender_id) in plain and len(html) > 1500


def details_from_html(html: str) -> str:
    soup=BeautifulSoup(html,'html.parser')
    content=soup.select_one('#tenderDetailsForm') or soup.select_one('#content') or soup.body or soup
    for tag in content.select('script,style,noscript'):
        tag.decompose()
    lines = [text(x) for x in content.get_text('\n',strip=True).splitlines()]
    cleaned=[]
    for line in lines:
        if line and (not cleaned or cleaned[-1] != line): cleaned.append(line)
    return '\n'.join(cleaned)[:100000]


def detail_pairs_from_html(html: str) -> list[list[str]]:
    """Best-effort label/value extraction from table-like layouts."""
    soup=BeautifulSoup(html,'html.parser')
    content=soup.select_one('#tenderDetailsForm') or soup.body or soup
    for tag in content.select('script,style,noscript'):
        tag.decompose()
    pairs=[];seen=set()
    def add(label,value):
        label=text(label).rstrip(':： ').strip();value=text(value)
        if not label or not value or len(label)>70 or label==value:return
        if (label,value) in seen:return
        seen.add((label,value));pairs.append([label,value])
    for tr in content.select('tr'):
        cells=[c for c in tr.find_all(['td','th'],recursive=False)]
        if len(cells) in (2,4,6):
            vals=[text(c.get_text(' ',strip=True)) for c in cells]
            for i in range(0,len(vals),2):add(vals[i],vals[i+1])
    for lab in content.select('label'):
        sib=lab.find_next_sibling()
        if sib is not None:add(lab.get_text(' ',strip=True),sib.get_text(' ',strip=True))
    return pairs[:250]


# ----------------------------------------------------------- document groups
def _js_args(call: str) -> list[str]:
    """Split the literal arguments of `fn(a, 'b', null)`; only simple literals are expected."""
    m=re.search(r'\((.*)\)',call or '',re.S)
    if not m:return []
    out=[];cur='';quote=None
    for ch in m.group(1):
        if quote:
            if ch==quote:quote=None
            else:cur+=ch
        elif ch in '\'"':quote=ch
        elif ch==',':out.append(cur.strip());cur=''
        elif ch==')':break
        else:cur+=ch
    out.append(cur.strip())
    return out


def groups_from_html(html: str,expected_tender_id: str='') -> list[dict]:
    """Collect showAppendix(...) openers (document categories) from a site page.
    Known signature: showAppendix('/etend/appendix-openAppendix', null, '3193', '675227', 'true', ...)."""
    soup=BeautifulSoup(html or '','html.parser')
    found={}
    for tag in soup.select('[onclick],[href^="javascript:"]'):
        handler=tag.get('onclick') or tag.get('href') or ''
        if 'showAppendix(' not in handler: continue
        call=handler[handler.index('showAppendix('):]
        args=_js_args(call)
        if len(args)<4 or not args[2].isdigit() or not args[3].isdigit(): continue
        doc_type,doc_id=args[2],args[3]
        label=text(tag.get_text(' ',strip=True))
        around=label
        box=tag.find_parent(['tr','li'])
        if box is None and tag.parent is not None and str(tag.parent).count('showAppendix(')==1:box=tag.parent
        if box is not None and str(box).count('showAppendix(')==1:around=text(box.get_text(' ',strip=True))
        count=(re.search(r'تعداد\s*(?:فایل)?\s*[:：]?\s*([۰-۹0-9]+)',label) or
               re.search(r'تعداد\s*(?:فایل)?\s*[:：]?\s*([۰-۹0-9]+)',around))
        size=(re.search(r'حجم\s*(?:فایل)?\s*[:：]?\s*([\d۰-۹.,]+\s*(?:MB|KB|GB|مگا\s*بایت|کیلو\s*بایت|بایت))',label,re.I) or
              re.search(r'حجم\s*(?:فایل)?\s*[:：]?\s*([\d۰-۹.,]+\s*(?:MB|KB|GB|مگا\s*بایت|کیلو\s*بایت|بایت))',around,re.I))
        title=re.split(r'تعداد\s*فایل',label)[0].strip() or ('دسته '+doc_type)
        found[(doc_type,doc_id)]={'document_type':doc_type,'document_id':doc_id,'title':title,
                         'count':int(latin_digits(count.group(1))) if count else None,
                         'size':size.group(1) if size else '','opener':call.split(';')[0][:600]}
    groups=list(found.values())
    if expected_tender_id:
        own=[g for g in groups if g['document_id']==str(expected_tender_id)]
        if own:groups=own
    # one entry per category
    uniq={}
    for g in groups:uniq.setdefault(g['document_type'],g)
    return list(uniq.values())


def file_rows_from_html(html: str) -> list[dict]:
    """Fallback: file rows rendered as links/buttons carrying an appendixId."""
    soup=BeautifulSoup(html or '','html.parser')
    out={}
    for tag in soup.select('[href*="appendix"],[onclick*="ppendix"]'):
        blob=(tag.get('href') or '')+' '+(tag.get('onclick') or '')
        m=re.search(r'appendixId[=:,\s\'"(]+(\d+)',blob) or re.search(r'download\w*\(\s*[\'"]?(\d+)',blob)
        if not m:continue
        row=tag.find_parent('tr')
        cells=[text(td.get_text(' ',strip=True)) for td in row.find_all('td')] if row else []
        name=next((c for c in cells if re.search(r'\.\w{2,5}$',c) or len(c)>6),'') or text(tag.get_text(' ',strip=True))
        ext=re.search(r'\.(\w{2,5})$',name)
        out[m.group(1)]={'appendix_id':m.group(1),'display_name':name or m.group(1),'extension':ext.group(1) if ext else '',
                         'size':next((c for c in cells if re.search(r'(KB|MB|بایت)',c,re.I)),''),'comment':'','created':''}
    return list(out.values())


def looks_like_file_list(data) -> bool:
    if not isinstance(data,dict):return False
    rows=_file_items(data)
    if not isinstance(rows,list):return False
    if not rows:return any(k in data for k in ('appendixList','records','gridModel'))
    keys=' '.join(rows[0].keys()).lower() if isinstance(rows[0],dict) else ''
    return any(k in keys for k in ('file','appendix','attach','format'))


TEMPLATE_KEYS=(('documentid','{document_id}'),('documenttype','{document_type}'),('appendixid','{appendix_id}'))


def make_template(url: str, post_pairs=None, method='GET') -> dict:
    """Generalise a recorded request: ids become placeholders, secrets are dropped."""
    from urllib.parse import urlparse, parse_qsl
    u=urlparse(url)
    defaults={}
    def conv(pairs):
        out=[]
        for k,v in pairs:
            low=k.lower().replace('_','').replace('.','')
            if is_secret_name(k):continue
            if k.endswith('_conversation'):out.append([k,'{conv}']);defaults[k]=v;continue
            ph=next((p for key,p in TEMPLATE_KEYS if key in low),None)
            out.append([k,ph or v])
        return out
    q=conv(parse_qsl(u.query,keep_blank_values=True));b=conv(post_pairs or [])
    return {'path':u.path,'method':method.upper(),'query':q,'body':b,'defaults':defaults}


def fill_template(tpl: dict, conv: dict, **values) -> tuple[str,list,list]:
    def fill(pairs):
        out=[]
        for k,v in pairs:
            if v=='{conv}':v=conv.get(k) or (tpl.get('defaults') or {}).get(k,'')
            for name,val in values.items():v=v.replace('{'+name+'}',str(val))
            out.append((k,v))
        return out
    return tpl['path'],fill(tpl.get('query') or []),fill(tpl.get('body') or [])


def json_shape(data, depth=0):
    """Keys/types only, plus a short sample of the first list row (secrets removed)."""
    if isinstance(data,dict):
        if depth>2:return '{…}'
        return {k:('[حذف]' if is_secret_name(k) else json_shape(v,depth+1)) for k,v in list(data.items())[:60]}
    if isinstance(data,list):
        return [f'{len(data)} ردیف']+([json_shape(data[0],depth+1)] if data else [])
    if isinstance(data,str):return redact(data[:80])
    return data


def redact_html(html: str) -> str:
    s=re.sub(r'(name=["\'][^"\']*(?:csrf|token)[^"\']*["\'][^>]*?value=["\'])[^"\']*',r'\1[حذف]',html or '',flags=re.I)
    s=re.sub(r'(value=["\'])[^"\']*(["\'][^>]*name=["\'][^"\']*(?:csrf|token))',r'\1[حذف]\2',s,flags=re.I)
    return redact(s)


def find_appendix_list_url(body: str) -> str:
    """The appendix dialog builds a jqGrid whose url points to appendix-list.action."""
    for m in re.finditer(r'''["']([^"'<>\s]*appendix-list\.action[^"'<>\s]*)["']''',body or ''):
        return html_lib.unescape(m.group(1))
    return ''


LIST_KEYS=('appendixList','gridModel','rows','data','list','items')


def _file_items(data):
    """Setad returns {'appendixList':[...]} (confirmed from a real recording); older
    jqGrid endpoints use gridModel/rows. Fall back to the first list of objects."""
    if not isinstance(data,dict):return None
    for k in LIST_KEYS:
        if isinstance(data.get(k),list):return data[k]
    for v in data.values():
        if isinstance(v,list) and v and isinstance(v[0],dict):return v
    return None


def human_size(value) -> str:
    try:n=float(value)
    except (TypeError,ValueError):return text(value)
    for unit in ('B','KB','MB','GB'):
        if n<1024 or unit=='GB':
            return (f'{n:.0f} {unit}' if unit in ('B','KB') else f'{n:.1f} {unit}')
        n/=1024


def file_rows_from_json(data: dict) -> list[dict]:
    items=_file_items(data)
    if not isinstance(items,list): raise ValueError('پاسخ فایل‌ها آرایه فایل (appendixList / gridModel / rows) ندارد.')
    out=[]
    for row in items:
        if not isinstance(row,dict): continue
        if isinstance(row.get('cell'),list): continue
        file_id=row.get('appendixId') or row.get('id') or row.get('fileId')
        if isinstance(file_id,dict): file_id=file_id.get('id')
        if file_id is None:
            continue
        display = text(row.get('showFileName') or row.get('fileName') or row.get('name'))
        fmt=text(row.get('showFileFormat') or row.get('fileFormat') or row.get('fileExtention')
                 or row.get('fileExtension') or row.get('extension')).lstrip('.')
        size=row.get('showFileSize') or row.get('fileSize')
        out.append({
            'appendix_id':str(file_id), 'display_name':display or str(file_id),
            'extension':fmt, 'size':human_size(size) if isinstance(size,(int,float)) else text(size),
            'comment':text(row.get('comment') or row.get('description')),'created':text(row.get('createDate'))
        })
    return out


# ------------------------------------------------ favorite (my calls) arguments
FAV_POSITIONS=[('price',('price',)),('organizationId',('organ',)),('typeId',('type',)),('setupId',('setup',))]


def flatten(obj, prefix='', depth=0):
    if isinstance(obj,dict) and depth<4:
        for k,v in obj.items():
            yield from flatten(v,f'{prefix}.{k}' if prefix else str(k),depth+1)
    elif not isinstance(obj,(list,dict)):
        yield prefix,obj


def _same(a,b) -> bool:
    if a is None or b is None or a=='' or b=='':return False
    try:return float(str(a))==float(str(b))
    except ValueError:return str(a).strip()==str(b).strip()


def learn_favorite_mapping(samples: list[dict], raws: dict) -> dict:
    """Learn which JSON fields the site's favoriteForm(id, price, org, type, setup) uses,
    from rows that are visible in the live grid. Never guesses: returns only consistent paths."""
    pairs=[(s,raws.get(str(s['id']))) for s in samples if raws.get(str(s['id']))]
    if not pairs:return {}
    mapping={}
    for pos,hints in FAV_POSITIONS:
        candidates=None
        for sample,raw in pairs:
            here={p for p,v in flatten(raw) if _same(v,sample.get(pos))}
            candidates=here if candidates is None else candidates & here
        if not candidates:return {}
        hinted=[c for c in candidates if any(h in c.lower() for h in hints)]
        pick=sorted(hinted or candidates,key=lambda c:(c.count('.'),len(c)))[0]
        if len(candidates)>1 and not hinted and len(pairs)<2:return {}
        mapping[pos]=pick
    mapping['_samples']=len(pairs)
    return mapping


def favorite_args_from_raw(raw: dict, mapping: dict):
    if not mapping or not raw:return None
    flat=dict(flatten(raw))
    out={'id':str(raw.get('id'))}
    for pos,_ in FAV_POSITIONS:
        path=mapping.get(pos)
        if not path or flat.get(path) in (None,''):return None
        out[pos]=str(flat[path])
    return out


# ------------------------------------------------------------------- display
FIELD_LABELS = {
    'number':'شماره فراخوان','title':'عنوان','typeName':'نوع فراخوان','organization.name':'دستگاه مناقصه‌گزار',
    'operationProvinceName':'استان محل اجرا','operationCityName':'شهر محل اجرا','domainCatName':'دسته‌بندی',
    'subjectClassification':'طبقه‌بندی موضوعی','domainsDescription':'شرح فعالیت','publicNotificationDate':'تاریخ انتشار',
    'documentsDeadlineDate':'مهلت دریافت اسناد','proposalDeadlineDate':'مهلت ارسال پیشنهاد','openingDate':'زمان بازگشایی',
    'tenderDocumentsPrice':'مبلغ خرید اسناد','id':'شناسه داخلی سامانه',
}


def raw_fields(raw_json: str) -> list[tuple[str,str]]:
    try:raw=json.loads(raw_json or '{}')
    except ValueError:return []
    out=[]
    for k,v in flatten(raw):
        if v in (None,'','null') or isinstance(v,bool):continue
        out.append((k,text(v)))
    return out


def safe_name(value: str, max_chars=95) -> str:
    v=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',text(value)).strip('. ')
    return (v[:max_chars].rstrip('. ') or 'unnamed')


def content_is_html(headers: dict, body: bytes) -> bool:
    mime=str(headers.get('content-type','')).lower()
    begin=body[:600].lstrip().lower()
    return ('text/html' in mime or begin.startswith(b'<!doctype html') or begin.startswith(b'<html')
            or begin.startswith(b'<head') or begin.startswith(b'<body'))


_SECRET_NAME=re.compile(r'(csrf|token|session|jsession|auth|pass|cookie|ticket)',re.I)
_LONG_TOKEN=re.compile(r'[A-Za-z0-9+/_=-]{32,}')


def redact(value: str) -> str:
    """Diagnostics must never carry cookies/tokens."""
    s=str(value or '')
    s=re.sub(r'((?:csrf|token|session|jsessionid|ticket)[\w.-]*\s*[=:]\s*)[^&\s"\';,]+',r'\1[حذف]',s,flags=re.I)
    return _LONG_TOKEN.sub('[حذف]',s)


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name or ''))


# ------------------------------------------------- v0.3: Persian titles identical to the site
KEY_ALIASES = {
    'number': ('number', 'tenderNumber'), 'title': ('title', 'subject', 'tenderTitle'),
    'type_name': ('typeName', 'tenderTypeName', 'tenderType'), 'organization': ('organization.name', 'organizationName', 'organization'),
    'province': ('operationProvinceName', 'provinceName'), 'city': ('operationCityName', 'cityName'),
    'category': ('domainCatName', 'subjectClassification'), 'description': ('domainsDescription', 'domainDescription'),
    'published': ('publicNotificationDate', 'publishDate'), 'documents_deadline': ('documentsDeadlineDate', 'receiveDocumentsDeadline'),
    'proposal_deadline': ('proposalDeadlineDate', 'proposalDeadline'), 'opening_date': ('openingDate', 'proposalOpeningDate'),
    'price': ('tenderDocumentsPrice', 'documentsPrice'),
}
DEFAULT_TITLES = {
    'number': 'شماره فراخوان', 'title': 'عنوان فراخوان', 'type_name': 'نوع فراخوان', 'organization': 'دستگاه مناقصه‌گزار',
    'province': 'استان محل اجرا', 'city': 'شهر محل اجرا', 'category': 'دسته‌بندی', 'description': 'شرح فعالیت',
    'published': 'تاریخ انتشار', 'documents_deadline': 'مهلت دریافت اسناد', 'proposal_deadline': 'مهلت ارسال پیشنهاد',
    'opening_date': 'زمان بازگشایی', 'price': 'مبلغ خرید اسناد',
}


def site_title(field: str, learned: dict | None = None) -> str:
    """Persian title of a tender field exactly as the site's own grid header (learned), else a default."""
    learned = learned or {}
    for key in KEY_ALIASES.get(field, (field,)):
        if learned.get(key):
            return re.sub(r'\s*\(\s*[A-Za-z][A-Za-z0-9 _\-/.]*\)\s*$', '', learned[key]).strip() or learned[key]   # no English gloss
    return DEFAULT_TITLES.get(field, field)


def raw_label(key: str, learned: dict | None = None):
    """Persian label for a raw JSON key, or None when the key has no Persian title (technical field)."""
    learned = learned or {}
    if learned.get(key):
        return learned[key]
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    return None


_SECTION_WORDS = [
    ('زمان‌بندی', ('تاریخ', 'مهلت', 'زمان', 'ساعت', 'بازگشایی')),
    ('مالی و تضمین', ('مبلغ', 'تضمین', 'ضمانت', 'ریال', 'قیمت', 'برآورد', 'سپرده', 'هزینه', 'بودجه', 'اعتبار')),
    ('دستگاه و تماس', ('دستگاه', 'سازمان', 'کارفرما', 'مناقصه‌گزار', 'آدرس', 'نشانی', 'تلفن', 'پست', 'نماینده', 'کد')),
]


def group_pairs(pairs):
    """Split the site's detail label/value pairs into titled sections (order kept, titles are fixed)."""
    sections = {'مشخصات فراخوان': [], 'زمان‌بندی': [], 'مالی و تضمین': [], 'دستگاه و تماس': []}
    for label, value in pairs or []:
        placed = False
        for name, words in _SECTION_WORDS:
            if any(w in label for w in words):
                sections[name].append((label, value));placed = True;break
        if not placed:
            sections['مشخصات فراخوان'].append((label, value))
    return [(k, v) for k, v in sections.items() if v]


TECH_LABELS = {
    'allSetupType': 'نوع برگزاری (مراحل)', 'type': 'نوع فراخوان', 'tenderType': 'نوع فراخوان',
    'favoriteCount': 'تعداد علاقه‌مندان', 'advertisementCount': 'تعداد آگهی', 'tenderDocumentsPrice': 'مبلغ خرید اسناد',
    'evaluationType': 'نوع ارزیابی', 'state': 'وضعیت', 'status': 'وضعیت', 'currency': 'واحد پول',
    'guaranteeAmount': 'مبلغ تضمین', 'estimatePrice': 'برآورد', 'estimatedPrice': 'برآورد',
}
VALUE_LABELS = {
    'ONE_PART': 'یک‌مرحله‌ای', 'TWO_PART': 'دومرحله‌ای', 'ONE_STAGE': 'یک‌مرحله‌ای', 'TWO_STAGE': 'دومرحله‌ای',
    'PUBLIC_TENDER': 'مناقصه عمومی', 'LIMITED_TENDER': 'مناقصه محدود',
    'COMPACT_PUBLIC_TENDER': 'مناقصه عمومی فشرده', 'QUALITY_EVALUATION_PUBLIC_TENDER': 'مناقصه عمومی با ارزیابی کیفی',
    'COMPACT_QUALITY_EVALUATION_PUBLIC_TENDER': 'مناقصه عمومی فشرده با ارزیابی کیفی',
    'TWO_STAGE_PUBLIC_TENDER': 'مناقصه عمومی دومرحله‌ای', 'TRUE': 'بله', 'FALSE': 'خیر',
}
_HIDDEN_KEY = re.compile(r'(^|\.)(id|recCount|version)$|Id$|Ids$|Code$', re.I)


def value_label(v):
    t = str(v).strip()
    return VALUE_LABELS.get(t.upper(), t)


def technical_fields(raw_json: str, learned: dict | None = None):
    """(persian_rows, technical_rows) from the list JSON.
    Empty values and internal ids are dropped; known English keys/enum values get Persian titles."""
    fa, tech = [], []
    for k, v in raw_fields(raw_json):
        val = '' if v is None else str(v).strip()
        if val in ('', 'None', 'null', '[]', '{}'):
            continue
        lab = raw_label(k, learned) or TECH_LABELS.get(k) or TECH_LABELS.get(k.split('.')[-1])
        if lab:
            fa.append((lab, value_label(val)))
        elif not _HIDDEN_KEY.search(k):
            tech.append((k, value_label(val)))
    return fa, tech



# ------------------------------------------------------------------- «+» button (site's own formula)
# favoriteForm(id, Number(tenderDocumentsPrice), organization.id, tenderTypeId, allSetupTypeId) — from the
# site's favoriteCountViewFormatter; the list JSON carries type/allSetupType as names, the button sends codes.
TENDER_TYPE_CODES = {
    'QUALITY_EVALUATION_TENDER': 4120, 'PUBLIC_TENDER': 4121, 'QUALITY_EVALUATION_PUBLIC_TENDER': 4122,
    'SHORT_LIST_QUALITY_EVALUATION': 4123, 'COMPACT_QUALITY_EVALUATION_PUBLIC_TENDER': 4128,
    'CONSULTING_SERVICES_QUALITY_EVALUATION': 4130, 'COMPETENCY_ASSESSMENT': 4134,
}
SETUP_TYPE_CODES = {'ONE_PART': 3101, 'TWO_PART': 3102, 'CONCURRENT': 3103, 'NON_CONCURRENT': 3104,
                    'WITHOUT_PUBLICATION': 3105}


def _js_number(v):
    if v in (None, ''):
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def favorite_args_from_list(raw: dict):
    """The five favoriteForm arguments built from one list row, like the site's grid formatter."""
    if not isinstance(raw, dict) or raw.get('id') is None:
        return None
    org = raw.get('organization')
    org_id = org.get('id') if isinstance(org, dict) else raw.get('organization.id', raw.get('organizationId'))
    if org_id in (None, ''):
        return None
    return {'id': str(raw['id']), 'price': _js_number(raw.get('tenderDocumentsPrice')), 'organizationId': str(org_id),
            'typeId': TENDER_TYPE_CODES.get(str(raw.get('type') or '')),
            'setupId': SETUP_TYPE_CODES.get(str(raw.get('allSetupType') or ''))}


def is_favorited(raw: dict) -> bool:
    """favoriteCount > 0 → the site shows the grey star: already in «فراخوان‌های من»."""
    try:
        return float(raw.get('favoriteCount') or 0) > 0
    except (TypeError, ValueError):
        return False


def codes_from_details_html(html: str) -> dict:
    out = {}
    m = re.search(r'name="tenderDto\.tender\.type"[^>]*value="(\d+)"', html or '') or \
        re.search(r'value="(\d+)"[^>]*name="tenderDto\.tender\.type"', html or '')
    if m:
        out['type'] = int(m.group(1))
    sel = re.search(r'<select[^>]*name="tenderDto\.tender\.setupType"[^>]*>(.*?)</select>', html or '', re.S)
    if sel:
        opt = re.search(r'<option[^>]*value="(\d+)"[^>]*selected', sel.group(1)) or \
              re.search(r'<option[^>]*selected[^>]*value="(\d+)"', sel.group(1))
        if opt:
            out['setup'] = int(opt.group(1))
    return out


def my_call_tender_ids(rows) -> set:
    """Tender ids in a «فراخوان‌های من» grid; real rows look like {entity:{…}, id:null}."""
    out = set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        e = r.get('entity') if isinstance(r.get('entity'), dict) else {}
        pt = e.get('participationTender') if isinstance(e.get('participationTender'), dict) else {}
        pt_t = pt.get('tender') if isinstance(pt.get('tender'), dict) else {}
        if pt_t.get('id') not in (None, ''):          # real site: entity.participationTender.tender.id
            out.add(str(pt_t['id']))
            continue
        for c in (r.get('tenderId'), r.get('id'), e.get('id'), e.get('tenderId'),
                  (e.get('tender') or {}).get('id') if isinstance(e.get('tender'), dict) else None,
                  (r.get('tender') or {}).get('id') if isinstance(r.get('tender'), dict) else None):
            if c not in (None, ''):
                out.add(str(c))
    return out


TENDER_STATE_NAMES = {'REPEATED': 'تجدید شده', 'REVOCATION': 'لغو شده'}
# the site's participation states that mean «packets already uploaded/sent» (deleting is then locked in the app)
SENT_STATES = {'END_PROPOSAL_DEADLINE_DATE', 'SEND_PACKETS', 'SENT_PACKETS', 'PACKETS_SENT', 'OPENING', 'IN_OPENING'}


def my_call_states(rows) -> dict:
    """tender id -> {'state','state_name','tender_state'} from «فراخوان‌های من» rows (as the site shows them)."""
    out = {}
    for r in rows or []:
        e = r.get('entity') if isinstance(r, dict) and isinstance(r.get('entity'), dict) else {}
        pt = e.get('participationTender') if isinstance(e.get('participationTender'), dict) else {}
        t = pt.get('tender') if isinstance(pt.get('tender'), dict) else {}
        if t.get('id') in (None, ''):
            continue
        ts = str(t.get('state') or '')
        name = TENDER_STATE_NAMES.get(ts) or str(pt.get('stateName') or pt.get('state') or '')
        ed = t.get('lastTenderEdition') if isinstance(t.get('lastTenderEdition'), dict) else {}
        g = lambda k: ('' if t.get(k) in (None, '') else str(t.get(k)))
        out[str(t['id'])] = {'state': str(pt.get('state') or ''), 'state_name': name.strip(), 'tender_state': ts,
                             'downloads': pt.get('downloadCount'), 'type': str(t.get('type') or ''),
                             'opening': g('openingDate'), 'eval_deadline': g('evaluationDeadlineDate'),
                             'proposal': g('proposalDeadlineDate'), 'edition_date': g('supplierLastEditionDate'),
                             'edition_no': '' if ed.get('supplierNumber') in (None, '') else str(ed['supplierNumber'])}
    return out
