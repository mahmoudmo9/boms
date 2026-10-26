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

1. Extract the new release zip anywhere (for example `Downloads\boms-0.3.0`).
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

## RFQ follow-up rule (mark as sent)

BOMS sends nothing; *Mark as sent* records the outgoing message and, unless you say otherwise, a follow-up.
The dialog shows that follow-up before you confirm: action "Chase RFQ response" (in the recipient's
language) due on the RFQ's *respond-by* date. Both can be edited. If the RFQ has no respond-by date you must
either pick a follow-up date or tick *No follow-up* and write the reason; without either the server answers
`next_action_required`. The RFQ history (*sent* event) records which follow-up was created.

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

## Manual checks for v0.2.1 (parties fixes)

Run once on the Windows PC after `update.bat` from 0.2.0 (not yet run there):

**Update**
- [ ] Run the 0.2.1 `scripts\update.bat`: it prints `0.2.0 -> 0.2.1`, a `pre_update` backup appears, and *Run restore test* passes afterwards.
- [ ] Existing contacts: phone/WhatsApp numbers show in international form (`+98 912 …`); nothing else changed.

**Delete and archive**
- [ ] A new contact without interactions: *Delete* → one-line confirmation → gone; the party's History shows the deletion.
- [ ] A phone/email row: *Delete* removes only that row.
- [ ] A party with an interaction: *Delete* shows the counts (interactions, follow-ups, documents) and *Archive instead*.
- [ ] A new party without history: *Delete* → back to the parties list.
- [ ] Archive a party with an open follow-up: the dialog asks *Cancel them* / *Keep them*; with *Keep them* the follow-up stays in the Command Center with an *Archived* badge; with *Cancel them* it is closed with "party archived".
- [ ] Danger zone: the cascade button stays disabled until the exact party name is typed; afterwards the party, its interactions and follow-ups are gone and the attached documents still open from *Documents*.

**Interactions**
- [ ] *Correct* an interaction: move it to another party (search in the picker), change channel, direction, date and time → it appears under the other party with its follow-up; the attached document stays attached.

**Phone input**
- [ ] For a party in the UAE the country select shows the UAE by default; for a party without country it shows Iran. Typing `+98…` or `0098…` switches to Iran.
- [ ] `050 123 4567` on a UAE party is stored as `+971 50 123 4567`; `123` gives a clear "not a possible phone number" message.
- [ ] The same number on a second contact asks "This number is also registered for … Add anyway?"; *Yes* adds it, *No* adds nothing.
- [ ] Ctrl+K finds the contact by `0912`, `09123456789`, `912345`, `989123456789` and `+98 912 345 6789` (use your own number).
- [ ] Persian and English: the phone field and the new buttons do not overflow at 1280 px.

## Manual checks for v0.3.0 (sourcing and RFQ)

Run once on the Windows PC after `update.bat` from 0.2.1 (not yet run there):

**Update**
- [ ] Run the 0.3.0 `scripts\update.bat`: it prints `0.2.1 -> 0.3.0`, a `pre_update` backup appears, and *Run restore test* passes afterwards (now 36 tables).
- [ ] The sidebar shows *Sourcing & RFQ* (Inquiries, Catalog, Message templates) and *Cases* without a "Phase" label.
- [ ] Settings → *Company*: enter the company name and a Persian and an English signature.

**Inquiry to case**
- [ ] On a party's interaction click *Create inquiry*: party, channel and text are filled in. Save.
- [ ] *Import*: paste three lines from Excel (name, quantity, unit) → the columns are recognised; a row with "abc" as quantity is flagged and unchecked; *Add* creates the items. Also import an `.xlsx` file.
- [ ] Open an item, add properties (e.g. Grade, CAS) — earlier property names are suggested.
- [ ] Decision: a hard check "No" blocks *Convert to case* with the reason; yellow needs the confirmation box; "Order before payment" needs the approval line; red rejects the inquiry.
- [ ] Green → *Convert to case*: the case shows the same items.

**RFQ and offers**
- [ ] Give a Chinese supplier the HS heading of an item (party → Capabilities). *New RFQ* suggests that supplier.
- [ ] RFQ for two suppliers: the foreign one gets an English e-mail (Dear + contact name, item table, signature), the Iranian one a Persian WhatsApp text with a Jalali date. *Copy text* works; *Open in mail app* opens Outlook/the default mail app with subject and body.
- [ ] *Mark as sent*: the supplier's Interactions tab shows the outgoing message and the Command Center the follow-up; the items show *RFQ sent*. *Excel* downloads the item list.
- [ ] Record two offers in different currencies (Enter moves down the price column), attach a PDF; the comparison shows one group per currency, *Lowest* in each, and "Not directly comparable" when Incoterms differ.
- [ ] *Select* an offer; selecting another one asks for a reason; the case gate turns green when every item is selected or marked "no coverage".
- [ ] Item → *Create product*; the product page shows the offered prices (min/median/max) and the demand.
- [ ] Command Center → *Sourcing* shows items without RFQ, overdue replies, expiring offers and the coverage percentage.
- [ ] Ctrl+K finds the inquiry, case, item, RFQ, offer and product (also with Arabic ي/ك); a supplier is found by its capability tag.
- [ ] Every new page in Persian and English, light and dark: no horizontal scrolling at 1280 px.

## Manual checks for v0.3.1 (sourcing fixes)

Run once on the Windows PC after `update.bat` from 0.3.0 (not yet run there):

- [ ] Run the 0.3.1 `scripts\update.bat`: it prints `0.3.0 -> 0.3.1`, a `pre_update` backup appears, and *Run restore test* passes afterwards (36 tables, no migration in this release).
- [ ] **Withdraw a selected offer:** select an offer for an item, then withdraw that offer → the item shows *Selection lost, choose again* on the case Items tab, its status falls back (*Has offer* if another valid offer exists, otherwise *RFQ sent*), the case gate lists it again and Command Center → *Sourcing* → *Selections lost* links to it. Reactivating the offer gives *Has offer*, not *Selected*.
- [ ] **Type a reason in each dialog** (type, do not paste, a few words with spaces): mark no coverage, cancel item, reject inquiry, change selection, cancel follow-up, mark as sent (action and *No follow-up* reason), template editor, new product. The cursor stays in the field and the whole text arrives.
- [ ] **Mark as sent** on an RFQ with a respond-by date shows "Will create the follow-up … due …"; on an RFQ without one the button stays disabled until a date is chosen or *No follow-up* has a reason.
- [ ] **Delete a supplier that has RFQs:** *Delete* and the danger-zone cascade both show "Cannot delete, still in use" with RFQ recipients / offers counts — no technical database text, no error page. A supplier with only capability tags deletes and its tags are gone.
- [ ] **Case danger zone** (case → History): the button stays disabled until the exact title is typed; afterwards the case, its RFQs and offers are gone, the documents still open from *Documents* and the supplier's sent/received interactions are still there.
- [ ] **Duplicate product check:** with an existing product "پلی‌اتیلن سنگین / HDPE X", creating "پلي‌اتيلن سنگين" (Arabic ي/ك, Persian name only) warns; "hdpe x" alone warns; an unrelated name does not; *confirm* saves anyway.
- [ ] **RFQ builder in Persian and English:** the language select shows "English"/"فارسی" in full next to the channel select; at a narrow window the two selects wrap instead of being cut.
