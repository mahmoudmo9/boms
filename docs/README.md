# BOMS

<div dir="rtl">

## فارسی

**BOMS** نرم‌افزار مدیریت بازرگانی و سفارش‌ها برای یک کاربر است که روی رایانه ویندوزی خودتان اجرا می‌شود و به اینترنت نیاز ندارد. این نسخه (فاز ۱) «اسکلت سیستم» است: ورود و قفل خودکار، تنظیمات، اطلاعات پایه (کشورها، ارزها، واحدها)، بایگانی اسناد، جستجوی سراسری، گزارش رویدادها، پشتیبان‌گیری شبانه و آزمون خودکار بازیابی.

### نصب

۱. فایل `boms-<نسخه>-win64.zip` را از حالت فشرده خارج کنید.
۲. در پوشه `scripts` روی `install.bat` دوبار کلیک کنید (با کاربر معمولی ویندوز، نه Administrator).
۳. اگر Python 3.12 یا PostgreSQL 18 نصب نباشد، برنامه نصب سعی می‌کند آن‌ها را با `winget` نصب کند. اگر اینترنت در دسترس نباشد، دقیقاً می‌گوید کدام فایل را از کجا دانلود کنید و منتظر می‌ماند.
۴. پوشه داده‌ها را انتخاب کنید (پیش‌فرض `D:\BOMS-Data` یا اگر درایو D نباشد `C:\BOMS-Data`)، رمز کاربر `postgres` را وارد کنید و برای BOMS رمز عبور (دو بار) انتخاب کنید.
۵. پس از پایان، میان‌بر **BOMS** روی دسکتاپ ساخته می‌شود. نام کاربری `admin` است.

BOMS فقط از همین رایانه در نشانی `http://127.0.0.1:8765` در دسترس است و با ورود به ویندوز خودبه‌خود (پنهان) اجرا می‌شود.

**توصیه امنیتی:** رمزگذاری BitLocker را برای درایوهای `C:\BOMS` و پوشه داده‌ها روشن کنید. BOMS آن را الزامی نمی‌کند.

### کارهای روزمره

| کار | روش |
|---|---|
| پشتیبان‌گیری دستی | صفحه «سیستم و پشتیبان‌گیری» ← «پشتیبان‌گیری اکنون»، یا `scripts\backup.bat` |
| آزمون بازیابی | همان صفحه ← «اجرای آزمون بازیابی» (هر ماه خودکار هم انجام می‌شود) |
| به‌روزرسانی | فایل zip نسخه جدید را باز کنید و `scripts\update.bat` همان نسخه جدید را اجرا کنید |
| توقف / اجرا | `C:\BOMS\app\scripts\stop.bat` و `start.bat` |
| بازیابی روی رایانه جدید | `scripts\restore.bat <پوشه پشتیبان>` — جزئیات در `OPERATIONS.md` |

راهنمای کامل پشتیبان‌گیری، بازیابی و به‌روزرسانی در فایل `OPERATIONS.md` است.

</div>

## English

**BOMS** is a single-user trading and order-management app that runs on your own Windows 10/11 PC,
fully offline. This release (Phase 1) is the system skeleton: login and idle lock, settings, base data
(countries, currencies, units), document store, global search (Ctrl+K), event log, nightly backups and
an automated restore test. Later phases add the business workspaces shown in the sidebar.

### Install

1. Extract `boms-<version>-win64.zip`.
2. In the `scripts` folder, double-click `install.bat` (as your normal Windows user).
3. If Python 3.12 or PostgreSQL 18 is missing, the installer tries `winget`. Offline, it prints exactly
   which installer to download from where, waits, and continues once it is installed.
4. Choose the data folder (default `D:\BOMS-Data`, or `C:\BOMS-Data` without a D: drive), enter the
   `postgres` superuser password, and choose the BOMS password (twice).
5. A **BOMS** desktop shortcut opens the app in its own window. The user name is `admin`.

BOMS listens only on `http://127.0.0.1:8765` (this PC) and starts hidden at Windows logon.
Running `install.bat` again offers **repair** and never overwrites data.

**Security:** enabling BitLocker on the drives holding `C:\BOMS` and the data folder is recommended.

### Everyday tasks

| Task | How |
|---|---|
| Back up now | System & Backup page → "Back up now", or `scripts\backup.bat` |
| Restore test | System & Backup page → "Run restore test" (also runs monthly) |
| Update | extract the new release zip, run *its* `scripts\update.bat` |
| Stop / start | `C:\BOMS\app\scripts\stop.bat`, `start.bat` |
| Disaster recovery on a new PC | `scripts\restore.bat <backup folder>`, see `OPERATIONS.md` |

### For developers

```bash
# backend (Python 3.12, PostgreSQL with pg_trgm + unaccent)
python3.12 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
export BOMS_DB_NAME=boms_dev BOMS_DB_USER=boms_dev BOMS_DB_PASSWORD=... BOMS_SESSION_KEY=... \
       BOMS_PG_SUPERUSER_PASSWORD=...           # secrets come from env vars outside Windows
cd backend
../.venv/bin/python -m app.cli init-db && ../.venv/bin/python -m app.cli migrate
../.venv/bin/python -m app.cli seed && ../.venv/bin/python -m app.cli create-user
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765     # API + built frontend
../.venv/bin/python -m app.worker                                   # jobs + scheduler

# tests (creates/drops boms_test* databases; superuser password in BOMS_TEST_PG_SUPERUSER_PASSWORD)
../.venv/bin/python -m pytest -q

# frontend
cd ../frontend && npm ci && npm test && npm run lint && npm run build   # build -> backend/app/static
npm run dev                                                           # http://localhost:5173, proxies /api

# release zip (needs internet on the build machine only)
cd .. && .venv/bin/python scripts/build_release.py
```

See `ARCHITECTURE.md` for the design and conventions and `OPERATIONS.md` for backup, restore and update.
