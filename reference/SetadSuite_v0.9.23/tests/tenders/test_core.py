import json
from pathlib import Path
import pytest
from setad_tender.db import Database
from setad_tender.parsers import groups_from_html,file_rows_from_json,safe_name,content_is_html,details_from_html


def sample():
    return {
      'id':675227,'number':'2005000000123456','title':'عملیات آسفالت',
      'typeName':'مناقصه عمومی','operationProvinceName':'یزد','operationCityName':'تفت',
      'organization':{'id':4026,'name':'شهرداری نمونه'},
      'domainsDescription':'تأمین و اجرا','publicNotificationDate':'1405/07/28 20:00:00',
      'documentsDeadlineDate':'1405/08/08 12:00:00',
      'proposalDeadlineDate':'1405/08/18 12:00:00','remainingTime':'123'
    }

def test_db_preserves_user_selection_and_history(tmp_path):
    db=Database(tmp_path/'store.db')
    assert db.add_tenders([sample()])==(1,0,0)
    db.select_many(['675227'],True)
    db.save_tracking('675227','در حال استعلام','زیاد','تماس با تأمین‌کننده')
    raw=sample();raw['remainingTime']='122'
    assert db.add_tenders([raw])==(0,0,1) # volatile clock not a tender update
    raw['title']='عملیات آسفالت گرم'
    assert db.add_tenders([raw])==(0,1,0)
    current=db.tender('675227')
    assert current['selected']==1
    assert current['tracking_status']=='در حال استعلام'
    assert current['priority']=='زیاد'
    assert current['note']=='تماس با تأمین‌کننده'
    assert current['title']=='عملیات آسفالت گرم'
    assert db.conn.execute('SELECT COUNT(*) FROM tender_changes').fetchone()[0]==1
    db.close()


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


def test_document_tracking_persists(tmp_path):
    db=Database(tmp_path/'files.db');db.add_tenders([sample()])
    db.save_groups('675227',[{'document_type':'3193','title':'اسناد فنی','count':1,'size':'1.47MB'}])
    db.save_files('675227','3193',[{'appendix_id':'9750481','display_name':'Fanni11','extension':'pdf'}])
    db.set_file_result('675227','3193','9750481',str(tmp_path/'Fanni11.pdf'),'دریافت‌شده')
    files=db.files('675227')
    assert len(files)==1 and files[0]['group_title']=='اسناد فنی' and files[0]['state']=='دریافت‌شده'
    db.save_files('675227','3193',[{'appendix_id':'9750481','display_name':'Fanni11','extension':'pdf'}])
    assert db.files('675227')[0]['state']=='دریافت‌شده'
    db.close()
