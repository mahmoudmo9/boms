# BOMS operations: backup, restore, update

All paths below assume the defaults: program `C:\BOMS\app`, configuration `C:\BOMS\config.json`,
data folder `D:\BOMS-Data` (yours may be `C:\BOMS-Data` or another folder chosen at install).

## What lives where

| Item | Location |
|---|---|
| Program, Python venv, built UI | `C:\BOMS\app` |
| Non-secret settings (data folder, DB name/port, PostgreSQL bin path) | `C:\BOMS\config.json` |
| Secrets: DB password, session key, archive password | Windows Credential Manager → *Generic credentials* → `BOMS` |
| Database | PostgreSQL 18, database `boms`, role `boms` |
| Uploaded files (read-only, named by SHA-256) | `<data>\files\aa\bb\<sha256>` |
| Backups | `<data>\backups\db`, `<data>\backups\files`, `<data>\backups\archive` |
| Logs (rotated, 5 × 5 MB) | `<data>\logs\backend.log`, `worker.log`, `worker.heartbeat` |

Two Task Scheduler tasks, **BOMS Backend** and **BOMS Worker**, start hidden at logon and restart
after a crash (every minute). The UI's *System & Backup* page shows whether the worker is alive.

## Backups

**Nightly** at 02:00 local time (Settings → *Nightly backup time*). If the PC was off, the missed
backup runs once at the next logon. **Manual**: *Back up now* on the System & Backup page or
`C:\BOMS\app\scripts\backup.bat` (`backup.bat -RestoreTest` also verifies it).

Each backup:

1. `pg_dump -Fc` into `backups\db\boms_<UTC time>_<kind>.dump`, plus a `.manifest.json` with the dump's
   SHA-256, size, schema revision and the **row count of every table at dump time** (counted inside the
   same database snapshot that pg_dump uses).
2. Copies new files from `files\` to `backups\files\` (content-addressed, so only new files are
   copied; each copy is hash-verified).
3. Optional **second copy** (Settings → *Second backup copy*, e.g. `E:\BOMS-Backup` on an external
   drive): the same dump, manifest and file mirror. If the drive is not connected the second copy is
   marked *skipped* with the reason; the main backup still succeeds.
4. Optional **encrypted archive** (Settings → *Encrypted archive*): an AES-256 zip of the latest dump,
   its manifest and a list of all file hashes, for keeping a copy away from this PC. The password is
   stored in Credential Manager from the Settings page. Without a password the archive is skipped.
   Note: the archive holds the database only; files are in the (unencrypted) file mirror.
5. **Retention**: keeps the newest dump of each of the last 7 days, the last 4 weeks and the last
   12 months. The most recent successful dump is never deleted. Old archives follow the dumps.
6. Result recorded in the backup history (System & Backup page) and the event log.

## Restore test (monthly + on demand)

Runs automatically on the 1st of each month (one hour after the backup time) and on *Run restore test*.
It restores the latest dump into a temporary database `boms_restore_test`, compares every table's row
count with the manifest, checks that every document's file exists in `backups\files` and re-hashes a
random sample of 20 files, then drops the temporary database. A failure names the problem (for example
the corrupted file). **Treat a failed restore test as urgent**: run a new backup and a new test; if it
still fails, check the disk.

## Restore

### Disaster recovery onto a clean PC

You need a backup folder: the old `<data>\backups` folder, or the second copy (e.g. `E:\BOMS-Backup`).
It must contain `db\` (dumps + manifests) and `files\`.

1. Install Windows 10/11 x64. Extract the BOMS release zip (same or newer version).
2. Run `scripts\restore.bat E:\BOMS-Backup` (your backup folder).
3. The installer checks/installs Python 3.12 and PostgreSQL 18, asks for the new data folder and the
   `postgres` password, generates a new DB password and session key, then:
   creates the role and database, runs `pg_restore` of the newest dump (verifying its SHA-256 against
   the manifest), copies all files into the new data folder verifying each hash, compares row counts,
   applies any newer migrations, registers the tasks and creates the shortcut.
4. It prints a summary; log in with your **old** BOMS password (it is part of the restored database).

To restore an older dump, run from `C:\BOMS\app\backend` after a normal install without data:
`..\venv\Scripts\python.exe -m app.cli restore --backup-dir E:\BOMS-Backup --dump E:\BOMS-Backup\db\<file>.dump`.

### Restoring over an existing installation

`restore.bat` refuses to overwrite an existing installation. To replace the current data:

1. `C:\BOMS\app\scripts\stop.bat`
2. Take a manual copy of the current `<data>` folder (just in case).
3. In *SQL Shell (psql)* as `postgres`: `DROP DATABASE boms;`
4. Rename `C:\BOMS\config.json` to `config.old.json` and move the old data folder away.
5. Run `restore.bat <backup folder>` and choose a data folder.

## Update

1. Extract the new release zip anywhere (for example `Downloads\boms-0.2.0`).
2. Run **its** `scripts\update.bat`.
3. The updater stops BOMS, runs a `pre_update` backup (**aborts without changing anything if the backup
   fails**), replaces `backend`, `scripts`, `wheelhouse` and `docs` in `C:\BOMS\app` (the old ones are
   kept as `*.previous` until the next update), installs the new Python packages offline, runs the
   database migrations, starts BOMS and prints `old -> new` version.
4. If package installation or a migration fails, it puts the previous program files back and starts
   the old version. If a migration had already changed the database, restore the `pre_update` dump
   (see *Restore*).

## Repair

Run `install.bat` again and choose **Repair**: it recreates the Python environment from the
wheelhouse, re-checks the database role and migrations, re-registers the tasks and the shortcut,
and can reset the app password. Data is never touched.

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser shows "can't reach 127.0.0.1" | `start.bat`; then `<data>\logs\backend.log` |
| Worker shown as *Not running* | Task Scheduler → *BOMS Worker* → History; `<data>\logs\worker.log` |
| Backup failed | backup history tooltip / `worker.log`; PostgreSQL service `postgresql-x64-18` running? disk space? |
| "Host header not allowed" | open `http://127.0.0.1:8765` (not the PC name or IP) |
| Forgot the app password | `install.bat` → Repair → reset password |

## Manual test checklist for Windows (not yet run)

These steps could not be run in the Linux build environment and must be checked once on a real
Windows 10/11 PC. Tick each item.

**Install (clean PC, offline)**
- [ ] Disconnect from the internet. Run `scripts\install.bat` from the extracted zip as a normal user.
- [ ] Without Python 3.12: winget fails offline → the script prints the python.org URL and waits; install it → the script continues.
- [ ] Same for PostgreSQL 18 (EDB installer URL); set and note the `postgres` password; port 5432.
- [ ] Data folder prompt shows `D:\BOMS-Data` if D: is a fixed drive, else `C:\BOMS-Data`; folders `files`, `backups`, `logs` are created.
- [ ] Password mismatch and a password under 8 characters are rejected and asked again.
- [ ] `pip install --no-index` completes from the bundled wheelhouse (no network).
- [ ] Credential Manager → Windows Credentials → Generic: entries `BOMS/db_password`, `BOMS/session_key` exist; `C:\BOMS\config.json` contains no password.
- [ ] Task Scheduler has *BOMS Backend* and *BOMS Worker* (trigger: at logon of your user; settings: restart every 1 minute).
- [ ] Desktop shortcut *BOMS* opens Edge in app mode with the BOMS icon; Edge offers "Install BOMS" (PWA).
- [ ] Summary is printed, including the BitLocker recommendation.

**Runtime**
- [ ] Sign out of Windows and in again: BOMS is reachable without opening any console window.
- [ ] `http://<PC name>:8765` and `http://<LAN IP>:8765` from another device do **not** work (bound to 127.0.0.1).
- [ ] Kill `pythonw.exe` (worker) in Task Manager: it is restarted within about a minute; System page shows it alive again.
- [ ] Log in, change language/theme/calendar/digits; upload a PDF, a Persian-named file, a duplicate (409 message with link) and an `.exe` (rejected).
- [ ] *Back up now* → succeeded; *Run restore test* → passed (uses `pg_dump`/`pg_restore` from `C:\Program Files\PostgreSQL\18\bin`).
- [ ] Settings → second copy on a USB drive: backup copies there; unplug the drive → next backup succeeds with second copy *skipped*.
- [ ] Settings → encrypted archive → store a password (Credential Manager entry `BOMS/archive_password`) → next backup writes an AES zip that 7-Zip opens only with that password.
- [ ] Leave the PC idle past the idle-lock minutes → lock screen asks only for the password.
- [ ] Set the backup time 2 minutes ahead → nightly backup runs; turn the PC off over the backup time → it runs once after the next logon.

**Repair / update / restore**
- [ ] Run `install.bat` again → offers Repair; data and documents are unchanged afterwards.
- [ ] Build a release with a higher `VERSION`; run its `update.bat` → `pre_update` backup appears, version change printed, data intact.
- [ ] Stop PostgreSQL, run `update.bat` → pre-update backup fails → update aborts, nothing changed.
- [ ] On a second clean PC (or VM): `restore.bat <backup folder>` → login with the old password, documents open, restore test passes.
- [ ] `stop.bat` / `start.bat` work.

## Manual checks for v0.2.0 (trading parties)

Run once on the Windows PC after `update.bat` from 0.1.1 (not yet run there):

**Update**
- [ ] Run the 0.2.0 `scripts\update.bat`: it prints `0.1.1 -> 0.2.0`, a `pre_update` backup appears, and System & Backup → *Run restore test* passes afterwards (the backup now covers 18 tables).
- [ ] Existing documents, base data and settings are unchanged.

**Parties**
- [ ] Sidebar: *Command Center* and *Trading Parties* no longer show "Phase 3"; Trading Parties has *Parties* and *Funnels*.
- [ ] New party with a Persian name and the buyer role → it opens in stage *New lead*. Creating a second party with almost the same name shows the duplicate warning; Save works only after ticking "create anyway".
- [ ] Add a contact with WhatsApp `0912 123 4567`; adding `+98 912 123 4567` to another contact is refused and names the first party.
- [ ] Tick *Do not contact*: Save needs a reason; the red badge appears in the list, command center, funnel and search.

**Quick-log and follow-ups**
- [ ] Ctrl+Shift+L (and the header button) opens *Log interaction*. Save stays disabled until a next action with a due date, or *No follow-up needed* with a reason, is filled.
- [ ] Paste a WhatsApp message, drop a PDF onto the dialog, choose *Tomorrow*, move the stage → the interaction shows the text unchanged and the attachment; the PDF is also under Documents.
- [ ] Command center: the follow-up is under *Next 7 days*; *Done* with a next follow-up closes it and creates the next one; *Reschedule* moves it. Around midnight (Tehran time) items move from *Today* to *Overdue* at local midnight, not at 03:30.
- [ ] Settings → *Stale lead after* = 1 day: a lead without contact for a day appears under stale leads.

**Funnels and search**
- [ ] Funnels: move a card with *Move to…*; the party's History tab shows the stage change with old and new stage.
- [ ] Ctrl+K: type the party name with Arabic ي/ك, a contact's phone digits, or a word from the pasted message → the party, contact and interaction are found.
- [ ] Check every page in Persian and English, light and dark: no horizontal scrolling at 1280 px.
