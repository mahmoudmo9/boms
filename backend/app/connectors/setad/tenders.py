"""Tender operations (etend.setadiran.ir): connect, full list sync with unstable-pagination recovery, «فراخوان‌های من»,
document lists, downloads, add / remove «فراخوان‌های من».

Ported from SetadSuite v0.9.23 setad_tender/worker.py. BOMS changes: no QThread / command queue / run loop (the
Setad agent calls `_guarded(cmd, args, browser, store)` on its own thread); the Qt signals are plain callbacks with
the same names (`message`, `progress`, `result`, `failed`, `busy`); the SQLite `Database` is replaced by `store`,
any object with the same methods (BOMS: app.modules.listings.store.ListingStore; tests: connectors.setad.memory).
The sync, recovery passes, document and favourite logic are unchanged.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import threading
import time
from .bridge import SetadBrowser, SiteError, host_kind, JS_SSO_STATE, friendly_error
from .parsers import learn_favorite_mapping, favorite_args_from_raw, favorite_args_from_list, my_call_tender_ids, my_call_states
import math


class Signal:
    """Stand-in for the Qt signal: emit(...) calls the connected callback (BOMS: the agent's status writer)."""
    def __init__(self,*_types):
        self._fn=None
    def connect(self,fn):
        self._fn=fn
    def emit(self,*args):
        if self._fn is not None:self._fn(*args)


class Worker:
    def __init__(self,data_dir:Path,cancel_event:threading.Event|None=None):
        self.message = Signal(str)
        self.progress = Signal(int,int,int,int)  # page, total, uniques, reported
        self.result = Signal(str,object)
        self.failed = Signal(str,str)
        self.busy = Signal(str,bool)             # operation, running
        self.data_dir=Path(data_dir)
        self.cancel_event=cancel_event or threading.Event()
        self.inq_engine=None      # unused in BOMS (the purchase-call engine is driven by the agent itself)
        self.inq_alive=True

    def cancel(self):
        self.cancel_event.set()
        self.message.emit('درخواست توقف ثبت شد؛ پس از اتمام مرحله جاری متوقف می‌شود.')

    ETEND_CMDS={'sync','detail','documents','favorite','unfavorite','download','my_calls','batch','payment'}

    def _note_type(self,browser,db,tid):
        t=db.tender(str(tid)) or {}
        try:raw=json.loads(t.get('raw_json') or '{}')
        except ValueError:raw={}
        if raw.get('type'):browser.tender_types[str(tid)]=str(raw['type'])
        return raw

    @staticmethod
    def _session_lost(browser,exc):
        t=str(exc)
        if any(x in t for x in ('JSON','نشست','login','ورود','HTML','Expected JSON','منقضی')):return True
        try:
            return any(host_kind(p.url)=='sso' for p in browser.context.pages if not p.is_closed())
        except Exception:return False

    def _check_closed(self,browser):
        if browser.context is not None and not browser.alive():
            browser.close()
            self.result.emit('browser_closed',{})

    def _guarded(self,cmd,args,browser,db):
        """Tender commands need the «مناقصه‌گر» role: switch automatically, and retry once if the session was lost."""
        if cmd not in self.ETEND_CMDS:
            return self._dispatch(cmd,args,browser,db)
        if args.get('id') is not None:self._note_type(browser,db,args['id'])
        for tid in args.get('ids') or []:self._note_type(browser,db,tid)
        if browser.role!='ETEND':self.message.emit('در حال تغییر نقش ستاد به «مناقصه‌گر»...')
        browser.ensure_etend()
        try:
            return self._dispatch(cmd,args,browser,db)
        except Exception as e:
            if cmd=='batch' or not self._session_lost(browser,e):raise
            self.message.emit('نشست مناقصه قطع شده بود؛ دوباره وصل می‌شوم...')
            browser.ensure_etend(force=True)
            return self._dispatch(cmd,args,browser,db)

    def _dispatch(self,cmd,args,browser,db):
        if cmd=='set_download_dir':
            browser.download_dir=args.get('path');return
        if cmd=='browser':
            if args.get('download_dir'):browser.download_dir=args['download_dir']
            self.message.emit(browser.open())
            self.result.emit('browser',{'ready':True})
        elif cmd=='check':
            info=browser.capture()
            info['mapping']=self._learn_mapping(browser,db)
            self._after_connect(browser,db,info)
            self.result.emit('check',info)
        elif cmd=='connect':
            self._connect(browser,db,args)
        elif cmd=='show_browser':
            browser.restore()
        elif cmd=='set_role':
            if not browser.context or not browser.alive():
                raise SiteError('مرورگر ستاد باز نیست؛ ابتدا «اتصال به ستاد» را بزنید.')
            if args.get('role')=='EPROC':
                self.message.emit('در حال تغییر نقش ستاد به «تامین‌کننده»...')
                browser.ensure_eproc(browser.work_page(),wait_login=True,cancelled=self.cancel_event.is_set,say=self.message.emit)
            else:
                self.message.emit('در حال تغییر نقش ستاد به «مناقصه‌گر»...')
                browser.ensure_etend()
        elif cmd=='my_calls':
            n=self._sync_my_calls(browser,db)
            self.result.emit('my_calls',{'count':n,'quiet':bool(args.get('quiet'))})
        elif cmd=='batch':
            self._batch(browser,db,args)
        elif cmd=='payment':
            browser.open_payment_page(args['id'])
            db.log_action(str(args['id']),'باز کردن صفحه پرداخت اسناد','انجام شد','بدون پرداخت خودکار')
            self.result.emit('payment',{'id':str(args['id'])})
        elif cmd=='sync':
            self.cancel_event.clear()
            self._sync(browser,db,args.get('rows',50))
            try:self._sync_my_calls(browser,db)
            except Exception:pass
            self.result.emit('refresh',{})
        elif cmd=='detail':
            t=db.tender(args['id']) or {}
            val=browser.details(args['id'],t.get('number',''))
            db.save_detail(args['id'],val['text'],val['pairs'])
            if val['groups']:db.save_groups(args['id'],val['groups'],'جزئیات فراخوان')
            self.result.emit('detail',{'id':args['id'],'method':val['method']})
        elif cmd=='documents':
            self.cancel_event.clear()
            self.result.emit('documents',self._documents(browser,db,str(args['id']),args.get('helper',True)))
        elif cmd=='favorite':
            self._favorite(browser,db,str(args['id']),args.get('confirmed') is True)
        elif cmd=='unfavorite':
            self._unfavorite(browser,db,str(args['id']),args.get('confirmed') is True)
        elif cmd=='download':
            self._download(browser,db,args)
        elif cmd=='record_start':
            browser.start_recording()
            self.result.emit('record_start',{})
        elif cmd=='record_stop':
            data=browser.stop_recording()
            self._persist_learned(browser,db)
            data['app_version']=args.get('version','')
            data['created']=datetime.now().isoformat(timespec='seconds')
            folder=self.data_dir/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
            path=folder/f'setad-recording-{datetime.now():%Y%m%d-%H%M%S}.json'
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            self.result.emit('record_stop',{'path':str(path),'requests':len(data['requests']),
                'downloads':len(data['downloads']),'learned':sorted(data['learned'].keys())})
        elif cmd=='diagnose':
            data=browser.diagnostics()
            data['app_version']=args.get('version','')
            data['created']=datetime.now().isoformat(timespec='seconds')
            data['last_sync']={k:v for k,v in (db.last_sync() or {}).items() if k!='errors'}
            folder=self.data_dir/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
            path=folder/f'setad-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.json'
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            self.result.emit('diagnose',{'path':str(path)})

    # -----------------------------------------------------------------------
    def _after_connect(self,browser,db,info):
        labels=info.get('labels') or {}
        if labels:db.set_meta('column_labels',labels)
        try:info['my_calls']=self._sync_my_calls(browser,db)
        except Exception:info['my_calls']=None

    def _sync_my_calls(self,browser,db):
        """Mark tenders that are already in «فراخوان‌های من» on the site (+ the site's own status).
        None = list unreadable (nothing is changed then)."""
        rows=browser.get_my_calls_ids()
        if rows is None:return None
        states=my_call_states(rows)
        if states or not rows:                      # the real row shape (or a really empty list)
            known={t['id'] for t in db.list_tenders()}
            changes=db.save_site_states({k:v for k,v in states.items() if k in known})
            if changes:
                titles={t['id']:t.get('number') or t['id'] for t in db.list_tenders()}
                self.result.emit('status_changes',{'changes':[{'id':i,'number':titles.get(i,i),'old':o,'new':n,'code':(states.get(i) or {}).get('state','')} for i,o,n in changes]})
            for k,v in states.items():
                if v.get('type'):browser.tender_types[k]=v['type']
            return len(states)
        known={t['id'] for t in db.list_tenders()}
        ids=[i for i in my_call_tender_ids(rows) if i in known]
        if not ids:return 0 if not rows else None
        db.set_my_calls_bulk(ids,clear_others=True)
        return len(set(ids))

    def _connect(self,browser,db,args):
        """One-button connect: open the app browser, wait for the user's login, open «فراخوان‌ها»,
        verify the grid, then minimise the browser window."""
        self.cancel_event.clear()
        self.message.emit(browser.open())
        self.result.emit('browser',{'ready':True})
        if browser.role=='EPROC':
            self.message.emit('در حال تغییر نقش ستاد به «مناقصه‌گر»...')
            try:browser.ensure_etend(force=True)
            except SiteError as e:self.message.emit(str(e))
        t0=time.time();last_nav=0.0;attempts=0;info=None;role_tries=0
        limit=float(args.get('timeout',900))
        while time.time()-t0<limit:
            if self.cancel_event.is_set():
                self.result.emit('connect_cancel',{});return
            if not browser.alive():
                raise SiteError('پنجره مرورگر بسته شد. دوباره «اتصال به ستاد» را بزنید.')
            info=browser.probe_grid()
            if info:break
            role_page=None
            for p in [x for x in browser.context.pages if not x.is_closed()]:
                if host_kind(p.url)=='sso':
                    try:
                        if p.evaluate(JS_SSO_STATE).get('role'):role_page=p;break
                    except Exception:pass
            if role_page is not None and role_tries<3:
                role_tries+=1
                self.message.emit('انتخاب خودکار نقش «مناقصه‌گر» در ستاد...')
                try:browser.handle_role_page(role_page,'ETEND')
                except SiteError as e:self.message.emit(str(e))
                browser.pump(1500);continue
            if browser.has_site_tab():
                if time.time()-last_nav>7:
                    what=browser.goto_tenders(attempts);attempts+=1;last_nav=time.time()
                    self.message.emit(what or 'منتظر باز شدن فهرست «فراخوان‌ها» هستم...')
                else:
                    self.message.emit('منتظر باز شدن فهرست «فراخوان‌ها» هستم...')
            else:
                self.message.emit('منتظر ورود شما در مرورگر برنامه هستم...')
            browser.pump(800)
        if not info:
            raise SiteError('در زمان مقرر، ورود یا فهرست «فراخوان‌ها» شناسایی نشد. '
                            'در مرورگر برنامه وارد شوید، نقش «مناقصه‌گر» را انتخاب کنید و دوباره «اتصال به ستاد» را بزنید.')
        browser._set_role('ETEND')
        info['mapping']={'site_codes':True}
        self._after_connect(browser,db,info)
        info['minimized']=bool(args.get('minimize',True)) and browser.minimize()
        self.result.emit('check',info)

    def _batch(self,browser,db,args):
        self.cancel_event.clear()
        kind=args['kind'];ids=[str(i) for i in args['ids']]
        ok=0;bad=[];empty=[]
        for i,tid in enumerate(ids,1):
            if self.cancel_event.is_set():break
            t=db.tender(tid) or {}
            self.message.emit(f'{i} از {len(ids)}: {t.get("number","")}')
            self.progress.emit(i-1,len(ids),ok,len(ids))
            try:
                if kind=='favorite':
                    if t.get('in_my_calls'):ok+=1;continue
                    self._favorite(browser,db,tid,True,emit=False);ok+=1;time.sleep(0.5)
                elif kind=='documents':
                    res=self._documents(browser,db,tid,args.get('helper',True))
                    if res.get('all_empty'):empty.append(t.get('number',tid))
                    else:ok+=1
                    time.sleep(0.2)
            except Exception as e:
                bad.append(f"{t.get('number',tid)}: {str(e).splitlines()[0][:140]}")
        self.progress.emit(len(ids),len(ids),ok,len(ids))
        self.result.emit('batch',{'kind':kind,'ok':ok,'errors':bad,'empty':empty,'total':len(ids),
                                  'cancelled':self.cancel_event.is_set()})

    # -----------------------------------------------------------------------
    def _learn_mapping(self,browser,db):
        """Learn favoriteForm argument fields from rows visible in the site grid."""
        try:
            samples=browser.favorite_samples()
            if not samples:return db.meta('favorite_mapping') or {}
            raws=db.raw_map([s['id'] for s in samples])
            mapping=learn_favorite_mapping(samples,raws)
            if mapping:db.set_meta('favorite_mapping',mapping)
            return mapping or db.meta('favorite_mapping') or {}
        except Exception:
            return db.meta('favorite_mapping') or {}

    def _persist_learned(self,browser,db):
        if browser.learned.get('list'):
            db.set_meta('list_template',browser.learned['list']);browser.list_template=browser.learned['list']
        if browser.learned.get('download'):
            db.set_meta('download_template',browser.learned['download']);browser.download_template=browser.learned['download']

    def _documents(self,browser,db,tender_id,allow_helper=True):
        """List the files of every document category. Direct requests first (no tabs);
        the helper tab is only a fallback for categories the direct route could not read."""
        tender=db.tender(tender_id) or {}
        browser.trace=[]
        self._note_type(browser,db,tender_id)
        self.message.emit('در حال باز کردن صفحه «دریافت اسناد» در ستاد...')
        try:
            info,files,errors=browser.list_documents(tender_id)
        except SiteError as e:
            info=None;first_error=str(e)
        if info:
            groups=info['groups'];method='صفحه «دریافت اسناد»'
            db.clear_groups(tender_id);db.save_groups(tender_id,groups,method)
            total=0;warnings=list(errors)
            for g in groups:
                rows=files.get(str(g['document_type']),[])
                db.save_files(tender_id,g['document_type'],rows);total+=len(rows)
                if not rows and g.get('count') and not any(w.startswith(g.get('title','')) for w in warnings):
                    warnings.append(f"{g['title']}: سایت {g['count']} فایل اعلام کرده ولی فهرست آن برنگشت")
            if total==0 and info.get('paid'):
                warnings.append('اسناد این فراخوان پولی است؛ از «صفحه پرداخت اسناد» پرداخت را خودتان انجام دهید.')
            db.set_my_calls(tender_id,True)
            return {'id':tender_id,'count':total,'method':method,'warnings':warnings,'helper_used':False,
                    'no_groups':False,'all_empty':total==0,'trace':list(browser.trace),'verified':True,
                    'paid':bool(info.get('paid')) and total==0}
        if not tender.get('in_my_calls'):
            return {'id':tender_id,'count':0,'method':'','warnings':[first_error],'helper_used':False,'no_groups':True,
                    'all_empty':True,'not_added':True,'trace':list(browser.trace)}
        browser._log('مسیر «دریافت اسناد»: '+first_error.splitlines()[0][:150])
        self.message.emit('در حال شناسایی دسته‌های اسناد...')
        groups,method=browser.get_groups(tender_id,tender.get('number',''))
        base={'id':tender_id,'count':0,'method':method,'warnings':[],'helper_used':False,'no_groups':False}
        if not groups:
            base.update(all_empty=True,no_groups=True,trace=list(browser.trace))
            return base
        db.clear_groups(tender_id)
        db.save_groups(tender_id,groups,method)
        results={};warnings=[];retry=[]
        for i,group in enumerate(groups,1):
            if self.cancel_event.is_set():break
            self.message.emit(f'خواندن فهرست فایل‌ها: {group.get("title","")} ({i}/{len(groups)})')
            try:
                rows,declared,label=browser.get_files(tender_id,group)
            except Exception as e:
                warnings.append(group.get('title','')+': '+str(e));retry.append(group);continue
            expected=int(group.get('count') or 0)
            if (not rows and expected) or (rows and declared and declared>len(rows)):
                retry.append(group)
            if rows:results[str(group['document_type'])]=(rows,declared,label)
        if retry and allow_helper and not self.cancel_event.is_set():
            self.message.emit('خواندن مستقیم کامل نشد؛ تب کمکی برای دسته‌های ناقص باز می‌شود...')
            try:
                sandbox=browser.list_files_sandbox(tender_id,retry,tender.get('number',''))
                base['helper_used']=True
                for g in retry:
                    hit=sandbox.get(str(g['document_type']))
                    if hit and hit[0]:
                        results[str(g['document_type'])]=hit
                        warnings=[w for w in warnings if not w.startswith(g.get('title',''))]
            except Exception as e:
                browser._log(f'تب کمکی: {str(e)[:200]}')
            self._persist_learned(browser,db)
        total=0
        for group in groups:
            hit=results.get(str(group['document_type']))
            rows=hit[0] if hit else []
            db.save_files(tender_id,group['document_type'],rows)
            total+=len(rows)
            declared=hit[1] if hit else 0
            if hit and declared>len(rows):warnings.append(group['title']+': فهرست ناقص')
            elif not rows and group.get('count') and not any(w.startswith(group.get('title','')) for w in warnings):
                warnings.append(f"{group['title']}: سایت {group['count']} فایل اعلام کرده ولی فهرست آن برنگشت")
        base.update(count=total,all_empty=total==0,warnings=warnings,trace=list(browser.trace),
                    verified=True)
        return base

    def _favorite(self,browser,db,tender_id,confirmed,emit=True):
        """«+» exactly like the site: favoriteForm(id, price, organization.id, typeCode, setupCode)."""
        if not confirmed:raise SiteError('اقدام بدون تأیید صریح مجاز نیست.')
        tender=db.tender(tender_id)
        if not tender:raise SiteError('فراخوان در دیتابیس یافت نشد.')
        raw=self._note_type(browser,db,tender_id)
        args=browser.get_live_favorite_args(tender_id)
        source='دکمه همان ردیف در سایت'
        if not args:
            args=favorite_args_from_list(raw)
            source='داده فهرست + جدول کد سایت'
            if args and (args.get('typeId') is None or args.get('setupId') is None):
                codes=browser.details_codes(tender_id)
                if args.get('typeId') is None and codes.get('type'):args['typeId']=codes['type']
                if args.get('setupId') is None and codes.get('setup'):args['setupId']=codes['setup']
                source+=' + کد از صفحه جزئیات'
        if not args:
            raise SiteError('اطلاعات این فراخوان در فهرست ذخیره‌شده کامل نیست؛ یک‌بار «دریافت همه فراخوان‌ها» را بزنید و دوباره امتحان کنید.')
        try:
            ret=browser.add_my_calls(tender_id,args,True)
            db.set_my_calls(tender_id,True)
            db.log_action(tender_id,'افزودن به فراخوان‌های من','موفق',ret.get('method','')+' | '+source)
            if emit:self.result.emit('favorite',{'id':tender_id,'method':ret.get('method',''),'source':source})
        except Exception as exc:
            db.log_action(tender_id,'افزودن به فراخوان‌های من','ناموفق',str(exc))
            raise

    def _unfavorite(self,browser,db,tender_id,confirmed):
        """Remove from «فراخوان‌های من» on the site (the site itself refuses when it is not allowed)."""
        if not confirmed:raise SiteError('اقدام بدون تأیید صریح مجاز نیست.')
        try:
            browser.remove_my_call(tender_id,True)
        except Exception as exc:
            db.log_action(tender_id,'حذف از فراخوان‌های من در سایت','ناموفق',str(exc))
            raise
        db.set_my_calls(tender_id,False)
        try:
            with db.conn:db.conn.execute("UPDATE tenders SET site_state='', site_state_name='' WHERE id=?",(tender_id,))
        except Exception:pass
        db.log_action(tender_id,'حذف از فراخوان‌های من در سایت','موفق','')
        self.result.emit('unfavorite',{'id':tender_id})

    def _download(self,browser,db,args):
        self.cancel_event.clear()
        tid=str(args['id']);only={tuple(x) for x in args['file_keys']}
        tender=db.tender(tid)
        if not tender:raise SiteError('فراخوان در دیتابیس یافت نشد.')
        files=[f for f in db.files(tid) if (f['document_type'],f['appendix_id']) in only]
        openers={g['document_type']:g.get('opener') or '' for g in db.groups(tid)}
        ok=0;bad=[]
        for i,f in enumerate(files,1):
            if self.cancel_event.is_set():break
            self.message.emit(f'دریافت سند {i} از {len(files)}: {f["display_name"]}')
            self.progress.emit(i-1,len(files),ok,len(files))
            try:
                path,state=browser.download(tid,f['document_type'],f['appendix_id'],
                                           f['display_name'],f['extension'],
                                           Path(args['dest']),tender['number'],f['group_title'],f.get('document_id'),openers.get(f['document_type'],''))
                db.set_file_result(tid,f['document_type'],f['appendix_id'],path,state)
                ok+=1
            except Exception as e:
                db.set_file_result(tid,f['document_type'],f['appendix_id'],'','ناموفق',str(e))
                bad.append(f['display_name']+': '+str(e))
            time.sleep(0.12)
        self.progress.emit(len(files),len(files),ok,len(files))
        folder=str(Path(args['dest'])/tender['number']) if ok else ''
        self.result.emit('download',{'id':tid,'success':ok,'errors':bad,'folder':folder,
                                     'cancelled':self.cancel_event.is_set()})

    # -----------------------------------------------------------------------
    def _sync(self,browser,db,rows):
        info=browser.capture()
        reported=int(info.get('records') or 0)
        if reported<=0:raise SiteError('تعداد فراخوان‌های سایت مشخص نیست یا فهرست خالی است.')
        page_size=max(5,min(int(rows),100))
        data=browser.get_grid_page(1,page_size)
        expected=int(data.get('records') or reported)
        total=int(data.get('total') or 0)
        if total<=0 or total>10000:raise SiteError('تعداد صفحات دریافتی غیرمنتظره است.')
        run_id=db.start_sync(expected,total)
        seen=set(); duplicates=0; errors=[]; new=updated=0
        completed=0
        pages_of=defaultdict(list)     # id -> pages where it appeared during pass 1
        recovered={}                   # id -> page where it first appeared in pass 2
        self.message.emit(f'شروع دریافت: {expected:,} فراخوان، {total} صفحه')
        try:
            # Pass 1 = normal scan. Later passes (read-only re-scans) run ONLY while ids are missing:
            # pass 2 same page size; pass 3/4 use other page sizes (and reverse order), which moves the
            # page boundaries so ids shifted by the site's unstable pagination show up elsewhere.
            plan={1:(page_size,{}),2:(page_size,{}),3:(30,{'sord':'desc'}),4:(70,{})}
            for pass_no in (1,2,3,4):
                if self.cancel_event.is_set():break
                size,extra=plan[pass_no]
                if pass_no>1:
                    if errors or len(seen)>=expected:break
                    self.message.emit(f'به علت مغایرت شمارش، بازبینی صفحات شروع شد (دور {pass_no})؛ {expected-len(seen):,} شناسه کمبود.')
                pages_in_pass=total if pass_no<=2 else -(-expected//size)
                for p in range(1,pages_in_pass+1):
                    if self.cancel_event.is_set():break
                    page_data=data if pass_no==1 and p==1 else None
                    if page_data is None:
                        for attempt in range(3):
                            try:
                                page_data=browser.get_grid_page(p,size,extra)
                                break
                            except Exception as e:
                                if attempt==2:errors.append(f'دور {pass_no}، صفحه {p}: {e}')
                                else:time.sleep(0.8*(attempt+1))
                    if page_data is None:
                        self.progress.emit(p,pages_in_pass,len(seen),expected)
                        continue
                    records=page_data['gridModel']
                    incoming=[str(x.get('id')) for x in records if x.get('id') is not None]
                    if pass_no==1:
                        for tid in incoming:pages_of[tid].append(p)
                        duplicates+=sum(1 for tid in incoming if len(pages_of[tid])>1)
                    else:
                        for tid in incoming:
                            if tid not in seen and tid not in recovered:recovered[tid]=p
                    seen.update(incoming)
                    a,b,_=db.add_tenders(records)
                    db.set_my_calls_from_rows(records)
                    new+=a;updated+=b
                    if pass_no==1:completed+=1
                    db.sync_progress(run_id,min(p,total),len(seen),duplicates)
                    self.progress.emit(p,pages_in_pass,len(seen),expected)
                    if p%5==0 or p==pages_in_pass:
                        self.message.emit(f'دور {pass_no}: صفحه {p}/{pages_in_pass} — یکتا {len(seen):,}، تکراری {duplicates:,}')
                    time.sleep(0.2)
            dup_items=[(tid,len(pg),'، '.join(str(x) for x in pg)) for tid,pg in pages_of.items() if len(pg)>1]
            db.save_sync_issues(run_id,'duplicate',dup_items)
            db.save_sync_issues(run_id,'recovered',[(tid,1,str(pg)) for tid,pg in recovered.items()])
            cancelled=self.cancel_event.is_set()
            if cancelled:status='متوقف‌شده'
            elif errors or completed!=total or len(seen)!=expected:status='نیازمند بازبینی'
            else:status='کامل'
            if len(seen)!=expected:errors.append(f'تعداد اعلامی سایت {expected:,}؛ شناسه یکتای دریافت‌شده {len(seen):,}.')
            db.finish_sync(run_id,status,'\n'.join(errors))
            self.result.emit('sync',{'run_id':run_id,'status':status,'reported':expected,'unique':len(seen),
                       'duplicate':duplicates,'duplicate_ids':len(dup_items),'recovered':len(recovered),
                       'pages':total,'completed':completed,'new':new,'page_size':page_size,
                       'updated':updated,'errors':errors})
        except Exception as e:
            db.finish_sync(run_id,'خطا',str(e))
            raise
