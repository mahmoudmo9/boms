from datetime import date
from pathlib import Path
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from setad_tender.dates import j2g, parse_jalali, days_left
from setad_tender import workspace as W
from setad_tender.db import Database
from setad_tender.parsers import site_title, group_pairs, raw_label, technical_fields


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


def test_offer_calculation_and_blockers():
    q=[{'item':'پمپ','supplier':'A','qty':2,'unit_price':100,'chosen':0},{'item':'پمپ','supplier':'B','qty':2,'unit_price':90,'chosen':0},
       {'item':'لوله','supplier':'C','qty':10,'unit_price':5,'chosen':1}]
    r=W.calc_offer(q,10,10,20)
    assert r['cost']==250 and round(r['total'],2)==302.5 and r['lines'][0]['supplier']=='B'
    items=[{'envelope':'الف','title':'ضمانت','status':'آماده'},{'envelope':'ب','title':'x','status':'آماده نیست'}]
    bl=W.blockers(items,{'status':'درخواست شد','valid_until':'1405/08/01'},date(2026,10,21),'1405/08/10')
    assert any('پاکت ب' in b for b in bl) and any('تضمین هنوز' in b for b in bl) and any('اعتبار تضمین' in b for b in bl)
    assert W.doc_expiry('1405/07/01',date(2026,10,21))[0]=='expired' and W.doc_expiry('1405/08/05',date(2026,10,21))[0]=='soon'


def test_workspace_db(tmp_path):
    db=Database(tmp_path/'w.db')
    assert db.env_seed('9',W.DEFAULT_TEMPLATE) and not db.env_seed('9',W.DEFAULT_TEMPLATE)
    items=db.env_items('9');assert {i['envelope'] for i in items}=={'الف','ب','ج'}
    db.env_update(items[0]['id'],status='آماده');assert W.envelope_progress(db.env_items('9'))['الف']==(1,1)
    doc=db.company_doc_save(None,'ISO','گواهینامه','', '1406/01/01')
    db.env_update(items[1]['id'],company_doc_id=doc);db.company_doc_delete(doc)
    assert db.env_items('9')[1]['company_doc_id'] is None
    db.guarantee_save('9',kind='چک تضمین',status='صادر شد');assert db.guarantee('9')['status']=='صادر شد'
    qid=db.quote_save('9',None,'A','پمپ',2,100,0);db.quote_save('9',qid,'A','پمپ',3,100,1)
    assert db.quotes('9')[0]['qty']==3
    db.ws_save('9',stage=3,margin_pct=15);assert db.ws('9')['stage']==3 and db.ws('9')['margin_pct']==15
    db.add_tenders([{'id':5,'number':'n','title':'t'},{'id':6,'number':'m','title':'u'}])
    db.set_my_calls_bulk(['5']);db.set_my_calls_bulk(['6'],clear_others=True)
    assert [t['in_my_calls'] for t in sorted(db.list_tenders(),key=lambda x:x['id'])]==[0,1]


def test_sync_extra_passes_recover_ids_with_other_page_sizes(tmp_path):
    from setad_tender.worker import Worker
    # the site "loses" id 7 whenever page size is 50 (unstable boundary), but shows it at size 30
    ids=list(range(1,11))
    class Fake:
        def capture(self):return {'records':10}
        def get_grid_page(self,page_number,page_size,extra=None):
            pool=[i for i in ids if not (page_size==50 and i==7)]
            chunk=pool[(page_number-1)*page_size:page_number*page_size]
            return {'records':10,'total':-(-10//page_size),'gridModel':[{'id':i,'number':str(i),'title':'t'} for i in chunk]}
    w=Worker(tmp_path);db=Database(tmp_path/'s.db')
    w._sync(Fake(),db,50)
    assert len(db.list_tenders())==10
    assert db.last_sync()['status']=='کامل'
