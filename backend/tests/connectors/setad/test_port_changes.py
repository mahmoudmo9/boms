"""The deliberate behaviour changes of the port (each one is listed in docs/SETAD_PORT.md)."""
import types

from app.connectors.setad import bridge
from app.connectors.setad.memory import MemoryStore
from app.connectors.setad.rows import TRACKED_FIELDS, tracked_changes, tender_row


def test_edge_first_then_chrome_with_a_persistent_profile(tmp_path, monkeypatch):
    tried = []

    class Chromium:
        def launch_persistent_context(self, user_data_dir, channel=None, **opts):
            tried.append((channel, user_data_dir, opts["headless"]))
            if channel != "chrome":
                raise RuntimeError(f"{channel} is not installed")
            return types.SimpleNamespace(pages=[], on=lambda *a: None, new_page=lambda: types.SimpleNamespace(
                url="about:blank", goto=lambda *a, **k: None))

    fake = types.SimpleNamespace(chromium=Chromium(), stop=lambda: None)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: types.SimpleNamespace(start=lambda: fake))
    profile = tmp_path / "connectors" / "setad" / "browser_profile"
    b = bridge.SetadBrowser(profile)
    b.open()
    assert [t[0] for t in tried] == ["msedge", "chrome"]          # Edge first; Chrome found second
    assert {t[1] for t in tried} == {str(profile)} and profile.is_dir()
    assert b.channel == "chrome" and tried[0][2] is False          # visible window for login and captcha


def test_volatile_list_metadata_is_not_a_change():
    """SetadSuite wrote a change row on almost every sync (recCount and other counters); BOMS does not."""
    raw = {"id": 9, "number": "2005000000000009", "title": "خرید لوله", "recCount": 3664, "favoriteCount": None,
           "documentsDeadlineDate": "1405/08/20 12:00:00"}
    db = MemoryStore()
    db.add_tenders([raw])
    assert db.add_tenders([{**raw, "recCount": 3700, "favoriteCount": 1, "remainingTime": "5"}]) == (0, 0, 1)
    assert db.changes == []
    assert db.add_tenders([{**raw, "documentsDeadlineDate": "1405/08/25 12:00:00"}]) == (0, 1, 0)
    assert [c[1] for c in db.changes] == ["documents_deadline"]


def test_only_tracked_fields_are_compared():
    a = tender_row({"id": 1, "number": "1", "title": "x", "recCount": 1})
    b = tender_row({"id": 1, "number": "1", "title": "x", "recCount": 2, "anyOtherField": "y"})
    assert tracked_changes(a, b) == []
    assert "recCount" not in TRACKED_FIELDS and "proposal_deadline" in TRACKED_FIELDS


def test_zero_document_price_is_free_not_unknown():
    """Free tenders (price 0) must stay 0: SetadSuite 0.9.2 treats an unknown price as NOT free."""
    assert tender_row({"id": 1, "tenderDocumentsPrice": 0.0})["document_price"] == "0.0"
    assert tender_row({"id": 1, "tenderDocumentsPrice": None})["document_price"] is None
    assert tender_row({"id": 1})["document_price"] is None
