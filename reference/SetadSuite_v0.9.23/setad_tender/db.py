"""SQLite repository. All user decisions live separately from remotely refreshed tender rows."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def scalar(value):
    if value is None: return ''
    if isinstance(value, dict): return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list): return json.dumps(value, ensure_ascii=False)
    return str(value)

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=20, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA busy_timeout=10000')
        self.init()

    def init(self):
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS tenders (
            id TEXT PRIMARY KEY, number TEXT NOT NULL, title TEXT NOT NULL,
            type_name TEXT, province TEXT, city TEXT, organization TEXT,
            category TEXT, description TEXT, published TEXT,
            documents_deadline TEXT, proposal_deadline TEXT, opening_date TEXT,
            price TEXT, raw_json TEXT NOT NULL, content_hash TEXT NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 0,
            tracking_status TEXT NOT NULL DEFAULT 'جدید',
            priority TEXT NOT NULL DEFAULT 'عادی', note TEXT NOT NULL DEFAULT '',
            detail_text TEXT NOT NULL DEFAULT '', detail_updated TEXT,
            in_my_calls INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_tenders_number ON tenders(number);
        CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province);
        CREATE INDEX IF NOT EXISTS idx_tenders_organization ON tenders(organization);
        CREATE TABLE IF NOT EXISTS tender_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id TEXT NOT NULL, changed_at TEXT NOT NULL,
            old_json TEXT NOT NULL, new_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS groups (
            tender_id TEXT NOT NULL, document_type TEXT NOT NULL,
            title TEXT NOT NULL, reported_count INTEGER, reported_size TEXT,
            checked_at TEXT NOT NULL,
            PRIMARY KEY (tender_id, document_type)
        );
        CREATE TABLE IF NOT EXISTS files (
            tender_id TEXT NOT NULL, document_type TEXT NOT NULL,
            appendix_id TEXT NOT NULL, display_name TEXT NOT NULL,
            extension TEXT, size TEXT, comment TEXT, created TEXT,
            local_path TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'در انتظار',
            error TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL,
            PRIMARY KEY (tender_id, document_type, appendix_id)
        );
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL,
            finished TEXT, status TEXT NOT NULL, reported_count INTEGER,
            pages_total INTEGER, pages_done INTEGER NOT NULL DEFAULT 0,
            seen_unique INTEGER NOT NULL DEFAULT 0, duplicates INTEGER NOT NULL DEFAULT 0,
            errors TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id TEXT NOT NULL,
            action TEXT NOT NULL, at TEXT NOT NULL, result TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_issues (
            run_id INTEGER NOT NULL, kind TEXT NOT NULL, tender_id TEXT NOT NULL,
            occurrences INTEGER NOT NULL, pages TEXT NOT NULL,
            PRIMARY KEY (run_id, kind, tender_id)
        );
        CREATE TABLE IF NOT EXISTS workspace (
            tender_id TEXT PRIMARY KEY, stage INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '',
            margin_pct REAL NOT NULL DEFAULT 10, vat_pct REAL NOT NULL DEFAULT 10, other_costs REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '', updated TEXT
        );
        CREATE TABLE IF NOT EXISTS envelope_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id TEXT NOT NULL, envelope TEXT NOT NULL,
            title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'آماده نیست', file_path TEXT NOT NULL DEFAULT '',
            company_doc_id INTEGER, note TEXT NOT NULL DEFAULT '', sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_env_tender ON envelope_items(tender_id);
        CREATE TABLE IF NOT EXISTS company_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '', expires TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS guarantees (
            tender_id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT '', amount TEXT NOT NULL DEFAULT '',
            bank TEXT NOT NULL DEFAULT '', number TEXT NOT NULL DEFAULT '', issued TEXT NOT NULL DEFAULT '',
            valid_until TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'درخواست نشده',
            file_path TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id TEXT NOT NULL, supplier TEXT NOT NULL DEFAULT '',
            item TEXT NOT NULL DEFAULT '', qty REAL NOT NULL DEFAULT 1, unit_price REAL NOT NULL DEFAULT 0,
            chosen INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_quotes_tender ON quotes(tender_id);
        CREATE TABLE IF NOT EXISTS notes_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id TEXT NOT NULL,
            at TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL,
            note TEXT NOT NULL
        );
        ''')
        self._migrate('tenders','detail_json',"TEXT NOT NULL DEFAULT ''")
        self._migrate('tenders','site_state',"TEXT NOT NULL DEFAULT ''")
        self._migrate('tenders','site_state_name',"TEXT NOT NULL DEFAULT ''")
        for col in ('inquiry_deadline','last_edition_date','edition_no','site_type'):
            self._migrate('tenders',col,"TEXT NOT NULL DEFAULT ''")
        self._migrate('tenders','starred',"INTEGER NOT NULL DEFAULT 0")
        self._migrate('tenders','waived',"INTEGER NOT NULL DEFAULT 0")
        self._migrate('tenders','was_in_calls',"INTEGER NOT NULL DEFAULT 0")
        self.conn.execute("UPDATE tenders SET was_in_calls=1 WHERE in_my_calls=1 AND was_in_calls=0")
        self.conn.execute('''CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id TEXT NOT NULL, at TEXT NOT NULL,
            old_code TEXT NOT NULL DEFAULT '', new_code TEXT NOT NULL DEFAULT '',
            old_text TEXT NOT NULL DEFAULT '', new_text TEXT NOT NULL DEFAULT '')''')
        self._backfill_v06()
        self._migrate('groups','document_id',"TEXT NOT NULL DEFAULT ''")
        self._migrate('groups','opener',"TEXT NOT NULL DEFAULT ''")
        self._migrate('groups','method',"TEXT NOT NULL DEFAULT ''")
        self.conn.commit()

    def _backfill_v06(self):
        """Fill the v0.6 columns from the stored raw JSON for rows saved by older versions."""
        rows=self.conn.execute("SELECT id,raw_json FROM tenders WHERE inquiry_deadline='' AND last_edition_date='' AND edition_no=''").fetchall()
        upd=[]
        for r in rows:
            try:raw=json.loads(r['raw_json'])
            except ValueError:continue
            x=self.extra_fields(raw)
            if any(x.values()):upd.append((x['inquiry_deadline'],x['last_edition_date'],x['edition_no'],r['id']))
        if upd:self.conn.executemany('UPDATE tenders SET inquiry_deadline=?,last_edition_date=?,edition_no=? WHERE id=?',upd)

    @staticmethod
    def extra_fields(raw):
        ed=raw.get('lastTenderEdition') if isinstance(raw.get('lastTenderEdition'),dict) else {}
        no=scalar(ed.get('supplierNumber') or raw.get('lastTenderEdition.supplierNumber'))
        return {'inquiry_deadline':scalar(raw.get('inquiryDeadlineDate')),
                'last_edition_date':scalar(raw.get('supplierLastEditionDate')),
                'edition_no':no.strip()}

    def _migrate(self,table,column,decl):
        cols={r[1] for r in self.conn.execute(f'PRAGMA table_info({table})')}
        if column not in cols:
            self.conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')

    def meta(self,key,default=None):
        r=self.conn.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        if not r:return default
        try:return json.loads(r['value'])
        except ValueError:return default

    def set_meta(self,key,value):
        with self.conn:
            self.conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                              (key,json.dumps(value,ensure_ascii=False)))

    def raw_map(self,ids):
        ids=[str(x) for x in ids]
        if not ids:return {}
        q=','.join('?' for _ in ids)
        out={}
        for r in self.conn.execute(f'SELECT id,raw_json FROM tenders WHERE id IN ({q})',ids):
            try:out[r['id']]=json.loads(r['raw_json'])
            except ValueError:pass
        return out

    @staticmethod
    def tender_row(raw: dict) -> dict:
        org = raw.get('organization') or {}
        if not isinstance(org, dict): org = {}
        item_id = scalar(raw.get('id')).strip()
        if not item_id:
            raise ValueError('Tender has no internal id')
        # raw data is intentionally retained without assuming which 207 fields are populated
        stable = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
        # Do not treat a changing countdown value as a change in the tender itself.
        compare_raw = {k:v for k,v in raw.items() if k not in ('remainingTime','tenderEditionRemainingDeadline')}
        compare_blob = json.dumps(compare_raw, ensure_ascii=False, sort_keys=True, default=str)
        return {
            'id': item_id,
            'number': scalar(raw.get('number')),
            'title': scalar(raw.get('title')),
            'type_name': scalar(raw.get('typeName')),
            'province': scalar(raw.get('operationProvinceName')),
            'city': scalar(raw.get('operationCityName')),
            'organization': scalar(org.get('name') or raw.get('organization.name')),
            'category': scalar(raw.get('domainCatName') or raw.get('subjectClassification') or ''),
            'description': scalar(raw.get('domainsDescription')),
            'published': scalar(raw.get('publicNotificationDate')),
            'documents_deadline': scalar(raw.get('documentsDeadlineDate')),
            'proposal_deadline': scalar(raw.get('proposalDeadlineDate')),
            'opening_date': scalar(raw.get('openingDate')),
            'price': scalar(raw.get('tenderDocumentsPrice')),
            **Database.extra_fields(raw),
            'raw_json': stable,
            'content_hash': hashlib.sha256(compare_blob.encode('utf-8')).hexdigest(),
            'first_seen': now(), 'last_seen': now(),
        }

    def add_tenders(self, raws: Iterable[dict]) -> tuple[int,int,int]:
        added = updated = unchanged = 0
        cur = self.conn.cursor()
        for raw in raws:
            try: r = self.tender_row(raw)
            except (ValueError,AttributeError,TypeError): continue
            previous = cur.execute('SELECT content_hash,raw_json FROM tenders WHERE id=?', (r['id'],)).fetchone()
            if previous is None:
                fields = list(r)
                cur.execute(f"INSERT INTO tenders ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", [r[f] for f in fields])
                added += 1
            elif previous['content_hash'] != r['content_hash']:
                cur.execute('INSERT INTO tender_changes(tender_id,changed_at,old_json,new_json) VALUES (?,?,?,?)',
                            (r['id'], now(), previous['raw_json'], r['raw_json']))
                keys = [f for f in r if f != 'first_seen' and f != 'id']
                cur.execute('UPDATE tenders SET '+','.join(f'{k}=?' for k in keys)+' WHERE id=?',
                            [r[k] for k in keys] + [r['id']])
                updated += 1
            else:
                cur.execute('UPDATE tenders SET last_seen=? WHERE id=?', (now(),r['id']))
                unchanged += 1
        self.conn.commit()
        return added,updated,unchanged

    def list_tenders(self):
        return [dict(x) for x in self.conn.execute('''
            SELECT id,number,title,type_name,province,city,organization,category,
              description,published,documents_deadline,proposal_deadline,opening_date,price,
              inquiry_deadline,last_edition_date,edition_no,starred,site_state,site_state_name,site_type,waived,was_in_calls,
              selected,detail_updated,in_my_calls,last_seen,first_seen,
              (SELECT stage FROM workspace w WHERE w.tender_id=tenders.id) AS stage,
              (SELECT COUNT(*) FROM files f WHERE f.tender_id=tenders.id) AS file_count,
              (SELECT COUNT(*) FROM files f WHERE f.tender_id=tenders.id AND f.local_path<>'') AS downloaded_count
            FROM tenders ORDER BY published DESC, id DESC''')]

    def tender(self, tender_id):
        r = self.conn.execute('SELECT * FROM tenders WHERE id=?',(str(tender_id),)).fetchone()
        return dict(r) if r else None

    def select_many(self, ids, selected: bool):
        self.conn.executemany('UPDATE tenders SET selected=? WHERE id=?',
                              [(int(selected),str(x)) for x in ids])
        self.conn.commit()

    def save_tracking(self,tender_id,status,priority,note):
        with self.conn:
            self.conn.execute('UPDATE tenders SET tracking_status=?,priority=?,note=? WHERE id=?',
                              (status,priority,note,str(tender_id)))
            self.conn.execute('INSERT INTO notes_history(tender_id,at,status,priority,note) VALUES (?,?,?,?,?)',
                              (str(tender_id),now(),status,priority,note))

    def save_detail(self,tender_id,text,pairs=None):
        with self.conn:
            self.conn.execute('UPDATE tenders SET detail_text=?,detail_json=?,detail_updated=? WHERE id=?',
                              (text,json.dumps(pairs or [],ensure_ascii=False),now(),str(tender_id)))

    def save_groups(self,tender_id,groups,method=''):
        with self.conn:
            for g in groups:
                if not g.get('document_type'): continue
                self.conn.execute('''INSERT INTO groups(tender_id,document_type,title,reported_count,reported_size,checked_at,document_id,opener,method)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tender_id,document_type) DO UPDATE SET
                title=excluded.title,reported_count=excluded.reported_count,
                reported_size=excluded.reported_size,checked_at=excluded.checked_at,
                document_id=excluded.document_id,opener=excluded.opener,method=excluded.method''',
                (str(tender_id),str(g['document_type']),g.get('title',''),g.get('count'),g.get('size',''),now(),
                 str(g.get('document_id') or tender_id),g.get('opener') or '',method))

    def clear_groups(self,tender_id):
        with self.conn:
            self.conn.execute("DELETE FROM groups WHERE tender_id=? AND document_type NOT IN (SELECT document_type FROM files WHERE tender_id=?)",
                              (str(tender_id),str(tender_id)))

    def groups(self,tender_id):
        return [dict(x) for x in self.conn.execute('SELECT * FROM groups WHERE tender_id=? ORDER BY document_type', (str(tender_id),))]

    def save_files(self,tender_id,document_type,items):
        with self.conn:
            for f in items:
                if not f.get('appendix_id'): continue
                self.conn.execute('''INSERT INTO files(tender_id,document_type,appendix_id,display_name,extension,size,comment,created,checked_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tender_id,document_type,appendix_id) DO UPDATE SET
                display_name=excluded.display_name, extension=excluded.extension,
                size=excluded.size, comment=excluded.comment, created=excluded.created,
                checked_at=excluded.checked_at''',
                (str(tender_id),str(document_type),str(f['appendix_id']),
                 f.get('display_name',''),f.get('extension',''),f.get('size',''),
                 f.get('comment',''),f.get('created',''),now()))

    def files(self,tender_id):
        return [dict(x) for x in self.conn.execute('''SELECT f.*, COALESCE(g.title,f.document_type) AS group_title,
           COALESCE(NULLIF(g.document_id,''),f.tender_id) AS document_id
           FROM files f LEFT JOIN groups g ON f.tender_id=g.tender_id AND f.document_type=g.document_type
           WHERE f.tender_id=? ORDER BY group_title, display_name''',(str(tender_id),))]

    def set_file_result(self,tender_id,doc_type,file_id,path,state,error=''):
        with self.conn:
            self.conn.execute('UPDATE files SET local_path=?,state=?,error=? WHERE tender_id=? AND document_type=? AND appendix_id=?',
                              (str(path),state,error,str(tender_id),str(doc_type),str(file_id)))

    def reset_file_downloads(self,tender_id,keys=None):
        """v0.9.17: files are no longer on disk -> back to «not downloaded» (the site's file list stays). keys=[(doc_type,appendix_id)] or all."""
        with self.conn:
            if keys is None:
                self.conn.execute("UPDATE files SET local_path='',state='در انتظار',error='' WHERE tender_id=?",(str(tender_id),))
            else:
                for dt,fid in keys:
                    self.conn.execute("UPDATE files SET local_path='',state='در انتظار',error='' WHERE tender_id=? AND document_type=? AND appendix_id=?",
                                      (str(tender_id),str(dt),str(fid)))

    def set_my_calls(self,tender_id, yes=True):
        with self.conn:
            if yes:self.conn.execute('UPDATE tenders SET in_my_calls=1, was_in_calls=1, waived=0 WHERE id=?',(str(tender_id),))
            else:self.conn.execute('UPDATE tenders SET in_my_calls=0, was_in_calls=0 WHERE id=?',(str(tender_id),))

    def save_site_states(self,states):
        """«فراخوان‌های من» on the site: in_my_calls + the site's own status; others are cleared.
        Returns the list of status changes [(tender_id, old_text, new_text)] (also kept in status_history)."""
        changes=[]
        with self.conn:
            prev={r['id']:(r['site_state'],r['site_state_name']) for r in
                  self.conn.execute("SELECT id,site_state,site_state_name FROM tenders WHERE in_my_calls=1")}
            self.conn.execute("UPDATE tenders SET in_my_calls=0, site_state='', site_state_name='' WHERE in_my_calls=1 OR site_state<>''")
            for k,v in states.items():
                self.conn.execute('UPDATE tenders SET in_my_calls=1, was_in_calls=1, site_state=?, site_state_name=?, site_type=? WHERE id=?',
                                  (v.get('state',''),v.get('state_name',''),v.get('type',''),k))
                for col,key in (('opening_date','opening'),('inquiry_deadline','eval_deadline'),
                                ('proposal_deadline','proposal'),('last_edition_date','edition_date'),('edition_no','edition_no')):
                    if v.get(key):self.conn.execute(f'UPDATE tenders SET {col}=? WHERE id=?',(str(v[key]),k))
                old=prev.get(k)
                new=(v.get('state',''),v.get('state_name',''))
                if old is not None and old!=new:
                    changes.append((k,old[1] or old[0],new[1] or new[0]))
                    self.conn.execute('INSERT INTO status_history(tender_id,at,old_code,new_code,old_text,new_text) VALUES (?,?,?,?,?,?)',
                                      (k,now(),old[0],new[0],old[1],new[1]))
        return changes

    def set_waived(self,ids,on=True):
        """«صرف‌نظر» inside the app only (nothing on the site changes); restorable."""
        ids=[str(i) for i in ids]
        with self.conn:
            self.conn.executemany('UPDATE tenders SET waived=? WHERE id=?',[(int(bool(on)),i) for i in ids])

    def delete_work(self,tender_id):
        """«حذف کامل» inside the app: the tender's workspace, envelopes, quotes, guarantee and notes."""
        t=str(tender_id)
        with self.conn:
            for table in ('workspace','envelope_items','quotes','guarantees','notes_history'):
                try:self.conn.execute(f'DELETE FROM {table} WHERE tender_id=?',(t,))
                except sqlite3.OperationalError:pass
            self.conn.execute('UPDATE tenders SET waived=1, starred=0 WHERE id=?',(t,))

    def set_star(self,tender_id,on=True):
        with self.conn:
            self.conn.execute('UPDATE tenders SET starred=? WHERE id=?',(int(bool(on)),str(tender_id)))

    def status_history(self,tender_id):
        return [dict(r) for r in self.conn.execute('SELECT * FROM status_history WHERE tender_id=? ORDER BY id DESC',(str(tender_id),))]

    def set_my_calls_from_rows(self,rows):
        """Use the list's own favoriteCount (grey star on the site) as «in my calls»."""
        from .parsers import is_favorited
        pairs=[(1 if is_favorited(r) else 0,str(r['id'])) for r in rows
               if isinstance(r,dict) and r.get('id') is not None and 'favoriteCount' in r]
        if pairs:
            with self.conn:
                self.conn.executemany('UPDATE tenders SET in_my_calls=? WHERE id=?',pairs)
        return sum(p[0] for p in pairs)

    def set_my_calls_bulk(self,ids,clear_others=False):
        ids=[str(x) for x in ids]
        with self.conn:
            if clear_others:self.conn.execute('UPDATE tenders SET in_my_calls=0')
            self.conn.executemany('UPDATE tenders SET in_my_calls=1 WHERE id=?',[(i,) for i in ids])
        return len(ids)

    # --- tender workspace (v0.3) ---------------------------------------------------
    def ws(self,tender_id):
        r=self.conn.execute('SELECT * FROM workspace WHERE tender_id=?',(str(tender_id),)).fetchone()
        if r:return dict(r)
        return {'tender_id':str(tender_id),'stage':0,'decision':'','margin_pct':10.0,'vat_pct':10.0,'other_costs':0.0,'note':'','updated':None}

    def ws_save(self,tender_id,**fields):
        cur=self.ws(tender_id);cur.update(fields);cur['updated']=now()
        with self.conn:
            self.conn.execute('''INSERT INTO workspace(tender_id,stage,decision,margin_pct,vat_pct,other_costs,note,updated)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tender_id) DO UPDATE SET stage=excluded.stage,decision=excluded.decision,
              margin_pct=excluded.margin_pct,vat_pct=excluded.vat_pct,other_costs=excluded.other_costs,note=excluded.note,updated=excluded.updated''',
              (str(tender_id),int(cur['stage']),cur['decision'],float(cur['margin_pct']),float(cur['vat_pct']),
               float(cur['other_costs']),cur['note'],cur['updated']))

    def env_items(self,tender_id):
        return [dict(r) for r in self.conn.execute('SELECT * FROM envelope_items WHERE tender_id=? ORDER BY envelope,sort,id',(str(tender_id),))]

    def env_seed(self,tender_id,template):
        """template: {envelope: [titles]}. Seeds once per tender (never overwrites user edits)."""
        if self.env_items(tender_id):return False
        with self.conn:
            for env,titles in template.items():
                for i,t in enumerate(titles):
                    self.conn.execute('INSERT INTO envelope_items(tender_id,envelope,title,sort) VALUES(?,?,?,?)',(str(tender_id),env,t,i))
        return True

    def env_add(self,tender_id,envelope,title):
        with self.conn:
            n=self.conn.execute('SELECT COALESCE(MAX(sort),0)+1 FROM envelope_items WHERE tender_id=? AND envelope=?',(str(tender_id),envelope)).fetchone()[0]
            self.conn.execute('INSERT INTO envelope_items(tender_id,envelope,title,sort) VALUES(?,?,?,?)',(str(tender_id),envelope,title,n))

    def env_update(self,item_id,**fields):
        allowed={'title','status','file_path','company_doc_id','note'}
        sets=[(k,v) for k,v in fields.items() if k in allowed]
        if not sets:return
        with self.conn:
            self.conn.execute('UPDATE envelope_items SET '+','.join(f'{k}=?' for k,_ in sets)+' WHERE id=?',[v for _,v in sets]+[int(item_id)])

    def env_delete(self,item_id):
        with self.conn:self.conn.execute('DELETE FROM envelope_items WHERE id=?',(int(item_id),))

    def company_docs(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM company_docs ORDER BY category,title')]

    def company_doc_save(self,doc_id,title,category='',file_path='',expires='',note=''):
        with self.conn:
            if doc_id:
                self.conn.execute('UPDATE company_docs SET title=?,category=?,file_path=?,expires=?,note=? WHERE id=?',
                                  (title,category,file_path,expires,note,int(doc_id)));return int(doc_id)
            cur=self.conn.execute('INSERT INTO company_docs(title,category,file_path,expires,note) VALUES(?,?,?,?,?)',
                                  (title,category,file_path,expires,note));return cur.lastrowid

    def company_doc_delete(self,doc_id):
        with self.conn:
            self.conn.execute('UPDATE envelope_items SET company_doc_id=NULL WHERE company_doc_id=?',(int(doc_id),))
            self.conn.execute('DELETE FROM company_docs WHERE id=?',(int(doc_id),))

    def guarantee(self,tender_id):
        r=self.conn.execute('SELECT * FROM guarantees WHERE tender_id=?',(str(tender_id),)).fetchone()
        return dict(r) if r else {'tender_id':str(tender_id),'kind':'','amount':'','bank':'','number':'','issued':'',
                                  'valid_until':'','status':'درخواست نشده','file_path':'','note':''}

    def guarantee_save(self,tender_id,**f):
        cur=self.guarantee(tender_id);cur.update(f)
        with self.conn:
            self.conn.execute('''INSERT INTO guarantees(tender_id,kind,amount,bank,number,issued,valid_until,status,file_path,note)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tender_id) DO UPDATE SET kind=excluded.kind,amount=excluded.amount,
              bank=excluded.bank,number=excluded.number,issued=excluded.issued,valid_until=excluded.valid_until,
              status=excluded.status,file_path=excluded.file_path,note=excluded.note''',
              (str(tender_id),cur['kind'],cur['amount'],cur['bank'],cur['number'],cur['issued'],cur['valid_until'],
               cur['status'],cur['file_path'],cur['note']))

    def quotes(self,tender_id):
        return [dict(r) for r in self.conn.execute('SELECT * FROM quotes WHERE tender_id=? ORDER BY item,unit_price,id',(str(tender_id),))]

    def quote_save(self,tender_id,quote_id,supplier,item,qty,unit_price,chosen=0,note=''):
        with self.conn:
            if quote_id:
                self.conn.execute('UPDATE quotes SET supplier=?,item=?,qty=?,unit_price=?,chosen=?,note=? WHERE id=?',
                                  (supplier,item,qty,unit_price,int(chosen),note,int(quote_id)));return int(quote_id)
            cur=self.conn.execute('INSERT INTO quotes(tender_id,supplier,item,qty,unit_price,chosen,note) VALUES(?,?,?,?,?,?,?)',
                                  (str(tender_id),supplier,item,qty,unit_price,int(chosen),note));return cur.lastrowid

    def quote_delete(self,quote_id):
        with self.conn:self.conn.execute('DELETE FROM quotes WHERE id=?',(int(quote_id),))

    def workspace_summary(self):
        """tender_id -> (envelope done, envelope total) for the board/table."""
        out={}
        for r in self.conn.execute('''SELECT tender_id,COUNT(*) n,SUM(CASE WHEN status IN ('آماده','تحویل/آپلود شد') THEN 1 ELSE 0 END) d
                                      FROM envelope_items GROUP BY tender_id'''):
            out[r['tender_id']]=(r['d'] or 0,r['n'])
        return out

    def history(self,tender_id,limit=60):
        """Status changes on the site + actions done from the app, newest first."""
        t=str(tender_id);out=[]
        for r in self.conn.execute('SELECT at,old_text,new_text,old_code,new_code FROM status_history WHERE tender_id=?',(t,)):
            out.append({'at':r['at'],'kind':'site','text':f"وضعیت سایت: {r['old_text'] or r['old_code'] or '—'} ← {r['new_text'] or r['new_code']}"})
        for r in self.conn.execute('SELECT at,action,result,message FROM actions WHERE tender_id=?',(t,)):
            out.append({'at':r['at'],'kind':'app','text':f"{r['action']} — {r['result']}"+(f" ({r['message'][:120]})" if r['message'] else '')})
        out.sort(key=lambda x:x['at'],reverse=True)
        return out[:limit]

    def log_action(self,tender_id,action,result,message=''):
        with self.conn:
            self.conn.execute('INSERT INTO actions(tender_id,action,at,result,message) VALUES(?,?,?,?,?)',
                              (str(tender_id),action,now(),result,message[:1000]))

    def start_sync(self, reported, pages):
        cur=self.conn.execute('INSERT INTO sync_runs(started,status,reported_count,pages_total) VALUES (?,?,?,?)',
                              (now(),'در حال دریافت',reported,pages))
        self.conn.commit()
        return cur.lastrowid

    def sync_progress(self, run_id, page, unique, duplicates):
        with self.conn:
            self.conn.execute('UPDATE sync_runs SET pages_done=?,seen_unique=?,duplicates=? WHERE id=?',
                              (page,unique,duplicates,run_id))

    def finish_sync(self,run_id,status,errors):
        with self.conn:
            self.conn.execute('UPDATE sync_runs SET finished=?,status=?,errors=? WHERE id=?',
                              (now(),status,errors[:8000],run_id))

    def last_sync(self):
        r=self.conn.execute('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1').fetchone()
        return dict(r) if r else None

    def stats(self):
        st=dict(self.conn.execute('''SELECT COUNT(*) total,
         SUM(CASE WHEN selected=1 THEN 1 ELSE 0 END) selected,
         SUM(CASE WHEN in_my_calls=1 THEN 1 ELSE 0 END) my_calls,
         SUM(CASE WHEN detail_updated IS NOT NULL THEN 1 ELSE 0 END) detailed
         FROM tenders''').fetchone())
        f=self.conn.execute('''SELECT COUNT(DISTINCT tender_id) tenders, COUNT(*) files,
         SUM(CASE WHEN local_path<>'' THEN 1 ELSE 0 END) downloaded FROM files''').fetchone()
        st.update(with_docs=f['tenders'] or 0,files=f['files'] or 0,downloaded=f['downloaded'] or 0)
        return st

    # --- sync quality: duplicate / recovered ids ---------------------------------
    def save_sync_issues(self,run_id,kind,items):
        with self.conn:
            self.conn.executemany('INSERT OR REPLACE INTO sync_issues(run_id,kind,tender_id,occurrences,pages) VALUES(?,?,?,?,?)',
                [(run_id,kind,str(tid),int(n),pages) for tid,n,pages in items])

    def sync_runs(self,limit=30):
        return [dict(r) for r in self.conn.execute('''SELECT r.*,
           (SELECT COUNT(*) FROM sync_issues i WHERE i.run_id=r.id AND i.kind='duplicate') dup_ids,
           (SELECT COUNT(*) FROM sync_issues i WHERE i.run_id=r.id AND i.kind='recovered') rec_ids
           FROM sync_runs r ORDER BY r.id DESC LIMIT ?''',(limit,))]

    def sync_issues(self,run_id,kind):
        return [dict(r) for r in self.conn.execute('''SELECT i.tender_id,i.occurrences,i.pages,
           COALESCE(t.number,'') number,COALESCE(t.title,'') title,COALESCE(t.organization,'') organization,
           COALESCE(t.province,'') province
           FROM sync_issues i LEFT JOIN tenders t ON t.id=i.tender_id
           WHERE i.run_id=? AND i.kind=? ORDER BY i.occurrences DESC, t.number''',(run_id,kind))]

    def close(self):
        self.conn.close()
