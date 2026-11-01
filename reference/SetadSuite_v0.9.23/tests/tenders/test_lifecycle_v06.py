from datetime import date, timedelta
from setad_tender import lifecycle as LC
from setad_tender.dates import jalali_of
from setad_tender.db import Database

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


def test_db_fields_star_history(tmp_path):
    db = Database(tmp_path / 'a.db')
    raw = {'id': 674259, 'number': '2005', 'title': 't', 'inquiryDeadlineDate': '1405/08/23 19:00',
           'supplierLastEditionDate': '1405/07/30 13:46', 'lastTenderEdition': {'supplierNumber': 2}}
    db.add_tenders([raw])
    t = db.tender('674259')
    assert t['inquiry_deadline'].startswith('1405/08/23') and t['edition_no'] == '2'
    db.set_star('674259', True)
    assert db.tender('674259')['starred'] == 1
    assert db.save_site_states({'674259': {'state': 'ADD_TO_MY_FAVORITE', 'state_name': 'a', 'opening': '1405/08/25 10:00'}}) == []
    assert db.tender('674259')['opening_date'].startswith('1405/08/25')
    ch = db.save_site_states({'674259': {'state': 'IN_WATING_SENDING_PACKETS', 'state_name': 'b'}})
    assert ch == [('674259', 'a', 'b')] and len(db.status_history('674259')) == 1
