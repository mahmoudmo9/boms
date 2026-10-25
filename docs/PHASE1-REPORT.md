# BOMS Phase 1 — Build Report

**Project:** BOMS, a single-user, bilingual (Persian/English) trading and order-management web app that runs offline on one Windows 10/11 PC.
**Scope of this report:** Phase 1 ("system skeleton"), built against the specification `boms-phase1-prompt-claude-code.md`.
**Repository:** `mahmoudmo9/boms`, branch `claude/admiring-lovelace-ykpanl` (no pull request opened).
**Status (short):** all four milestones are implemented and their automated tests pass in a Linux cloud container. **Nothing has been executed on Windows yet**: install, Task Scheduler, Credential Manager and the clean-PC restore are untested and have a manual checklist in `docs/OPERATIONS.md`.

---

## 1. Environment the work was done in (important for review)

- The code was written and tested by Claude Code in a **temporary Ubuntu 24.04 cloud container**, not on the user's Windows PC.
- That container had **PostgreSQL 16**, not 18, and its network proxy blocked every PostgreSQL 18 download source. With the user's approval, development and tests used PostgreSQL 16. The user's PC has PostgreSQL 18, which is what the installer targets.
- Python 3.12 venv, Node.js 22 for building the frontend.
- PowerShell scripts were linted with PowerShell 7.4 + PSScriptAnalyzer 1.23 (unpacked into a temp folder, used only for linting); they were **not executed on Windows**.
- With the user's approval, each milestone was committed and pushed (the spec said "never push"; the container is ephemeral, so work would otherwise be lost).

Commits:

| Commit | Content |
|---|---|
| `a7603d3` | Milestone 1: backend core, database, migrations, seed data, Persian normalization, events/audit |
| `a148dab` | Milestone 2: documents, global search, job runner/scheduler, backup and restore test |
| `a67bf5b` | Milestone 3: frontend shell, pages, i18n, themes; served by the backend |
| `8bd19ae` | Milestone 4: Windows scripts, wheelhouse/release builder, docs |
| `f8df8ae` | Fix: install/update stop early when not run from a built release folder |

---

## 2. Stack actually used

| Area | Choice (versions pinned) |
|---|---|
| Backend | Python 3.12, FastAPI 0.162, Uvicorn 0.54, SQLAlchemy 2.1 (typed ORM), Alembic 1.20, Pydantic 2.14 |
| DB driver | psycopg 3.3 (`psycopg[binary]`) |
| Database | PostgreSQL 18 on target (16 in dev), extensions `pg_trgm`, `unaccent` |
| Passwords | argon2-cffi (Argon2) |
| Secrets | `keyring` → Windows Credential Manager; environment variables on non-Windows dev machines |
| PDF text | PyMuPDF 1.28 (pinned `<2`, see deviations) |
| Encrypted archive | pyzipper (AES-256 zip) |
| Frontend | React 19.1, TypeScript 5.9, Vite 7.1, Tailwind CSS 4.1 (logical properties only), TanStack Query 5 + Table 8, react-router 7, i18next 25 / react-i18next 15 |
| Jalali dates | date-fns-jalali 4.1 |
| Font | Vazirmatn (Arabic-script subset), bundled woff2 via `@fontsource/vazirmatn` |
| Tests | pytest (backend), Vitest (frontend utilities + i18n) |
| Windows scripts | PowerShell 5.1-compatible `.ps1` + `.bat` wrappers |

---

## 3. What was built

### 3.1 Repository layout

```
backend/
  app/
    core/        config, secrets, db, dbadmin (superuser ops), errors, security, web (HTTP security
                 middleware), time, money, text (Persian normalization), files (content store), logs, modules
    modules/
      system/    user/auth, settings, base data, seed data, jobs service, backup/restore, health, ops API
      events/    event log + audit models, record(), list API
      documents/ file store, upload, file-type blocking, links, PDF text job, search provider
      search/    provider registry, search service, API
    worker/      job runner, handler registry, scheduler, entry point (python -m app.worker)
    cli.py       commands used by the Windows scripts
    launch.py    Task Scheduler entry point (reads C:\BOMS\config.json)
    main.py      FastAPI app; serves the built frontend from app/static
  migrations/versions/  0001_core, 0002_system, 0003_documents_search (hand-written SQL)
  tests/         11 test files + Persian normalization fixture
  pyproject.toml, requirements.lock (Windows pins), alembic.ini
frontend/
  src/ (shell, pages, components, lib, i18n/fa.json + en.json), public/ (manifest, icons),
  scripts/check-logical.mjs (lint against left/right utilities)
scripts/   install, update, backup, restore, start, stop (.ps1 + .bat), common.ps1,
           build_release.py, lock_windows.py, PSScriptAnalyzerSettings.psd1
wheelhouse/  README (wheels are downloaded by build_release.py, not committed)
docs/      README.md (Persian + English), ARCHITECTURE.md, OPERATIONS.md, PHASE1-REPORT.md
```

**Module rule:** each module writes only its own tables; cross-module calls go through public service functions (`events.record`, `jobs.enqueue`, `documents.service.link`, `settings.get`) or events. New modules plug in without editing existing ones: a `handlers.py` file registers background jobs and a `searchable.py` file registers search providers; both are discovered automatically.

### 3.2 Database (migrations 0001–0003)

- Schemas created: `sys`, `ref`, `core`, `outreach`, `tender`, `ops`, `fin`, `compliance`, `analytics` (only `sys` and `core` have tables).
- **Tables (11):** `sys.app_user`, `sys.setting`, `sys.country`, `sys.currency`, `sys.unit`, `sys.job`, `sys.backup_run`, `core.event`, `core.audit`, `core.document`, `core.document_link`.
- **Conventions:** UUID primary keys via `uuidv7()` (natural codes for base data, bigint identity for event/audit); all timestamps `timestamptz` in UTC; `created_at`/`updated_at` with an `updated_at` trigger; money helper `Money` (Decimal, NUMERIC(18,4) convention, FX NUMERIC(20,10), floats rejected).
- **Single user:** unique index on `((true))` on `sys.app_user`.
- **Append-only `core.event` and `core.audit`:** a trigger raises on UPDATE, DELETE and TRUNCATE (even for the superuser), and the app role's own UPDATE/DELETE/TRUNCATE privileges are revoked.
- **Audit:** generic trigger `core.audit_row(pk, omit...)` on every mutable `sys`/`core` table; records I/U/D with before/after JSON; omits `password_hash`, `text_content`, `search_vector`.
- **Roles:** the app connects as a non-superuser role that owns the database and app schemas, with `CREATEDB` (needed by the restore test). The superuser is used only by install/restore (`app.cli init-db` / `restore`).
- **Seed (idempotent `app.cli seed`):** 249 ISO 3166-1 countries and 178 ISO 4217 codes with Persian names (fund, metal, bond and test codes seeded inactive), 33 units with base factors (count→piece, weight→kg, length→m, area→m², volume→m³, time→second; packaging units such as box/pallet have kind `other`, factor 1, not convertible).

### 3.3 Persian text normalization

One rule set implemented as Python `app.core.text.normalize_fa` and as IMMUTABLE SQL `core.normalize_fa(text)`: Arabic ي/ى→ی, ك→ک, ة→ه; tatweel and diacritics removed; Persian/Arabic-Indic digits→Latin; ZWNJ, zero-width and bidi format characters→space; whitespace collapsed; ASCII and Latin-1 letters lowercased. A test runs both on a shared fixture list and asserts identical output. Used by all search indexes and queries.

### 3.4 Events and audit

`events.record(db, entity_type, entity_id, action, data, source, actor)` writes in the caller's transaction (rollback removes the event). Every state-changing service call records an event (login/lock/unlock, preference and password changes, settings, base data create/update/activate/deactivate, seed, documents create/update/link/unlink/text extraction, jobs enqueue/retry/done/failed, backups and restore tests). API: `GET /api/events` with entity type, entity id, action, date range and paging; `GET /api/events/facets`.

### 3.5 Documents

- Multipart upload streamed to a temp file while computing SHA-256 and enforcing the size limit (setting, default 100 MB; also an early Content-Length check).
- Stored at `files/<aa>/<bb>/<sha256>`, no extension, made read-only.
- Duplicate hash → HTTP 409 `duplicate_document` with the existing id and title (also handles concurrent duplicate uploads).
- Blocked by extension (exe, dll, bat, cmd, ps1, js, vbs, msi, scr, com, jar, lnk, hta) and by content (PE "MZ", ELF, Windows shortcut header, MSI compound-file CLSID, Java archive manifest/classes, `#!`, `@echo off`, `<hta:application`) → HTTP 415.
- MIME sniffed for PDF/PNG/JPEG/GIF/WebP; only those preview inline; everything else downloads as attachment with the original (including Persian) file name.
- PDF text extraction runs as a background job (PyMuPDF, text layer only, no OCR); `text_status` = pending/done/empty/failed.
- Endpoints: upload, list (search, type filter, entity filter, sort, paging), get, edit title/notes/language, download, preview, link, unlink. **No delete.**

### 3.6 Global search

- Ctrl+K command palette; results grouped by type (documents, countries, currencies, units), arrow keys + Enter.
- Documents: generated `tsvector` (`simple` config on normalized title, file name, notes, first 300k chars of text) with prefix matching, plus `pg_trgm` word similarity (threshold 0.4) on title + file name for typos. Base data: substring + trigram on codes and both names. GIN indexes on all expressions.
- Registration interface: `app.modules.search.registry.register(SearchProvider(...))`, discovered from each module's `searchable.py`.

### 3.7 Background jobs and scheduler

- Jobs are rows in `sys.job`; claimed with `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`.
- The handler runs in a transaction that also marks the job `done`; failures roll back the handler's writes and retry after 30 s × 2^(attempt−1) (max 1 h) up to `max_attempts`, recording `last_error`.
- Handler registry by job type (`@job_handler("type")` in each module's `handlers.py`).
- One worker at a time (PostgreSQL advisory lock); on start it re-queues jobs left `running`.
- Scheduler inside the worker: nightly backup (setting, default 02:00 local) and monthly restore test (1st of month, backup time + 1 h). A run missed while the PC was off runs **once** at the next start.
- Health: worker heartbeat file (`logs/worker.heartbeat`), queued/running/done/failed counts, data-folder disk free space, last backup, last restore test.

### 3.8 Backup and restore

**Backup** (`backup.run` job, CLI, or UI button):
1. `pg_dump -Fc` to `backups/db/boms_<UTC>_<kind>.dump`. Row counts of every app table are taken inside the **same snapshot** (`pg_export_snapshot` + `pg_dump --snapshot`) and written to a `.manifest.json` with SHA-256, size, schema revision and app version.
2. Incremental, hash-verified mirror of `files/` into `backups/files/`.
3. Optional secondary destination (e.g. external drive): same dump, manifest and mirror; if unavailable → `secondary_status = skipped` with reason, primary still succeeds.
4. Optional AES-256 zip archive (dump + manifest + list of file hashes); password from Credential Manager; skipped if no password.
5. Retention: newest dump per day for the last 7 days, per ISO week for 4 weeks, per month for 12 months; the latest successful dump is never deleted.
6. Recorded in `sys.backup_run` plus events.

**Restore test** (monthly job and button): verifies the dump's SHA-256, restores into `<db>_restore_test` (`boms_restore_test` in production), compares every table's row count with the manifest, checks that every `core.document.sha256` exists in `backups/files` and re-hashes a random sample of 20, drops the temp database, writes `restore_test_*` columns and an event. Failures name the problem (e.g. the corrupted file path).

**Full restore** (`app.cli restore`, used by `restore.ps1` on a clean PC): verifies the dump checksum, refuses if the database already exists, creates role + database, `pg_restore`, copies files into the data folder verifying hashes, compares row counts, prints a summary.

### 3.9 Security

- Uvicorn bound to 127.0.0.1 only; middleware rejects any Host other than `127.0.0.1:8765` / `localhost:8765`.
- Single-user Argon2 login; HMAC-signed session cookie (HttpOnly, SameSite=Strict) holding user id, password fingerprint (password change logs out other sessions), last activity and lock flag.
- Idle lock after `idle_lock_minutes` → HTTP 423; lock screen asks only for the password. UI polling (`X-BOMS-Background: 1`) does not count as activity; the UI also locks itself client-side and sends a keep-alive while the user is active.
- CSRF: double-submit token (cookie + `X-CSRF-Token` header) on every state-changing request plus same-origin `Origin` check.
- Login/unlock/password-change attempts rate-limited: 5 failures per 5 minutes → 429.
- Security headers: CSP `default-src 'self'`, nosniff, no-referrer, COOP.
- Secrets (DB password, session key, archive password) only in Credential Manager / env vars; never in files, DB or logs. Installer and docs recommend BitLocker; not enforced.

### 3.10 Frontend

- Shell: sidebar on the start side (right in Persian, left in English) with all 12 workspaces in spec order; unbuilt ones open a placeholder naming their phase. Header with search (Ctrl+K), language toggle, theme toggle, lock, logout.
- Working pages: Login, Lock screen, Documents (drag-and-drop upload, duplicate message with link, list, detail with metadata edit, preview, download, links, history), Base Data (countries/currencies/units: search, add, edit, activate/deactivate), Event Log (filters incl. Jalali/Gregorian date input, paging), System & Backup (health cards, Back up now, Run restore test, backup history, recent jobs), Settings (display prefs, username, idle lock, password change, data folder read-only, backup time, secondary destination, encrypted archive + password, max upload size). Base Data, Event Log and System & Backup are sub-pages of the Settings workspace.
- `dir` and `lang` set on `<html>`; language, calendar (Jalali/Gregorian), digits (Persian/Latin) and theme (light/dark/system) persist to `sys.app_user`.
- All UI text from `fa.json`/`en.json`; mixed-direction values wrapped in `<bdi>`; tabular numbers; one blue accent; light and dark design tokens.
- PWA: `manifest.webmanifest` + icons; no service worker. Built frontend served by the backend with long-cache hashed assets and an SPA fallback.

### 3.11 Windows scripts and release

- `install.ps1` (via `install.bat`): checks Windows 10/11 x64 and disk space; installs Python 3.12 / PostgreSQL 18 via winget, or prints the exact download URL and waits; asks data folder (default `D:\BOMS-Data` if D: is a fixed drive, else `C:\BOMS-Data`), the `postgres` password and the app password twice; copies program files to `C:\BOMS\app`; creates the venv from the bundled wheelhouse (`pip install --no-index`); generates DB password + session key into Credential Manager; creates role/database/extensions, migrates, seeds, creates user `admin`; registers "BOMS Backend" and "BOMS Worker" tasks (at logon, hidden via `pythonw`, restart every minute on failure); creates an Edge app-mode desktop shortcut; starts both; prints a summary and the BitLocker recommendation. Re-running offers **Repair** (data untouched). `-RestoreFrom` mode is used by `restore.ps1`.
- `update.ps1`: stop, `pre_update` backup (aborts with nothing changed if it fails), replace program files (keeps `*.previous`), offline pip install, migrate, start, print old→new version; rolls back program files if packages or migration fail.
- `backup.ps1` (optional `-RestoreTest`), `restore.ps1 <backup folder>`, `start.ps1`, `stop.ps1`, each with a `.bat` wrapper.
- Since `f8df8ae`, install/update first verify they are running from a built release (VERSION, lock file, built UI, wheels) and stop with instructions otherwise.
- `scripts/lock_windows.py` generates `backend/requirements.lock` (35 packages) with markers evaluated for Windows; `scripts/build_release.py` builds the frontend, downloads the 35 win_amd64/cp312 wheels, verifies the dependency closure for Windows, and produces `dist/boms-0.1.0-win64.zip` (31 MB).

---

## 4. Test results (all executed in the Linux container)

| Command | Result |
|---|---|
| `cd backend && ../.venv/bin/python -m pytest -q` | **110 passed** |
| `cd frontend && npx vitest run` | **13 passed** (2 files) |
| `npx tsc -b` | no type errors |
| `npm run lint` (blocks physical left/right Tailwind classes) | ok |
| `Invoke-ScriptAnalyzer -Path scripts` (incl. PS 5.1 syntax compatibility) | **0 findings** |

Backend tests per file: auth 15, backup 14, events/audit 12, jobs 10, documents 11, base data 9, search 7, text 4, money 4, migrations 3, settings 2.

Spec section 12 requirements, each covered by passing tests:

| Requirement | Covered by |
|---|---|
| Migrations empty → head, down one step and back | `test_migrations.py` |
| `core.event` / `core.audit` reject UPDATE and DELETE (and TRUNCATE) | `test_events_audit.py` (app role: privilege error; superuser: trigger error) |
| Audit trigger records I/U/D | `test_events_audit.py` |
| Same file twice → one copy + 409 with existing id | `test_documents.py` |
| Executable uploads rejected (extension and content) | `test_documents.py` |
| Python and SQL `normalize_fa` identical on shared fixtures | `test_text.py` |
| Search finds Persian word typed with Arabic ي/ك, and a misspelled Latin word | `test_search.py` ("كيفيت", "hydrolic", "specifcation") |
| Job fails twice then succeeds → `done`, attempts = 3; concurrent workers never double-run | `test_jobs.py` (6 threads, 60 jobs) |
| Full cycle: seed, upload, backup, restore test `passed`; corrupt one backup file → `failed` naming that file | `test_backup.py` |
| Retention keeps the right dumps | `test_backup.py` |
| Auth: wrong password, rate limit, idle lock, CSRF, wrong Host | `test_auth.py` |
| `fa.json` and `en.json` have identical keys | `i18n.test.ts` (plus: every literal `t("key")` in the code exists) |

Additional checks run:
- Real worker process against a dev database: on first start it caught up the missed nightly backup and monthly restore test; backup succeeded, restore test passed; SIGTERM stopped it cleanly.
- Browser test (Playwright/Chromium) against the running server: login (wrong then right password), upload + duplicate upload with Persian file name, all working pages in Persian and English × light and dark (28 combinations): no horizontal overflow, no external network requests, sidebar on the correct side; Ctrl+K palette search and navigation; lock and unlock.
- Install sequence (`init-db`, `migrate`, `seed`, `create-user`, `status`) run twice from the built release folder: second run creates nothing new; `app.launch` started the backend from a `config.json`.

---

## 5. Problems found and fixed during the work

| Problem | Fix |
|---|---|
| PostgreSQL 18 unavailable in the cloud container | Approved to use 16; migration 0001 creates `core.uuidv7()` only if `pg_catalog.uuidv7()` is missing (on 18 the built-in is used) |
| PyMuPDF 2.0 pulls in onnxruntime, numpy, networkx (huge for an offline wheelhouse) | Pinned `pymupdf<2` (1.28, no dependencies) |
| "hydrolic" scored 0.46 against "hydraulic", below a 0.5 fuzzy threshold | Threshold set to 0.4 |
| Full restore failed on `COMMENT ON EXTENSION` when the superuser pre-created extensions | Database created without extensions; `pg_restore` (as the app role) creates the trusted extensions |
| Sidebar off-screen in RTL; fixed-width inputs stretched; mixed "۲۹ GB" text order in RTL | Responsive classes fixed; width logic fixed; Persian byte units in Persian |
| Upload of the same file twice in a row did not re-trigger the file input | Input value reset after each upload |
| `pip download --platform` evaluates markers for the build machine, missing Windows-only deps | `lock_windows.py` evaluates markers for Windows (adds `pywin32-ctypes`, `tzdata`, `psycopg-binary`); build verifies closure |
| User ran `install.bat` from the git source folder → `Copy-Item: Cannot find path ...\VERSION` | Install/update now check for a built release first and explain how to build/use the zip |

---

## 6. Deviations from the specification

1. **PostgreSQL 16 for development/tests** (approved). Target remains 18; untested on 18.
2. **Pushed to the remote** (approved).
3. **PyMuPDF pinned below 2.0** (dependency size).
4. **Wheels not committed** to `wheelhouse/` (31 MB of binaries); `build_release.py` downloads exact pinned versions and verifies them.
5. **Base Data, Event Log, System & Backup are sub-pages of Settings**, so the sidebar keeps exactly the 12 specified workspaces.
6. **Extra columns/settings:** `sys.backup_run.details` (error, archive status, retention info), `core.document.text_status`, `created_at`/`updated_at` on base-data/job/backup tables, `core.document.created_at`/`updated_at` in addition to `uploaded_at`; settings `backup.archive_path`, `upload.max_mb`.
7. **Encrypted archive** contains the dump, its manifest and a list of file hashes (not the files themselves), matching the spec wording.
8. **Worker heartbeat** stored as a file in `logs/` instead of a DB row (avoids an audit row every few seconds).
9. **Sessions** are signed cookies (allowed by the spec); login rate limiting is in-memory (single process).
10. **No service worker** (optional in the spec).
11. **Lowercasing** in normalization covers ASCII and Latin-1 letters only, so Python and SQL give identical results.
12. **Full-text index** covers the first 300,000 characters of extracted text (PostgreSQL tsvector size limit).

## 7. Dependencies added beyond the stack table

- Runtime: `psycopg[binary]` (PostgreSQL driver for SQLAlchemy), `python-multipart` (required by FastAPI for uploads). Everything else in `requirements.lock` is a sub-dependency.
- Tests: `httpx` (FastAPI test client).
- Frontend: `@fontsource/vazirmatn` (bundled font files).

## 8. Not yet run / known limitations

**Not yet run (needs a real Windows PC):** `install.ps1`, `update.ps1`, `restore.ps1`, Task Scheduler tasks, Credential Manager writes, Edge shortcut/PWA install, winget, behaviour on PostgreSQL 18 (built-in `uuidv7`, `pg_dump`/`pg_restore` 18). Step-by-step checklist: `docs/OPERATIONS.md`, section "Manual test checklist for Windows".

**Known limitations to review:**
- The append-only guarantees protect against application bugs; a database owner could still re-grant privileges or drop triggers (documented).
- `Find-PgBin` only checks the default path `C:\Program Files\PostgreSQL\18\bin`; a custom install path would not be detected.
- If an update's migration succeeds but a later step fails, program files roll back but the database does not; restoring the `pre_update` backup is documented.
- In the browser test, the lock request was reported by Chromium as `ERR_ABORTED` although the server returned 204 and locking/unlocking worked; not reproduced with a direct fetch.
- Scanned (image-only) PDFs get `text_status = empty`; no OCR in Phase 1.

## 9. Open questions for the owner

1. Country IL is seeded with the Persian name "اسرائیل" (neutral ISO name); can be renamed in Base Data.
2. Should packaging units (set, box, carton, pallet, roll, drum, bag, coil, bundle) remain non-convertible (`other`, factor 1)?
3. Confirm the PostgreSQL 18 install path on the target PC if it is not the default.

## 10. How to install (target PC)

1. Use the release zip `boms-0.1.0-win64.zip` (or build it with `python scripts/build_release.py`). Do **not** run the installer from the git source folder.
2. Extract it, run `scripts\install.bat` from the extracted folder as the normal Windows user.
3. After install: open BOMS from the desktop shortcut (user `admin`), then on System & Backup run "Back up now" and "Run restore test" to confirm PostgreSQL 18 backup/restore.
4. Work through the checklist in `docs/OPERATIONS.md`.
