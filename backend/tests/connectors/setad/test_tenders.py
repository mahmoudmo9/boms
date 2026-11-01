"""Tender tests ported from SetadSuite v0.9.23 tests/tenders (test_core.py, test_lifecycle_v06.py, test_v02.py,
test_v03.py, test_sync_offline.py).

Parser, lifecycle and date tests are unchanged apart from the imports. Tests that used the SQLite `Database` run on
the in-memory store with the same interface (connectors.setad.memory.MemoryStore); their assertions differ only
where BOMS deliberately differs: a change is recorded per tracked field (not per whole raw row), and SetadSuite's
own tracking/selection columns, the v0.3 tender workspace (Phase 7b) and SQLite migrations do not exist in BOMS.
"""
from datetime import date, timedelta

from app.connectors.setad import lifecycle as LC
from app.connectors.setad.dates import days_left, j2g, jalali_of, parse_jalali
from app.connectors.setad.memory import MemoryStore
from app.connectors.setad.parsers import (content_is_html, details_from_html, detail_pairs_from_html,
    favorite_args_from_raw, file_rows_from_json, find_appendix_list_url, group_pairs, groups_from_html,
    learn_favorite_mapping, looks_like_details, raw_label, redact, safe_name, site_title, technical_fields)
from app.connectors.setad.tenders import Worker


def sample():
    return {
      'id':675227,'number':'2005000000123456','title':'عملیات آسفالت',
      'typeName':'مناقصه عمومی','operationProvinceName':'یزد','operationCityName':'تفت',
      'organization':{'id':4026,'name':'شهرداری نمونه'},
      'domainsDescription':'تأمین و اجرا','publicNotificationDate':'1405/07/28 20:00:00',
      'documentsDeadlineDate':'1405/08/08 12:00:00',
      'proposalDeadlineDate':'1405/08/18 12:00:00','remainingTime':'123'
    }


def test_db_preserves_user_selection_and_history():
    """test_core.py::test_db_preserves_user_selection_and_history: volatile clock fields are not a change, a title
    change is exactly one change row (BOMS: one row per tracked field; selection/tracking columns are BOMS-side)."""
    db=MemoryStore()
    assert db.add_tenders([sample()])==(1,0,0)
    raw=sample();raw['remainingTime']='122'
    assert db.add_tenders([raw])==(0,0,1) # volatile clock not a tender update
    raw['title']='عملیات آسفالت گرم'
    assert db.add_tenders([raw])==(0,1,0)
    assert db.tender('675227')['title']=='عملیات آسفالت گرم'
    assert db.changes==[('675227','title','عملیات آسفالت','عملیات آسفالت گرم')]


def test_groups_from_handler_do_not_assume_3195():
    page='''<table onclick="return showAppendix('/etend/appendix-openAppendix', null, '3193', '675227', 'true', 'reloadForm', null, 'reloadCsrfToken')">اسناد فنی تعداد فایل 1 حجم فایل 1.47MB</table>
    <table onclick="return showAppendix('/etend/appendix-openAppendix', null, '7013', '675227', 'true', 'reloadForm', null, 'reloadCsrfToken')">اسناد ارزیابی کیفی تعداد فایل 1 حجم فایل 729KB</table>
    <table onclick="return showAppendix('/etend/appendix-openAppendix', null, '3192', 'wrong-id', 'true', 'reloadForm', null, 'reloadCsrfToken')">نباید نمایش داده شود</table>'''
    rows=groups_from_html(page,'675227')
    assert len(rows)==2
    assert [x['document_type'] for x in rows]==['3193','7013']
    assert rows[0]['count']==1


def test_files_parser_sample():
    response={'records':1,'gridModel':[{'id':9750481,'fileName':'Fanni11',
                                       'showFileName':'Fanni11','showFileFormat':'pdf',
                                       'fileSize':'۱.۴۷ مگابایت','comment':'اسناد فنی','createDate':'۱۴۰۵/۰۷/۲۸'}]}
    rows=file_rows_from_json(response)
    assert rows==[{'appendix_id':'9750481','display_name':'Fanni11','extension':'pdf',
                   'size':'۱.۴۷ مگابایت','comment':'اسناد فنی','created':'۱۴۰۵/۰۷/۲۸'}]


def test_download_safe_filename_and_invalid_responses():
    assert safe_name('../some|bad?.pdf').count('/')==0
    assert safe_name('a:b')=='a_b'
    assert content_is_html({'content-type':'text/html'},b'<html>Login</html>')
    assert content_is_html({'content-type':'application/pdf'},b'<!doctype html><html>Session Expired')
    assert not content_is_html({'content-type':'application/pdf'},b'%PDF-1.7...')


def test_detail_text_is_readable():
    result=details_from_html('<form id="tenderDetailsForm"><table><tr><td>عنوان</td><td>آسفالت گرم</td></tr></table><script>evil()</script></form>')
    assert 'آسفالت گرم' in result and 'evil()' not in result


def test_document_tracking_persists():
    db=MemoryStore();db.add_tenders([sample()])
    db.save_groups('675227',[{'document_type':'3193','title':'اسناد فنی','count':1,'size':'1.47MB'}])
    db.save_files('675227','3193',[{'appendix_id':'9750481','display_name':'Fanni11','extension':'pdf'}])
    db.set_file_result('675227','3193','9750481','/x/Fanni11.pdf','دریافت‌شده')
    files=db.files('675227')
    assert len(files)==1 and files[0]['group_title']=='اسناد فنی' and files[0]['state']=='دریافت‌شده'
    db.save_files('675227','3193',[{'appendix_id':'9750481','display_name':'Fanni11','extension':'pdf'}])
    assert db.files('675227')[0]['state']=='دریافت‌شده'


T = date(2026, 10, 22)
J = lambda n: jalali_of(T + timedelta(days=n)) + ' 12:00'


def test_quality_uses_inquiry_deadline():
    r = {'type_name': 'ارزیابی کیفی برای مناقصه عمومی', 'documents_deadline': J(-1), 'inquiry_deadline': J(10),
         'in_my_calls': 1, 'site_state': 'IN_WATING_SENDING_PACKETS', 'site_state_name': 'در انتظار ارسال پاکت'}
    c = LC.classify(r, today=T)
    assert c['stage'] == 'prepare' and c['days'] == 10 and c['kind'] == 'send' and c['actionable']


def test_not_added_docs_passed_is_missed():
    c = LC.classify({'documents_deadline': J(-2), 'proposal_deadline': J(5)}, today=T)
    assert c['stage'] == 'missed' and not c['actionable']


def test_browse_uses_docs_deadline():
    c = LC.classify({'documents_deadline': J(3), 'proposal_deadline': J(15)}, today=T)
    assert c['stage'] == 'browse' and c['days'] == 3 and c['kind'] == 'docs'


def test_need_pay_and_unknown_state_verbatim():
    c = LC.classify({'in_my_calls': 1, 'site_state': 'ADD_TO_MY_FAVORITE', 'documents_deadline': J(1)}, today=T)
    assert c['stage'] == 'pay' and c['days'] == 1
    c = LC.classify({'in_my_calls': 1, 'site_state': 'X', 'site_state_name': 'در حال بررسي'}, today=T)
    assert c['stage'] == 'site' and c['label'] == 'در حال بررسي' and not c['actionable']


def test_mapping_overrides():
    c = LC.classify({'in_my_calls': 1, 'site_state': 'X', 'site_state_name': 'foo'}, {'X': 'missed'}, today=T)
    assert c['stage'] == 'missed'


def test_db_fields_star_history():
    """test_lifecycle_v06.py::test_db_fields_star_history (stars are BOMS screening, not the machine row)."""
    db = MemoryStore()
    raw = {'id': 674259, 'number': '2005', 'title': 't', 'inquiryDeadlineDate': '1405/08/23 19:00',
           'supplierLastEditionDate': '1405/07/30 13:46', 'lastTenderEdition': {'supplierNumber': 2}}
    db.add_tenders([raw])
    t = db.tender('674259')
    assert t['inquiry_deadline'].strftime('%H:%M') == '19:00' and t['edition_no'] == '2'
    assert db.save_site_states({'674259': {'state': 'ADD_TO_MY_FAVORITE', 'state_name': 'a'}}) == []
    ch = db.save_site_states({'674259': {'state': 'IN_WATING_SENDING_PACKETS', 'state_name': 'b'}})
    assert ch == [('674259', 'a', 'b')] and len(db.status_rows) == 1


def test_groups_keep_opener_and_document_id():
    html='''<a onclick="showAppendix('/etend/appendix-openAppendix', null, '3193', '675227', 'true', 'x'); return false;">اسناد فنی تعداد فایل ۲ حجم فایل 1.2 MB</a>
            <a onclick="showAppendix('/etend/appendix-openAppendix', null, '9999', '111', 'true')">پیوست سازمان</a>'''
    g=groups_from_html(html,'675227')
    assert len(g)==1 and g[0]['document_type']=='3193' and g[0]['count']==2
    assert g[0]['opener'].startswith("showAppendix('/etend/appendix-openAppendix'")


def test_find_appendix_list_url_unescapes():
    body="jQuery('#g').jqGrid({url:'/etend/appendix-list.action?documentId=1&amp;documentType=3193&amp;c=9'})"
    assert find_appendix_list_url(body)=='/etend/appendix-list.action?documentId=1&documentType=3193&c=9'


def test_favorite_mapping_learned_and_applied():
    raws={'1':{'id':1,'tenderDocumentsPrice':0.0,'organization':{'id':55},'tenderTypeId':4,'setupCode':2,'other':4},
          '2':{'id':2,'tenderDocumentsPrice':150.0,'organization':{'id':77},'tenderTypeId':3,'setupCode':2,'other':9}}
    samples=[{'id':'1','price':'0.0','organizationId':'55','typeId':'4','setupId':'2'},
             {'id':'2','price':'150','organizationId':'77','typeId':'3','setupId':'2'}]
    m=learn_favorite_mapping(samples,raws)
    assert m['organizationId']=='organization.id' and m['typeId']=='tenderTypeId'
    args=favorite_args_from_raw({'id':9,'tenderDocumentsPrice':5,'organization':{'id':1},'tenderTypeId':4,'setupCode':1},m)
    assert args=={'id':'9','price':'5','organizationId':'1','typeId':'4','setupId':'1'}


def test_favorite_mapping_refuses_to_guess():
    raws={'1':{'id':1,'a':4,'b':4,'c':2,'d':0,'organization':{'id':5}}}
    samples=[{'id':'1','price':'0','organizationId':'5','typeId':'4','setupId':'2'}]
    assert learn_favorite_mapping(samples,raws)=={}


def test_detail_pairs_and_validation():
    html='<form id="tenderDetailsForm"><table><tr><td>شماره فراخوان</td><td>2005</td><td>مبلغ</td><td>10 ریال</td></tr></table></form>'
    assert ['مبلغ','10 ریال'] in detail_pairs_from_html(html)
    assert looks_like_details(html,'1','2005')
    assert not looks_like_details('<form><input type="password"></form>','1','2005')


def test_redact_tokens():
    s=redact('a?csrf_token=abc123&x=1 jsessionid=XYZ '+'A'*40)
    assert 'abc123' not in s and 'XYZ' not in s and 'A'*40 not in s


def test_count_and_size_per_category_not_borrowed():
    html='''<form><a onclick="showAppendix('/x', null, '3193', '5', 'true')">اسناد فنی تعداد فایل 2 حجم فایل 1.2 MB</a>
            <a onclick="showAppendix('/x', null, '3192', '5', 'true')">شرایط</a></form>
            <table><tr><td><a onclick="showAppendix('/x', null, '7013', '5', 'true')">ارزیابی</a></td><td>تعداد فایل: ۴</td><td>حجم فایل: 300 KB</td></tr></table>'''
    g={x['document_type']:x for x in groups_from_html(html,'5')}
    assert g['3193']['count']==2 and g['3193']['size']=='1.2 MB'
    assert g['3192']['count'] is None and g['3192']['size']==''
    assert g['7013']['count']==4 and g['7013']['size']=='300 KB'


def test_templates_generalise_ids_and_drop_secrets():
    from app.connectors.setad.parsers import make_template, fill_template, file_rows_from_html, looks_like_file_list
    t=make_template('https://h/etend/appendix-list.action?documentId=5&documentType=3193&appendix_conversation=9&csrf_token=s')
    assert ['csrf_token','s'] not in t['query']
    path,q,_=fill_template(t,{},document_id=77,document_type=3194)
    assert dict(q)=={'documentId':'77','documentType':'3194','appendix_conversation':'9'}
    path,q,_=fill_template(t,{'appendix_conversation':'12'},document_id=1,document_type=2)
    assert dict(q)['appendix_conversation']=='12'
    rows=file_rows_from_html('<table><tr><td>نقشه.pdf</td><td><a href="/etend/appendix-download?appendixId=41&documentId=5">دانلود</a></td></tr></table>')
    assert rows[0]['appendix_id']=='41' and rows[0]['extension']=='pdf'
    assert looks_like_file_list({'records':1,'gridModel':[{'id':1,'showFileName':'a'}]})
    assert not looks_like_file_list({'records':1,'gridModel':[{'id':1,'title':'tender'}]})


def test_real_setad_appendix_list_shape():
    """Shape captured from a real etend.setadiran.ir recording (v0.2.1)."""
    from app.connectors.setad.parsers import file_rows_from_json, looks_like_file_list
    data={'advertise':'2','errorMessage':'','appendixList':[{'appendixState':None,'comment':'دستورالعمل ارزیابی کیفی',
          'createDate':'1405/07/29 14:37:16','documentId':675631,'fileExtention':'rar','fileName':'DastoramalArzyabiKeyfi',
          'fileSize':1009879,'id':9757252,'recCount':0,'version':1}]}
    assert looks_like_file_list(data)
    r=file_rows_from_json(data)[0]
    assert r['appendix_id']=='9757252' and r['display_name']=='DastoramalArzyabiKeyfi' and r['extension']=='rar'
    assert r['size']=='986 KB' and r['comment']=='دستورالعمل ارزیابی کیفی'
    assert looks_like_file_list({'advertise':'2','appendixList':[],'errorMessage':''})


def test_evaluation_download_page_openers():
    html="""<td onclick="showAppendix('/etend/appendix-openAppendix', null, '6287', '675631', 'true', 'reloadForm', null, 'reloadCsrfToken')">گزارش شناخت تعداد فایل 1 حجم فایل 11KB</td>
            <td onclick="showAppendix('/etend/appendix-openAppendix', null, '6288', '675631', 'true', 'reloadForm', null, 'reloadCsrfToken')">مستندات استعلام ارزیابی کیفی تعداد فایل 1 حجم فایل 986KB</td>"""
    g={x['document_type']:x for x in groups_from_html(html,'675631')}
    assert g['6287']['count']==1 and g['6287']['size']=='11KB' and g['6287']['title']=='گزارش شناخت'
    assert g['6288']['count']==1 and g['6288']['size']=='986KB'


def test_sync_issues_roundtrip():
    db=MemoryStore()
    db.add_tenders([{'id':5,'number':'N5','title':'T'}])
    run=db.start_sync(10,1)
    db.save_sync_issues(run,'duplicate',[('5',2,'1، 2')])
    assert db.issues[(run,'duplicate')]==[('5',2,'1، 2')]


def test_jalali_conversion():
    assert j2g(1405,7,29)==(2026,10,21)
    assert j2g(1404,1,1)==(2025,3,21)
    assert parse_jalali('۱۴۰۵/۰۸/۰۵ 14:00')==date(2026,10,27)
    assert days_left('1405/08/05',date(2026,10,21))==6
    assert days_left('خراب')is None


def test_site_titles_come_from_site_headers_first():
    assert site_title('number',{'number':'شماره فراخوان سایت'})=='شماره فراخوان سایت'
    assert site_title('price')=='مبلغ خرید اسناد'
    assert raw_label('typeName',{'typeName':'نوع (سایت)'})=='نوع (سایت)'
    assert raw_label('somethingInternalId') is None
    fa,tech=technical_fields('{"number":"1","tenderTypeId":4,"title":"x"}',{})
    assert [k for k,_ in fa]==['شماره فراخوان','عنوان'] and tech==[]   # internal ids hidden
    fa,tech=technical_fields('{"allSetupType":"ONE_PART","favoriteCount":null,"recCount":3664,"organization":{"id":7043},"foo":"x"}',{})
    assert fa==[('نوع برگزاری (مراحل)','یک‌مرحله‌ای')] and tech==[('foo','x')]


def test_group_pairs_sections():
    g=dict(group_pairs([['مبلغ تضمین','1'],['عنوان','x'],['مهلت ارسال','d'],['نشانی','y']]))
    assert 'مالی و تضمین' in g and 'زمان‌بندی' in g and 'دستگاه و تماس' in g and g['مشخصات فراخوان']==[('عنوان','x')]


def test_sync_extra_passes_recover_ids_with_other_page_sizes(tmp_path):
    """test_v03.py: the site "loses" id 7 whenever page size is 50 (unstable boundary), but shows it at size 30."""
    ids=list(range(1,11))
    class Fake:
        def capture(self):return {'records':10}
        def get_grid_page(self,page_number,page_size,extra=None):
            pool=[i for i in ids if not (page_size==50 and i==7)]
            chunk=pool[(page_number-1)*page_size:page_number*page_size]
            return {'records':10,'total':-(-10//page_size),'gridModel':[{'id':i,'number':str(i),'title':'t'} for i in chunk]}
    w=Worker(tmp_path);db=MemoryStore()
    w._sync(Fake(),db,50)
    assert len(db.list_tenders())==10
    assert db.last_sync()['status']=='کامل'


def test_unstable_pages_second_pass_recovers_missing_id(tmp_path):
    """test_sync_offline.py (no Qt stubs needed any more)."""
    class FakeBrowser:
        hits={1:0,2:0}
        def capture(self):return {'records':4}
        def get_grid_page(self,page_number,page_size,extra=None):
            self.hits[page_number]+=1
            vals=([1,2] if self.hits[1]==1 else [1,4]) if page_number==1 else [2,3]
            return {'page':page_number,'records':4,'total':2,'gridModel':
                    [{'id':v,'number':str(v),'title':'فراخوان '+str(v)} for v in vals]}
    worker=Worker(tmp_path)
    db=MemoryStore()
    browser=FakeBrowser()
    worker._sync(browser,db,50)
    assert len(db.list_tenders())==4
    assert db.last_sync()['status'].startswith('کامل')
    assert browser.hits[1]==2
