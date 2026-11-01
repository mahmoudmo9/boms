from types import SimpleNamespace
import pytest
from setad_tender.bridge import SetadBrowser, SiteError, is_site_url, safe_page_label, JS_SOURCE

class FakeFrame:
    def __init__(self, url, grid=None, info=None):
        self.url=url
        self.grid=grid
        self.info=info or {'grid':False,'form':False,'loaded':'complete'}
        self.page=None
        self.used=[]
    def evaluate(self, script, args=None):
        self.used.append(script)
        if script==JS_SOURCE:return self.grid
        return self.info

class FakePage:
    def __init__(self,url,frames=None):
        self.url=url
        self.frames=frames or [FakeFrame(url)]
        for f in self.frames:f.page=self
        self.closed=False
        self.ctx=None
    def is_closed(self):return self.closed
    def wait_for_timeout(self,ms):
        # Like real Playwright: queued browser events are applied only during a call.
        if self.ctx:self.ctx.dispatch()

class FakeContext:
    def __init__(self,pages):
        self.pages=pages
        self.pending=[]
        for p in pages:p.ctx=self
    def dispatch(self):
        while self.pending:self.pending.pop(0)(self)
    def cookies(self):
        self.dispatch();return []

def browser_with(*pages):
    obj=SetadBrowser.__new__(SetadBrowser)
    obj.context=FakeContext(list(pages))
    obj.source=None
    obj.source_frame=None
    obj._closed=False
    obj.conv={}
    obj.trace=[]
    return obj


def test_login_in_new_tab_is_seen_after_pumping(monkeypatch):
    """Regression for v0.1.1: cached state still shows the SSO page; the grid tab
    only becomes visible once Playwright dispatches queued events."""
    monkeypatch.setattr('setad_tender.bridge.time.sleep',lambda _:None)
    sso=FakePage('https://sso.setadiran.ir/login')
    b=browser_with(sso)
    def user_logged_in(ctx):
        grid=FakeFrame('https://etend.setadiran.ir/etend/indexPage.action',grid=DATA)
        sso.url='https://etend.setadiran.ir/etend/indexPage.action'
        sso.frames=[grid];grid.page=sso
    b.context.pending.append(user_logged_in)
    assert b.capture()['records']==3580


def test_still_on_login_page_says_so(monkeypatch):
    monkeypatch.setattr('setad_tender.bridge.time.sleep',lambda _:None)
    b=browser_with(FakePage('https://sso.setadiran.ir/login?ticket=secret'))
    with pytest.raises(SiteError) as exc:b.capture()
    assert 'sso.setadiran.ir' in str(exc.value)
    assert 'secret' not in str(exc.value)

DATA={'url':'https://etend.setadiran.ir/etend/afterLoginCallMainPageCartable-search.action',
      'postData':{},'rows':5,'records':3580,'pages':716,'filters':{}}

def test_detects_newer_tender_tab_not_stale_home():
    grid=FakeFrame('https://etend.setadiran.ir/etend/indexPage.action',grid=DATA)
    active=FakePage('https://etend.setadiran.ir/etend/indexPage.action',frames=[grid])
    home=FakePage('https://etend.setadiran.ir/etend/indexPage.action')
    b=browser_with(active,home)
    result=b.capture()
    assert result['records']==3580
    assert b._target() is grid


def test_find_in_same_origin_iframe():
    main=FakeFrame('https://etend.setadiran.ir/etend/indexPage.action')
    sub=FakeFrame('https://etend.setadiran.ir/etend/frame.action',grid=DATA)
    b=browser_with(FakePage(main.url,frames=[main,sub]))
    assert b.capture()['records']==3580
    assert b._target() is sub


def test_missing_list_gives_actionable_message(monkeypatch):
    monkeypatch.setattr('setad_tender.bridge.time.sleep',lambda _:None)
    home=FakePage('https://etend.setadiran.ir/etend/indexPage.action')
    b=browser_with(home)
    with pytest.raises(SiteError,match='فراخوان‌ها') as exc:
        b.capture()
    assert 'مرورگر' in str(exc.value)


def test_not_attached_to_regular_browser(monkeypatch):
    monkeypatch.setattr('setad_tender.bridge.time.sleep',lambda _:None)
    b=browser_with(FakePage('https://login.example.org/sso?password=secret'))
    with pytest.raises(SiteError) as exc:b.capture()
    assert 'اختصاصی' in str(exc.value)
    assert 'secret' not in str(exc.value)


def test_host_and_diagnostics_safety():
    assert is_site_url('https://etend.setadiran.ir/etend/indexPage.action')
    assert not is_site_url('https://etend.setadiran.ir.attacker.example/path')
    assert not is_site_url('http://etend.setadiran.ir/etend/indexPage.action')
    assert 'secret' not in safe_page_label('https://etend.setadiran.ir/etend/indexPage.action?csrf_token=secret')
