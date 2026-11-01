"""v0.2: request learning helpers, favorite-argument learning, duplicates storage, redaction."""
from setad_tender.parsers import (groups_from_html, find_appendix_list_url, learn_favorite_mapping,
    favorite_args_from_raw, detail_pairs_from_html, looks_like_details, redact)
from setad_tender.db import Database


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


def test_sync_issues_roundtrip(tmp_path):
    db=Database(tmp_path/'t.db')
    db.add_tenders([{'id':5,'number':'N5','title':'T'}])
    run=db.start_sync(10,1)
    db.save_sync_issues(run,'duplicate',[('5',2,'1، 2')])
    rows=db.sync_issues(run,'duplicate')
    assert rows[0]['number']=='N5' and rows[0]['pages']=='1، 2'
    assert db.sync_runs()[0]['dup_ids']==1
    db.close()


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    path=tmp_path/'old.db'
    c=sqlite3.connect(path)
    c.execute("CREATE TABLE groups (tender_id TEXT NOT NULL, document_type TEXT NOT NULL, title TEXT NOT NULL, reported_count INTEGER, reported_size TEXT, checked_at TEXT NOT NULL, PRIMARY KEY (tender_id, document_type))")
    c.commit();c.close()
    db=Database(path)
    db.save_groups('1',[{'document_type':'3193','title':'x','document_id':'1','opener':'showAppendix()'}],'m')
    assert db.groups('1')[0]['opener']=='showAppendix()'
    db.close()


def test_count_and_size_per_category_not_borrowed():
    html='''<form><a onclick="showAppendix('/x', null, '3193', '5', 'true')">اسناد فنی تعداد فایل 2 حجم فایل 1.2 MB</a>
            <a onclick="showAppendix('/x', null, '3192', '5', 'true')">شرایط</a></form>
            <table><tr><td><a onclick="showAppendix('/x', null, '7013', '5', 'true')">ارزیابی</a></td><td>تعداد فایل: ۴</td><td>حجم فایل: 300 KB</td></tr></table>'''
    g={x['document_type']:x for x in groups_from_html(html,'5')}
    assert g['3193']['count']==2 and g['3193']['size']=='1.2 MB'
    assert g['3192']['count'] is None and g['3192']['size']==''
    assert g['7013']['count']==4 and g['7013']['size']=='300 KB'


def test_templates_generalise_ids_and_drop_secrets():
    from setad_tender.parsers import make_template, fill_template, file_rows_from_html, looks_like_file_list
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
    from setad_tender.parsers import file_rows_from_json, looks_like_file_list
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
