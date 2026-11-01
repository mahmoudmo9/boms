"""Local SQLite store: needs, detail snapshots, the follow-up funnel, suppliers and RFQs.

Used only from the GUI thread.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import time
from pathlib import Path

from parser import Need
import pipeline

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS needs (
    need_no TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    deadline_at REAL,
    deadline_exact INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS details (
    need_no TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    need_no TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS case_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    need_no TEXT NOT NULL,
    at REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rfqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    need_no TEXT NOT NULL,
    supplier_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    sent_at REAL,
    responded_at REAL,
    data TEXT NOT NULL DEFAULT '{}',
    UNIQUE(need_no, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_needs_last_seen ON needs(last_seen);
CREATE INDEX IF NOT EXISTS idx_rfqs_need ON rfqs(need_no);
CREATE INDEX IF NOT EXISTS idx_rfqs_supplier ON rfqs(supplier_id);
"""


def _need_from(data: str) -> Need:
    d = json.loads(data)
    fields = {f.name for f in dataclasses.fields(Need)}
    return Need(**{k: d.get(k, "") for k in fields})


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.con.commit()
        self.cleanup_orphans()

    def cleanup_orphans(self) -> int:
        """Remove RFQs whose case no longer exists (left behind by older versions)."""
        cur = self.con.execute("DELETE FROM rfqs WHERE need_no NOT IN (SELECT need_no FROM cases)")
        self.con.commit()
        return cur.rowcount

    def close(self):
        try:
            self.con.commit()
            self.con.close()
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------ settings
    def get(self, key: str, default=None):
        row = self.con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return pipeline.DEFAULT_SETTINGS.get(key, default) if default is None else default
        return json.loads(row["value"])

    def set(self, key: str, value):
        self.con.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, json.dumps(value, ensure_ascii=False)))
        self.con.commit()

    def settings(self) -> dict:
        out = dict(pipeline.DEFAULT_SETTINGS)
        for row in self.con.execute("SELECT key, value FROM settings"):
            out[row["key"]] = json.loads(row["value"])
        return out

    # ------------------------------------------------------------ needs
    def upsert_needs(self, needs: list[Need], now: float | None = None) -> list[str]:
        """Insert/refresh needs from the board. Returns need numbers that were not known before."""
        now = now or time.time()
        new = []
        for n in needs:
            data = json.dumps(dataclasses.asdict(n), ensure_ascii=False)
            hours = pipeline.deadline_hours_from_text(n.response_deadline)
            estimate = now + hours * 3600 if hours is not None else None
            row = self.con.execute("SELECT deadline_exact FROM needs WHERE need_no=?", (n.need_no,)).fetchone()
            if row is None:
                new.append(n.need_no)
                self.con.execute(
                    "INSERT INTO needs(need_no, data, first_seen, last_seen, deadline_at, deadline_exact) VALUES(?,?,?,?,?,0)",
                    (n.need_no, data, now, now, estimate))
            elif row["deadline_exact"]:
                self.con.execute("UPDATE needs SET data=?, last_seen=? WHERE need_no=?", (data, now, n.need_no))
            else:
                self.con.execute("UPDATE needs SET data=?, last_seen=?, deadline_at=COALESCE(?, deadline_at) WHERE need_no=?",
                                 (data, now, estimate, n.need_no))
        self.con.commit()
        return new

    def needs_seen_since(self, since: float) -> list[Need]:
        rows = self.con.execute("SELECT data FROM needs WHERE last_seen >= ? ORDER BY rowid", (since,)).fetchall()
        return [_need_from(r["data"]) for r in rows]

    def get_need(self, need_no: str) -> Need | None:
        row = self.con.execute("SELECT data FROM needs WHERE need_no=?", (need_no,)).fetchone()
        return _need_from(row["data"]) if row else None

    def need_meta(self, need_nos: list[str] | None = None) -> dict[str, dict]:
        sql = "SELECT need_no, first_seen, last_seen, deadline_at, deadline_exact FROM needs"
        rows = self.con.execute(sql).fetchall() if need_nos is None else [
            r for chunk in _chunks(need_nos, 500)
            for r in self.con.execute(sql + f" WHERE need_no IN ({','.join('?' * len(chunk))})", chunk).fetchall()]
        return {r["need_no"]: dict(r) for r in rows}

    def set_exact_deadline(self, need_no: str, ts: float):
        self.con.execute("UPDATE needs SET deadline_at=?, deadline_exact=1 WHERE need_no=?", (ts, need_no))
        self.con.commit()

    # ------------------------------------------------------------ detail snapshots
    def save_detail(self, need_no: str, payload: dict):
        self.con.execute("INSERT INTO details(need_no, payload, fetched_at) VALUES(?,?,?) "
                         "ON CONFLICT(need_no) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
                         (need_no, json.dumps(payload, ensure_ascii=False), time.time()))
        self.con.commit()

    def get_detail(self, need_no: str) -> dict | None:
        row = self.con.execute("SELECT payload FROM details WHERE need_no=?", (need_no,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def details_for(self, need_nos: list[str]) -> dict[str, dict]:
        out = {}
        for chunk in _chunks(need_nos, 500):
            q = f"SELECT need_no, payload FROM details WHERE need_no IN ({','.join('?' * len(chunk))})"
            for r in self.con.execute(q, chunk):
                out[r["need_no"]] = json.loads(r["payload"])
        return out

    # ------------------------------------------------------------ cases
    def get_case(self, need_no: str) -> dict | None:
        row = self.con.execute("SELECT * FROM cases WHERE need_no=?", (need_no,)).fetchone()
        if not row:
            return None
        case = dict(row)
        case["data"] = json.loads(case["data"] or "{}")
        return case

    def cases(self, stages: set[str] | None = None) -> list[dict]:
        out = []
        for row in self.con.execute("SELECT * FROM cases ORDER BY updated_at DESC"):
            if stages is None or row["stage"] in stages:
                c = dict(row)
                c["data"] = json.loads(c["data"] or "{}")
                out.append(c)
        return out

    def case_stages(self) -> dict[str, str]:
        return {r["need_no"]: r["stage"] for r in self.con.execute("SELECT need_no, stage FROM cases")}

    def set_stage(self, need_no: str, stage: str, note: str | None = None):
        now = time.time()
        old = self.get_case(need_no)
        if old is None:
            self.con.execute("INSERT INTO cases(need_no, stage, created_at, updated_at, data) VALUES(?,?,?,?,'{}')",
                             (need_no, stage, now, now))
        else:
            self.con.execute("UPDATE cases SET stage=?, updated_at=? WHERE need_no=?", (stage, now, need_no))
        if old is None or old["stage"] != stage:
            text = f"مرحله: {pipeline.STAGE_TITLE.get(stage, stage)}"
            if note:
                text += f" — {note}"
            self.add_event(need_no, text, commit=False)
        self.con.commit()

    def update_case_data(self, need_no: str, **changes):
        case = self.get_case(need_no)
        if case is None:
            return
        data = case["data"]
        data.update(changes)
        self.con.execute("UPDATE cases SET data=?, updated_at=? WHERE need_no=?",
                         (json.dumps(data, ensure_ascii=False), time.time(), need_no))
        self.con.commit()

    def delete_case(self, need_no: str):
        """Remove a case completely, including its RFQs and history."""
        self.con.execute("DELETE FROM rfqs WHERE need_no=?", (need_no,))
        self.con.execute("DELETE FROM case_events WHERE need_no=?", (need_no,))
        self.con.execute("DELETE FROM cases WHERE need_no=?", (need_no,))
        self.con.commit()

    def case_has_work(self, need_no: str) -> bool:
        """True when deleting the case would lose something the user entered."""
        case = self.get_case(need_no)
        if case is None:
            return False
        d = case["data"]
        if self.con.execute("SELECT 1 FROM rfqs WHERE need_no=?", (need_no,)).fetchone():
            return True
        checks = d.get("checklist") or {}
        return bool((d.get("note") or "").strip() or (isinstance(checks, dict) and any(checks.values()))
                    or d.get("proforma") or d.get("submitted_at") or d.get("result"))

    def add_event(self, need_no: str, text: str, commit: bool = True):
        self.con.execute("INSERT INTO case_events(need_no, at, text) VALUES(?,?,?)", (need_no, time.time(), text))
        if commit:
            self.con.commit()

    def events(self, need_no: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT at, text FROM case_events WHERE need_no=? ORDER BY at DESC, id DESC", (need_no,))]

    # ------------------------------------------------------------ suppliers
    def suppliers(self) -> list[dict]:
        rows = self.con.execute("""
            SELECT s.*,
                   (SELECT COUNT(*) FROM rfqs r WHERE r.supplier_id = s.id) AS rfq_count,
                   (SELECT COUNT(*) FROM rfqs r WHERE r.supplier_id = s.id AND r.status = 'answered') AS answer_count,
                   (SELECT COUNT(*) FROM cases c WHERE json_extract(c.data, '$.final_rfq') IN
                        (SELECT id FROM rfqs r WHERE r.supplier_id = s.id)
                        AND json_extract(c.data, '$.result') = 'won') AS win_count
            FROM suppliers s ORDER BY s.name""").fetchall()
        return [dict(r) for r in rows]

    def get_supplier(self, sid: int) -> dict | None:
        row = self.con.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def save_supplier(self, sup: dict) -> int:
        cols = ("name", "contact", "phone", "email", "city", "tags", "note")
        values = [str(sup.get(c, "") or "").strip() for c in cols]
        if sup.get("id"):
            self.con.execute(f"UPDATE suppliers SET {', '.join(c + '=?' for c in cols)} WHERE id=?", (*values, sup["id"]))
            sid = int(sup["id"])
        else:
            cur = self.con.execute(f"INSERT INTO suppliers({', '.join(cols)}, created_at) VALUES({','.join('?' * len(cols))}, ?)",
                                   (*values, time.time()))
            sid = int(cur.lastrowid)
        self.con.commit()
        return sid

    def supplier_usage(self, sid: int) -> list[dict]:
        """RFQs of this supplier with their case stage and whether it is the chosen supplier there."""
        rows = self.con.execute("""SELECT r.id, r.need_no, c.stage, json_extract(c.data, '$.final_rfq') AS final_rfq
                                   FROM rfqs r LEFT JOIN cases c ON c.need_no = r.need_no
                                   WHERE r.supplier_id=?""", (sid,)).fetchall()
        return [{"rfq_id": r["id"], "need_no": r["need_no"], "stage": r["stage"],
                 "chosen": r["final_rfq"] == r["id"]} for r in rows]

    def delete_supplier(self, sid: int, with_rfqs: bool = False) -> bool:
        """Delete a supplier. With `with_rfqs`, its RFQs go too — except when it is the chosen
        supplier of an active case (that would break the case's pricing)."""
        usage = self.supplier_usage(sid)
        if usage and not with_rfqs:
            return False
        if any(u["chosen"] and u["stage"] in pipeline.STAGE_KEYS for u in usage):
            return False
        for u in usage:
            if u["chosen"]:
                case = self.get_case(u["need_no"])
                if case:
                    data = case["data"]
                    data["final_rfq"] = None
                    self.con.execute("UPDATE cases SET data=? WHERE need_no=?", (json.dumps(data, ensure_ascii=False), u["need_no"]))
        self.con.execute("DELETE FROM rfqs WHERE supplier_id=?", (sid,))
        self.con.execute("DELETE FROM suppliers WHERE id=?", (sid,))
        self.con.commit()
        return True

    def suggested_suppliers(self, group: str, exclude_need: str) -> list[dict]:
        """Suppliers that already quoted for needs of the same goods/service group, or are tagged with it."""
        if not group:
            return []
        out, seen = [], set()
        rows = self.con.execute("""
            SELECT s.*, COUNT(r.id) AS times, SUM(r.status='answered') AS answered
            FROM rfqs r JOIN suppliers s ON s.id = r.supplier_id JOIN needs n ON n.need_no = r.need_no
            WHERE r.need_no != ? AND (json_extract(n.data, '$.goods_group') = ? OR json_extract(n.data, '$.service_group') = ?)
            GROUP BY s.id ORDER BY answered DESC, times DESC""", (exclude_need, group, group)).fetchall()
        for r in rows:
            seen.add(r["id"])
            out.append(dict(r))
        for r in self.con.execute("SELECT * FROM suppliers WHERE tags LIKE ?", (f"%{group}%",)):
            if r["id"] not in seen:
                d = dict(r)
                d["times"] = 0
                d["answered"] = 0
                out.append(d)
        return out

    # ------------------------------------------------------------ RFQs
    def rfqs(self, need_no: str) -> list[dict]:
        rows = self.con.execute("""SELECT r.*, s.name AS supplier, s.phone, s.contact, s.email
                                   FROM rfqs r JOIN suppliers s ON s.id = r.supplier_id
                                   WHERE r.need_no=? ORDER BY r.id""", (need_no,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            out.append(d)
        return out

    def rfq_counts(self) -> dict[str, tuple[int, int]]:
        return {r["need_no"]: (r["n"], r["a"] or 0) for r in self.con.execute(
            "SELECT need_no, COUNT(*) AS n, SUM(status='answered') AS a FROM rfqs WHERE status != 'draft' GROUP BY need_no")}

    def add_rfq(self, need_no: str, supplier_id: int) -> int:
        cur = self.con.execute("INSERT OR IGNORE INTO rfqs(need_no, supplier_id, status, data) VALUES(?,?,'draft','{}')",
                               (need_no, supplier_id))
        self.con.commit()
        if cur.lastrowid and cur.rowcount:
            return int(cur.lastrowid)
        row = self.con.execute("SELECT id FROM rfqs WHERE need_no=? AND supplier_id=?", (need_no, supplier_id)).fetchone()
        return int(row["id"])

    def update_rfq(self, rfq_id: int, status: str | None = None, **data_changes):
        row = self.con.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
        if row is None:
            return
        data = json.loads(row["data"] or "{}")
        data.update(data_changes)
        sent_at, responded_at = row["sent_at"], row["responded_at"]
        if status == "sent" and not sent_at:
            sent_at = time.time()
        if status == "answered":
            responded_at = responded_at or time.time()
            sent_at = sent_at or responded_at
        self.con.execute("UPDATE rfqs SET status=?, sent_at=?, responded_at=?, data=? WHERE id=?",
                         (status or row["status"], sent_at, responded_at, json.dumps(data, ensure_ascii=False), rfq_id))
        self.con.commit()

    def delete_rfq(self, rfq_id: int):
        self.con.execute("DELETE FROM rfqs WHERE id=?", (rfq_id,))
        self.con.commit()


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
