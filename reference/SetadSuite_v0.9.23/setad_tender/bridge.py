"""Site adapter. Browser-driven authentication; same-origin requests; no stored secrets.

Design note (v0.2): the site uses per-session Struts "conversation" ids
(e.g. callMainPageCartableAction_conversation=N). Hard-coding them breaks.
Instead of guessing URLs, the adapter calls the site's OWN JavaScript function
(showTenderRegister, favoriteForm, showAppendix ...) inside the live page with the
network stubbed out, captures the exact request it would send, and replays that
request with fetch() - so the visible page never navigates away from the list.
"""
from __future__ import annotations
import base64
import json
import re
import time
from datetime import datetime
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qsl
from .parsers import (groups_from_html, file_rows_from_json, DOCUMENT_FALLBACK, content_is_html, safe_name,
                      details_from_html, detail_pairs_from_html, looks_like_details, looks_like_login,
                      find_appendix_list_url, redact, is_secret_name, file_rows_from_html, looks_like_file_list,
                      make_template, fill_template, json_shape, redact_html, _js_args,
                      codes_from_details_html, my_call_tender_ids)

SITE='https://etend.setadiran.ir'
# The three Setad hosts the app talks to (tests point these at local fakes).
HOSTS={'etend':'etend.setadiran.ir','eproc':'eproc.setadiran.ir','sso':'sso2.setadiran.ir'}
EPROC_BOARD='https://eproc.setadiran.ir/eproc/needBoardInfo-load.do?pager=true'
ROLE_WORDS={'ETEND':['مناقصه گر','مناقصه‌گر','مناقصه'],
            'EPROC':['تامین کننده','تأمین کننده','تامین‌کننده','تأمین‌کننده']}
ROLE_TITLES={'ETEND':'مناقصه‌گر','EPROC':'تامین‌کننده'}
ROLE_HOST={'ETEND':'etend','EPROC':'eproc'}
# document page per tender type (observed on the real site)
DOCS_ACTIONS={'QUALITY_EVALUATION_TENDER':['evaluationDocumentDownloadAndPayment-execute','downloadTenderDocs-load']}
DOCS_DEFAULT=['downloadTenderDocs-load','evaluationDocumentDownloadAndPayment-execute']
# site function that opens a tender's details, per tender type (from the grid formatter)
DETAIL_FN={'QUALITY_EVALUATION_TENDER':'evaluationSupplierView','SHORT_LIST_QUALITY_EVALUATION':'evaluation4ListSupplierView',
           'COMPETENCY_ASSESSMENT':'evaluation4ListSupplierView','CONSULTING_SERVICES_QUALITY_EVALUATION':'consultingEvaluationCounselorView'}


def host_kind(raw_url):
    try:netloc=urlparse(str(raw_url)).netloc.lower()
    except (TypeError,ValueError):return None
    for k,h in HOSTS.items():
        if netloc==h:return k
    return None


def friendly_error(text) -> str:
    """Technical browser/network errors → a plain Persian sentence (anything else is returned unchanged)."""
    t=str(text or '')
    if any(x in t for x in ('ERR_ABORTED','ERR_CONNECTION','ERR_NAME_NOT_RESOLVED','ERR_TIMED_OUT','ERR_INTERNET','ERR_NETWORK',
                            'net::','Timeout ','timeout exceeded','Timeout exceeded')):
        return ('سایت ستاد در حال حاضر پاسخ نمی‌دهد (ممکن است خارج از ساعت کاری یا در حال به‌روزرسانی باشد). '
                'چند دقیقه بعد دوباره امتحان کنید.')
    if any(x in t for x in ('Target page, context or browser has been closed','Target closed','Browser has been closed',
                            'has been closed','Connection closed')):
        return 'پنجره مرورگر ستاد بسته شد. برای ادامه «اتصال به ستاد» را بزنید.'
    if 'Execution context was destroyed' in t or 'frame was detached' in t:
        return 'صفحه ستاد وسط کار عوض شد. چند لحظه بعد دوباره امتحان کنید.'
    return t


def friendly_nav_error(e) -> str:
    t=str(e)
    if any(x in t for x in ('ERR_ABORTED','ERR_CONNECTION','ERR_NAME_NOT_RESOLVED','ERR_TIMED_OUT','Timeout','timeout','ERR_INTERNET')):
        return ('سایت ستاد در حال حاضر پاسخ نمی‌دهد (ممکن است خارج از ساعت کاری یا در حال به‌روزرسانی باشد). '
                'چند دقیقه بعد دوباره امتحان کنید.')
    return 'باز کردن صفحه ستاد ممکن نشد: '+t.splitlines()[0][:160]


def is_setad_url(raw_url: str) -> bool:
    """Either Setad system (etend = tenders, eproc = purchase); used only by the site-flow recorder."""
    try:
        parsed=urlparse(raw_url)
        return parsed.scheme=='https' and parsed.hostname in ('etend.setadiran.ir','eproc.setadiran.ir')
    except (TypeError,ValueError):
        return False


def is_site_url(raw_url: str) -> bool:
    """Trust only the exact authenticated site, not hosts with matching prefixes."""
    try:
        parsed=urlparse(raw_url)
        return parsed.scheme=='https' and parsed.hostname=='etend.setadiran.ir'
    except (TypeError,ValueError):
        return False


def safe_page_label(raw_url: str) -> str:
    """Diagnostics contain only host/path, never query strings or login tokens."""
    try:
        parsed=urlparse(raw_url)
        return (parsed.hostname or '(بدون آدرس)')+(parsed.path or '/')[:105]
    except (TypeError,ValueError):
        return '(آدرس نامعتبر)'


JS_SOURCE = '''() => {
 const grid=window.jQuery?.('#tendersGrid');
 if (!grid || !grid.length || typeof grid.jqGrid !== 'function') return null;
 const get=k=>grid.jqGrid('getGridParam',k);
 const url=get('url');
 if (!url) return null;
 const u=new URL(url,location.href);
 const labels={};
 try { const names=get('colNames')||[], model=get('colModel')||[];
   model.forEach((m,i)=>{ const t=String(names[i]||'').replace(/<[^>]*>/g,'').trim();
     if (m && m.name && t && m.name!=='cb' && m.name!=='rn') labels[m.name]=t; }); } catch(e) {}
 return {url:u.href,postData:get('postData')||{},rows:get('rowNum'),
         records:get('records'),pages:get('lastpage'),labels,
         filters:Object.fromEntries(u.searchParams.entries())};
}'''

JS_FETCH_JSON = '''async a => {
 const u=new URL(a.url,location.href);
 if (u.origin!==location.origin) throw Error('Blocked cross-origin request');
 for (const [k,v] of Object.entries(a.postData||{})) {
   if (v!==null && v!==undefined && ['string','number','boolean'].includes(typeof v)) u.searchParams.set(k,String(v));
 }
 for (const [k,v] of Object.entries(a.overrides||{})) u.searchParams.set(k,String(v));
 const controller = new AbortController();
 const timeout = setTimeout(()=>controller.abort(),25000);
 try {
   const resp=await fetch(u.href,{method:'GET',credentials:'same-origin',cache:'no-store',signal:controller.signal,
     headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
   const body=await resp.text();
   if (!resp.ok) throw Error('HTTP '+resp.status);
   try {return JSON.parse(body)} catch {throw Error('Expected JSON; login/session may have expired')}
 } finally {clearTimeout(timeout)}
}'''

# Collect per-session conversation ids, forms and site function sources (diagnostics only).
JS_PROBE = r'''() => {
 const conv={};
 const add=s=>{ if(!s) return; const re=/([A-Za-z0-9]+Action_conversation)=([0-9A-Za-z_-]+)/g; let m;
   while((m=re.exec(String(s)))) conv[m[1]]=m[2]; };
 add(location.href);
 document.querySelectorAll('form[action],a[href],[onclick]').forEach(e=>{
   add(e.getAttribute('action'));add(e.getAttribute('href'));add(e.getAttribute('onclick'))});
 document.querySelectorAll('input[name$="_conversation"]').forEach(i=>{ if(i.value) conv[i.name]=i.value });
 document.querySelectorAll('script:not([src])').forEach(s=>add((s.textContent||'').slice(0,300000)));
 try{ const g=window.jQuery&&jQuery('#tendersGrid'); if(g&&g.length&&g.jqGrid) add(g.jqGrid('getGridParam','url')); }catch(e){}
 const fns={};
 for (const k of Object.keys(window)) { try{ const f=window[k];
   if(typeof f==='function' && /tender|appendix|doc|favor|download|cartable|register|call|attach/i.test(k)) {
     const src=Function.prototype.toString.call(f); if(!/\[native code\]/.test(src)) fns[k]=src.slice(0,5000);} }catch(e){} }
 const forms=[...document.forms].slice(0,30).map(f=>({id:f.id||'',name:f.getAttribute('name')||'',
   action:(f.getAttribute('action')||''),method:(f.getAttribute('method')||'get'),
   inputs:[...f.elements].map(e=>e.name).filter(Boolean).slice(0,80)}));
 const scripts=[...document.querySelectorAll('script[src]')].map(s=>s.getAttribute('src')).slice(0,60);
 return {conv, fns, forms, scripts, title:document.title, path:location.pathname,
         jquery:!!window.jQuery, grid:!!document.querySelector('#tendersGrid')};
}'''

# Call a site function with the network stubbed; return the requests it tried to send.
JS_INTERCEPT = r'''async a => {
 const cap=[]; const W=window; const $=W.jQuery;
 const abs=u=>{try{return new URL(String(u),location.href).href}catch(e){return String(u)}};
 const pairs=d=>{ try{
   if(d===undefined||d===null) return [];
   if(typeof d==='string') return [...new URLSearchParams(d)];
   if(d instanceof FormData) return [...d].filter(x=>typeof x[1]==='string');
   if(d instanceof URLSearchParams) return [...d];
   if(typeof d==='object') return [...new URLSearchParams($&&$.param?$.param(d,true):Object.entries(d).map(([k,v])=>[k,String(v)]))];
 }catch(e){} return []; };
 const P=HTMLFormElement.prototype, X=XMLHttpRequest.prototype;
 const saved={submit:P.submit, rsubmit:P.requestSubmit, open:W.open, fetch:W.fetch, xo:X.open, xs:X.send,
   xh:X.setRequestHeader, confirm:W.confirm, alert:W.alert, ajax:$&&$.ajax};
 const formCap=f=>cap.push({kind:'form',url:abs(f.getAttribute('action')||location.href),
   method:String(f.getAttribute('method')||'GET').toUpperCase(),data:pairs(new FormData(f))});
 const onSubmit=e=>{ formCap(e.target); e.preventDefault(); e.stopImmediatePropagation(); };
 P.submit=function(){formCap(this)};
 if(saved.rsubmit) P.requestSubmit=function(){formCap(this)};
 document.addEventListener('submit',onSubmit,true);
 W.open=u=>{cap.push({kind:'open',url:abs(u||'about:blank'),method:'GET',data:[]});return null};
 W.fetch=(u,o)=>{o=o||{};cap.push({kind:'fetch',url:abs(u&&u.url||u),method:String(o.method||'GET').toUpperCase(),data:pairs(o.body)});return new Promise(()=>{})};
 X.open=function(m,u){this.__c={kind:'xhr',url:abs(u),method:String(m).toUpperCase(),data:[]}};
 X.setRequestHeader=function(){};
 X.send=function(b){ if(this.__c){this.__c.data=pairs(b);cap.push(this.__c)} };
 W.confirm=()=>true; W.alert=()=>{};
 if($&&saved.ajax){ $.ajax=function(u,o){ const s=(typeof u==='object')?u:Object.assign({},o||{},{url:u});
   cap.push({kind:'ajax',url:abs(s.url||location.href),method:String(s.type||s.method||'GET').toUpperCase(),data:pairs(s.data)});
   return $.Deferred().promise(); } }
 let error=null, missing=false;
 try {
   if (a.code) { (new Function(a.code)).call(W); }
   else { const f=W[a.fn]; if(typeof f!=='function') missing=true; else f.apply(W,a.args||[]); }
   if(!missing) await new Promise(r=>setTimeout(r,a.wait||450));
 } catch(e){ error=String(e&&e.message||e).slice(0,300) }
 finally {
   P.submit=saved.submit; if(saved.rsubmit) P.requestSubmit=saved.rsubmit;
   document.removeEventListener('submit',onSubmit,true);
   W.open=saved.open; W.fetch=saved.fetch; X.open=saved.xo; X.send=saved.xs; X.setRequestHeader=saved.xh;
   W.confirm=saved.confirm; W.alert=saved.alert; if($&&saved.ajax) $.ajax=saved.ajax;
 }
 return {captured:cap,error,missing};
}'''

JS_REPLAY = '''async a => {
 const u=new URL(a.url,location.href);
 if (u.origin!==location.origin) throw Error('Blocked cross-origin request');
 const body=new URLSearchParams(a.data||[]);
 const opt={method:a.method||'GET',credentials:'same-origin',cache:'no-store',headers:{}};
 if (a.xhr) {opt.headers['X-Requested-With']='XMLHttpRequest';}
 if (opt.method==='GET') { if(a.kind==='form') u.search=''; for (const [k,v] of body) u.searchParams.append(k,v); }
 else { opt.body=body.toString(); opt.headers['Content-Type']='application/x-www-form-urlencoded; charset=UTF-8'; }
 const ctl=new AbortController(); const t=setTimeout(()=>ctl.abort(),30000); opt.signal=ctl.signal;
 try { const r=await fetch(u.href,opt); const text=await r.text();
   return {ok:r.ok,status:r.status,text,path:new URL(r.url).pathname,ctype:r.headers.get('content-type')||''};
 } finally {clearTimeout(t)}
}'''

JS_FETCH_BINARY = '''async a => {
 const u=new URL(a.path,location.href);
 if (u.origin!==location.origin) throw Error('Blocked cross-origin request');
 for (const [k,v] of Object.entries(a.params||{})) u.searchParams.set(k,String(v));
 const r=await fetch(u.href,{credentials:'same-origin',cache:'no-store'});
 const b=new Uint8Array(await r.arrayBuffer()); let s='';
 for (let i=0;i<b.length;i+=0x8000) s+=String.fromCharCode.apply(null,b.subarray(i,i+0x8000));
 return {ok:r.ok,status:r.status,ctype:r.headers.get('content-type')||'',b64:btoa(s)};
}'''

JS_FAV_SAMPLES = r'''() => {
 const out=[]; const grid=document.querySelector('#tendersGrid'); if(!grid) return out;
 for (const a of grid.querySelectorAll('a[onclick*="favoriteForm("]')) {
   const m=(a.getAttribute('onclick')||'').match(/favoriteForm\(\s*(\d+)\s*,\s*([\d.]+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/);
   if (m) out.push({id:m[1],price:m[2],organizationId:m[3],typeId:m[4],setupId:m[5]});
 }
 return out;
}'''

JS_ADD = '''async a => {
 if (!a.confirmed) throw Error('Explicit user confirmation required');
 const params=new URLSearchParams({tenderId:String(a.id),tenderDocumentsPrice:String(a.price),
   organizationId:String(a.organizationId),tenderTypeId:String(a.typeId),allSetupType:String(a.setupId)});
 if (typeof window.getCsrfTokenParamNameAndValue === 'function') {
   const parts=String(window.getCsrfTokenParamNameAndValue()).replace(/^&/,'');
   for (const [k,v] of new URLSearchParams(parts).entries()) params.set(k,v);
 } else {
   const input=document.getElementsByName('csrf_token')[0]; if(input) params.set('csrf_token',input.value);
 }
 const u=new URL('/etend/callMainPageCartable-add.action',location.href);
 for (const [k,v] of Object.entries(a.conv||{})) u.searchParams.set(k,String(v));
 const response=await fetch(u.href,{
   method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
   'X-Requested-With':'XMLHttpRequest','Accept':'application/json'},body:params.toString()});
 const body=await response.text();
 return {ok:response.ok,status:response.status,text:body};
}'''

JS_NATIVE_FAVORITE = '''args => {
 if (typeof window.favoriteForm!=='function') throw Error('تابع favoriteForm در صفحه نیست');
 const c=window.confirm, al=window.alert; window.confirm=()=>true; window.alert=()=>{};
 try { window.favoriteForm(...args); } finally { setTimeout(()=>{window.confirm=c; window.alert=al;},3000); }
 return true;
}'''

JS_SSO_STATE = '''() => ({role: !!document.querySelector('input[name=appType]'),
 pwd: !!document.querySelector('input[type=password]'), roles: document.querySelectorAll('input[name=role]').length})'''

JS_PICK_SYSTEM = '''id => { const r=document.getElementById(id); if(!r) return false; if(!r.checked) r.click();
 try{ r.dispatchEvent(new Event('change',{bubbles:true})); }catch(e){} return true; }'''

JS_PICK_ROLE = r'''words => {
 const norm=t=>String(t||'').replace(/[\u200c\u200f\u200e]/g,' ').replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/\s+/g,' ').trim();
 const items=[...document.querySelectorAll('input[name=role]')];
 if (!items.length) return null;
 const lab=i=>{ const l=document.querySelector('label[for="'+i.id+'"]'); return norm(l?l.textContent:i.value); };
 for (const w of words) for (const i of items) if (lab(i).includes(norm(w))) { if(!i.checked) i.click(); return lab(i); }
 if (items.length===1) { if(!items[0].checked) items[0].click(); return lab(items[0]); }
 return '';
}'''

JS_START_ROLE = '''() => { const b=document.getElementById('start-button')||[...document.querySelectorAll('button')].find(x=>/شروع|ورود|تایید|تأیید/.test(x.textContent));
 if(!b) return false; b.click(); return true; }'''

JS_CLICK_MENU = r'''() => {
 const mk=document.getElementById('callMainPageCartableExecuteMenuLink');      // the site's own «فراخوان ها» menu link
 if (mk) { try { mk.click(); return 'menu-link'; } catch(err) {} }
 const norm=t=>String(t||'').replace(/[\u200c\u200f\u200e]/g,' ').replace(/\s+/g,' ').trim();
 const want=['فراخوان ها','فراخوانها'];
 const els=[...document.querySelectorAll('a,li,span,div,button')];
 for (const e of els) {
   if (e.children.length>3) continue;
   const t=norm(e.textContent);
   if (want.includes(t) && !t.includes('من')) {
     const target=e.closest('a')||e; try { target.click(); return t; } catch(err) {}
   }
 }
 return '';
}'''

JS_ANCHOR_DOWNLOAD = '''a => {
 const u=new URL(a.url,location.href);
 if (u.origin!==location.origin) throw Error('Blocked cross-origin request');
 document.querySelectorAll('[data-stm-dl]').forEach(e=>e.remove());
 const el=document.createElement('a'); el.href=u.href; el.setAttribute('download',a.name||''); el.target='_self';
 el.setAttribute('data-stm-dl','1'); el.style.display='none'; document.body.appendChild(el); el.click();
 setTimeout(()=>el.remove(),1500); return true;
}'''

JS_FIND_DL = r'''id => {
 const q=String(id);
 const hit=e=>{ const h=(e.getAttribute('href')||'')+' '+(e.getAttribute('onclick')||'');
   return (/appendix-?download|download/i.test(h) && (new RegExp('(appendixId=|\\b)'+q+'\\b')).test(h)); };
 const els=[...document.querySelectorAll('a,button,span,i,img,input,[onclick]')].filter(hit);
 return els.length;
}'''

JS_CLICK_DL = r'''id => {
 const q=String(id);
 const hit=e=>{ const h=(e.getAttribute('href')||'')+' '+(e.getAttribute('onclick')||'');
   return (/appendix-?download|download/i.test(h) && (new RegExp('(appendixId=|\\b)'+q+'\\b')).test(h)); };
 const els=[...document.querySelectorAll('a,button,span,i,img,input,[onclick]')].filter(hit);
 if (!els.length) return false; (els[0].closest('a')||els[0]).click(); return true;
}'''

JS_PAGE_ASSETS = '''() => ({scripts:[...document.querySelectorAll('script[src]')].map(s=>s.src),
  styles:[...document.querySelectorAll('link[rel="stylesheet"]')].map(l=>l.href)})'''

JS_RUN_CODE = '''c => { (new Function(c)).call(window); return true; }'''

JS_CLOSE_DIALOGS = '''() => { try { window.jQuery && jQuery('.ui-dialog-content').dialog('close'); } catch(e) {} }'''

SANDBOX_URL = SITE+'/etend/stm-sandbox.action'
STATIC_EXT = ('.js','.css','.png','.jpg','.jpeg','.gif','.svg','.woff','.woff2','.ttf','.eot','.ico','.map')

JS_UPDATE_CSRF = '''v => {
 // exactly what the site does: document.getElementsByName('csrf_token').item(0).value = newCsrfTokenValue
 if (!v) return false;
 const n=document.getElementsByName('struts.token.name')[0];
 const name=(n && n.value && document.getElementsByName(n.value)[0]) ? n.value : 'csrf_token';
 const i=document.getElementsByName(name)[0]; if(!i) return false; i.value=v; return true;
}'''

# getCsrfTokenParamNameAndValue() reads the *name* of the token field from struts.token.name — keep it intact
JS_REPAIR_TOKEN = '''() => {
 const n=document.getElementsByName('struts.token.name')[0];
 if (n && n.value && !document.getElementsByName(n.value)[0] && document.getElementsByName('csrf_token')[0]) { n.value='csrf_token'; return true; }
 return false;
}'''

JS_TOKEN_PARAMS = '''() => {
 try { if (typeof window.getCsrfTokenParamNameAndValue==='function') return String(window.getCsrfTokenParamNameAndValue()).replace(/^&/,''); } catch(e){}
 const i=document.getElementsByName('csrf_token')[0]; return i ? 'struts.token.name=csrf_token&csrf_token='+encodeURIComponent(i.value) : '';
}'''


class SiteError(RuntimeError): pass


def _num(value):
    """Turn '675227' / '0.0' into JS-number-friendly values (the site passes number literals)."""
    s=str(value)
    try:
        f=float(s)
        return int(f) if f.is_integer() and '.' not in s.rstrip('0').rstrip('.') else f
    except ValueError:
        return s


class SetadBrowser:
    def __init__(self,profile_dir: Path):
        self.profile_dir=Path(profile_dir)
        self.profile_dir.mkdir(parents=True,exist_ok=True)
        self._temp_profile=None
        self.playwright=None
        self.context=None
        self.source=None
        self.source_frame=None
        self.work=None            # the ONE shared tab: both sections navigate inside it
        self._closed=False
        self.conv={}          # per-session Struts conversation ids discovered on the page
        self.trace=[]         # strategy log of the last operation (shown to user / diagnostics)
        self._details_html={} # tender id -> raw details page (for the helper tab)
        self.list_template=None      # learned request template for a category's file list
        self.download_template=None  # learned request template for a file download
        self.learned={}              # templates learned during this session (worker persists them)
        self.download_dir=None       # where manual downloads in the app browser are saved
        self._dl_queue=[];self._rec=None;self.saved_downloads=[];self._native=False
        self.role=None              # 'ETEND' / 'EPROC' — Setad allows one active role at a time
        self.on_role=None           # callback(role) set by the worker
        self.channel=None
        self.tender_types={}        # tender id -> list 'type' (picks details / documents page)
        self._docs_open={}          # tender id -> info of the «دریافت اسناد» page opened in this session

    # --- Event pumping -------------------------------------------------------
    # Playwright's sync API dispatches browser events only while a Playwright call
    # runs; pump() lets it process navigations/new tabs that happened meanwhile.
    def pump(self,ms:int=0):
        if not self.context:
            if ms:time.sleep(ms/1000)
            return
        for p in list(self.context.pages):
            try:
                if not p.is_closed():
                    p.wait_for_timeout(ms)
                    return
            except Exception:
                continue
        try:
            self.context.cookies()
        except Exception:
            self._closed=True
        if ms:time.sleep(ms/1000)

    def alive(self) -> bool:
        if self.context is None or self._closed:return False
        self.pump(0)
        return not self._closed

    def _mark_closed(self,*_):
        self._closed=True

    def open(self,start=None):
        start=start or SITE+'/etend/indexPage.action'
        if self.context is not None and not self.alive():
            self.close()
        if self.context is not None and not [p for p in self.context.pages if not p.is_closed()]:
            try:
                p=self.context.new_page()
                self.work=p
                p.goto(start,wait_until='domcontentloaded',timeout=45000)
                return 'تب جدید در مرورگر اختصاصی باز شد؛ وارد شوید و «فراخوان‌ها» را باز کنید.'
            except Exception:
                self.close()
        if self.context is not None:
            try:
                self.page().bring_to_front()
            except Exception:
                try:
                    if self.context.pages:self.context.pages[-1].bring_to_front()
                except Exception:pass
            return 'مرورگر اختصاصی برنامه از قبل باز است؛ همان‌جا بخش «فراخوان‌ها» را باز کنید و «بررسی اتصال» را بزنید.'
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start()
        launch_errors=[]
        browser=self.playwright.chromium
        self._temp_profile=tempfile.TemporaryDirectory(prefix='setad_browser_')
        opts=dict(user_data_dir=self._temp_profile.name,headless=False,accept_downloads=True,
                  locale='fa-IR',viewport={'width':1360,'height':860})
        for target in ('chrome','msedge',None):
            try:
                if target:
                    self.context=browser.launch_persistent_context(channel=target,**opts)
                    self.channel=target
                else:
                    self.context=browser.launch_persistent_context(**opts)
                break
            except Exception as e:
                launch_errors.append(f'{target or "Playwright Chromium"}: {str(e).splitlines()[0]}')
        if self.context is None:
            self.playwright.stop();self.playwright=None
            self._temp_profile.cleanup();self._temp_profile=None
            raise SiteError('مرورگر قابل اجرا پیدا نشد. Chrome یا Edge نصب کنید یا دستور playwright install chromium را اجرا کنید.\n'+'\n'.join(launch_errors))
        self._closed=False
        self.context.on('close',self._mark_closed)
        self.context.on('page',self._watch_page)
        for pg in self.context.pages:self._watch_page(pg)
        p=self.context.pages[0] if self.context.pages else self.context.new_page()
        self.work=p
        if not is_site_url(p.url) and host_kind(p.url) is None:
            try:p.goto(start,wait_until='domcontentloaded',timeout=45000)
            except Exception as e:raise SiteError(friendly_nav_error(e))
        return 'مرورگر باز شد؛ در سامانه وارد شوید و نقش مناقصه‌گر، سپس «فراخوان‌ها» را باز کنید.'

    def close(self):
        try:
            if self.context: self.context.close()
        except Exception: pass
        self.context=None;self.source=None;self.source_frame=None;self.work=None;self._closed=False;self.conv={}
        self.role=None;self._docs_open={}
        try:
            if self.playwright:self.playwright.stop()
        except Exception: pass
        self.playwright=None
        if self._temp_profile:
            try:self._temp_profile.cleanup()
            except Exception:pass
            self._temp_profile=None

    # --- Locating the tender list ---------------------------------------------
    def _site_tabs(self):
        if not self.context:
            raise SiteError('ابتدا دکمه «بازکردن مرورگر» را بزنید.')
        self.pump(0)
        if self._closed:
            raise SiteError('پنجره مرورگر اختصاصی بسته شده است. دوباره «بازکردن مرورگر» را بزنید و وارد شوید.')
        return [p for p in self.context.pages
                if not p.is_closed() and is_site_url(p.url)]

    def page(self):
        tabs=self._site_tabs()
        if not tabs:
            other=[safe_page_label(p.url) for p in self.context.pages if not p.is_closed()]
            hint='، '.join(other[:4]) or 'هیچ تبی باز نیست'
            raise SiteError(self._login_hint()+
                'صفحه ستاد در مرورگر اختصاصی برنامه پیدا نشد. '
                'از پنجره‌ای استفاده کنید که با دکمه «بازکردن مرورگر» باز شده است.\n'
                'تب‌های برنامه: '+hint)
        if self.source_frame is not None:
            try:
                owner=self.source_frame.page
                if owner in tabs and not owner.is_closed():return owner
            except Exception:pass
        for p in reversed(tabs):
            if '/etend/indexPage.action' in p.url:return p
        return tabs[-1]

    def _login_hint(self) -> str:
        try:
            for p in self.context.pages:
                if p.is_closed():continue
                host=(urlparse(p.url).hostname or '').lower()
                if host.endswith('setadiran.ir') and host!='etend.setadiran.ir':
                    return ('یکی از تب‌ها هنوز روی صفحه ورود/زیرسامانه دیگر ستاد است ('+host+'). '
                            'ورود را کامل کنید تا به etend.setadiran.ir برگردید.\n')
        except Exception:pass
        return ''

    def _grid_candidates(self):
        if not self.context:
            raise SiteError('ابتدا مرورگر اختصاصی برنامه را باز کنید.')
        self.pump(0)
        if self._closed:
            raise SiteError('پنجره مرورگر اختصاصی بسته شده است. دوباره «بازکردن مرورگر» را بزنید و وارد شوید.')
        pages=[p for p in self.context.pages if not p.is_closed()]
        diagnostics=[]
        for p in reversed(pages):
            for f in list(p.frames):
                if not is_site_url(f.url):continue
                try:
                    src=f.evaluate(JS_SOURCE)
                    if src and is_site_url(src.get('url','')):
                        return src,f,diagnostics
                    state=f.evaluate("""() => ({grid: !!document.querySelector('#tendersGrid'),
                        form: !!document.querySelector('#callMainPageCartableForm'), loaded: document.readyState})""")
                    diagnostics.append({'path':safe_page_label(f.url),'grid':bool(state.get('grid')),
                                        'form':bool(state.get('form')),'loaded':state.get('loaded')})
                except Exception:
                    diagnostics.append({'path':safe_page_label(f.url),'grid':False,'form':False,'loaded':'در حال بارگذاری'})
        return None,None,diagnostics

    def capture(self):
        src=frame=None
        diagnostics=[]
        for attempt in range(12):
            src,frame,diagnostics=self._grid_candidates()
            if src:break
            if attempt<11:self.pump(500)
        if not src:
            tabs=[safe_page_label(p.url) for p in self.context.pages if not p.is_closed()]
            if not self._site_tabs():
                raise SiteError(self._login_hint()+'صفحه ستاد در مرورگر اختصاصی برنامه پیدا نشد.\n'
                    'ورود را حتماً در پنجره‌ای انجام دهید که خود برنامه باز کرده، نه مرورگر معمولی ویندوز.\n'
                    'تب‌های برنامه: '+(' | '.join(tabs[:5]) or 'هیچ تب باز نیست'))
            has_grid=any(d.get('grid') for d in diagnostics)
            where=' | '.join(d['path'] for d in diagnostics[:5]) or 'اطلاعات صفحه قابل خواندن نیست'
            reason=('جدول در صفحه وجود دارد، ولی هنوز آماده دریافت نشده است.' if has_grid
                    else 'وارد سایت شده‌اید، اما جدول بخش «فراخوان‌ها» در تب‌های برنامه پیدا نشد.')
            raise SiteError(reason+'\n'
                'در مرورگری که برنامه باز کرده است: نقش «مناقصه‌گر» → از منوی سمت راست «فراخوان‌ها» '
                '(نه «فراخوان‌های من») را باز کنید، صبر کنید جدول ظاهر شود، سپس «بررسی اتصال» را بزنید.\n'
                'صفحه‌های بررسی‌شده: '+where)
        self.source=src
        self.source_frame=frame
        self.refresh_conversations()
        safe_filters={}
        for k,v in src.get('filters',{}).items():
            if is_secret_name(k): continue
            if k.startswith('callMainPageCartableDto.') and v and v!='-1':safe_filters[k]=v
        return {'records':src.get('records'), 'pages':src.get('pages'), 'labels':src.get('labels') or {},
                'rowNum':src.get('rows'),'filters':safe_filters,
                'page':safe_page_label(frame.url)}

    def _target(self):
        if self.source_frame is not None:
            try:
                if is_site_url(self.source_frame.url) and not self.source_frame.page.is_closed():
                    return self.source_frame
            except Exception:pass
        if self.source is None:
            try:
                self.capture()
                return self.source_frame
            except SiteError:
                pass
        return self.page().main_frame

    # --- Conversation ids and request learning --------------------------------
    def refresh_conversations(self):
        found={}
        try:
            for p in self.context.pages:
                if p.is_closed():continue
                for f in p.frames:
                    if not is_site_url(f.url):continue
                    try:
                        info=f.evaluate(JS_PROBE)
                        found.update(info.get('conv') or {})
                    except Exception:pass
        except Exception:pass
        if found:self.conv.update(found)
        return dict(self.conv)

    def _log(self,text):
        self.trace.append(redact(text)[:300])

    def learn_requests(self,frame,fn=None,args=None,code=None,wait=450):
        """Run a site function with all network access stubbed and return the
        same-origin requests it attempted. Real navigations are answered with
        HTTP 204 so the visible page stays where it is."""
        page=frame.page
        navs=[]
        def handler(route,request):
            try:
                if request.is_navigation_request():
                    navs.append({'kind':'nav','url':request.url,'method':request.method,
                                 'data':parse_qsl(request.post_data or '',keep_blank_values=True)
                                        if (request.headers.get('content-type','').startswith('application/x-www-form-urlencoded')) else []})
                    route.fulfill(status=204,body='')
                else:
                    route.continue_()
            except Exception:
                try:route.continue_()
                except Exception:pass
        page.route('**/*',handler)
        try:
            res=frame.evaluate(JS_INTERCEPT,{'fn':fn,'args':args or [],'code':code,'wait':wait})
        finally:
            try:page.unroute('**/*',handler)
            except Exception:pass
        if res.get('missing'):
            self._log(f'تابع {fn} در صفحه وجود ندارد')
            return []
        if res.get('error'):
            self._log(f'خطای اجرای تابع سایت: {res["error"]}')
        reqs=[r for r in (res.get('captured') or [])+navs if is_site_url(r.get('url',''))]
        self._log(f'درخواست‌های شناسایی‌شده از {fn or "دکمه سایت"}: '+
                  (', '.join(f'{r["kind"]}:{safe_page_label(r["url"])}' for r in reqs) or 'هیچ'))
        for r in reqs:
            for k,v in parse_qsl(urlparse(r['url']).query):
                if k.endswith('_conversation'):self.conv[k]=v
            for k,v in r.get('data') or []:
                if k.endswith('_conversation'):self.conv[k]=v
        return reqs

    def replay(self,frame,req,xhr=None):
        if xhr is None:xhr=req.get('kind') in ('ajax','xhr','fetch')
        return frame.evaluate(JS_REPLAY,{'url':req['url'],'method':req.get('method') or 'GET',
                                         'data':req.get('data') or [],'xhr':xhr,'kind':req.get('kind')})

    def _conv_query(self,*prefixes):
        items=[(k,v) for k,v in self.conv.items() if not prefixes or any(k.startswith(p) for p in prefixes)]
        return '&'.join(f'{k}={v}' for k,v in items)

    # --- Tender list ----------------------------------------------------------
    def get_grid_page(self,page_number:int=1,page_size:int=50,extra=None):
        if not self.source:self.capture()
        overrides={'page':page_number,'rows':page_size}
        overrides.update(extra or {})
        data=self._target().evaluate(JS_FETCH_JSON,{'url':self.source['url'],'postData':self.source.get('postData') or {},
                                               'overrides':overrides})
        if not isinstance(data,dict) or not isinstance(data.get('gridModel'),list):
            raise SiteError('سرور فهرست معتبر JSON برنگرداند؛ نشست یا فیلترها را بررسی کنید.')
        return data

    # --- Details --------------------------------------------------------------
    def details(self,tender_id,number='',reset=True):
        """Returns {'text','pairs','groups','method'} for one tender."""
        if reset:self.trace=[]
        frame=self._target()
        tid=str(tender_id)
        attempts=[]
        fn=DETAIL_FN.get(self.tender_types.get(tid,''),'showTenderRegister')
        for req in self.learn_requests(frame,fn,[_num(tid)]):
            if 'appendix' in req['url']:continue
            attempts.append((f'تابع {fn} سایت',req))
        conv=self.conv.get('callMainPageCartableAction_conversation')
        base='/etend/tenderDetails-execute.action'
        body=[('tenderId',tid),('backActionName','afterLoginCallMainPageCartable-execute')]
        if conv:attempts.append(('درخواست مستقیم با conversation='+conv,
                                 {'kind':'form','url':SITE+base+'?callMainPageCartableAction_conversation='+conv,'method':'POST','data':body}))
        attempts.append(('درخواست مستقیم بدون conversation',{'kind':'form','url':SITE+base,'method':'POST','data':body}))
        last=''
        for label,req in attempts:
            try:
                r=self.replay(frame,req)
            except Exception as e:
                last=f'{label}: {e}';self._log(last);continue
            html=r.get('text') or ''
            if r.get('ok') and looks_like_details(html,tid,number):
                self._log(f'موفق: {label}')
                self._details_html[tid]=html
                return {'text':details_from_html(html),'pairs':detail_pairs_from_html(html),
                        'groups':groups_from_html(html,tid),'method':label}
            why='صفحه ورود (نشست منقضی)' if looks_like_login(html) else f'HTTP {r.get("status")} → {r.get("path")}'
            last=f'{label}: پاسخ نامعتبر ({why})';self._log(last)
        raise SiteError('جزئیات کامل از سامانه دریافت نشد. اطلاعات فهرست همچنان نمایش داده می‌شود.\n'+
                        '\n'.join(self.trace[-6:]))

    # --- Documents -------------------------------------------------------------
    def get_groups(self,tender_id,number=''):
        """Document categories, WITHOUT requiring «فراخوان‌های من» when the site allows it."""
        tid=str(tender_id)
        try:
            d=self.details(tid,number,reset=False)
            if d['groups']:
                self._log(f'{len(d["groups"])} دسته سند از صفحه جزئیات پیدا شد')
                return d['groups'],'جزئیات فراخوان'
            self._log('صفحه جزئیات دسته سندی نداشت')
        except SiteError:
            self._log('جزئیات برای یافتن دسته‌ها در دسترس نبود')
        frame=self._target()
        conv=self.conv.get('myCallsCartableAction_conversation')
        variants=[]
        if conv:variants.append(f'?myCallsCartableAction_conversation={conv}')
        variants.append('')
        pages=[('evaluationDocumentDownloadAndPayment-execute.action','POST'),('downloadTenderDocs-load.action','POST'),
               ('downloadTenderDocs-load.action','GET')]
        for q in variants:
            for action,method in pages:
                try:
                    r=self.replay(frame,{'kind':'form','url':SITE+'/etend/'+action+q,'method':method,
                                         'data':[('tenderId',tid),('backActionName','myCallsCartable-execute')]},xhr=True)
                except Exception as e:
                    self._log(f'{action} {method}: {e}');continue
                if r.get('ok'):
                    groups=groups_from_html(r.get('text',''),tid)
                    if groups:
                        self._log(f'دسته‌ها از صفحه دانلود اسناد ({action}) خوانده شد')
                        return groups,'صفحه دانلود اسناد'
                self._log(f'{action}{" + conversation" if q else ""}: دسته‌ای برنگشت')
        self._log('هیچ دسته سندی از سایت خوانده نشد')
        return [],'بدون دسته'

    # --- Helper tab: run the site's own document dialog ---------------------------
    def background_page(self):
        """A helper tab that does NOT take the foreground (CDP createTarget background=true); falls back to a normal tab."""
        try:
            sess=self.context.new_cdp_session(self.work_page())
            try:
                with self.context.expect_page(timeout=8000) as pi:
                    sess.send('Target.createTarget',{'url':'about:blank','background':True})
                return pi.value
            finally:
                try:sess.detach()
                except Exception:pass
        except Exception:
            return self.context.new_page()

    def _open_sandbox(self,html):
        """Open the tender's details page in a helper tab on the site origin (served
        locally from the HTML we already fetched), with the site's own scripts."""
        frame=self._target()
        try:assets=frame.evaluate(JS_PAGE_ASSETS)
        except Exception:assets={'scripts':[],'styles':[]}
        low=html.lower()
        inject=''.join(f'<link rel="stylesheet" href="{u}">' for u in assets.get('styles',[]) if is_site_url(u))
        has_jq=bool(re.search(r'<script[^>]+src=[^>]*jquery',low))
        if not has_jq:
            inject+=''.join(f'<script src="{u}"></script>' for u in assets.get('scripts',[]) if is_site_url(u))
        if '<head' in low:
            doc=re.sub(r'(<head[^>]*>)',lambda m:m.group(1)+inject,html,count=1,flags=re.I)
        else:
            doc=f'<!doctype html><html><head><meta charset="utf-8">{inject}</head><body>{html}</body></html>'
        page=self.background_page()
        page.route(SANDBOX_URL,lambda route,req:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=doc))
        page.goto(SANDBOX_URL,wait_until='load',timeout=45000)
        try:page.wait_for_load_state('networkidle',timeout=7000)
        except Exception:pass
        try:self.page().bring_to_front()
        except Exception:pass
        return page

    def list_files_sandbox(self,tender_id,groups,number=''):
        """For each category, click the site's own opener in the helper tab and take the
        exact file-list response the site's grid receives. Returns {doc_type:(rows,declared,label)}."""
        tid=str(tender_id)
        openers=[g for g in groups if g.get('opener')]
        if not openers:return {}
        html=self._details_html.get(tid)
        if not html:
            try:self.details(tid,number,reset=False);html=self._details_html.get(tid)
            except SiteError:return {}
        if not html:return {}
        try:page=self._open_sandbox(html)
        except Exception as e:
            self._log(f'تب کمکی باز نشد: {e}');return {}
        seen=[];results={}
        def on_resp(r):
            try:
                if r.request.resource_type in ('xhr','fetch','document'):seen.append(r)
            except Exception:pass
        page.on('response',on_resp)
        try:
            ok=page.evaluate("() => typeof window.showAppendix")
            self._log('تب کمکی: تابع showAppendix '+('موجود است' if ok=='function' else 'پیدا نشد ('+str(ok)+')'))
            for g in openers:
                start=len(seen);checked=set();found=None;paths=[]
                try:page.evaluate(JS_RUN_CODE,g['opener'])
                except Exception as e:
                    self._log(f'{g.get("title")}: اجرای دکمه سایت خطا داد: {str(e)[:150]}');continue
                t0=time.time()
                while time.time()-t0<15 and not found:
                    page.wait_for_timeout(300)
                    for r in seen[start:]:
                        if id(r) in checked:continue
                        checked.add(id(r));paths.append(safe_page_label(r.url).split('/',1)[-1])
                        try:data=r.json()
                        except Exception:continue
                        if looks_like_file_list(data):found=(r,data);break
                    if not found and time.time()-t0>4 and len(seen)==start:break
                self._log(f'{g.get("title")}: درخواست‌های پنجره پیوست: '+(', '.join(paths) or 'هیچ'))
                if found:
                    r,data=found;req=r.request
                    for k,v in parse_qsl(urlparse(req.url).query):
                        if k.endswith('_conversation'):self.conv[k]=v
                    post=[]
                    try:
                        if req.post_data and 'urlencoded' in (req.headers.get('content-type') or ''):
                            post=parse_qsl(req.post_data,keep_blank_values=True)
                    except Exception:pass
                    full=data
                    try:
                        if req.method=='GET':
                            full=page.evaluate(JS_FETCH_JSON,{'url':req.url,'postData':{},'overrides':{'page':1,'rows':-1}})
                        else:
                            body=[(k,v) for k,v in post if k not in ('rows','page')]+[('page','1'),('rows','-1')]
                            rr=page.evaluate(JS_REPLAY,{'url':req.url,'method':'POST','data':body,'xhr':True,'kind':'xhr'})
                            full=json.loads(rr.get('text') or '{}') if rr.get('ok') else data
                    except Exception:full=data
                    if not looks_like_file_list(full):full=data
                    try:rows=file_rows_from_json(full)
                    except ValueError:rows=[]
                    declared=int(full.get('records') or len(rows)) if isinstance(full,dict) else len(rows)
                    results[str(g['document_type'])]=(rows,declared,'پنجره پیوست سایت (تب کمکی)')
                    self.learned['list']=make_template(req.url,post,req.method)
                else:
                    rows=file_rows_from_html(page.content())
                    if rows:results[str(g['document_type'])]=(rows,len(rows),'پنجره پیوست سایت (از صفحه)')
                try:page.evaluate(JS_CLOSE_DIALOGS)
                except Exception:pass
        finally:
            try:page.remove_listener('response',on_resp)
            except Exception:pass
            try:page.close()
            except Exception:pass
            try:self.page().bring_to_front()
            except Exception:pass
        return results

    def get_files(self,tender_id,group):
        """Returns (rows, declared_count, method). Tries the site's own showAppendix first."""
        frame=self._target()
        tid=str(tender_id)
        doc_id=str(group.get('document_id') or tid)
        doc_type=str(group['document_type'])
        list_urls=[]
        if self.list_template:
            path,q,b=fill_template(self.list_template,self.conv,document_id=doc_id,document_type=doc_type)
            if not b:
                from urllib.parse import urlencode
                list_urls.append(('الگوی آموخته از سایت',SITE+path+('?'+urlencode(q) if q else '')))
        opener=group.get('opener') or ''
        if opener:
            for req in self.learn_requests(frame,code=opener,wait=500):
                if 'appendix-list' in req['url']:
                    list_urls.append(('لیست از تابع سایت',req['url']));continue
                try:
                    r=self.replay(frame,req)
                    found=find_appendix_list_url(r.get('text',''))
                    if found:list_urls.append(('لیست از پنجره پیوست سایت',found))
                    else:self._log('پنجره پیوست باز شد ولی آدرس فهرست فایل در آن نبود')
                except Exception as e:
                    self._log(f'باز کردن پنجره پیوست: {e}')
        # the dialog request itself (without opening any tab): showAppendix(url, null, type, id, ...)
        jsargs=_js_args(opener) if opener else []
        if len(jsargs)>=4 and jsargs[0].startswith('/etend/'):
            for method in ('POST','GET'):
                try:
                    r=self.replay(frame,{'kind':'ajax','url':SITE+jsargs[0],'method':method,
                                         'data':[('documentType',doc_type),('documentId',doc_id)]},xhr=True)
                    found=find_appendix_list_url(r.get('text','')) if r.get('ok') else ''
                    for k,v in re.findall(r'([A-Za-z]+_conversation)=([0-9A-Za-z_-]+)',r.get('text','') or ''):self.conv[k]=v
                    if found and ('documentId=' in found) and not found.rstrip().endswith('='):
                        list_urls.append(('لیست از پنجره پیوست (بدون تب)',found));break
                except Exception as e:
                    self._log(f'پنجره پیوست ({method}): {str(e)[:120]}')
        plain=f'{SITE}/etend/appendix-list.action?documentId={doc_id}&documentType={doc_type}'
        list_urls.append(('لیست مستقیم',plain))
        cq=self._conv_query()
        if cq:list_urls.append(('لیست مستقیم + conversation',plain+'&'+cq))
        last_err=None;empty_ok=None
        for label,url in list_urls:
            try:
                data=frame.evaluate(JS_FETCH_JSON,{'url':url,'postData':{},
                        'overrides':{'_search':'false','rows':-1,'page':1,'sidx':'','sord':'asc'}})
            except Exception as e:
                last_err=f'{label}: {e}';self._log(last_err);continue
            if not isinstance(data,dict):
                last_err=f'{label}: پاسخ نامعتبر';self._log(last_err);continue
            try:rows=file_rows_from_json(data)
            except ValueError as e:
                last_err=f'{label}: {e}';self._log(last_err);continue
            err=data.get('errorMessage')
            if err not in (None,'','0',0):
                last_err=f'{label}: پیام سایت: {err}';self._log(last_err);continue
            declared=data.get('records')
            if declared is not None and int(declared)>0 and len(rows)==0:
                keys=list((data.get('gridModel') or [{}])[0].keys()) if data.get('gridModel') else []
                raise SiteError('فایل در سامانه موجود است، اما شناسه آن از JSON شناسایی نشد. فیلدها: '+', '.join(keys[:30]))
            if rows:
                self._log(f'{group.get("title")}: {len(rows)} فایل ({label})')
                return rows,int(declared or len(rows)),label
            empty_ok=(label,int(declared or 0))
        if empty_ok:return [],0,empty_ok[0]
        raise SiteError(last_err or 'فهرست فایل‌ها دریافت نشد.')

    # --- Connection helpers (v0.3) -----------------------------------------------------
    def probe_grid(self):
        """One quick, non-blocking look for the tender grid. Returns capture() info or None."""
        if not self.context:return None
        try:
            src,frame,_=self._grid_candidates()
        except SiteError:
            return None
        if not src:return None
        try:return self.capture()
        except SiteError:return None

    def has_site_tab(self):
        try:return bool(self._site_tabs())
        except SiteError:return False

    def goto_tenders(self,attempt=0):
        """Best effort: open «فراخوان‌ها» in the tab the user is on. Never touches other menus."""
        try:page=self.page()
        except SiteError:return ''
        try:
            if page.evaluate("() => !!document.querySelector('input[type=password]')"):return ''
        except Exception:return ''
        try:
            clicked=page.evaluate(JS_CLICK_MENU)
            if clicked:
                self.pump(1200);return 'منوی «فراخوان‌ها» باز شد'
        except Exception:pass
        if attempt>=2:
            try:
                page.goto(SITE+'/etend/afterLoginCallMainPageCartable-execute.action',wait_until='domcontentloaded',timeout=30000)
                self.pump(800);return 'صفحه فهرست فراخوان‌ها مستقیم باز شد'
            except Exception:pass
        return ''

    def minimize(self):
        """Minimise the app browser window (Chromium DevTools window API). Silent on failure."""
        try:
            pg=self.page();sess=self.context.new_cdp_session(pg)
            win=sess.send('Browser.getWindowForTarget')
            sess.send('Browser.setWindowBounds',{'windowId':win['windowId'],'bounds':{'windowState':'minimized'}})
            try:sess.detach()
            except Exception:pass
            return True
        except Exception:
            return False

    def restore(self,page=None):
        try:
            pg=page if page is not None else self.page();sess=self.context.new_cdp_session(pg)
            win=sess.send('Browser.getWindowForTarget')
            sess.send('Browser.setWindowBounds',{'windowId':win['windowId'],'bounds':{'windowState':'normal'}})
            try:sess.detach()
            except Exception:pass
            pg.bring_to_front();return True
        except Exception:
            return False

    def _fresh_token(self,frame):
        """Page token may be stale (another tab / manual use consumed it): repair the name field and ask the site for a fresh value."""
        try:frame.evaluate(JS_REPAIR_TOKEN)
        except Exception:pass
        return self._reload_csrf(frame)

    def get_my_calls_ids(self):
        """Raw rows of «فراخوان‌های من» exactly as the site asks for them, or None when unreadable."""
        from .dates import jalali_of
        from datetime import date
        frame=self._target()
        try:
            self._fresh_token(frame)
            conv=self._mycalls_conv(frame)
        except Exception as e:
            self._log('باز کردن «فراخوان‌های من»: '+str(e)[:120]);return None
        today=jalali_of(date.today())
        rows=[];page=1;total=1
        try:
            while page<=total and page<=200:
                token=dict(parse_qsl(frame.evaluate(JS_TOKEN_PARAMS) or '',keep_blank_values=True))
                params=dict(token)
                params.update({'currentDate':today,'firstDateOfYear':today[:4]+'/01/01','countSeen':'','firstLoaded':'true',
                               'myCallsCartableDto.numberTenderId':'','myCallsCartableDto.numberTenderId_widget':'',
                               'myCallsCartableDto.tenderType':'-1','myCallsCartableDto.tenderTitle':'','myCallsCartableDto.provinceId':'-1',
                               'myCallsCartableDto.organizationName':'','myCallsCartableDto.state':'-1'})
                if conv:params['myCallsCartableAction_conversation']=conv
                params.update({'_search':'false','nd':str(int(time.time()*1000)),'rows':100,'page':page,'sidx':'','sord':'asc'})
                data=frame.evaluate(JS_FETCH_JSON,{'url':SITE+'/etend/myCallsCartable-search.action','postData':{},'overrides':params})
                if not isinstance(data,dict) or not isinstance(data.get('gridModel'),list):
                    self._log('فهرست «فراخوان‌های من» ساختار شناخته‌شده نداشت');return None
                rows+=[x for x in data['gridModel'] if isinstance(x,dict)]
                total=int(data.get('total') or 1);page+=1
            return rows
        except Exception as e:
            self._log(f'خواندن «فراخوان‌های من»: {str(e)[:160]}');return None

    @staticmethod
    def _snippet(text):
        t=re.sub(r'<[^>]+>',' ',text or '');t=re.sub(r'\s+',' ',t).strip()
        return redact(t)[:160]

    # ---- v0.9.1: «فراخوان‌های من» inside the ONE shared tab, exactly like a person does it (recorded flow:
    #      menu click → myCallsCartable-execute → -search → -delete / downloadTenderDocs-load, all in the same page)
    MY_CALLS_LINK=re.compile(r'فراخوان[\s\u200c]*(ها|‌ها)[\s\u200c]*من')

    def _find_ctx(self,page,fn,sec):
        """The page or sub-frame that owns the site's function `fn`."""
        t0=time.time()
        while time.time()-t0<sec:
            for fr in [page]+list(page.frames):
                try:
                    if fr.evaluate(f"() => typeof window.{fn}==='function'"):return fr
                except Exception:pass
            try:page.wait_for_timeout(400)
            except Exception:time.sleep(0.4)
        return None

    def _shared_my_calls(self,fn,new_tab=False):
        """Open «فراخوان‌های من» and return (page, ctx) where `fn` exists. Default: in the shared tab (delete).
        new_tab=True: a dedicated tab that walks the same real path (payment page stays open there, the shared tab stays free)."""
        self.ensure_etend(allow_hold=True)
        page=self.context.new_page() if new_tab else self.work_page()
        def has_nav():
            try:return bool(page.evaluate("() => typeof window.navigateBody==='function'"))
            except Exception:return False
        if not has_nav():
            try:page.goto(SITE+'/etend/indexPage.action',wait_until='domcontentloaded',timeout=45000)
            except Exception as e:raise SiteError(friendly_nav_error(e))
            t0=time.time()
            while time.time()-t0<20 and not has_nav():page.wait_for_timeout(400)
        tried=[]
        ctx=self._find_ctx(page,fn,1)
        if ctx is None:
            # 1) the real menu link, like a click by a person
            try:
                link=page.locator('a',has_text=self.MY_CALLS_LINK).first
                if link.count():
                    link.click(timeout=8000);tried.append('کلیک منو')
            except Exception:pass
            ctx=self._find_ctx(page,fn,14)
        if ctx is None:
            # 2) the site's own navigation function
            try:
                page.evaluate("() => navigateBody('/etend/myCallsCartable-execute.action','firstLoaded=true')");tried.append('navigateBody')
            except Exception:pass
            ctx=self._find_ctx(page,fn,14)
        if ctx is None:
            if new_tab:
                try:page.close()
                except Exception:pass
            else:
                try:page.bring_to_front()
                except Exception:pass
            raise SiteError('صفحهٔ «فراخوان‌های من» در مرورگر برنامه آماده نشد (روش‌های امتحان‌شده: '+('، '.join(tried) or 'هیچ')+
                            '). همان‌جا دستی انجام دهید و بعد «همگام‌سازی فراخوان‌های من» را بزنید.')
        return page,ctx

    def _back_to_list(self):
        """After a visit to «فراخوان‌های من» put the shared tab back on the «فراخوان‌ها» grid the app reads from."""
        self.source=None;self.source_frame=None
        try:self.ensure_etend(force=True)
        except Exception:pass

    def payment_hold(self):
        """True while the shared tab still shows the document/payment page (do not navigate away under the user)."""
        w=self.work
        try:
            if w is None or w.is_closed():return False
            u=w.url or ''
            return any(k in u for k in ('downloadTenderDocs','payment','psp-call','bank'))
        except Exception:
            return False

    JS_DELETE_RECORDED="""async (id) => {
        const val = n => { const e = document.querySelector('input[name="'+n+'"]'); return e ? e.value : ''; };
        const tokName = val('struts.token.name');
        const csrf = val('csrf_token') || (tokName ? val(tokName) : '');
        let conv = '';
        for (const r of performance.getEntriesByType('resource').reverse()) {
            const m = /myCallsCartableAction_conversation=(\\d+)/.exec(r.name);
            if (m) { conv = m[1]; break; }
        }
        if (!conv) { const m = /myCallsCartableAction_conversation[^0-9]{0,40}(\\d+)/.exec(document.documentElement.innerHTML); if (m) conv = m[1]; }
        if (!csrf || !conv) return {ok:false, why:'token='+(!!csrf)+' conv='+(!!conv)};
        const body = new URLSearchParams();
        body.set('selectedTenderId', id);
        body.set('struts.token.name', tokName || 'csrf_token');
        body.set('csrf_token', csrf);
        const r = await fetch('/etend/myCallsCartable-delete.action?myCallsCartableAction_conversation='+conv,
            {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}, body: body.toString()});
        return {ok:true, status:r.status, text: await r.text()};
    }"""

    def _delete_like_recording(self,ctx,tid):
        """The exact request recorded from a manual delete (POST selectedTenderId + the page's own tokens, same conversation)."""
        for fr in [ctx]:
            try:
                r=fr.evaluate(self.JS_DELETE_RECORDED,int(tid))
            except Exception as e:
                self._log('حذف مطابق ضبط: '+str(e)[:120]);return None,''
            if r and r.get('ok'):return r.get('status'),r.get('text') or ''
            self._log('حذف مطابق ضبط ممکن نشد: '+str((r or {}).get('why')))
        return None,''

    def remove_my_call(self,tender_id,confirmed=False):
        """Remove a tender from «فراخوان‌های من» by running the site's own deleteAction(tenderId) inside its own
        «فراخوان‌های من» page, in the shared tab (the page's conversation id is baked in, so no other way works)."""
        if not confirmed:raise SiteError('تأیید صریح کاربر دریافت نشده است.')
        if not self.context:raise SiteError('ابتدا به ستاد وصل شوید.')
        tid=str(tender_id)
        page,ctx=self._shared_my_calls('deleteAction')
        try:page.wait_for_load_state('networkidle',timeout=8000)      # let the grid of that conversation load, like for a user
        except Exception:pass
        page.wait_for_timeout(600)
        status,text=self._delete_like_recording(ctx,tid)
        if status is None:
            # tokens / conversation not readable from the page → fall back to the page's own function
            try:
                with page.expect_response(lambda r:'myCallsCartable-delete.action' in r.url,timeout=25000) as ri:
                    ctx.evaluate("id => deleteAction(id)",int(tid))
                resp=ri.value
                try:text=resp.text()
                except Exception:text=''
                status=resp.status
            except Exception as e:
                raise SiteError('حذف انجام نشد: '+friendly_error(str(e).splitlines()[0][:160]))
        try:data=json.loads(text)
        except ValueError:
            if looks_like_login(text):raise SiteError('نشست ستاد منقضی شده است؛ دوباره «اتصال به ستاد» را بزنید.')
            raise SiteError(f'سایت جواب حذف را نداد (وضعیت {status}). پاسخ سایت: «{self._snippet(text) or "خالی"}».')
        err=data.get('errorMessage') if isinstance(data,dict) else None
        if err not in (None,'','0',0):
            if str(err).strip()=='4000':raise SiteError('توکن امنیتی سایت منقضی بود؛ یک‌بار دیگر امتحان کنید.')
            raise SiteError('سایت حذف را قبول نکرد: '+str(err))
        if str(data.get('selectedTenderId',''))!=tid:
            raise SiteError('جواب سایت برای حذف نامشخص بود.')
        self._docs_open.pop(tid,None)
        self._back_to_list()
        return True

    def open_payment_page(self,tender_id):
        """Open «دریافت اسناد» exactly like the site does, in its OWN new tab (walks indexPage → «فراخوان‌های من» → «دریافت اسناد»
        like a person), so the shared tab stays free for other tenders. Never pays: paying at the bank is done by the user."""
        if not self.context:raise SiteError('ابتدا به ستاد وصل شوید.')
        tid=str(tender_id)
        fn='showEvaluationDocumentDownload' if self.tender_types.get(tid,'') in ('QUALITY_EVALUATION_TENDER','SHORT_LIST_QUALITY_EVALUATION','COMPETENCY_ASSESSMENT') else 'showDocumentDownload'
        page,ctx=self._shared_my_calls(fn,new_tab=True)
        ctx.evaluate(f"id => {fn}(id)",int(tid))
        t0=time.time()
        while time.time()-t0<25:
            try:
                if page.evaluate("() => !!document.getElementById('payDownloadCostEnable') || !!document.querySelector('[onclick*=\"showAppendix\"]')"):break
            except Exception:pass
            page.wait_for_timeout(400)
        try:page.bring_to_front()
        except Exception:pass
        self.restore(page)
        return True

    def details_codes(self,tender_id):
        """tenderTypeId / allSetupType codes from the tender's details page (fallback for unknown types)."""
        tid=str(tender_id)
        html=self._details_html.get(tid)
        if not html:
            try:self.details(tid,'',reset=False)
            except SiteError:pass
            html=self._details_html.get(tid)
        return codes_from_details_html(html or '')

    # --- Add to «فراخوان‌های من» ----------------------------------------------
    def get_live_favorite_args(self,tender_id):
        try:
            for s in self._target().evaluate(JS_FAV_SAMPLES):
                if str(s.get('id'))==str(tender_id):return s
        except Exception:pass
        return None

    def favorite_samples(self):
        try:return self._target().evaluate(JS_FAV_SAMPLES) or []
        except Exception:return []

    def _in_my_calls(self,tender_id):
        """True/False when «فراخوان‌های من» could be read, None otherwise."""
        rows=self.get_my_calls_ids()
        if rows is None:return None
        return str(tender_id) in my_call_tender_ids(rows)

    @staticmethod
    def _add_verdict(r):
        """('ok'|'error'|'unknown', note) for one add response."""
        if not isinstance(r,dict):return 'unknown','پاسخ نامعلوم',None
        text=(r.get('text') or '').strip()
        if not r.get('ok'):return 'unknown',f'HTTP {r.get("status")}',None
        try:data=json.loads(text)
        except ValueError:
            low=text[:4000].lower()
            if 'type="password"' in low or "type='password'" in low or 'j_password' in low:
                return 'expired','صفحه ورود برگشت (نشست منقضی شده)',None
            snippet=re.sub(r'<[^>]+>',' ',text);snippet=re.sub(r'\s+',' ',snippet).strip()[:120]
            return 'unknown','پاسخ JSON نبود'+(f' («{snippet}»)' if snippet else ' (پاسخ خالی)'),None
        if isinstance(data,dict):
            csrf=data.get('newCsrfTokenValue') or None
            err=data.get('errorMessage')
            if err not in (None,'','0',0):
                if str(err).strip()=='4000':return 'retry','کد ۴۰۰۰ (توکن امنیتی سایت)',csrf
                if 'قبلا' in str(err) or 'قبلاً' in str(err) or 'تکراری' in str(err):return 'ok','قبلاً افزوده شده بود',csrf
                return 'error',str(err),csrf
            return 'ok','',csrf
        return 'ok','',None

    def _site_add(self,frame,call):
        """Run the site's own favoriteForm(...) like a click and return its answer. None if the function is missing."""
        try:
            if not frame.evaluate("() => typeof window.favoriteForm === 'function'"):return None
        except Exception:return None
        page=frame.page
        try:frame.evaluate(JS_REPAIR_TOKEN)
        except Exception:pass
        try:
            with page.expect_response(lambda r:urlparse(r.url).path.endswith('callMainPageCartable-add.action'),timeout=15000) as ri:
                frame.evaluate(JS_NATIVE_FAVORITE,call)
            resp=ri.value
            try:text=resp.text()
            except Exception:text=''
            return {'ok':resp.ok,'status':resp.status,'text':text}
        except Exception as e:
            msg=str(e).splitlines()[0][:160]
            self._log('دکمه افزودن سایت: '+msg)
            return {'ok':False,'status':0,'text':'','error':msg}

    def _reload_csrf(self,frame):
        """The site's own token refresh (/etend/reloadCsrfToken)."""
        try:
            r=self.replay(frame,{'kind':'xhr','url':SITE+'/etend/reloadCsrfToken','method':'POST',
                                 'data':[('struts.token.name','csrf_token')]},xhr=True)
            data=json.loads(r.get('text') or '{}')
            val=data.get('newCsrfTokenValue') if isinstance(data,dict) else None
            if not val and isinstance(data,dict):
                val=next((v for k,v in data.items() if isinstance(v,str) and v and ('csrf' in k.lower() or 'token' in k.lower())),None)
            if val:
                frame.evaluate(JS_UPDATE_CSRF,val);self._log('توکن امنیتی سایت تازه شد');return True
        except Exception as e:
            self._log('تازه کردن توکن: '+str(e)[:100])
        return False

    def add_my_calls(self,tender_id,args:dict,confirmed:bool):
        """Add one tender to «فراخوان‌های من» exactly like the site's «+» button:
        favoriteForm(id, price, organizationId, tenderTypeId, allSetupType). Error 4000 = stale token → refresh, retry."""
        if not confirmed:raise SiteError('تأیید صریح کاربر دریافت نشده است.')
        if not args or str(args.get('id'))!=str(tender_id):
            raise SiteError('مشخصات لازم برای افزودن این فراخوان در دسترس نیست.')
        self.trace=[]
        tid=str(tender_id)
        frame=self._target()
        def jsv(v):
            if v is None or v=='':return None
            try:
                f=float(v);return int(f) if f.is_integer() else f
            except (TypeError,ValueError):return None
        call=[jsv(args['id']),jsv(args.get('price')) or 0,jsv(args.get('organizationId')),jsv(args.get('typeId')),jsv(args.get('setupId'))]
        notes=[]
        for attempt in range(3):
            r=self._site_add(frame,call);label='دکمه افزودن خود سایت'
            if r is not None and r.get('error'):
                notes.append('دکمه افزودن خود سایت: خطای صفحه ('+friendly_error(r['error'])[:120]+')')
                r=None
            if r is None:
                try:frame.evaluate(JS_REPAIR_TOKEN)
                except Exception:pass
                r=frame.evaluate(JS_ADD,dict(id=call[0],price=call[1],organizationId=call[2],typeId=call[3],setupId=call[4],confirmed=True,conv={}))
                label='درخواست مستقیم افزودن'
            verdict,note,csrf=self._add_verdict(r)
            if csrf:
                try:frame.evaluate(JS_UPDATE_CSRF,csrf)
                except Exception:pass
            if verdict=='ok':
                self._log('موفق: '+label)
                return {'method':label+(' — '+note if note else '')}
            if verdict=='expired':
                raise SiteError('نشست ستاد منقضی شده است. دوباره «اتصال به ستاد» را بزنید.')
            if verdict=='error' and not re.search(r'توکن|token|csrf',note,re.I):
                raise SiteError('سایت افزودن فراخوان را تأیید نکرد: '+note)
            notes.append(f'{label}: {note}')
            if verdict=='unknown' and self._in_my_calls(tid):
                return {'method':label+' — تأیید از «فراخوان‌های من»'}
            self._reload_csrf(frame)
        if self._in_my_calls(tid):return {'method':'تأیید از «فراخوان‌های من»'}
        raise SiteError('افزودن انجام نشد. نتیجه تلاش‌ها:\n'+'\n'.join(notes))

    # --- Setad role (one active role at a time) ---------------------------------
    def _set_role(self,role):
        if role!=self.role:
            self.role=role
            if role!='ETEND':
                self.source=None;self.source_frame=None;self._docs_open={}
            if self.on_role:
                try:self.on_role(role)
                except Exception:pass

    def handle_role_page(self,page,system):
        """Fill Setad's role-selection page: system radio, role radio, «شروع»."""
        sys_id=system  # input ids are EPROC / ETEND / EAUC
        if not page.evaluate(JS_PICK_SYSTEM,sys_id):
            raise SiteError('گزینه سامانه در صفحه انتخاب نقش ستاد پیدا نشد.')
        picked=None;t0=time.time()
        while time.time()-t0<15:
            page.wait_for_timeout(300)
            try:picked=page.evaluate(JS_PICK_ROLE,ROLE_WORDS[system])
            except Exception:picked=None
            if picked:break
        if not picked:
            raise SiteError(f'نقش «{ROLE_TITLES[system]}» در صفحه انتخاب نقش ستاد پیدا نشد.')
        self._log(f'انتخاب نقش: {picked}')
        page.wait_for_timeout(250)
        if not page.evaluate(JS_START_ROLE):
            raise SiteError('دکمه «شروع» در صفحه انتخاب نقش پیدا نشد.')
        t0=time.time()
        while time.time()-t0<40:
            try:
                page.wait_for_timeout(400)
                if host_kind(page.url)!='sso':return True
            except Exception:
                time.sleep(0.4)
        raise SiteError('پس از انتخاب نقش، ستاد سامانه را باز نکرد.')

    def goto_system(self,page,system,url,timeout=70):
        """Open a Setad system page; answers the role page automatically. Returns 'ok' or 'login'."""
        want=ROLE_HOST[system]
        try:page.goto(url,wait_until='domcontentloaded',timeout=45000)
        except Exception as e:
            if host_kind(page.url)!='sso':raise SiteError(friendly_nav_error(e))
        handled=0;t0=time.time()
        while time.time()-t0<timeout:
            kind=host_kind(page.url)
            if kind=='sso':
                try:st=page.evaluate(JS_SSO_STATE)
                except Exception:st={}
                if st.get('role') and handled<2:
                    self.handle_role_page(page,system);handled+=1
                    continue
                if st.get('pwd'):return 'login'
            elif kind==want:
                if handled:
                    try:page.goto(url,wait_until='domcontentloaded',timeout=45000)
                    except Exception as e:raise SiteError(friendly_nav_error(e))
                    if host_kind(page.url)=='sso':handled=1;continue
                self._set_role(system)
                return 'ok'
            try:page.wait_for_timeout(400)
            except Exception:time.sleep(0.4)
        raise SiteError('باز شدن سامانه ستاد بیش از حد طول کشید.')

    def work_page(self):
        """The single shared tab. Tender and needs sections both navigate inside it (role switch, board, «فراخوان‌ها»).
        Short-lived tabs (payment, delete) are separate on purpose."""
        w=self.work
        try:
            if w is not None and not w.is_closed():return w
        except Exception:pass
        pages=[p for p in self.context.pages if not p.is_closed()]
        pref=[p for p in pages if host_kind(p.url) is not None]          # an existing Setad tab first
        blank=[p for p in pages if host_kind(p.url) is None and not str(p.url).startswith('chrome')]
        self.work=(pref or blank or [None])[0] or self.context.new_page()
        return self.work

    def _etend_page(self):
        return self.work_page()

    HOLD_MSG='صفحهٔ دریافت اسناد/پرداخت هنوز در مرورگر برنامه باز است؛ بعد از پایان کار، تب را به «فراخوان‌ها» برگردانید و دوباره امتحان کنید.'

    def ensure_etend(self,force=False,allow_hold=False):
        """Make sure the tender role is active and the «فراخوان‌ها» grid is captured."""
        if not self.context or not self.alive():
            raise SiteError('مرورگر ستاد باز نیست؛ ابتدا «اتصال به ستاد» را بزنید.')
        if not allow_hold and self.payment_hold():raise SiteError(self.HOLD_MSG)
        if not force and self.role=='ETEND' and self.source is not None:return
        if not force and self.role in (None,'ETEND'):
            if self.probe_grid():
                self._set_role('ETEND');return
        page=self._etend_page()
        st=self.goto_system(page,'ETEND',SITE+'/etend/indexPage.action')
        if st=='login':
            try:page.bring_to_front()
            except Exception:pass
            self.restore()
            raise SiteError('برای ادامه، در پنجره مرورگر برنامه وارد ستاد شوید و دوباره امتحان کنید.')
        self.source=None;self.source_frame=None
        for attempt in range(6):
            if self.probe_grid():break
            self.goto_tenders(attempt);self.pump(1200)
        if self.source is None:self.capture()
        self._set_role('ETEND')

    def ensure_eproc(self,page,force=False,wait_login=False,cancelled=None,say=None):
        """Make sure the supplier (needs) role is active in the given tab.
        wait_login=True: when a login is needed, wait for the user (like the tender connect) instead of failing."""
        if self.payment_hold():raise SiteError(self.HOLD_MSG)
        if not force and self.role=='EPROC' and host_kind(page.url)=='eproc':return 'ok'
        st=self.goto_system(page,'EPROC',EPROC_BOARD)
        if st=='login':
            try:page.bring_to_front()
            except Exception:pass
            self.restore()
            if wait_login:return self.wait_login_then_role('EPROC',cancelled=cancelled,say=say)
            raise SiteError('برای ادامه، در پنجره مرورگر برنامه وارد ستاد شوید و دوباره «دریافت» را بزنید.')
        return st

    LOGIN_MSG_KEY='وارد ستاد شوید'

    def wait_login_then_role(self,system,limit=900,cancelled=None,say=None):
        """Wait for the user to log in (nothing is navigated meanwhile), answer Setad's role page for
        `system` automatically, then open that system's start page. Same behaviour as the tender connect."""
        t0=time.time();role_tries=0;said=False
        while time.time()-t0<limit:
            if cancelled and cancelled():raise SiteError('انتظار برای ورود لغو شد.')
            if not self.alive():raise SiteError('پنجره مرورگر بسته شد. دوباره اتصال را بزنید.')
            role_page=None;site_page=None
            for p in [x for x in self.context.pages if not x.is_closed()]:
                k=host_kind(p.url)
                if k=='sso':
                    try:
                        if p.evaluate(JS_SSO_STATE).get('role'):role_page=p;break
                    except Exception:pass
                elif k in ROLE_HOST.values():site_page=p
            if role_page is not None and role_tries<3:
                role_tries+=1
                if say:say(f'انتخاب خودکار نقش «{ROLE_TITLES[system]}» در ستاد...')
                self.handle_role_page(role_page,system)
                self.pump(800);continue
            if role_page is None and site_page is not None:
                page=self.work_page()
                url=EPROC_BOARD if system=='EPROC' else SITE+'/etend/indexPage.action'
                if self.goto_system(page,system,url)=='ok':return 'ok'
            if not said and say:
                say('منتظر ورود شما در مرورگر برنامه هستم...');said=True
            self.pump(800)
        raise SiteError('در زمان مقرر ورود انجام نشد. در مرورگر برنامه وارد شوید و دوباره اتصال را بزنید.')

    # --- «دریافت اسناد» page (the only route the site allows for listing/downloading) ---
    def _mycalls_conv(self,frame):
        r=self.replay(frame,{'kind':'xhr','url':SITE+'/etend/myCallsCartable-execute.action','method':'POST',
                             'data':[('firstLoaded','true')]},xhr=True)
        html=r.get('text') or ''
        if looks_like_login(html):raise SiteError('نشست ستاد منقضی شده است؛ دوباره «اتصال به ستاد» را بزنید.')
        found=re.findall(r'myCallsCartableAction_conversation["\'\s]*(?:=|:|value=)["\'\s]*(\d+)',html)
        conv=found[-1] if found else None
        if conv:self.conv['myCallsCartableAction_conversation']=conv
        return conv or self.conv.get('myCallsCartableAction_conversation')

    def open_docs_page(self,tender_id,force=False):
        tid=str(tender_id)
        hit=self._docs_open.get(tid)
        if hit and not force and time.time()-hit['t']<600:return hit
        frame=self._target()
        conv=self._mycalls_conv(frame)
        q=f'?myCallsCartableAction_conversation={conv}' if conv else ''
        last=''
        for action in DOCS_ACTIONS.get(self.tender_types.get(tid,''),DOCS_DEFAULT):
            try:
                r=self.replay(frame,{'kind':'xhr','url':SITE+f'/etend/{action}.action'+q,'method':'POST',
                                     'data':[('tenderId',tid),('backActionName','myCallsCartable-execute')]},xhr=True)
            except Exception as e:
                last=f'{action}: {str(e)[:120]}';self._log(last);continue
            html=r.get('text') or ''
            groups=groups_from_html(html,tid) if r.get('ok') else []
            if groups:
                info={'t':time.time(),'action':action,'conv':conv,'groups':groups,
                      'paid':bool(re.search(r'enablePayBtnButtons|payBtn|پرداخت',html))}
                self._docs_open[tid]=info
                self._log(f'صفحه «دریافت اسناد» باز شد ({action}، {len(groups)} دسته)')
                return info
            if looks_like_login(html):last=f'{action}: صفحه ورود'
            else:
                txt=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html)).strip()
                last=f'{action}: '+(txt[:140] if txt else f'HTTP {r.get("status")}')
            self._log(last)
        raise SiteError('صفحه «دریافت اسناد» این فراخوان باز نشد. اگر هنوز به «فراخوان‌های من» افزوده نشده، ابتدا «افزودن» را بزنید.\n'+last)

    def list_documents(self,tender_id):
        """Categories and files exactly like the site: «دریافت اسناد» → openAppendix → appendix-list."""
        tid=str(tender_id)
        info=self.open_docs_page(tid,force=True)
        frame=self._target();files={};errors=[]
        for g in info['groups']:
            dt=str(g['document_type'])
            try:self.replay(frame,{'kind':'xhr','url':SITE+'/etend/appendix-openAppendix','method':'GET',
                                   'data':[('documentType',dt),('documentId',tid),('readOnly','true')]},xhr=False)
            except Exception:pass
            try:
                data=frame.evaluate(JS_FETCH_JSON,{'url':SITE+'/etend/appendix-list.action','postData':{},
                    'overrides':{'documentId':tid,'documentType':dt,'_search':'false','rows':-1,'page':1,'sidx':'','sord':'asc'}})
                files[dt]=file_rows_from_json(data)
            except Exception as e:
                errors.append(f"{g.get('title','')}: {str(e)[:120]}");files[dt]=[]
        return info,files,errors

    # --- Download ---------------------------------------------------------------
    @staticmethod
    def _looks_html_file(path:Path) -> bool:
        try:head=path.read_bytes()[:600].lstrip().lower()
        except OSError:return False
        return head.startswith((b'<!doctype html',b'<html',b'<head',b'<body'))

    def _save_native(self,page,url,name,tmp:Path,timeout=40000):
        """Real browser download (same mechanism as clicking the site's own link): an in-page
        anchor with the download attribute, so cookies/referer/conversation behave exactly like a manual click."""
        self._native=True
        try:
            with page.expect_download(timeout=timeout) as di:
                page.evaluate(JS_ANCHOR_DOWNLOAD,{'url':url,'name':name})
            d=di.value
            d.save_as(str(tmp))
        finally:
            self._native=False
        if not tmp.exists() or tmp.stat().st_size==0:raise SiteError('فایل خالی دریافت شد.')
        if self._looks_html_file(tmp):
            tmp.unlink(missing_ok=True);raise SiteError('به‌جای فایل، صفحه HTML دریافت شد.')

    def _dialog_download(self,tender_id,appendix_id,opener,tmp:Path):
        """Open the site's own attachment dialog in a helper tab and click the site's own download
        button of that file (the exact manual flow)."""
        tid=str(tender_id)
        html=self._details_html.get(tid)
        if not html:
            self.details(tid,'',reset=False);html=self._details_html.get(tid)
        if not html or not opener:raise SiteError('پنجره پیوست سایت برای این فایل در دسترس نیست.')
        page=self._open_sandbox(html)
        self._native=True
        try:
            page.evaluate(JS_RUN_CODE,opener)
            t0=time.time();found=0
            while time.time()-t0<15 and not found:
                page.wait_for_timeout(400)
                found=page.evaluate(JS_FIND_DL,str(appendix_id))
            if not found:raise SiteError('دکمه دانلود این فایل در پنجره پیوست سایت پیدا نشد.')
            with page.expect_download(timeout=40000) as di:
                page.evaluate(JS_CLICK_DL,str(appendix_id))
            di.value.save_as(str(tmp))
        finally:
            self._native=False
            try:page.close()
            except Exception:pass
            try:self.page().bring_to_front()
            except Exception:pass
        if not tmp.exists() or tmp.stat().st_size==0:raise SiteError('فایل خالی دریافت شد.')
        if self._looks_html_file(tmp):
            tmp.unlink(missing_ok=True);raise SiteError('به‌جای فایل، صفحه HTML دریافت شد.')

    def download(self,tender_id,doc_type,appendix_id,display_name,extension,dest_root:Path,number:str,group_title:str,document_id=None,opener=''):
        """Tries, in order: (1) direct request with the learned template, (2) plain request, (3) in-page fetch,
        (4) real browser download of the same URL, (5) the site's own download button in its attachment dialog."""
        if not self.context:raise SiteError('نشست ستاد متصل نیست.')
        name=safe_name(display_name)
        ext=safe_name(extension,12).lstrip('.') if extension else ''
        if ext and not name.lower().endswith('.'+ext.lower()):name+='.'+ext
        target=Path(dest_root)/safe_name(number)/safe_name(group_title)
        target.mkdir(parents=True,exist_ok=True)
        filepath=target/name
        doc_id=str(document_id or tender_id)
        params={'appendixId':str(appendix_id),'documentId':doc_id,'documentType':str(doc_type)}
        attempts=[];urls=[]
        try:self.open_docs_page(tender_id)
        except SiteError as e:attempts.append('صفحه «دریافت اسناد»: '+str(e).splitlines()[0][:120])
        if self.download_template and not self.download_template.get('body'):
            path,q,_=fill_template(self.download_template,self.conv,appendix_id=appendix_id,document_id=doc_id,document_type=doc_type)
            urls.append(('الگوی آموخته',path,dict(q)))
        urls.append(('درخواست ساده','/etend/appendix-download',params))
        cq=dict(parse_qsl(self._conv_query('appendix')))
        if cq:urls.append(('درخواست + conversation','/etend/appendix-download',dict(params,**cq)))
        content=None
        for label,path,prm in urls:
            try:
                resp=self.context.request.get(SITE+path,params=prm,headers={'Referer':SITE+'/etend/indexPage.action'},timeout=90000,fail_on_status_code=False)
                if resp.ok:
                    body=resp.body();headers={str(k).lower():v for k,v in resp.headers.items()}
                    if body and not content_is_html(headers,body):content=body;break
                    attempts.append(f'{label}: صفحه HTML')
                else:attempts.append(f'{label}: HTTP {resp.status}')
            except Exception as e:
                attempts.append(f'{label}: {str(e)[:80]}')
        if content is None and self._docs_open.get(str(tender_id)):
            # the site may have forgotten the docs page (new conversation): reopen it once and retry
            try:
                self.open_docs_page(tender_id,force=True)
                resp=self.context.request.get(SITE+'/etend/appendix-download',params=params,timeout=90000,fail_on_status_code=False)
                body=resp.body() if resp.ok else b''
                if body and not content_is_html({str(k).lower():v for k,v in resp.headers.items()},body):content=body
                else:attempts.append('پس از بازکردن دوباره صفحه اسناد: '+('صفحه HTML' if body else f'HTTP {resp.status}'))
            except Exception as e:
                attempts.append('پس از بازکردن دوباره صفحه اسناد: '+str(e)[:80])
        if content is None:
            try:
                r=self._target().evaluate(JS_FETCH_BINARY,{'path':'/etend/appendix-download','params':params})
                body=base64.b64decode(r.get('b64') or '') if r.get('ok') else b''
                if body and not content_is_html({'content-type':r.get('ctype','')},body):content=body
                else:attempts.append('درخواست از داخل صفحه: '+('صفحه HTML' if body else f'HTTP {r.get("status")}'))
            except Exception as e:
                attempts.append('درخواست از داخل صفحه: '+str(e)[:80])
        final=None
        if content is None:
            tmp=filepath.with_name(filepath.name+'.dl')
            try:
                page=self._target().page if hasattr(self._target(),'page') else self.page()
                from urllib.parse import urlencode
                u=SITE+urls[0][1]+'?'+urlencode(urls[0][2])
                self._save_native(page,u,name,tmp);final=tmp
            except Exception as e:
                attempts.append('دانلود مرورگر: '+str(e).splitlines()[0][:90])
            if final is None:
                try:
                    self._dialog_download(tender_id,appendix_id,opener,tmp);final=tmp
                except Exception as e:
                    attempts.append('دکمه خود سایت: '+str(e).splitlines()[0][:90])
            if final is None:
                tmp.unlink(missing_ok=True)
                raise SiteError('دریافت فایل با هیچ روشی نشد:\n'+'\n'.join(attempts)+
                                '\nاگر دانلود دستی در مرورگر برنامه جواب می‌دهد، «ضبط روند سایت» را بزنید و یک‌بار دستی دانلود کنید.')
            content=final.read_bytes();final.unlink(missing_ok=True)
        if len(content)==0:raise SiteError('فایل خالی دریافت شد.')
        if filepath.exists() and filepath.stat().st_size==len(content):
            return str(filepath),'قبلاً دریافت‌شده'
        if filepath.exists():
            stem=filepath.stem; suffix=filepath.suffix
            i=2
            while filepath.exists():
                filepath=target/f'{stem}_{i}{suffix}';i+=1
        tmp=filepath.with_name(filepath.name+'.part')
        try:
            tmp.write_bytes(content)
            tmp.replace(filepath)
        finally:
            if tmp.exists():tmp.unlink()
        return str(filepath),'دریافت‌شده'

    # --- Manual downloads, idle tick and the site-flow recorder ------------------------
    def _watch_page(self,page):
        try:page.on('download',lambda d:None if self._native else self._dl_queue.append(d))
        except Exception:pass

    def tick(self):
        """Called by the worker while idle: process browser events, save manual downloads,
        and collect recorder entries."""
        self.pump(0)
        while self._dl_queue:
            d=self._dl_queue.pop(0)
            try:
                name=safe_name(d.suggested_filename or 'download')
                folder=Path(self.download_dir or Path.home()/'Downloads')/'دانلودهای مرورگر برنامه'
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/name;i=2
                while target.exists():
                    target=folder/f'{Path(name).stem}_{i}{Path(name).suffix}';i+=1
                d.save_as(str(target))
                if self._rec is not None:
                    self._rec['downloads'].append({'time':time.time()-self._rec['t0'],'path':urlparse(d.url).path,
                        'query':self._safe_pairs(parse_qsl(urlparse(d.url).query,keep_blank_values=True)),
                        'file':d.suggested_filename,'saved':str(target)})
                self.saved_downloads.append(str(target))
            except Exception as e:
                if self._rec is not None:self._rec['errors'].append('download: '+str(e)[:200])
        if self._rec is not None:self._rec_process()


    @staticmethod
    def _safe_pairs(pairs):
        return [[k,'[حذف]' if is_secret_name(k) else redact(v)[:200]] for k,v in pairs]

    def start_recording(self):
        if not self.context:raise SiteError('ابتدا مرورگر را باز کنید.')
        if self._rec is not None:return
        self._rec={'t0':time.time(),'pending':[],'entries':[],'downloads':[],'errors':[]}
        self._rec_handler=lambda r:self._rec is not None and self._rec['pending'].append(r)
        self.context.on('response',self._rec_handler)

    def _rec_process(self):
        rec=self._rec
        while rec['pending']:
            r=rec['pending'].pop(0)
            try:
                req=r.request
                rtype=req.resource_type
                u=urlparse(r.url)
                if rtype not in ('document','xhr','fetch','other') or u.path.lower().endswith(STATIC_EXT):continue
                if not is_setad_url(r.url) or r.url.startswith(SANDBOX_URL):continue
                headers={k.lower():v for k,v in r.headers.items()}
                ctype=headers.get('content-type','')
                post=[]
                if req.post_data and 'urlencoded' in (req.headers.get('content-type') or ''):
                    post=parse_qsl(req.post_data,keep_blank_values=True)
                e={'time':round(time.time()-rec['t0'],1),'type':rtype,'method':req.method,'path':u.path,
                   'query':self._safe_pairs(parse_qsl(u.query,keep_blank_values=True)),'post':self._safe_pairs(post),
                   'status':r.status,'content_type':ctype.split(';')[0],
                   'disposition':redact(headers.get('content-disposition',''))[:200]}
                if 'json' in ctype or 'html' in ctype or 'text' in ctype or 'javascript' in ctype:
                    try:body=r.body()
                    except Exception:body=b''
                    e['size']=len(body)
                    txt=body[:3_000_000].decode('utf-8','replace')
                    try:
                        data=json.loads(txt)
                        e['json']=json_shape(data)
                        if looks_like_file_list(data):
                            e['file_list']=True
                            self.learned['list']=make_template(r.url,post,req.method)
                    except ValueError:
                        if 'html' in ctype or '<' in txt[:200]:
                            e['html']=redact_html(txt)[:150000]
                else:
                    e['size']=int(headers.get('content-length') or 0)
                    if r.status==200 and ('attachment' in headers.get('content-disposition','').lower() or
                                          any(x in ctype for x in ('pdf','zip','octet','msword','officedocument','rar','image/'))):
                        e['file_download']=True
                        self.learned['download']=make_template(r.url,post,req.method)
                rec['entries'].append(e)
            except Exception as ex:
                rec['errors'].append(str(ex)[:200])

    def stop_recording(self):
        if self._rec is None:raise SiteError('ضبطی در جریان نیست.')
        self.pump(300)
        self._rec_process()
        try:self.context.remove_listener('response',self._rec_handler)
        except Exception:pass
        rec=self._rec;self._rec=None
        for d in rec['downloads']:
            # A browser download that never produced a response event (e.g. direct link) still teaches the URL.
            if 'download' not in self.learned and d.get('path'):
                self.learned['download']=make_template(SITE+d['path']+'?'+'&'.join(f'{k}={v}' for k,v in d['query']))
        return {'duration_sec':round(time.time()-rec['t0']),'requests':rec['entries'],'downloads':rec['downloads'],
                'errors':rec['errors'],'learned':{k:v for k,v in self.learned.items()},
                'conversation_ids':dict(self.conv)}

    @property
    def recording(self):
        return self._rec is not None

    # --- Diagnostics --------------------------------------------------------------
    def diagnostics(self):
        """Structure only: paths, parameter NAMES, function sources. No cookies/tokens/values."""
        out={'tabs':[],'frames':[],'conversation_ids':{},'trace':list(self.trace)}
        if not self.context:
            out['error']='مرورگر باز نیست';return out
        self.pump(0)
        for p in self.context.pages:
            if p.is_closed():continue
            out['tabs'].append(safe_page_label(p.url))
            for f in p.frames:
                if not is_site_url(f.url):continue
                try:info=f.evaluate(JS_PROBE)
                except Exception as e:
                    out['frames'].append({'path':safe_page_label(f.url),'error':str(e)[:200]});continue
                out['conversation_ids'].update(info.get('conv') or {})
                for form in info.get('forms') or []:
                    form['action']=redact(form.get('action',''))
                    form['inputs']=[n for n in form.get('inputs',[])]
                out['frames'].append({'path':safe_page_label(f.url),'title':info.get('title'),
                    'jquery':info.get('jquery'),'grid':info.get('grid'),'forms':info.get('forms'),
                    'scripts':[safe_page_label(s if '//' in s else SITE+s) for s in info.get('scripts') or []],
                    'functions':{k:redact(v) for k,v in (info.get('fns') or {}).items()}})
        try:
            if self.source_frame is not None:
                reqs=self.learn_requests(self.source_frame,'showTenderRegister',[0],wait=300)
                out['showTenderRegister_requests']=[{'kind':r['kind'],'method':r['method'],
                    'path':safe_page_label(r['url']),
                    'params':[k for k,_ in parse_qsl(urlparse(r['url']).query)]+[k for k,_ in r.get('data') or []]}
                    for r in reqs]
        except Exception as e:
            out['showTenderRegister_requests']=str(e)[:200]
        out['trace']=list(self.trace)
        return out
