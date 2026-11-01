"""Offline smoke-test of unstable pagination without installing Qt in the test container."""
import importlib
import sys
import types
from pathlib import Path


def test_unstable_pages_second_pass_recovers_missing_id(tmp_path,monkeypatch):
    signals=[]
    class Signal:
        def __init__(self,*args):pass
        def emit(self,*args):signals.append(args)
    class QThread:
        def __init__(self,*args):pass
    pyside=types.ModuleType('PySide6')
    qt=types.ModuleType('PySide6.QtCore');qt.Signal=Signal;qt.QThread=QThread
    with monkeypatch.context() as m:
        m.setitem(sys.modules,'PySide6',pyside)
        m.setitem(sys.modules,'PySide6.QtCore',qt)
        sys.modules.pop('setad_tender.worker',None)
        from setad_tender.worker import Worker
        from setad_tender.db import Database
        class FakeBrowser:
            hits={1:0,2:0}
            def capture(self):return {'records':4}
            def get_grid_page(self,page_number,page_size,extra=None):
                self.hits[page_number]+=1
                vals=([1,2] if self.hits[1]==1 else [1,4]) if page_number==1 else [2,3]
                return {'page':page_number,'records':4,'total':2,'gridModel':
                        [{'id':v,'number':str(v),'title':'فراخوان '+str(v)} for v in vals]}
        worker=Worker(tmp_path)
        db=Database(tmp_path/'test.db')
        browser=FakeBrowser()
        worker._sync(browser,db,50)
        assert len(db.list_tenders())==4
        assert db.last_sync()['status'].startswith('کامل')
        assert browser.hits[1]==2
        db.close()
    sys.modules.pop('setad_tender.worker',None)
