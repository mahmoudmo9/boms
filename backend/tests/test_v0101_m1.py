"""v0.10.1 milestone 1: the bugs of section 1, each with a test that failed before its fix."""
from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"

# Calls whose action is computed: file → every value it can take. A new computed call site fails the test until it is
# listed here (and labelled).
DYNAMIC = {
    "modules/catalog/service.py": {"archive", "unarchive"},
    "modules/tenders/results.py": {"result", "result_revised"},
    "modules/tenders/library.py": {"create", "update"},
    "modules/parties/service.py": {"archive", "unarchive", "method_archive", "method_unarchive"},
    "modules/finance/ratings.py": {"create", "update"},
    "modules/system/auth.py": {"login_failed", "unlock_failed", "password_change_failed"},
    "modules/system/jobs.py": {"failed", "retry"},
    "modules/system/backup.py": {"restore_test_ok", "restore_test_failed"},
    "modules/system/basedata.py": {"activate", "deactivate", "update"},
    "modules/listings/service.py": {"screen_star", "screen_unstar", "screen_reviewing", "screen_dismiss", "screen_restore",
                                    "screen_note", "screen_checklist", "add_my_call", "remove_my_call"},
    "modules/listings/store.py": {"detail_result", "download_result"},
    "modules/sourcing/coverage.py": {"select_offer", "unselect_offer"},
    "modules/sourcing/items.py": {"no_coverage", "no_coverage_clear"},
    "modules/execution/logistics.py": {"result", "update"},
}


def recorded_actions() -> tuple[dict[str, set[str]], list[str]]:
    """(action → entity types) for literal actions, and the computed call sites not listed in ``DYNAMIC``."""
    actions: dict[str, set[str]] = {}
    unlisted = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "record"
                    and getattr(node.func.value, "id", "") == "events" and len(node.args) >= 4):
                continue
            entity, action = node.args[1], node.args[3]
            entity_type = entity.value if isinstance(entity, ast.Constant) else "*"
            if isinstance(action, ast.Constant):
                actions.setdefault(action.value, set()).add(entity_type)
            elif rel in DYNAMIC:
                for value in DYNAMIC[rel]:
                    actions.setdefault(value, set()).add(entity_type)
            else:
                unlisted.append(f"{rel}:{node.lineno} {ast.unparse(action)}")
    return actions, unlisted


def test_every_event_kind_has_a_sentence_in_both_languages():
    actions, unlisted = recorded_actions()
    assert not unlisted, f"computed event actions not listed in DYNAMIC: {unlisted}"
    assert len(actions) > 150
    for lang in ("fa", "en"):
        events = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))["events"]
        missing = sorted(a for a in actions if a not in events["actions"])
        assert not missing, f"{lang}: event actions without a label: {missing}"
        no_subject = sorted(a for a in actions if "{{subject}}" not in events["actions"][a])
        assert not no_subject, f"{lang}: labels without the object: {no_subject}"
        nouns = {t for types in actions.values() for t in types if t != "*"}
        missing_nouns = sorted(t for t in nouns if t not in events["entities"])
        assert not missing_nouns, f"{lang}: entity types without a noun: {missing_nouns}"
        assert "{{subject}}" in events["generic"]


def test_case_events_name_the_child_record(client, db):
    from app.modules.events import service as events
    from app.modules.events.subjects import subjects

    case_id = uuid.uuid4()
    po_id = uuid.uuid4()
    e1 = events.record(db, "case", case_id, "purchase_order_add", {"purchase_order_id": str(po_id), "number": "PO-1405-0007"})
    e2 = events.record(db, "case", case_id, "update", {"changes": {}})
    first, second = subjects(db, [e1, e2])
    # the order no longer exists here, so the code comes from the event itself
    assert first == {"type": "purchase_order", "id": str(po_id), "code": "PO-1405-0007", "name": None}
    assert second["type"] == "case" and second["id"] == str(case_id)


def test_cash_tied_up_is_floored_per_deal_and_the_advance_kept_apart():
    """Section 1.4: one deal paid out 900 more than received, another received 400 more than paid out; before, the
    tile showed 500 («نقدینگی درگیر» netted across deals) and could go negative."""
    from app.modules.finance.overview import sum_positions

    a = {"USD": {"received": "100", "paid": "1000", "net_tied_up": "900"}}
    b = {"USD": {"received": "1000", "paid": "600", "net_tied_up": "-400"}, "IRR": {"received": "0", "paid": "0", "net_tied_up": "0"}}
    out = sum_positions([a, b])
    assert out["by_currency"] == [{"currency": "USD", "amount": "900"}]
    assert out["advance_by_currency"] == [{"currency": "USD", "amount": "400"}]
    assert out["cases"] == 1 and out["advance_cases"] == 1
    only_advance = sum_positions([b])
    assert only_advance["by_currency"] == []                       # never a negative «نقدینگی درگیر»


def test_rial_amounts_have_no_decimals_in_the_csv_export():
    """Section 1.5: a 30 % milestone of an IRR order of 717,249,998 is 215,174,999.4 (stored so); exports show the
    rial without decimals, other currencies as stored."""
    from decimal import Decimal

    from app.modules.finance.workspace import Csv

    csv = Csv("payments", "en", "gregorian")
    csv.add(paid_on="2026-11-12", direction="in", party="P", case="C", amount=Decimal("215174999.4000"), currency="IRR",
            fx_rate_to_base=None, base_amount=Decimal("215174999.4000"), reference="", allocated_to="", allocated_amount=None,
            unallocated=Decimal("0"))
    csv.add(paid_on="2026-11-12", direction="in", party="P", case="C", amount=Decimal("1373.5000"), currency="USD",
            fx_rate_to_base=Decimal("820000"), base_amount=Decimal("1126270000.4"), reference="", allocated_to="", allocated_amount=None,
            unallocated=None)
    text = csv.render().decode("utf-8-sig")
    assert "215174999.4" not in text and "215174999," in text
    assert "1373.5000" in text and "1126270000," in text


def test_shipment_status_follows_the_actual_dates(client, db):
    """Section 1.6: ATD means at least departed, ATA at least arrived, ATA never before ATD, and the status cannot
    move back behind the recorded dates. An old record that breaks the rule is flagged, not changed."""
    from datetime import date, timedelta

    from sqlalchemy import text

    from tests.test_execution_m3 import deal

    day = lambda n: (date.today() + timedelta(days=n)).isoformat()   # noqa: E731
    case, party, so, pos = deal(client)
    s = client.post("/api/shipments", json={"purchase_order_id": pos["USD"]["id"], "eta": day(20)}).json()
    assert s["status"] == "planned" and s["date_rule"]["conflicts"] == []

    r = client.patch(f"/api/shipments/{s['id']}", json={"atd": day(-2)})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_transit"                                   # suggested from the date and applied
    assert any(e["kind"] == "departed" for e in r.json()["events"])

    r = client.patch(f"/api/shipments/{s['id']}", json={"status": "planned"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "status_behind_dates"
    r = client.patch(f"/api/shipments/{s['id']}", json={"ata": day(-5)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ata_before_atd"
    r = client.patch(f"/api/shipments/{s['id']}", json={"ata": day(-1)})
    assert r.status_code == 200 and r.json()["status"] == "arrived"

    # an existing record that breaks the rule (as the v0.10.0 seed left one): flagged, still editable otherwise
    db.execute(text("UPDATE ops.shipment SET status = 'planned' WHERE id = :id"), {"id": s["id"]})
    db.commit()
    got = client.get(f"/api/shipments/{s['id']}").json()
    assert got["status"] == "planned" and got["date_rule"]["conflicts"] == ["status_behind_dates"]
    assert got["date_rule"]["suggested_status"] == "arrived"
    assert client.patch(f"/api/shipments/{s['id']}", json={"notes": "checked"}).status_code == 200


def test_a_delay_event_keeps_its_dates_as_dates(client):
    """Section 1.7: «ETA: 2026-12-07 → 2026-12-14» was stored as text and shown in Gregorian in the Persian UI; the
    event now carries the dates as fields and no generated text."""
    from datetime import date, timedelta

    from tests.test_execution_m3 import deal

    day = lambda n: (date.today() + timedelta(days=n)).isoformat()   # noqa: E731
    case, party, so, pos = deal(client)
    s = client.post("/api/shipments", json={"purchase_order_id": pos["USD"]["id"], "eta": day(10)}).json()
    got = client.patch(f"/api/shipments/{s['id']}", json={"eta": day(17)}).json()
    delay = next(e for e in got["events"] if e["kind"] == "delay")
    assert delay["note"] is None
    assert delay["details"] == {"field": "eta", "old": day(10), "new": day(17)}
