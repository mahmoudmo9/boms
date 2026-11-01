"""In-memory store with the `Database` interface the tender worker uses (SetadSuite v0.9.23 setad_tender/db.py).

Used by the connector tests (the ported SetadSuite tests ran against SQLite) and as the reference for the BOMS store
(app.modules.listings.store.ListingStore), which implements the same methods on PostgreSQL. Change tracking follows
the BOMS rule (rows.tracked_changes), not SetadSuite's whole-row hash.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .parsers import is_favorited
from .rows import tender_row, tracked_changes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self):
        self.tenders: dict[str, dict] = {}
        self.changes: list[tuple[str, str, object, object]] = []
        self.runs: list[dict] = []
        self.issues: dict[tuple[int, str], list] = {}
        self.meta_values: dict = {}
        self.actions: list[tuple] = []
        self.group_rows: dict[tuple[str, str], dict] = {}
        self.file_rows: dict[tuple[str, str, str], dict] = {}
        self.status_rows: list[tuple] = []

    # --- list rows ---------------------------------------------------------------------------------------
    def add_tenders(self, raws) -> tuple[int, int, int]:
        added = updated = unchanged = 0
        for raw in raws:
            try:
                row = tender_row(raw)
            except (ValueError, AttributeError, TypeError):
                continue
            tid = row["external_id"]
            old = self.tenders.get(tid)
            if old is None:
                self.tenders[tid] = {**row, "id": tid, "in_my_calls": 0, "site_state": "", "site_state_name": "",
                                     "first_seen": _now(), "last_seen": _now()}
                added += 1
                continue
            diffs = tracked_changes(old, row)
            for field, a, b in diffs:
                self.changes.append((tid, field, a, b))
            old.update(row)
            old["last_seen"] = _now()
            if diffs:
                updated += 1
            else:
                unchanged += 1
        return added, updated, unchanged

    def list_tenders(self):
        return [{"id": t["id"], "number": t.get("external_no", ""), **t} for t in self.tenders.values()]

    def tender(self, tender_id):
        t = self.tenders.get(str(tender_id))
        if t is None:
            return None
        import json
        return {**t, "number": t.get("external_no", ""), "raw_json": json.dumps(t.get("raw") or {}, ensure_ascii=False)}

    def raw_map(self, ids):
        return {str(i): self.tenders[str(i)]["raw"] for i in ids if str(i) in self.tenders}

    # --- «فراخوان‌های من» ----------------------------------------------------------------------------------
    def set_my_calls_from_rows(self, rows):
        n = 0
        for r in rows:
            if isinstance(r, dict) and r.get("id") is not None and "favoriteCount" in r and str(r["id"]) in self.tenders:
                on = 1 if is_favorited(r) else 0
                self.tenders[str(r["id"])]["in_my_calls"] = on
                n += on
        return n

    def set_my_calls(self, tender_id, yes=True):
        if str(tender_id) in self.tenders:
            self.tenders[str(tender_id)]["in_my_calls"] = 1 if yes else 0

    def set_my_calls_bulk(self, ids, clear_others=False):
        if clear_others:
            for t in self.tenders.values():
                t["in_my_calls"] = 0
        for i in ids:
            self.set_my_calls(i, True)
        return len(ids)

    def save_site_states(self, states):
        changes = []
        prev = {k: (t["site_state"], t["site_state_name"]) for k, t in self.tenders.items() if t["in_my_calls"]}
        for t in self.tenders.values():
            if t["in_my_calls"] or t["site_state"]:
                t.update(in_my_calls=0, site_state="", site_state_name="")
        for k, v in states.items():
            t = self.tenders.get(k)
            if t is None:
                continue
            t.update(in_my_calls=1, site_state=v.get("state", ""), site_state_name=v.get("state_name", ""))
            old, new = prev.get(k), (v.get("state", ""), v.get("state_name", ""))
            if old is not None and old != new:
                changes.append((k, old[1] or old[0], new[1] or new[0]))
                self.status_rows.append((k, old, new))
        return changes

    # --- sync runs -----------------------------------------------------------------------------------------
    def start_sync(self, reported, pages):
        self.runs.append({"id": len(self.runs) + 1, "status": "در حال اجرا", "reported_count": reported,
                          "pages_total": pages, "pages_done": 0, "seen_unique": 0, "duplicates": 0, "errors": ""})
        return len(self.runs)

    def sync_progress(self, run_id, page, unique, duplicates):
        self.runs[run_id - 1].update(pages_done=page, seen_unique=unique, duplicates=duplicates)

    def finish_sync(self, run_id, status, errors):
        self.runs[run_id - 1].update(status=status, errors=errors, finished=_now())

    def last_sync(self):
        return self.runs[-1] if self.runs else None

    def save_sync_issues(self, run_id, kind, items):
        self.issues[(run_id, kind)] = list(items)

    # --- meta, actions, details ------------------------------------------------------------------------------
    def meta(self, key, default=None):
        return self.meta_values.get(key, default)

    def set_meta(self, key, value):
        self.meta_values[key] = value

    def log_action(self, tender_id, action, result, message=""):
        self.actions.append((str(tender_id), action, result, message))

    def save_detail(self, tender_id, text, pairs=None):
        if str(tender_id) in self.tenders:
            self.tenders[str(tender_id)].update(detail_text=text, detail_pairs=pairs or [])

    # --- document groups and files ---------------------------------------------------------------------------
    def save_groups(self, tender_id, groups, method=""):
        for g in groups:
            if g.get("document_type"):
                self.group_rows[(str(tender_id), str(g["document_type"]))] = {**g, "method": method,
                                                                             "document_type": str(g["document_type"])}

    def clear_groups(self, tender_id):
        keep = {k[1] for k in self.file_rows if k[0] == str(tender_id)}
        for k in [k for k in self.group_rows if k[0] == str(tender_id) and k[1] not in keep]:
            del self.group_rows[k]

    def groups(self, tender_id):
        return [g for (t, _), g in sorted(self.group_rows.items()) if t == str(tender_id)]

    def save_files(self, tender_id, document_type, items):
        for f in items:
            if not f.get("appendix_id"):
                continue
            key = (str(tender_id), str(document_type), str(f["appendix_id"]))
            old = self.file_rows.get(key, {"local_path": "", "state": "در انتظار", "error": ""})
            self.file_rows[key] = {**old, **f, "document_type": str(document_type), "appendix_id": str(f["appendix_id"])}

    def files(self, tender_id):
        out = []
        for (t, dt, _), f in sorted(self.file_rows.items()):
            if t != str(tender_id):
                continue
            g = self.group_rows.get((t, dt), {})
            out.append({**f, "group_title": g.get("title") or dt, "document_id": g.get("document_id") or t})
        return out

    def set_file_result(self, tender_id, doc_type, file_id, path, state, error=""):
        key = (str(tender_id), str(doc_type), str(file_id))
        if key in self.file_rows:
            self.file_rows[key].update(local_path=str(path), state=state, error=error)
