"""The Setad agent: ``python -m app.connectors.setad.agent``.

Runs in the owner's desktop session so its Edge/Chrome window is visible (login, role, captcha). Started on demand
by the backend ("Connect to Setad"); one instance only (lock file in the data folder); exits after
``setad.agent_idle_minutes`` without commands or on "Disconnect".

Commands come from ``sys.job`` lane ``setad`` (the normal worker never takes that lane, so a long fetch or a captcha
wait never delays backups). All browser calls happen on this process's main thread (Playwright's sync API); a small
thread writes the heartbeat into ``ext.agent_status`` and picks up a cancel request. The connector never writes
tables itself: everything goes through ``app.modules.listings.store.ListingStore``.

Environment for tests / the offline browser check only: BOMS_SETAD_HEADLESS=1, BOMS_SETAD_FAKE=<module with
install(context)> (routes every Setad request to a local fake site; any other request goes to a dead proxy).
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

from app.connectors.setad.bridge import SetadBrowser, SiteError, friendly_error
from app.connectors.setad.eproc_engine import BrowserEngine
from app.connectors.setad.eproc_parser import Need
from app.connectors.setad.parsers import redact
from app.connectors.setad.rows import SOURCE_PURCHASE, SOURCE_TENDER
from app.connectors.setad.tenders import Worker
from app.core.db import new_session
from app.core.time import utcnow

log = logging.getLogger("boms.setad_agent")
HEARTBEAT_SECONDS = 2.0
QUICK_TENDER_PAGES = 20


# ---- single instance ---------------------------------------------------------------------------------------------

class InstanceLock:
    """An OS file lock held for the agent's lifetime (released automatically if the process dies)."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")  # noqa: SIM115
        try:
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(str(os.getpid()))
        self.fh.flush()
        return True

    def release(self) -> None:
        if self.fh is not None:
            try:
                if os.name != "nt":
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None


# ---- status row ----------------------------------------------------------------------------------------------------

DOWNLOAD_KEYS = ("downloaded", "skipped", "failed", "restricted", "no_files")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
FILE_PROGRESS = re.compile(r"پیوست\s*(\d+)\s*/\s*(\d+)")


def setup_logging(path: Path) -> logging.Handler:
    """v0.6.0: INFO log of the engine's and the tender worker's messages, rotated at 5 MB x 3 (secrets redacted
    before they are written)."""
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


LAUNCH_FAILED = "مرورگر قابل اجرا پیدا نشد"   # bridge.SetadBrowser.open when no channel could be launched


def status_text(text) -> str:
    """v0.6.0: a launch failure keeps its own text (with the per-channel errors); only a real close of the window
    reads «پنجره مرورگر ستاد بسته شد». Playwright's per-channel launch errors often contain "has been closed", which
    made friendly_error() report a closed window when the browser had never opened."""
    text = str(text or "")
    return text if LAUNCH_FAILED in text else friendly_error(text)


class Status:
    """ext.agent_status writer (no secrets: messages pass through the connector's redact())."""

    def __init__(self, session_factory=new_session):
        self.session = session_factory
        self.lock = threading.Lock()

    def set(self, **values) -> None:
        from app.modules.listings.store import write_agent_status

        for key in ("message", "last_error", "captcha_message"):
            if values.get(key):
                values[key] = redact(status_text(values[key]))[:1000]
        with self.lock:
            write_agent_status(self.session, **values)

    def cancel_requested(self) -> bool:
        from app.modules.listings.store import agent_cancel_requested

        return agent_cancel_requested(self.session)


# ---- the agent ------------------------------------------------------------------------------------------------------

class Agent:
    def __init__(self, data_dir: Path, browser: SetadBrowser | None = None, session_factory=new_session,
                 status: Status | None = None):
        from app.modules.listings.store import ListingStore

        self.data_dir = Path(data_dir)
        self.dir = self.data_dir / "connectors" / "setad"
        self.session = session_factory
        self.status = status or Status(session_factory)
        self.cancel = threading.Event()
        self.store = ListingStore(session_factory, self.dir)
        self.store.on_progress = lambda v: self.status.set(pages_done=v.get("pages_done"), pages_total=v.get("pages_total"),
                                                           rows_seen=v.get("rows_seen"))
        self.browser = browser or self._make_browser()
        self.browser.on_role = lambda role: self.status.set(role=role)
        self.engine = BrowserEngine(self.browser, self._purchase_event, self.cancel, self.dir)
        if os.environ.get("BOMS_SETAD_FAKE"):
            # the engine's hidden download browser is a second browser outside the fake host's routes: never use it
            # offline (downloads then run in the routed window, SetadSuite's own fallback)
            def _no_background():
                raise RuntimeError("offline fake host")
            self.engine._make_background_page = _no_background
        self.worker = Worker(self.dir, self.cancel)
        self.worker.message.connect(self._worker_message)
        self.worker.progress.connect(lambda p, t, u, r: self.status.set(pages_done=p, pages_total=t, rows_seen=u))
        self.worker.result.connect(self._tender_result)
        self._events: list[tuple[str, dict]] = []
        self.stop = False
        self.job_tag = "-"            # "<job id> <command>" prefix of log lines (the UI filters the log by job)
        if not os.environ.get("BOMS_SETAD_FAKE"):
            make_background = self.engine._make_background_page

            def _logged_background():
                try:
                    return make_background()
                except Exception:
                    # the hidden download browser could not start: say why (the visible window is used instead)
                    self.log("hidden download browser failed: " + traceback.format_exc().strip().splitlines()[-1])
                    raise
            self.engine._make_background_page = _logged_background

    def _make_browser(self) -> SetadBrowser:
        fake = os.environ.get("BOMS_SETAD_FAKE")
        extra, hook = {}, None
        if fake:
            hook = importlib.import_module(fake).install
            extra = {"proxy": {"server": "http://127.0.0.1:9"}}   # nothing unrouted can leave the machine
        channels = None if not fake else (None,)
        return SetadBrowser(self.dir / "browser_profile", headless=os.environ.get("BOMS_SETAD_HEADLESS") == "1",
                            channels=channels, launch_extra=extra, on_context=hook)

    # -- events from the ported code -------------------------------------------------------------------------------
    def log(self, message: str, level: int = logging.INFO) -> None:
        log.log(level, "%s %s", self.job_tag, redact(str(message)).replace("\n", " | ")[:2000])

    def _worker_message(self, message: str) -> None:
        self.log(message)
        self.status.set(message=message)

    def _purchase_event(self, kind: str, values: dict) -> None:
        self._events.append((kind, values))
        if kind in ("info", "progress", "error", "status", "completed_download", "completed_refresh"):
            text = values.get("message") or values.get("status") or (values.get("results") if kind.startswith("completed") else "")
            self.log(f"{kind}: {values.get('need_no', '')} {text}".strip(), logging.WARNING if kind == "error" else logging.INFO)
        if kind == "progress":
            m = FILE_PROGRESS.search(values.get("message") or "")
            if m:
                self.status.set(files_done=int(m.group(1)), files_total=int(m.group(2)))
        if kind == "needs":
            needs = values.get("needs") or []
            self.store.upsert_needs(needs)
            self._rows_seen = getattr(self, "_rows_seen", 0) + len(needs)
            self.store.progress(pages_done=values.get("pages"), pages_total=values.get("expected"),
                                rows_seen=self._rows_seen, duplicates=values.get("duplicates"))
        elif kind == "captcha":
            self.status.set(captcha_waiting=True, captcha_message=values.get("message"))
        elif kind == "captcha_done":
            self.status.set(captcha_waiting=False, captcha_message=None)
        elif kind in ("info", "progress", "status"):
            self.status.set(message=values.get("message") or values.get("status"))
        elif kind == "error":
            self.status.set(last_error=values.get("message"))
        elif kind == "connected":
            self.status.set(connected=True, role="EPROC", browser_channel=self.browser.channel)

    def _tender_result(self, kind: str, data) -> None:
        self._events.append((f"tender:{kind}", data if isinstance(data, dict) else {}))
        if kind == "browser_closed":
            self.status.set(connected=False, role=None)
        elif kind == "check":
            self.status.set(connected=True, role="ETEND", browser_channel=self.browser.channel)

    def _errors(self) -> list[str]:
        return [v.get("message", "") for k, v in self._events if k == "error"]

    # -- commands ----------------------------------------------------------------------------------------------------
    def _open(self) -> None:
        if self.browser.context is None or not self.browser.alive():
            self.status.set(message=self.browser.open())
            self.status.set(browser_channel=self.browser.channel)

    def cmd_connect(self, p: dict) -> dict:
        self._open()
        if p.get("role") == "ETEND":
            self.worker._connect(self.browser, self.store, {"timeout": 900, "minimize": True})
        else:
            self.engine.handle({"command": "launch"})
            if self._errors():
                raise SiteError(self._errors()[-1])
        return {"role": self.browser.role}

    def cmd_set_role(self, p: dict) -> dict:
        self._open()
        self.worker._dispatch("set_role", {"role": p.get("role") or "EPROC"}, self.browser, self.store)
        return {"role": self.browser.role}

    def _purchase_fetch(self, kind: str) -> dict:
        since = None
        if kind == "quick":
            since = self._quick_since()
            if since is None:
                raise SiteError("ابتدا یک‌بار «دریافت کامل» فراخوان‌های خرید را اجرا کنید تا فهرست پایه ساخته شود.")
        self._rows_seen = 0
        run_id = self.store.start_run(SOURCE_PURCHASE, kind)
        self.engine.handle({"command": "refresh", "mode": "search", "pages": 0, "since": since})
        errors = self._errors()
        done = [v for k, v in self._events if k == "completed_refresh"]
        status = ("cancelled" if self.cancel.is_set() else
                  "error" if errors and not getattr(self, "_rows_seen", 0) else
                  "needs_review" if errors or not done else "done")
        if done:
            self.store.progress(pages_done=done[-1].get("pages"), duplicates=done[-1].get("duplicates"))
        self.store.finish_run(status, "\n".join(errors))
        return {"run_id": str(run_id), "status": status}

    def _quick_since(self) -> str | None:
        from app.modules.listings.store import quick_since

        return quick_since(self.session)

    def _tender_fetch(self, kind: str) -> dict:
        if kind == "full":
            self.worker._guarded("sync", {"rows": 50}, self.browser, self.store)
            run = [d for k, d in self._events if k == "tender:sync"]
            return {"status": run[-1]["status"] if run else "?"}
        # quick: new tenders only — read pages until one brings nothing new (not in SetadSuite; see SETAD_PORT.md)
        self.browser.ensure_etend()
        run_id = self.store.start_run(SOURCE_TENDER, "quick")
        seen = 0
        errors = []
        try:
            for page in range(1, QUICK_TENDER_PAGES + 1):
                if self.cancel.is_set():
                    break
                data = self.browser.get_grid_page(page, 50)
                rows = data.get("gridModel") or []
                added, _changed, _same = self.store.add_tenders(rows)
                self.store.set_my_calls_from_rows(rows)
                seen += len(rows)
                self.store.progress(pages_done=page, pages_total=int(data.get("total") or 0), rows_seen=seen)
                if not rows or added == 0 or page >= int(data.get("total") or 0):
                    break
                time.sleep(0.2)
        except Exception as exc:
            errors.append(str(exc))
        status = "cancelled" if self.cancel.is_set() else ("error" if errors else "done")
        self.store.finish_run(status, "\n".join(errors))
        return {"run_id": str(run_id), "status": status}

    def cmd_full_fetch(self, p: dict) -> dict:
        return self._purchase_fetch("full") if p["source"] == SOURCE_PURCHASE else self._tender_fetch("full")

    def cmd_quick_fetch(self, p: dict) -> dict:
        return self._purchase_fetch("quick") if p["source"] == SOURCE_PURCHASE else self._tender_fetch("quick")

    def _listings(self, ids: list[str]):
        from app.modules.listings.store import listings_by_id

        return listings_by_id(self.session, ids)

    @staticmethod
    def _need(listing) -> Need:
        raw = listing.raw or {}
        return Need(**{k: str(raw.get(k, "")) for k in Need.__dataclass_fields__})

    def cmd_fetch_detail(self, p: dict) -> dict:
        ok, failed, listings = 0, [], []
        for listing in self._listings(p["listing_ids"]):
            if self.cancel.is_set():
                break
            self.status.set(listing_id=listing.id, files_done=None, files_total=None)
            before = len(failed)
            if listing.source == SOURCE_PURCHASE:
                self._events = []
                self.engine.handle({"command": "detail", "need": self._need(listing)})
                detail = next((v for k, v in self._events if k == "detail"), None)
                if detail and not detail.get("error"):
                    self.store.save_need_detail(listing.external_id, detail)
                    ok += 1
                else:
                    failed.append(listing.external_no)
            else:
                try:
                    self.worker._guarded("detail", {"id": listing.external_id}, self.browser, self.store)
                    ok += 1
                except Exception as exc:
                    failed.append(f"{listing.external_no}: {redact(str(exc))[:200]}")
            row = {"listing_id": str(listing.id), "external_no": listing.external_no,
                   "result": "failed" if len(failed) > before else "fetched", "failures": failed[before:]}
            listings.append(row)
            self.store.record_listing_result(listing.id, "detail_result", row)
        return {"ok": ok, "failed": failed, "listings": listings}

    def cmd_download_files(self, p: dict) -> dict:
        from app.modules.listings.service import files_dir

        with self.session() as db:
            root = files_dir(db)
        result: dict = {"ok": 0, "failed": [], "listings": [], "totals": dict.fromkeys(DOWNLOAD_KEYS, 0)}
        for listing in self._listings(p["listing_ids"]):
            if self.cancel.is_set():
                break
            self.status.set(listing_id=listing.id, files_done=None, files_total=None)
            if listing.source == SOURCE_PURCHASE:
                row = self._download_need(listing, root)
            else:
                row = self._download_tender(listing, root)
            result["listings"].append(row)
            for k in DOWNLOAD_KEYS:
                result["totals"][k] += row["counts"].get(k, 0)
            if row["result"] == "failed":
                result["failed"].append(f"{listing.external_no}: {'; '.join(row['failures'])[:300]}")
            else:
                result["ok"] += 1
            self.store.record_listing_result(listing.id, "download_result", row)
        return result

    def _download_need(self, listing, root: Path) -> dict:
        """One purchase call: the engine's own ``completed_download`` counts and failure messages (v0.6.0: was
        counted as ok whatever happened)."""
        self._events = []
        self.engine.handle({"command": "download", "needs": [self._need(listing)], "directory": str(root)})
        done = [v for k, v in self._events if k == "completed_download"]
        counts = dict.fromkeys(DOWNLOAD_KEYS, 0)
        counts.update((done[-1].get("results") or {}) if done else {})
        failures = [v.get("message", "") for k, v in self._events
                    if k == "info" and str(v.get("message", "")).startswith(("ناموفق", "نیاز "))]
        failures += self._errors()
        self.store.record_need_files(listing.external_id, root / listing.external_no)
        visible = any(k == "info" and "دانلود با مرورگر باز" in str(v.get("message", "")) for k, v in self._events)
        if visible:   # the hidden download browser was not available: put the Setad window away again
            self.browser.minimize()
            self.status.set(message="دانلود با پنجرهٔ ستاد انجام شد")
        state = ("failed" if not done or (counts["failed"] and not counts["downloaded"] and not counts["skipped"])
                 else "no_files" if counts["no_files"] else "partial" if counts["failed"] or counts["restricted"]
                 else "ok")
        return {"listing_id": str(listing.id), "external_no": listing.external_no, "result": state,
                "counts": counts, "failures": [redact(f)[:300] for f in failures], "visible_window": visible}

    def _download_tender(self, listing, root: Path) -> dict:
        counts = dict.fromkeys(DOWNLOAD_KEYS, 0)
        failures: list[str] = []
        try:
            self.worker._guarded("documents", {"id": listing.external_id}, self.browser, self.store)
            files = self.store.files(listing.external_id)
            keys = [[f["document_type"], f["appendix_id"]] for f in files]
            if not keys:
                counts["no_files"] = 1
            else:
                self.worker._guarded("download", {"id": listing.external_id, "file_keys": keys, "dest": str(root)},
                                     self.browser, self.store)
                states = self.store.file_states(listing.id)
                counts["downloaded"] = states.get("downloaded", 0)
                counts["failed"] = states.get("error", 0) + states.get("pending", 0) + states.get("missing", 0)
        except Exception as exc:
            failures.append(redact(str(exc))[:300])
            counts["failed"] += 1
        state = ("failed" if failures or (counts["failed"] and not counts["downloaded"]) else
                 "no_files" if counts["no_files"] else "partial" if counts["failed"] else "ok")
        return {"listing_id": str(listing.id), "external_no": listing.external_no, "result": state, "counts": counts,
                "failures": failures, "visible_window": False}

    def cmd_sync_my_calls(self, p: dict) -> dict:
        self.worker._guarded("my_calls", {}, self.browser, self.store)
        return {}

    def cmd_add_my_call(self, p: dict) -> dict:
        if p.get("confirmed") is not True:
            raise SiteError("تأیید صریح کاربر دریافت نشده است.")
        self.worker._guarded("favorite", {"id": p["external_id"], "confirmed": True}, self.browser, self.store)
        return {}

    def cmd_remove_my_call(self, p: dict) -> dict:
        if p.get("confirmed") is not True:
            raise SiteError("تأیید صریح کاربر دریافت نشده است.")
        self.worker._guarded("unfavorite", {"id": p["external_id"], "confirmed": True}, self.browser, self.store)
        return {}

    def cmd_open_payment_page(self, p: dict) -> dict:
        """Opens the documents/payment page in the Setad window; paying is always done by the owner."""
        self.worker._guarded("payment", {"id": p["external_id"]}, self.browser, self.store)
        return {}

    def cmd_record_start(self, p: dict) -> dict:
        self._open()
        self.worker._dispatch("record_start", {}, self.browser, self.store)
        self.status.set(recording=True)
        return {}

    def cmd_record_stop(self, p: dict) -> dict:
        self.worker._dispatch("record_stop", {"version": p.get("version", "")}, self.browser, self.store)
        self.status.set(recording=False)
        saved = [d for k, d in self._events if k == "tender:record_stop"]
        return saved[-1] if saved else {}

    def cmd_disconnect(self, p: dict) -> dict:
        self.stop = True
        return {}

    # -- loop --------------------------------------------------------------------------------------------------------
    def run_job(self, job_id, job_type: str, payload: dict) -> None:
        from app.modules.system import jobs

        name = job_type.split(".", 1)[1]
        self.job_tag = f"{job_id} {name}"
        self.log(f"start {redact(json.dumps(payload, ensure_ascii=False, default=str))[:500]}")
        self._events = []
        self.cancel.clear()
        self.status.set(command=name, job_id=job_id, last_error=None, pages_done=None, pages_total=None,
                        rows_seen=None, captcha_waiting=False, captcha_message=None)
        try:
            handler = getattr(self, f"cmd_{name}")
            result = handler(payload)
            self.log(f"done {json.dumps(result, ensure_ascii=False, default=str)[:1500]}")
            with self.session() as db:
                jobs.mark_done(db, job_id, result)
                db.commit()
        except Exception as exc:
            message = status_text(exc)
            log.warning("setad command %s failed: %s", name, redact(message.splitlines()[0] if message else ""))
            self.status.set(last_error=message)
            with self.session() as db:
                jobs.mark_failed(db, job_id, redact(traceback.format_exc()), 30.0)
                db.commit()
        finally:
            self.status.set(command=None, job_id=None, captcha_waiting=False, captcha_message=None, listing_id=None,
                            files_done=None, files_total=None)
            self.job_tag = "-"

    def serve(self, idle_minutes: float | None = None, poll: float = 0.5) -> None:
        from app.modules.system import jobs, settings

        last_work = time.monotonic()
        with self.session() as db:
            jobs.requeue_stale(db, lane="setad")
            db.commit()
            idle = idle_minutes if idle_minutes is not None else settings.get(db, "setad.agent_idle_minutes")
        while not self.stop:
            with self.session() as db:
                job = jobs.claim_next(db, lane="setad")
                job_info = (job.id, job.type, dict(job.payload)) if job else None
            if job_info:
                self.run_job(*job_info)
                last_work = time.monotonic()
                continue
            try:
                self.worker._check_closed(self.browser)
                self.browser.tick()
            except Exception:
                pass
            if time.monotonic() - last_work > idle * 60:
                self.status.set(message="بدون فرمان؛ اتصال ستاد بسته شد.")
                break
            time.sleep(poll)

    def heartbeat(self, stop: threading.Event) -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                self.status.set(heartbeat_at=utcnow())
                if self.status.cancel_requested():
                    self.cancel.set()
            except Exception:
                pass

    def close(self) -> None:
        try:
            self.browser.close()
        except Exception:
            pass
        self.status.set(connected=False, role=None, command=None, captcha_waiting=False, heartbeat_at=None, pid=None)


def main() -> int:
    from app.core.config import get_config

    data_dir = get_config().data_dir
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    setup_logging(logs / "setad-agent.log")
    lock = InstanceLock(data_dir / "connectors" / "setad" / "agent.lock")
    if not lock.acquire():
        log.info("another Setad agent is running; exiting")
        return 3
    agent = Agent(data_dir)
    stop_beat = threading.Event()
    beat = threading.Thread(target=agent.heartbeat, args=(stop_beat,), daemon=True)
    try:
        agent.status.set(pid=os.getpid(), started_at=utcnow(), heartbeat_at=utcnow(), connected=False,
                         cancel_requested=False, last_error=None, message=None)
        beat.start()
        agent.serve()
        return 0
    finally:
        stop_beat.set()
        agent.close()
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
