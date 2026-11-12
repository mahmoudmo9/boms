# BOMS architecture

BOMS is a modular monolith: one FastAPI backend, one PostgreSQL database, one
background worker process (same codebase). It runs on one Windows PC, bound to
`127.0.0.1:8765`, fully offline.

## Code layout

```
backend/app/
  core/            config, secrets, db session, errors, security, web middleware,
                   time, money, Persian text normalization, superuser db admin
  modules/
    system/        user + auth, settings, base data (countries/currencies/units), jobs, backup
    events/        append-only event log (core.event) + audit trail reader (core.audit)
    documents/     file store, documents, document links, PDF text extraction job
    search/        global search + provider registry
    parties/       trading parties, contacts, interactions, follow-ups, funnels, command center (Phase 3)
    sourcing/      inquiries, go/no-go decisions, cases, line items + import, RFQs, message templates,
                   supplier offers, coverage/comparison, capability tags (Phase 5)
    catalog/       products, aliases, categories, price and demand memory (Phase 5)
    costing/       tax parameters, cost templates, cost sheets, FX entries, computation, quote gate (Phase 6)
    quotes/        quotes (proforma invoices), numbering, approval, sending, outcomes, PDF/Word output (Phase 6)
  worker/          job runner, handler registry, scheduler  (python -m app.worker)
  cli.py           commands used by the Windows scripts
  launch.py        Task Scheduler entry point (reads C:\BOMS\config.json, runs backend or worker)
  main.py          FastAPI app (API + built frontend from app/static)
backend/migrations/  Alembic, hand-written SQL (0001 core, 0002 system, 0003 documents/search, 0004 parties,
                     0005 parties fixes, 0006 sourcing, 0007 costing, 0008 quotes); data/ holds the HS 2022
                     and ISIC Rev.4 seed files
frontend/          React + TypeScript + Vite + Tailwind (logical properties only), i18next
scripts/           Windows install/update/backup/restore/start/stop (.ps1 + .bat), release builder
wheelhouse/        Windows wheels (filled by scripts/build_release.py, not committed)
```

### Extension points for later modules

A new module (for example `modules/parties/`) adds its own `models.py`, `service.py`, `router.py`
and a migration for its tables in its schema (`ref`, `outreach`, `tender`, ...). It plugs into the
shared machinery **without editing other modules**:

- **Background jobs**: `modules/<name>/handlers.py` with `@job_handler("parties.something")`;
  the worker imports every module's `handlers.py` at start. Enqueue with
  `app.modules.system.jobs.enqueue(db, type, payload)`.
- **Global search**: `modules/<name>/searchable.py` calling
  `app.modules.search.registry.register(SearchProvider(...))`; discovered automatically.
- **Events**: `app.modules.events.service.record(...)` in the same transaction.
- **Documents**: link documents to its entities with `documents.service.link(db, doc_id, "party", id)`.
- **Audit**: attach `core.audit_row('<pk>')` and `core.set_updated_at()` triggers to new mutable tables.
- **Backups** cover every table in the app schemas automatically (row counts per table).
- **Hooks into earlier modules** (v0.4.0): `modules/<name>/hooks.py` registers callbacks with registries that
  earlier modules expose (`sourcing.items.register_sold_check`, `sourcing.inquiries.register_case_cleanup`,
  `parties.command_center.register_sourcing_extension`, `costing.usage.register_sheet_usage`).
  `app.core.modules.load_hooks()` imports every `hooks.py` once; the registries call it lazily, so the API
  process and the worker see the same hooks.
- **Reference counts** (v0.4.0): `modules/<name>/references.py` with `parties.references.register_reference_counter`
  adds a module's rows to the "in use" counts shown before a party or contact is deleted.
- **UI**: add the route in `frontend/src/App.tsx`, remove the workspace's `phase` in
  `frontend/src/lib/nav.ts`, add keys to both `fa.json` and `en.json` (a test enforces parity).

### Module rule

A module writes only its own tables. Modules talk to each other only through a
module's public service functions (`modules/<name>/service.py` or the documented
functions in its files) or by recording events. No module imports another
module's ORM models to write to them.

| Module   | Owns tables |
|----------|-------------|
| system   | `sys.app_user`, `sys.setting`, `sys.country`, `sys.currency`, `sys.unit`, `sys.job`, `sys.backup_run` |
| events   | `core.event`, `core.audit` (audit rows are written only by the trigger) |
| documents| `core.document`, `core.document_link` |
| parties  | `core.funnel_stage`, `core.party`, `core.party_role`, `core.contact`, `core.contact_method`, `core.interaction`, `core.followup` (Phase 3) |
| sourcing | `ops.payment_term`, `ops.item_status`, `ops.inquiry`, `ops.decision`, `ops."case"`, `ops.line_item`, `ops.rfq`, `ops.rfq_item`, `ops.rfq_recipient`, `ops.message_template`, `ops.supplier_offer`, `ops.offer_item`, `core.party_capability`; reads `ref.hs_code`, `ref.isic_code` (seeded by migration 0006) (Phase 5) |
| catalog  | `core.product`, `core.product_alias`, `core.product_category` (Phase 5) |
| costing  | `ops.tax_kind`, `ops.tax_parameter`, `ops.cost_template`, `ops.cost_template_line`, `ops.cost_sheet`, `ops.fx_rate_entry`, `ops.cost_line` (Phase 6) |
| quotes   | `ops.outcome_reason`, `ops.quote_sequence`, `ops.quote`, `ops.quote_item`; quote terms templates are rows of `ops.message_template` (kind `quote_terms`), written through the sourcing templates functions (Phase 6) |

## Database conventions

- **Schemas**: `sys`, `ref`, `core`, `outreach`, `tender`, `ops`, `fin`,
  `compliance`, `analytics` all exist from migration 0001. Phase 1 uses only
  `sys` and `core`.
- **Primary keys**: UUID generated by the database with `uuidv7()`. Base data
  tables use their natural code (ISO code, unit code) as key; append-only
  tables use `bigint` identity.
  PostgreSQL 18 has `uuidv7()` built in. On older servers migration 0001
  creates a compatible `core.uuidv7()`; column defaults resolve to whichever
  exists. *(Dev/CI deviation: the cloud dev container only has PostgreSQL 16.)*
- **Time**: every timestamp is `timestamptz`, stored in UTC. Python uses only
  timezone-aware datetimes (`core/time.py`; naive datetimes raise). Conversion
  to Jalali/Gregorian and local time happens only in the UI.
- **Money** (later phases): `NUMERIC(18,4)` amount plus a `currency` code
  column; FX rates `NUMERIC(20,10)`. Never float. Python uses
  `app.core.money.Money` (Decimal, rejects floats and mixed currencies).
- **created_at / updated_at** on every mutable table; `updated_at` is kept by
  the `core.set_updated_at()` trigger. Append-only tables carry
  `occurred_at` (`core.event`) or `changed_at` (`core.audit`) instead.
- **Roles**: the app connects as a dedicated non-superuser role (default
  `boms`) that owns the database and the app schemas and has `CREATEDB` (for
  the restore test). The PostgreSQL superuser is used only by install/restore
  scripts (`app.cli init-db`).
- **Text search**: every search index and query uses
  `core.normalize_fa(text)` (SQL, IMMUTABLE) / `app.core.text.normalize_fa`
  (Python). They are built from the same character tables and tested for
  identical output.

## Event log and audit

- `events.record(db, entity_type, entity_id, action, data, source, actor)` is
  the only way to write an event. It runs in the caller's transaction, so the
  event is committed or rolled back together with the change. Every
  state-changing service call records one.
- `core.audit` is filled by the generic trigger `core.audit_row(pk, omit...)`
  attached to every mutable table in `sys` and `core` (I/U/D with before/after
  JSON; `password_hash` is omitted).
- Both tables are append-only: a trigger raises on UPDATE, DELETE and
  TRUNCATE (even for a superuser), and the app role's own UPDATE/DELETE/TRUNCATE
  privileges are revoked. Note: an owner can re-grant itself privileges and
  drop triggers; these guards stop application bugs, not a hostile DBA.

## HTTP security

- Uvicorn binds to `127.0.0.1` only. A middleware rejects any `Host` header
  other than `127.0.0.1:8765` / `localhost:8765` (DNS rebinding).
- Single user, Argon2 password. Session = HMAC-signed, HttpOnly,
  SameSite=Strict cookie holding user id, password fingerprint (a password
  change invalidates other sessions), last-activity time and a locked flag.
  After `idle_lock_minutes` without user activity the API answers `423 locked`
  until the password is re-entered. UI polling sends `X-BOMS-Background: 1`,
  which does not count as activity.
- CSRF: double-submit token (`boms_csrf` cookie + `X-CSRF-Token` header) on
  every state-changing request, plus same-origin `Origin` check.
- Failed password checks (login, unlock, password change) are rate limited:
  5 per 5 minutes.
- Secrets (DB password, session key, archive password) live in Windows
  Credential Manager (`keyring`, service `BOMS`); on non-Windows dev machines
  in environment variables. Never in files, the database, or logs.

## API conventions

- JSON under `/api`. Errors: `{"error": {"code", "message", "details"}}`;
  `code` is a stable key the UI translates.
- Lists: `?page=&page_size=` → `{items, total, page, page_size}`.
- Decimals are sent as strings. Datetimes as ISO 8601 UTC.
- The UI sends `X-BOMS-Client: ui`; events from those requests get
  `source = 'ui'`, other HTTP clients `api`, the worker `worker`, CLI `script`.

## Documents

- Upload is streamed to `<data>/files/.incoming` while computing SHA-256 and enforcing the size limit
  (Settings → max upload, default 100 MB), then moved to `files/<aa>/<bb>/<sha256>` (no extension) and
  made read-only. An existing hash returns `409 duplicate_document` with the existing id and title.
- Rejected by extension (`exe dll bat cmd ps1 js vbs msi scr com jar lnk hta`) and by content
  (PE `MZ`, ELF, Windows shortcut header, MSI compound file, Java archive, `#!`, `@echo off`,
  `<hta:application`).
- MIME type is sniffed for PDF and images; only those are previewed inline. Everything else downloads
  as an attachment with the original file name.
- PDFs get a `documents.extract_text` job (PyMuPDF, text layer only). `text_status`: `pending`,
  `done`, `empty` (probably a scan), `failed` (corrupt/encrypted).
- No hard delete in Phase 1.

## Search

`core.document.search_vector` is a generated `tsvector` (`simple` config) over normalized title and
file name (weight A), notes (B) and extracted text (C, first 300k chars). Queries are normalized with
`normalize_fa`, turned into prefix `tsquery` terms, and combined with `pg_trgm` word similarity
(threshold 0.4) on title + file name for typo tolerance. Base data uses substring + trigram matching on
code and both names. All expressions have GIN indexes. Results are grouped by provider type.

## Jobs and scheduler

- `sys.job` rows; the worker claims with `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`.
- The handler runs in a transaction that also marks the job `done`, so its writes commit only on
  success. Failures retry after `30 s × 2^(attempt-1)` (max 1 h) up to `max_attempts`, recording
  `last_error`. One worker runs at a time (PostgreSQL advisory lock); at start it re-queues jobs left
  `running` by a stopped worker.
- The scheduler (in the worker loop, local time) computes each schedule's latest due time and enqueues
  once if the last run is older, so runs missed while the PC was off happen once at the next start.
  Phase 1: nightly backup (`backup.time`, default 02:00) and monthly restore test (1st of the month,
  backup time + 1 h). Phase 5: hourly `sourcing.expire` (RFQ recipients past `respond_by` ->
  `no_response`, offers past `valid_until` -> `expired`; status + event only, nobody is contacted).
- Heartbeat: `<data>/logs/worker.heartbeat`, written every loop (≈2 s); "alive" = younger than 60 s.

## Backup

See `OPERATIONS.md`. Row counts are taken in a `REPEATABLE READ` transaction whose snapshot is
exported to `pg_dump --snapshot`, so the restore test can compare counts exactly.

## Frontend

React 19 + TypeScript, Vite, Tailwind CSS 4 with design tokens (CSS variables for light/dark),
TanStack Query/Table, react-router, i18next. `dir`/`lang` on `<html>` follow the user's language;
layout uses logical utilities only (`npm run lint` fails on `ml-/mr-/left-/right-/text-left…`).
Dates: Jalali (`date-fns-jalali`) or Gregorian, Persian or Latin digits, from the user's settings;
the API always uses ISO UTC. Vazirmatn (Arabic-script subset, bundled woff2) for Persian, system font
for Latin. Mixed-direction values are wrapped in `<bdi>`. No CDN, no external requests; no service
worker (the PWA manifest alone makes the app installable).

## Design note (not implemented): separate owner and runtime roles

**Status:** proposal for the owner to decide; no code has been changed for it.

**Today.** One role (`boms`) owns the database, the schemas and every table, and the app runs as that role.
The append-only guards on `core.event` / `core.audit` (trigger + revoked UPDATE/DELETE/TRUNCATE) stop
application bugs, but an owner can still `DROP TRIGGER`, `ALTER TABLE` or re-`GRANT` itself privileges
(verified in review). So anything that runs SQL as `boms` (a bug, a future SQL-injection hole, a tool
using the app's credentials) could rewrite the history.

**Proposal.** Two roles:

| Role | Login | Used by | Rights |
|---|---|---|---|
| `boms_owner` | yes, password in Credential Manager (`BOMS/owner_password`) | `init-db`, migrations, install/update/restore scripts only | owns the database, schemas, tables, functions, triggers |
| `boms_app` | yes, password in Credential Manager (`BOMS/db_password`) | backend, worker, CLI backup and restore test | `USAGE` on schemas; `SELECT/INSERT/UPDATE/DELETE` on mutable tables; **only `SELECT, INSERT`** on `core.event` and `core.audit`; `USAGE` on sequences; `EXECUTE` on functions; `CREATEDB` for the restore test; not owner of anything, so it cannot drop triggers or change grants |

`ALTER DEFAULT PRIVILEGES FOR ROLE boms_owner` grants `boms_app` the standard rights on future tables, and
each migration that creates an append-only table adds its narrower grant explicitly.

**What would change**

- `app.cli init-db` (superuser): create both roles; database owned by `boms_owner`; set default
  privileges; store the second secret. For an existing install, a one-time conversion as superuser:
  create `boms_owner`, `REASSIGN OWNED BY boms TO boms_owner`, then grant `boms` (now the runtime role)
  the rights above. This needs the `postgres` password once (the installer's Repair already asks for it).
- Migrations (`migrations/env.py`, `app.cli migrate`): connect as `boms_owner` (new `owner_password`
  secret) instead of the app role; a new migration adds the grants and default privileges.
  Downgrades also run as owner.
- `update.ps1`: migrations run as owner (the secret is in Credential Manager, so no new prompt);
  the first update after this change runs the one-time conversion and needs the `postgres` password.
- `restore.ps1` / `app.cli restore`: `pg_restore` as `boms_owner`; then re-apply the runtime grants.
- Backup: `pg_dump` as `boms_app` works (it needs only `SELECT`). Restore test: unchanged (it restores into
  a throw-away database that the app role creates and owns).
- Tests: the fixtures create both roles; the append-only test additionally asserts that the runtime role
  gets `must be owner` on `DROP TRIGGER`.

**What it does not solve.** Anyone with the Windows user's session can read both secrets from Credential
Manager, and the PostgreSQL superuser can do anything. The change raises the bar from "any SQL the app
can run" to "deliberate use of the owner credentials".

**Cost.** One more secret, one more connection setting for migrations, a one-time ownership conversion
on existing installs, and test fixture changes. Roughly one day of work including Windows verification.

## Trading parties (Phase 3, v0.2.0)

Module `app/modules/parties/` (models, schemas, service, interactions, command_center, router, searchable,
normalize, clock). Migration `0004_parties` adds seven tables in `core`, all with UUIDv7 keys,
`created_at`/`updated_at`, the `updated_at` trigger and the generic audit trigger.

| Table | Notes |
|---|---|
| `core.funnel_stage` | Stage vocabulary per role, seeded by the migration: buyer (new_lead … dormant), supplier (identified … dormant), other roles (active, dormant). |
| `core.party` | `name_fa`/`name_en` (at least one, CHECK), generated `name_norm = normalize_fa(fa + ' ' + en)` with a trigram index, `kind`, `country_iso2` → `sys.country`, `do_not_contact` + required reason (CHECK), `status` active/archived (real delete only when nothing depends on it, since v0.2.1), `ref_company_id` reserved for the later world-companies portal (no FK, no UI). |
| `core.party_role` | One row per (party, role), UNIQUE. `(role, stage)` is a foreign key to `core.funnel_stage(role, code)`, so the vocabulary is enforced by the database. |
| `core.contact` | Names, job title, primary flag (one active primary per party, partial unique index), status. |
| `core.contact_method` | `type`, raw `value` (as typed), `value_norm`, primary flag, status. Since v0.2.1 (migration 0005): partial UNIQUE `(contact_id, type, value_norm) WHERE status = 'active'` (the same contact cannot hold a value twice: 409) plus a plain index on `(type, value_norm)`; the same value on another contact is allowed after a warning. Phone/WhatsApp are parsed with `phonenumbers` and stored as E.164 (`+989123456789`); email lowercased; Telegram without `@`. |
| `core.interaction` | Party (required), optional contact of the same party, channel, direction, `occurred_at`, subject, raw `body` (never altered), generated `body_norm`, `no_followup_reason`. Full-text index on subject + body, trigram index on subject. A trigger allows only subject/body to change and forbids DELETE, except under the transaction-local flags described in *v0.2.1* below; corrections are recorded as events with before/after. |
| `core.followup` | Optional interaction, party, action, `due_on` (date), status open/done/cancelled, `done_at`, `done_note` (required when cancelled, CHECK). |

**Next action is mandatory.** Creating an interaction requires exactly one of a follow-up or a
`no_followup_reason` (422 `next_action_required` / `next_action_conflict`). A deferred constraint trigger
checks the same rule at commit as a backstop.

**Duplicates.** `POST /api/parties` first looks for parties whose name has pg_trgm similarity ≥ 0.6 (per
language or combined); if any exist it answers `200 {"created": false, "possible_duplicates": [...]}` and
stores nothing; the client repeats the call with `confirm_duplicate: true`. Contact methods are a hard 409.

**Command center.** `GET /api/command-center` returns overdue / today / next 7 days (open follow-ups by
`due_on`), stale leads (active buyers in new_lead/contacted/in_conversation/quoted and suppliers in
identified/contacted/responded whose last interaction — or stage change if none — is older than the
`parties.stale_lead_days` setting, default 14), funnel counts per role and stage, and `overdue_count`.
"Today" is the PC's local date (the same zone the backup scheduler uses), never the UTC date.

**Integration with other modules** (public functions only): `events.record` for every write,
`documents.service.link/unlink` for attachments (`entity_type` `interaction` or `party` in
`core.document_link`), `settings.get` for `parties.stale_lead_days`, `searchable.py` registers the
party, contact (names + contact values) and interaction (subject + text) search providers.
Routes: `/api/parties`, `/api/contacts`, `/api/interactions`, `/api/followups`, `/api/command-center`.
Backups and the restore test include the new tables automatically.

### Parties fixes (v0.2.1, migration `0005_parties_fixes`)

- **Real deletes.** `DELETE /api/contacts/methods/{id}` (always), `DELETE /api/contacts/{id}` (only when no
  interaction references the contact; its methods go with it) and `DELETE /api/parties/{id}` (only without
  interactions, follow-ups and document links; contacts, methods and roles go with it). Otherwise
  `409 in_use` with counts, e.g. `{"interactions": 2, "followups": 1, "documents": 0}`. Each delete is one
  transaction; the event's `data.deleted` is a full snapshot and the audit trigger writes the `D` rows.
  `core.event` / `core.audit` stay append-only (`core.forbid_change` is unchanged).
- **Test-data cleanup.** `DELETE /api/parties/{id}?cascade=true` with `{"confirm_name": "<exact name_fa or
  name_en>"}` (else 422 `confirm_name_mismatch`) also deletes the party's interactions, follow-ups and
  document links (stored files are not touched). The service sets `boms.allow_interaction_delete = 'on'`
  with `set_config(..., true)` (transaction-local); the trigger function `core.interaction_delete_guard`
  rejects every other DELETE on `core.interaction`. The snapshot holds every deleted interaction.
- **Interaction corrections.** `PATCH /api/interactions/{id}` also takes `party_id`, `contact_id` (must belong
  to the resulting party, or null), `channel`, `direction`, `occurred_at`. `core.interaction_guard` allows
  these columns only under the transaction-local flag `boms.interaction_edit = 'on'`;
  `no_followup_reason` and `created_at` never change. Moving to another party moves the follow-ups created
  from that interaction (event `followup.move`); document links stay. Event `interaction.correct` has
  `before`/`after` of every changed field.
- **Archive.** `POST /api/parties/{id}/archive` takes `{"open_followups": "cancel" | "keep"}` (default cancel).
  Cancel closes them with note "party archived" and an event each; kept ones stay in the command center,
  whose rows carry `party_status`.
- **Phones.** `phonenumbers` parses numbers typed locally, with `+` or with `00` (Persian digits too). Region =
  the request's `region`, else the party's `country_iso2`, else `IR`. Numbers that fail
  `is_possible_number` are rejected with 422 `invalid_phone` and a reason. Responses add `value_display`
  (international format). `GET /api/parties/phone-regions` lists the `sys.country` rows phonenumbers knows,
  with their calling code. The migration prefixes existing phone/WhatsApp `value_norm` with `+` (no re-parse);
  the downgrade strips it and fails if a value is shared by two contacts by then.
- **Phone search.** The contact search provider takes the query's digits (if at least 4 were typed), strips
  leading zeros and matches `value_norm LIKE '%digits%'`: `0912`, `09123456789`, `912345`, `989123456789`
  and `+98 912 345 6789` all find the contact.
- **Shared numbers.** Adding (or creating a contact with, or changing to) a value that another active contact
  holds answers `200 {"created": false, "shared_with": [{contact_name, party_name, party_id, ...}]}` and stores
  nothing; the client repeats with `confirm_shared: true`. Archived methods are ignored by these checks and by
  the unique index; re-adding an archived value creates a new row.

## Sourcing and RFQ (Phase 5, v0.3.0, migration `0006_sourcing`)

Modules `app/modules/sourcing/` (inquiries, items, importing, extract, templates, rfq, offers, coverage,
capabilities, dashboard, searchable, handlers, router) and `app/modules/catalog/` (service, router,
searchable). All new mutable tables have UUIDv7 keys (codes for the vocabularies and `ref` tables),
`created_at`/`updated_at`, the `updated_at` trigger and the audit trigger; every change records an event in the
same transaction. Money is `NUMERIC(18,4)` with a currency column; there is no currency conversion.

**Deal flow.**
1. `ops.inquiry` (party optional, source channel, kind, `received_at`, reply-due date, subject, `raw_text`
   stored unchanged, status, optional `source_interaction_id`). "Create inquiry" on a Phase 3 interaction
   pre-fills party, channel, text and the link (`GET /api/inquiries/prefill`).
2. `ops.decision` (one per inquiry; history in events): traffic light, one-line reason, three hard checks
   (`feasible_sourcing`, `exposure_acceptable`, `requirements_ok`: yes/no/unknown + note), entered exposure
   estimate + currency, payment term from `ops.payment_term`; "order before payment" requires
   `ordering_before_payment_reason` (CHECK + 422). Red rejects the inquiry with the reason.
3. Conversion gate (`POST /api/inquiries/{id}/convert`): 409 `decision_required`, `hard_check_failed`
   (with the failing checks), `decision_red`, `confirmation_required` (yellow without `confirmed`), or
   `already_converted`. The case copies payment term, approval line and exposure; the inquiry's
   `ops.line_item` rows get `case_id` (never copied). Cases can also start without an inquiry.
4. `ops.line_item`: free name/description, quantity + `unit_code` (`sys.unit`) or `unit_text`, target price +
   currency, destination, Incoterm + place, required-by, packaging, HS code, route, notes, `specs` jsonb
   (list of `{key, value, unit?}`; key suggestions from earlier use, case-insensitive after `normalize_fa`),
   status from `ops.item_status`, `no_coverage_confirmed` + reason, `selected_offer_item_id`. Import without
   AI: pasted table/list, `.csv`, `.xlsx` (openpyxl) -> column mapping -> preview with per-row errors ->
   bulk create. `sourcing/extract.py` defines `ItemExtractor` with a disabled default (no external calls).
5. RFQs: `ops.rfq`, `ops.rfq_item` (optional quantity/unit/note overrides), `ops.rfq_recipient` (party,
   default contact = primary active contact, channel, language, template, exact `message_text`).
   `ops.message_template` holds the texts (seeded en/fa for e-mail and WhatsApp; one default per language +
   channel); placeholders are a fixed set (`{supplier_name}`, `{contact_name}`, `{case_title}`,
   `{items_table}`, `{respond_by}`, `{signature}`), unknown ones are a 422 on save; Persian texts show the
   reply-by date in the Jalali calendar. `company.name` and `company.signature` (per language) are settings.
   Defaults: suppliers in Iran get WhatsApp in Persian, others e-mail in English. Nothing is sent by BOMS:
   "mark as sent" creates an OUTGOING interaction (parties public service) with the exact text and a
   follow-up (default "Chase RFQ response" on `respond_by`), moves the items to `rfq_sent`, and sets the RFQ
   `sent`. RFQ status: draft -> sent -> answered (no recipient still waiting and at least one replied, or all
   declined) / no_response; cancelled is manual. `.xlsx` export of the item list.
6. Offers: `ops.supplier_offer` (header: channel incl. WeChat, received, valid until, currency, Incoterm,
   payment terms, lead time, compliance notes, raw text) + `ops.offer_item` (available, unit price, price
   basis per quantity, unit, MOQ, lead time, deviation, packaging). Recording creates an INCOMING interaction
   (WeChat -> channel `other`, subject "WeChat") with the Phase 3 next-action rule, moves offered items to
   `has_offer`, marks the matching recipient `replied` and refreshes the RFQ status. A newer offer can
   supersede an older one of the same supplier (kept, status `superseded`).
7. Coverage/comparison: valid offers = active and not past `valid_until`. Comparison rows are grouped by
   currency, then by unit group (units of one convertible kind in `sys.unit`, otherwise the exact unit);
   inside a group the lowest normalized price (`unit_price / price_per_quantity / base_factor`) is flagged
   unless Incoterms differ ("not directly comparable"). Selecting an offer row sets
   `selected_offer_item_id` + status `selected`; changing it needs a reason (event). Case gate: every
   non-cancelled item is `selected` or `no_coverage_confirmed`.

**Catalog.** `core.product` (names, `name_norm` trigram index, kind note, default unit, HS code, category,
status) + `core.product_alias` (grades, trade names, CAS numbers) + `core.product_category` (self-reference).
Creating a product warns about similar names/aliases (pg_trgm >= 0.6) and needs `confirm_duplicate`. The
product page is computed, nothing extra is stored: every offer row for the product, min/median/max per
(currency, unit group) all time and last 12 months, demand (inquiries, cases, quantity per month, buyers),
suppliers by offers and by HS capability.

**Capability tags.** `ref.hs_code` (HS 2022: 96 chapters, 1228 headings; source UN Comtrade via
datasets/harmonized-system, ODC-PDDL) and `ref.isic_code` (ISIC Rev.4: 21 sections, 88 divisions), with an
`edition` column. Persian titles exist for chapters and sections only; missing ones are NULL and the UI shows
the English title with a marker. `core.party_capability` stores `kind` (hs/isic/tag), `code` as text (no FK,
so a new edition can replace the reference rows) or a free tag (`tag_norm` = lower(`normalize_fa`)), unique
per party. Uses: party list filter `capability=hs:3907|isic:C20|tag:x` (a heading also matches its chapter),
RFQ supplier suggestions (4-digit heading first, then chapter; suggestions only), product page, and the party
search result.

**Hooks into earlier modules** (the only changes outside the new modules):
- parties UI: "Create inquiry" on an interaction; "Capabilities" card on the party Overview.
- parties API: `GET /api/parties?capability=…` (ids from `sourcing.capabilities.matching_party_ids`), party
  search also matches capability codes/titles/tags, command-center response gains `sourcing`
  (`sourcing.dashboard.summary`: items without RFQ, overdue RFQ replies, offers expiring in 7 days, cases not
  covered, and the share of open items with a coverage status).
- system: settings `company.name`, `company.signature`; worker schedule `sourcing_expiry_hourly`;
  `backup.table_counts` quotes table names (`ops."case"` is a reserved word).

Routes: `/api/inquiries`, `/api/cases` (+ `/{id}/coverage`, `/{id}/comparison`), `/api/line-items`,
`/api/rfqs`, `/api/offers`, `/api/message-templates`, `/api/products`, `/api/capabilities`. Delete only when
nothing depends on a row (409 `in_use` with counts), otherwise cancel/withdraw/archive.


### Sourcing fixes (v0.3.1, no migration)

**Item status derivation.** `sourcing.items.recompute_item_status(db, item, source, actor, today=None)` is the
only code that sets a line item's coverage status. It is called after every mutation that can change the
answer: offer recorded / superseded / withdrawn / reactivated / deleted / expired, `valid_until` changed,
offer row patched (`available`, price), selection set or cleared, RFQ recipient sent / declined / replied /
no_response / removed, RFQ cancelled / deleted, no-coverage set or cleared, and the hourly expiry job. Order:
1. `cancelled` stays; `sold` / `delivered` / `closed` (later phases) are never touched;
2. the selected offer row is still valid (offer `active`, not past `valid_until`, row `available`) -> `selected`;
3. any valid available offer row -> `has_offer`;
4. any RFQ that is not cancelled, includes the item and has a recipient that is not `draft` (`sent`,
   `replied`, `declined`, `no_response`, `expired`; v0.3.2 — before, only `sent`/`replied`) -> `rfq_sent`;
5. otherwise `uncovered`.

A selection that is no longer valid is cleared in the same transaction with an event `selection_lost`
(`old_offer_item_id`, `cause`: withdrawn / expired / superseded / deleted / unavailable, `old_status`,
`new_status`); another offer is never picked automatically and reactivating an offer does not restore the
selection. `no_coverage_confirmed` is a separate flag and is not changed. Deleting a selected offer is
therefore allowed (it used to be a 409). The command center lists items with a `selection_lost` event in the
last 14 days that are not selected again (`sourcing.selection_lost`); `/api/cases/{id}/coverage` marks them
(`selection_lost: true`) for the badge on the case Items tab.

**Reference-counter registry.** `parties/references.py` lets later modules tell the parties module which of
their rows point at a party or contact without parties importing their tables:
`register_reference_counter(name, party_fn, cleanup=..., contact_fn=..., non_blocking=(...))`. Registrations
live in each module's `references.py` and are discovered with `load_module_parts("references")` (like
`searchable.py`). `sourcing/references.py` counts `inquiries`, `cases`, `rfq_recipients`, `offers` and
`capabilities` per party and `rfq_recipients`, `offers` per contact. The counts are merged into the 409
`in_use` details of party and contact deletes. Capability tags do not block a delete; the registered cleanup
removes them (event `capabilities_removed`). A cascade party delete removes only the party's own rows
(interactions, follow-ups, document links); with any registered blocking count it is a 409 `in_use`.

**Errors.** The flush helpers (`sourcing.common.flush`, `catalog.service._flush`, `parties.service._flush`) no
longer copy the database message into the API error: FK violations map to stable codes (`unknown_unit`,
`unknown_reference`, `in_use` when a row is still referenced, ...) with only the constraint name as detail.

**Test-data cleanup.** `DELETE /api/cases/{id}?cascade=true` with `{"confirm_title": "<exact title>"}` deletes
the case, its line items, RFQs (+ items, recipients), offers (+ rows) and document links; files, interactions
(their follow-ups) and the source inquiry stay. `DELETE /api/inquiries/{id}?cascade=true` with
`{"confirm_subject": "<subject or DELETE>"}` does the same for an inquiry without a case (items, decision,
document links). Both record an event with a full snapshot; the audit trigger records the `D` rows.

**Product duplicates.** Each given name (and alias) is compared separately with `core.normalize_fa(name_fa)`,
`core.normalize_fa(name_en)` and every alias; the greatest similarity counts and exact normalized equality is
always a duplicate (score 1). Used by create, create-from-item and update (`PATCH /api/products/{id}` returns
409 `possible_duplicate` with the list unless `confirm_duplicate`).

**Mark as sent.** The dialog shows the follow-up that will be created (action in the recipient's language,
due date from `respond_by`, both editable) or takes an explicit no-follow-up reason; the `rfq` event `sent`
records `followup_id` (the follow-up row also points at the interaction) or `no_followup_reason`.

### Sourcing fixes 2 (v0.3.2, no migration)

- **`no_response` keeps `rfq_sent`.** See rule 4 above: an RFQ that was sent keeps its items at `rfq_sent` even
  when nobody answered. Command center *Sourcing* gains `no_response_resend`: open-case items in `rfq_sent`
  whose every non-draft recipient of every non-cancelled RFQ is `no_response` or `declined` ("no reply, send
  again"). `items_without_rfq` stays "items still `uncovered`". The coverage percentage is unchanged.
  Statuses stored by v0.3.1 under the old rule are repaired by the hourly `sourcing.expire` job, which also
  recomputes items still `uncovered` that have a non-draft recipient (no migration; within an hour of the update).
- **Cascade case delete** also cancels, through `parties.interactions.cancel_followup` (note "case deleted",
  one event each), the open follow-ups attached to the interactions of the deleted RFQ recipients and offers
  (found with the new public `parties.interactions.open_followups_of_interactions`). Interactions stay; other
  follow-ups of the supplier are untouched; the delete snapshot lists `cancelled_followups`.
- **Contact person on offers.** Offer, comparison row, RFQ recipient and product price history carry
  `contact_name_fa/en` (archived contacts are still named). `contact_id` must belong to the offer's party on
  create and patch (422 `contact_not_of_party`); the incoming interaction uses the same contact.
- **RFQ screen.** Default title `RFQ <n> - <first item name>`, unique within the case, when none is typed.
  `templates.render` drops every sentence that uses `{respond_by}` when the RFQ has no date (also for
  owner-edited templates). Sent recipients' text is read-only in the UI; the API already answers 409
  `recipient_sent` to text edits of non-draft recipients.


## Costing, pricing and quotes (Phase 6, v0.4.0, migrations `0007_costing`, `0008_quotes`)

Modules `app/modules/costing/` (compute, service, usage, searchable, hooks, router) and `app/modules/quotes/`
(numbering, service, output, references, handlers, searchable, hooks, router). Same conventions as Phase 5: UUIDv7
keys, `updated_at` and audit triggers, an event in the same transaction for every change, `NUMERIC(18,4)` money
with a currency column. Everything runs offline: exchange rates and tax rates are typed in by the owner; there is
no FX download, no tariff database and no e-mail sending.

**Tax parameters** (`ops.tax_kind`, `ops.tax_parameter`): kind (customs duty, levy, VAT, ...), name, rate %,
deal type (`import`/`export`/`domestic`/`all`), `effective_from`/`effective_to`, `confirmed_by`/`confirmed_on`.
The rate is never edited: the owner ends a parameter and adds a new one. A parameter in use cannot be deleted
(409 `in_use`). A sheet line linked to a parameter takes the parameter in force on the sheet date.

**Cost templates** (`ops.cost_template`, `ops.cost_template_line`): default import, export and domestic templates
are seeded; lines carry kind, labels fa/en, basis, allocation, paid-before-receipt and the tax kind. Editing a
template never changes existing sheets.

**Cost sheets** (`ops.cost_sheet`, `ops.fx_rate_entry`, `ops.cost_line`): one or more versions per case, status
`draft` -> `final` (at most one final sheet per case; finalizing supersedes the previous final) -> `superseded`.
Only drafts change; "new version" copies a sheet. A new sheet starts from a template (or the deal type's default,
or blank); purchase lines are filled from the items' selected offers (`source_offer_item_id`, unit converted).
FX entries are per sheet: pair, rate, rate kind (free text with suggestions), source note, `as_of`.
IRR amounts are whole rials (0 decimals, `DECIMALS_OVERRIDE`), with no automatic rial/toman conversion.

**Computation** (`costing/compute.py`, pure `Decimal` functions):

1. Every line amount is converted to the pricing currency (direct pair, or the reverse pair divided; missing pair:
   422 `fx_missing`) and rounded once, at line level.
2. Item lines belong to their item (`per_unit` x quantity); case lines are allocated by value, quantity, equally
   or by manual shares; the rounding remainder goes to the largest share, so shares always sum to the line.
3. CIF = purchase + international freight + insurance; `percent_of_cif` / `percent_of_purchase` lines per item.
4. VAT never enters the cost: a percent VAT line applies to the selling price before VAT, shown separately.
5. Exposure = supplier prepayment + lines paid before receipt - customer prepayment (not below 0).
   Cost of money = exposure x annual rate x days / 365. Guarantee = guarantee % x total price x annual rate x
   guarantee days / 365. Customer prepayment and guarantee depend on the price, so prices are solved by
   fixed-point iteration; both amounts are allocated to items by cost.
6. Unit price: markup `cost x (1 + p)` or margin `cost / (1 - p)` (p < 100 %, else 422 `invalid_margin`), then
   rounding (`none`, `nearest`, `up` to a step); a manual unit price replaces it. Margin % = (price - cost) /
   price and markup % = (price - cost) / cost are both always shown.

**Warnings** (not blocking): the offer behind a purchase line is no longer valid, the item's selected offer
changed, a linked tax parameter is unconfirmed, FX older than `costing.fx_max_age_days` (setting, default 3).

**Quote gate** (`GET /api/cost-sheets/{id}/gate`), all failures returned together: sheet final, all FX present,
lines complete, every item priced, total and per-item minimum prices, validity not later than the earliest
selected offer validity and the newest FX date + max age, tax parameters confirmed, FX recent. FX age and
unconfirmed parameters can be overridden with a reason (stored on the sheet, recorded as an event). The default
validity (`quotes.default_validity_days`, 7) is shortened to the allowed date (`valid_until_capped`).

**Quotes** (`ops.quote`, `ops.quote_item`, `ops.quote_sequence`, `ops.outcome_reason`):

- Created from a sheet that passes the gate (409 `gate_failed` otherwise). Defaults: buyer = case party, its
  primary contact, language `fa` for an Iranian buyer else `en`, payment terms from the case, terms text from the
  default `quote_terms` template of that language (placeholders `buyer_name`, `valid_until`, `payment_terms`,
  `incoterm`, `lead_time`, `bank_details`). Items copy the sheet's prices; a manual price is marked.
- Number `PI-<year>-<seq:04d>`: the year in the user's calendar (Jalali for Jalali users), the sequence row locked
  with `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, so numbers are unique and gap-free under concurrency.
  Every revision gets its own number and points to the quote it supersedes.
- Status: `draft` -> `approved` (re-checks the gate, minimums and buyer; locks the quote: 409 `quote_locked`)
  -> `sent` (records an interaction with the buyer, a "chase" follow-up due the day before validity ends unless a
  reason is given, and optionally moves the buyer to the `quoted` funnel stage) -> `accepted` /
  `partially_accepted` / `rejected` from per-row outcomes (`accepted`, `rejected` with a required reason,
  `no_reply`, `negotiating`, optional competitor price + currency). `expired` (hourly `quotes.expire` job,
  status + event only), `withdrawn` (cancels the chase follow-ups), `superseded` (revise). Drafts can be deleted.
- Case result: when no quote of the case is still open (draft, approved, sent), "case won/lost" sets the case
  status through `sourcing.cases.update_case` (409 `quotes_undecided` otherwise).
- Output: `GET /api/quotes/{id}/print` (HTML, embedded Vazirmatn font, RTL for fa, DRAFT watermark before
  approval); `POST /api/quotes/{id}/outputs` with `pdf` (headless Edge/Chrome `--print-to-pdf`, path from setting
  `pdf.browser_path` or found automatically, proxy set to a dead local port; no browser: 424 `pdf_unavailable`)
  or `docx` (python-docx; RTL paragraphs and Tahoma for fa, DRAFT in the header). Files are stored in Documents
  and linked to the quote with role `output`. Letterhead data: settings `company.name_fa/en`, `address`,
  `phone`, `email`, `website`, `registration`, `logo_document_id`, `footer`, `bank_details`.

**Hooks into earlier modules** (no behaviour change for data without quotes):

- `sourcing.items.register_sold_check(quotes.is_sold)`: an item accepted in an accepted or partially accepted
  quote derives `sold`; `cancelled`, `delivered` and `closed` items are never changed.
- `sourcing.inquiries.register_case_cleanup`: the cascade delete of a test case removes quotes (order 10) and
  cost sheets (order 20) before the sourcing rows; files stay in Documents.
- `parties.command_center.register_sourcing_extension(quotes.dashboard)`: *quotes awaiting approval* (drafts),
  *sent or expired without an outcome, validity ending within 3 days or passed*, *sheets with stale FX*, *won / lost in the last 30 days*.
- `parties.references`: quotes count when a party or contact is deleted. Search providers `cost_sheet`, `quote`.
- Product page: `GET /api/quotes/by-product/{id}` (sent quote rows with min/median/max per currency and unit
  group); party page: `GET /api/quotes?party_id=`.

### Costing and quote fixes (v0.5.0 section 0, migration `0009_quote_fixes`)

- **Approval re-checks the current prices.** Besides the gate and the per-item / total minimums, a unit price below
  the unit landed cost gives 409 `below_cost` (items listed) unless the request has `confirm_below_cost: true`
  with a `reason` (event `approve_below_cost`). The quote editor warns in red while a price is typed below cost
  or below the item minimum.
- **Finalize** returns 409 `gate_failing` with the failures (other than "not final") unless `confirm: true`; the
  UI shows the checklist first. Unfilled lines (no amount, no percent) can be saved as 0 with the note "N/A" in
  one step (`POST /api/cost-sheets/{id}/lines/not-applicable`) or removed (`.../lines/remove-unused`; purchase
  lines stay, an empty one means an unpriced item).
- **Terms text:** template lines whose values are all empty are omitted, and so are "Label:" lines left without a
  value (also in the HTML/PDF/Word of stored texts). A draft's terms rebuild automatically when payment terms,
  delivery terms, lead time, Incoterm, validity, buyer or language change, unless the owner edited the text by
  hand (`ops.quote.terms_manual`); then the UI offers "rebuild from template".
- **Persian digits:** in Persian texts made from templates (RFQ messages, quote terms), dates and numbers follow the
  user's digit setting (Persian by default); names, codes and e-mails are never converted. The RFQ Excel export
  keeps Latin digits.
- **Revision numbers:** a revision keeps the base number with a version suffix (`PI-1405-0001-v2`); the gap-free
  base sequence counts first versions only; output file names are the number (plus `-DRAFT` before approval).
- **Persian terms:** exposure «نقدینگی درگیر», margin «حاشیهٔ سود», markup «مارک‌آپ» on every screen.

## Setad connector and screening (Phase 7a, v0.5.0, migration `0010_listings`)

### Connector (`app/connectors/setad/`)

The site-reading code of the owner's SetadSuite v0.9.23 (purchase calls «فراخوان‌های خرید» on eproc, tenders on
etend) is ported with its parsers, captcha wait, recovery, «فراخوان‌های من», attachments and recorder unchanged.
The full mapping (file by file, function by function) and the behaviour changes are in
[`SETAD_PORT.md`](SETAD_PORT.md). `reference/` holds the original source as read-only reference material: it is
never imported at runtime and never shipped (`build_release.py` refuses a release that contains it, browser
profiles, the attachments cache or diagnostics).

- The connector drives the installed **Microsoft Edge** (`channel="msedge"`), then Chrome, with a persistent profile
  in `<data folder>/connectors/setad/browser_profile`; Playwright's own browsers are not bundled.
- The owner logs in and types every captcha in the visible window. BOMS never solves captchas, never pays, never
  submits an offer and never uploads to Setad. The only site writes are add / remove «فراخوان‌های من», each refused
  without `confirm: true` (422 `confirmation_required`) and recorded as an event.
- Passwords, cookies and tokens are never written to the database, logs or diagnostics (SetadSuite's `redact`).
- Tests run against an offline fake host (`tests/connectors/setad/fakesite.py`: routes for `*.setadiran.ir`,
  everything else aborted, a dead proxy as a second guard) and saved fixtures.

### The Setad agent and the `setad` job lane

`python -m app.connectors.setad.agent` is a separate process started on demand by the backend
(`POST /api/setad/agent/start`) on the owner's PC, so the Edge window is visible on the desktop. It:

- holds a single-instance OS file lock (`<data>/connectors/setad/agent.lock`); a second agent exits at once;
- takes only jobs of lane `setad` from `sys.job` (`jobs.claim_next(db, lane="setad")`); the normal worker takes only
  lane `default`, so a backup runs while a fetch waits for a captcha;
- writes its status every 2 s to `ext.agent_status` (connected, role, command, pages, rows, captcha waiting,
  message, heartbeat) and reads `cancel_requested` there (`POST /api/setad/cancel`): a cancelled fetch ends
  cleanly with its run `cancelled`;
- exits after `setad.agent_idle_minutes` without commands.

Commands: `connect`, `set_role`, `full_fetch`, `quick_fetch`, `fetch_detail`, `download_files`, `sync_my_calls`,
`add_my_call`, `remove_my_call`, `open_payment_page`, `record_start`, `record_stop`, `disconnect`.

### Schema `ext` (module `listings`)

| Table | Content |
|---|---|
| `harvest_run` | one row per fetch: source, kind (full / quick), status (running / done / needs_review / cancelled / error), pages, rows seen, new, changed, duplicates, errors, issues |
| `listing` | machine rows refreshed from the site, unique per (source, external_id); `search_norm` (generated, trigram index); `first_run_id`, `last_full_run_id`; no audit trigger |
| `listing_change` | one row per change of a tracked field (deadlines, edition, state, document price, required validity, …); never for volatile list metadata (`recCount`) |
| `listing_detail` | detail page: field pairs, buyer note, items table, text |
| `listing_file` | attachments: state pending / downloaded / missing / error, local path in the attachments cache, SHA-256, `document_id` once copied into the document store |
| `listing_screening` | the owner's decisions (audited): new / starred / reviewing / converted / dismissed (reason required), note, checklist, `inquiry_id` |
| `agent_status` | the single status row the UI polls |

List rule (SetadSuite 0.9.23): a listing is shown when it was seen since the start of the last **full** fetch of its
source, or when it is starred, reviewing or converted ("Include listings not seen in the last full fetch" shows
everything). A quick fetch only adds and refreshes rows; it never hides older ones.

The attachments cache (`setad.files_dir`, default `<data>/setad-files`) is **not** in the nightly backup: files of a
converted listing are copied into the document store, which is backed up. "Clear cache" deletes only connector files;
"Purge" deletes listings older than `setad.retention_days` that are not starred, reviewing or converted.

### Conversion to an inquiry (hooks)

`listings.convert` creates the inquiry through the sourcing service (it never writes sourcing tables itself):
kind `rfq` (purchase call) or `tender`, channel `setad` with the Setad number and link (`ops.inquiry.listing_id`,
`external_no`, `external_url`), received = published, `response_due_at` = the exact deadline from the detail page
(else the list deadline), `required_price_validity`, delivery province / city, buyer note in the inquiry text; the
buyer party matched by normalized name, or picked from suggestions / created with the Phase 3 duplicate warning
(contact lines go to the party notes); items from the detail table (Setad goods code as a spec, product
suggestions from the catalog) or one item from the description; downloaded files uploaded to the document store
(hashed, deduplicated) and linked. A second conversion gives 409 `already_converted`.

Hooks registered in `listings/hooks.py`:
- `sourcing.inquiries.register_inquiry_cleanup` — deleting the inquiry (cascade) puts the listing back to
  `reviewing` and clears `inquiry_id`; the listing stays.
- `parties.command_center.register_section("setad", …)` — the command center's Setad section (due starred /
  reviewing listings, converted listings whose deadline changed, new listings matching warn keywords, the last run
  per source with a warning after 3 days).
- `listings/searchable.py` — global search by number, title, organization (converted ones link to the inquiry).

Deadline change after conversion: `GET /api/listings/by-inquiry/{id}` returns the listing's current deadline when it
differs from `inquiry.response_due_at`; the inquiry and case show a banner; *Apply* calls
`sourcing.inquiries.apply_response_deadline`, which moves the deadline and the open follow-ups of the buyer and of
the case's RFQ chases that were due on or before the old deadline day by the same number of days (event
`deadline_apply`). Nothing is applied silently.

### Setad proforma (on Phase 6 quotes)

A quote whose case comes from a Setad inquiry: Persian quotes use the seeded `quote_terms` template "Setad (fa)"
(placeholders `{addressee}`, `{setad_number}` added to the quote-terms set); `valid_until` defaults to the buyer's
required price validity, capped by the offers / FX limit; the approval gate fails with
`validity_shorter_than_required` (both dates and the limit in the failure) unless accepted with a reason
(`POST /api/quotes/{id}/validity-override`, `ops.quote.validity_override_reason`, event `gate_override`). Persian
outputs write the total in words (SetadSuite's `number_words`); the file name carries the Setad number
(`PI-1405-0001-Setad-<number>.pdf`); the letterhead shows the national ID, economic code and signer
(Settings → Letterhead). The owner uploads the file to Setad by hand.

### Carry-over fixes (v0.6.0 section 0, migration `0011_listing_fixes`)

- Setad list rows: the guarantee and estimate are read from the real keys (`guarantyPrice`, `guarantyPriceCurrency`,
  `guarantyDescription`; `financialEstimatePrice`, `tndaFinancialEstimatesPrice`, `elvFinancialEstimatePrice`) with
  the older keys as fallbacks; a row without an amount never clears a value taken from the detail page, and the
  detail page fills the guarantee from a «مبلغ…» label or a value in ریال/تومان. New `ext.listing` columns
  `guarantee_currency`, `guarantee_description`, `estimate_currency`.
- Agent jobs: one queued job per listing and command, one full / quick fetch per source (`already_queued` in the
  bulk answer); `GET /api/setad/jobs/{id}` (per-listing results), `GET /api/setad/log` (the agent log, rotated
  5 MB × 3, every line tagged with the job id and command); `ext.agent_status.listing_id`, `files_done`,
  `files_total` drive the per-row progress in the screening table.
- Quote outputs: the fixed footer is drawn in the `@page` bottom margin box (no blank second page).

## Tenders (Phase 7b, v0.6.0, migration `0012_tenders`)

Module `app/modules/tenders/` (all tables in `ops`, audited by `core.audit_row`). A **tender** is the tender part of
a case (one per case): it is created automatically when an inquiry of kind `tender` becomes a case (hook below), or
by *Make this a tender* on any case (`POST /api/cases/{id}/tender`).

| Table | Content |
|---|---|
| `tender` | one per case: Setad number, type, stages, document price, estimate (amount + currency pairs), stage (screening → documents → pricing → guarantee → envelopes → submitted → opening → result → closed), participation (undecided / yes / no + reason), financial mode (`buyer_form` summary or `letterhead` quote), proposal validity days, submission (at, channel, note, override reason), result (won / lost / cancelled / no_result, reason, winner, price, rank), `appendix_seen` and `setad_dates_seen` (what the tender last saw on Setad) |
| `tender_date` | one per kind (documents / proposal / questions / quality-docs deadline, briefing, site visit, opening, offer valid until) plus any number of `other` with a label; `remind_days_before int[]`; source setad / manual / addendum |
| `tender_date_change` | every change of a date: old, new, reason (required), addendum |
| `tender_addendum` | addenda, Q&A and extensions; a cancellation needs `confirm_cancellation` |
| `company_document` | the company documents library (title, category, file in the document store, issued / expires, archived) |
| `envelope_template`, `envelope_template_line` | envelope checklists; the default «SetadSuite» template (14 lines, A/B/C) is seeded |
| `envelope_item` | the tender's checklist: envelope A (bid bond) / B (documents) / C (price), kind document / bid_bond / price_form, status not_ready → in_progress → needs_signature → ready → submitted, optional company document or guarantee |
| `guarantee`, `guarantee_event` | bid / performance / advance-payment / retention guarantees: form, amount, fee, blocked deposit, bank, number, valid until, beneficiary; status to_request → requested → issued → ready_to_upload → submitted → extended → released / claimed / cancelled with one event per step |
| `tender_followup` | links from the tender to the parties follow-ups it created (purpose date_reminder, guarantee_expiry, guarantee_release, opening, contract) |
| `tender_cost` | documents purchase, guarantee fee, deposit, travel, other; refundable flag, paid / refunded dates |
| `tender_proposal`, `tender_proposal_line` | the financial proposal (summary mode): versions from the final cost sheet, lines with unit prices, totals, VAT, total in words |
| `tender_result_reason` | the lost-reason list (8 seeded, editable in Settings → Tenders) |

**Setad prefill.** A case from a Setad tender listing gets the number, type, stages, document price, estimate, the
Setad dates (source `setad`), a draft bid bond with the Setad guarantee amount, a documents-purchase cost and the
default envelope template. *Refresh from Setad* lists every difference to the listing (nothing is applied without
the owner ticking it). The **dates banner** lists only dates Setad changed after the tender last saw them
(`setad_dates_seen`): a date the owner moved on purpose (an addendum, a manual change) is not offered back; *Apply*
changes the date with the reason «تمدید/تغییر در ستاد», *Keep my dates* (`POST /api/tenders/{id}/setad-dates/keep`)
marks the Setad values as seen. Grown Setad addenda counters show «new addenda on Setad» until an addendum is
recorded or the banner is dismissed.

**Reminders.** All reminders are ordinary parties follow-ups (so they appear in the command center and the party
pages), created through the parties public service and linked in `tender_followup`. Date reminders: N days before
each date (`tenders.reminder_days`, default [3, 1], per date editable); guarantee expiry: `tenders.guarantee_reminder_days`
(default [30, 7]) before *valid until*; release: `tenders.release_followup_days` (default 7) after a lost or
cancelled result, or after a won tender's performance guarantee is submitted; opening: on the opening day after
submission; contract: 3 days after a won result. A changed date or validity moves its open reminders; a result, a
cancelled case or a deleted case cancels them.

**Submission.** `GET /api/tenders/{id}/blockers` lists everything that is not ready (participation not «yes»,
empty or incomplete envelopes, bid bond not issued, bond validity shorter than the proposal validity, proposal not
approved, deadline passed, expired company documents). *Mark as submitted* refuses with 422 `blockers_remain`
unless an override reason is given (kept on the tender and in the event).

**Result.** *Lost* needs a reason; the case becomes won / lost / cancelled (or stays open for *no result*); a won
tender marks the case items sold through the registered sold check; the result can be revised (both kept in events).

**Financial proposal.** `buyer_form` mode: a proposal version is built from the final cost sheet (prices editable
while draft); approval refuses prices below the landed cost without a reason (422 `below_cost`, the v0.5.0 rule);
outputs as print view, PDF (Edge headless) and Word, named `Tender-<number>-proposal-v<n>[-DRAFT].<ext>`.
`letterhead` mode uses Phase 6 quotes with the seeded «Tender (fa)» terms and the tender number.

Hooks registered in `tenders/hooks.py` (new registries in earlier modules are marked *new*):
- `sourcing.inquiries.register_case_converted` (*new*) — the tender part of a converted tender inquiry;
- `sourcing.inquiries.register_case_status_changed` (*new*) — a cancelled case cancels the tender's open reminders;
- `sourcing.inquiries.register_case_cleanup(5, …)` — deleting a case removes its tender rows and cancels reminders,
  before the quotes (10) and cost sheets (20);
- `sourcing.items.register_sold_check` — a won tender sells the case's items;
- `quotes.service.register_terms_source` (*new*) — letterhead mode uses «Tender (fa)» with the tender number;
- `quotes.service.register_product_quote_rows` (*new*) — approved proposals appear in a product's quote history;
- `parties.command_center.register_section("tenders", …)` — dates within 3 days, incomplete envelopes near the
  deadline, guarantees expiring or awaiting release, company documents expiring, Setad changes not applied,
  submitted tenders waiting for the result;
- `tenders/searchable.py` — global search for tenders, guarantees and company documents.

Validation convention as elsewhere: a CHECK violation is 422 with the constraint name; a unique or still-referenced
row is 409 (an issued guarantee cannot be deleted: 409 `guarantee_issued`).

## Execution and shipping (Phase 8, v0.7.0, migration `0013_execution`)

**Section 0.** Output documents follow their own language, not the user's settings: Persian quotes (and Setad
proformas), quote terms text, tender proposal summaries and the order documents below always use Jalali dates and
Persian digits; English outputs use Gregorian dates and Latin digits (`quotes.output.output_style`). The UI still
follows the user.

Module `app/modules/execution/` (all tables in `ops`, audited by `core.audit_row`).

| Table | Content |
|---|---|
| `sales_order_sequence`, `purchase_order_sequence` | gap-free numbers per year of the user's calendar (`SO-1405-0001`, `PO-1405-0001`), handed out under a row lock like quote numbers |
| `sales_order` (+ `sales_order_item`, `sales_order_change`) | the customer's order: source quote / tender proposal / manual, customer and contact, customer ref, contract date, signed document, currency, price basis, Incoterm, payment and delivery terms, delivery due date and place, warranty months, performance guarantee; status draft → confirmed → in_progress → delivered → closed (Phase 9) / cancelled; amendments after confirmation (field, old, new, reason, document) |
| `purchase_order` (+ `purchase_order_item`, `purchase_order_change`) | one per supplier (and currency): number with `-v2` revisions (`supersedes_id`), language, terms text (`po_terms` templates), ready date, `direct_to_customer`; status draft → approved → sent → confirmed → in_production → ready → shipped → received → closed / cancelled / superseded; ready-date history |
| `payment_milestone` (+ `payment_record`) | money in (customer, on a sales order) or out (supplier or other, on a PO or the case): percent of the order or amount + currency, due date or event; status expected / partly / done derived from the payment records; cancelled with a reason |
| `process_template` (+ `process_template_step`), `process` (+ `process_step`) | checklists per deal type (import, export, domestic; three seeded, editable as data): group, code, labels fa/en, the reference a step produces, needs-a-document, default offset days; per case one process per deal type with status, reference, started / done / due dates, document (or a reason), remind days |
| `shipment` (+ `shipment_item`, `shipment_event`, `shipment_document`) | inbound / outbound, mode, carrier / forwarder / insurer, transport document kind and number, containers, ETD / ETA / ATD / ATA, `first_eta`, status; events (an ETA / ETD change writes one), documents by kind |
| `inspection` | pre-shipment / on arrival / third party / internal; result; items checked (jsonb) |
| `receipt` (+ `receipt_item`) | goods received from a supplier: quantity and condition ok / damaged / short per PO item |
| `delivery` (+ `delivery_item`) | deliveries to the customer with the receipt document («رسید انبار» / «صورتجلسه تحویل») |
| `claim` | against supplier / carrier / insurer or from the customer: kind, links (PO, shipment, receipt, delivery, inspection), items (jsonb), claimed and resolved amounts (informational until Phase 9), status open → submitted → negotiating → resolved / rejected / withdrawn |
| `execution_followup` | which parties follow-up BOMS created for which order / step / claim (purposes po_confirm, po_ready, step_reminder, claim, invoice, warranty_end) |

**Sales order.** Created from an accepted or partially accepted quote (its accepted items only, with prices and
terms; the case offers a «Create sales order» prompt, nothing is created automatically), from a won tender's approved
proposal (organizer as customer, performance guarantee linked) or by hand from the case's `sold` items. One open order
per quote / proposal (409 `order_exists` with its id). Confirmation needs the signed document or the reason
«بدون سند امضاشده» (kept and in the event); confirming creates the process checklist of the deal type of the current
cost sheet (hook). After confirmation, quantities, prices, delivery dates and terms change only through an amendment
(`POST /api/sales-orders/{id}/amend`); a quantity never goes below what was delivered. The order acknowledgement is
printed / PDF / Word in fa or en with a DRAFT mark until confirmed.

**Payment milestones and cash.** A percent resolves against the order total. Payment records derive the status; a
paid milestone is never deleted (reverse the record with a reason, or cancel). The case's cash position (received,
paid, net tied up per currency, still expected) is shown next to the Phase 6 computed exposure. Ordering gate: sending
a PO while the order's customer prepayment milestone is still `expected` gives 409 `customer_prepayment_missing`
unless `confirm_without_prepayment` with a reason (kept on the PO and in the event; the Phase 5 wording).

**Purchase orders.** "Create POs" groups a confirmed order's items by the supplier and currency of each item's
selected offer, prefilled from the offer (the cost sheet's own purchase-price rule) and the `po_terms` template of the
PO language (supplier in Iran → fa); items without a selected offer are listed. Approval locks the numbers and checks
the price against the current cost sheet's purchase price of the item (same currency) plus
`execution.po_price_tolerance_percent`; above it, 409 `po_above_cost_sheet` unless confirmed with a reason. Mark sent
records an outgoing interaction with the follow-up «پیگیری تأیید سفارش» after `execution.po_confirm_days`; the
supplier's confirmation closes it, keeps a changed ready date in the history and creates «پیگیری آماده شدن»
`execution.ready_followup_days_before` the ready date. Production statuses are set by hand; `received` follows the
receipts.

**Process checklists.** Due dates are the confirmation day plus each step's offset; reminders (default
`execution.step_reminder_days`, per step editable) are parties follow-ups that move with the date and are cancelled
when the step is done or not applicable or the case is lost / cancelled / closed. A step that needs a document is not
done without one unless a reason is given (CHECK `process_step_document`, 422 `document_required` before it). On a
domestic checklist «PO sent» and «goods ready» follow the PO.

**Shipments and receipts.** Shipped quantities of a PO item never exceed its ordered quantity (422 `over_shipped`).
Delay warnings: ETA passed without ATA; ETA later than the first ETA by more than `execution.delay_warning_days`; a
PO ready date passed while the PO is not ready. A failed inspection, and a receipt with damaged or short lines, offer a
prefilled claim. A PO delivered directly to the customer takes no receipt.

**Claims.** Each status change is an event; while open there is always one open «پیگیری ادعا» on the counterparty,
the next created `execution.claim_followup_days` after the previous is done (hourly job `execution.claim_followups`).

**Deliveries and item status.** The delivered quantity of an order item never exceeds the ordered one
(422 `over_delivered`). `recompute_item_status` stays the only place that derives item status: `cancelled` and
`closed` are frozen; `delivered` is set and cleared only from delivery quantities through a registered delivered
check (an item marked delivered before v0.7.0 without delivery data stays as it is); otherwise `sold` as Phases 6 / 7b
set it. When every item is delivered the order becomes `delivered` and BOMS creates «صدور فاکتور و پیگیری تسویه»
(`execution.invoice_followup_days`), the warranty end as a follow-up on its date and, with a linked performance
guarantee, its release reminder (Phase 7b). Reversing a delivery (reason required, while the order is not closed)
recomputes everything and cancels those follow-ups.

Hooks and registries (new ones marked *new*):
- `sourcing.items.register_delivered_check` (*new*) — `delivered` from delivery quantities;
- `sourcing.inquiries.register_case_status_changed` — a lost / cancelled / closed case cancels step reminders;
- `sourcing.inquiries.register_case_cleanup(1, …)` — the case cascade delete removes every execution row and cancels
  its follow-ups, before tenders (5), quotes (10) and cost sheets (20); files stay in the store;
- `execution.sales_orders.register_order_confirmed` (*new*) — the checklist on confirmation;
- `execution.purchase_orders.register_process_hook` (*new*) — PO events that tick domestic steps;
- `parties.command_center.register_section("execution", …)` — «اجرا»: POs sent and not confirmed after
  `execution.po_confirm_days`, ready dates passed, shipments late or delayed, steps due within 3 days or overdue,
  payments past due (in and out), open claims, sales orders with delivery due within 7 days or overdue;
- `parties.references` — sales orders, POs, claims, shipments, inspections and milestones count against a party delete;
- `execution/searchable.py` — orders and POs (number, customer / supplier, refs), shipments (transport document,
  containers), process step references (order registration, kotaj), claims;
- `sourcing.templates` — template kind `po_terms` with its placeholders (`supplier_name`, `contact_name`,
  `payment_terms`, `incoterm`, `ready_due_on`, `delivery_place`, `delivery_terms`, `case_title`, `signature`).

A confirmed sales order, an approved or sent PO, a delivery of a closed order and a paid milestone are never deleted
one by one (cancel or reverse). Validation convention as elsewhere: CHECK violations 422 with the constraint name,
unique / still referenced 409.

## Internal tasks and deal finance (Phase 9, v0.8.0, migrations `0014_tasks`, `0015_finance`)

### Tasks instead of party follow-ups (section 0.1)

Module `app/modules/tasks/` owns `core.task` (title, due date and optional time, status open / done / cancelled with a
done note — a cancel needs one, priority, the case and party as context only, `source` / `source_kind` / `source_id`,
`remind_of_due`, `remind_days_before`, notes; audited). Kinds: `tender_date`, `process_step`, `guarantee_expiry`,
`warranty_end`, `warranty_remind`, `opening`, `contract`, `invoice_issue`, `manual`. Public service `tasks.service`:
create, update, move, done, cancel, reopen, `tasks_of`, `cancel_by_source`, and `sync` (one task per remind day before
a date, moved with it, cancelled when the date goes away or the source is done / closed / deleted; none for a date that
has passed). A task never appears on a party's follow-up list.

`tenders.reminders` and `execution.followups` keep their call signatures and route by purpose: internal purposes
(`date_reminder`, `guarantee_expiry`, `opening`, `contract`; `step_reminder`, `invoice`, `warranty_end`,
`warranty_remind`) are tasks; counterparty purposes (RFQ chases, `po_confirm`, `po_ready`, `claim`,
`guarantee_release`, manual follow-ups) stay parties follow-ups. Both return `(link, item)` pairs with the same
attributes, so callers do not care which kind they hold.

Migration `0014` moves every follow-up linked through `ops.tender_followup` / `ops.execution_followup` with an internal
purpose into a task (same due date, status, done note, case, party, source record, days before; `due_at` from the
tender date), records an event `task` / `reminders_moved` with the counts per kind, and deletes the link rows and the
original follow-ups (the audit trigger keeps them). Downgrade drops `core.task` (moved reminders are not turned back).

API: `GET /api/tasks` («کارهای من»: overdue, today, this week, later, done; filters `case_id`, `kind`, `q`),
`GET /api/cases/{id}/tasks`, `POST /api/tasks` (manual), `PATCH /api/tasks/{id}`, `POST .../done|move|cancel|reopen`.
Command center section `tasks` (overdue, today, tomorrow). The case's tasks are deleted by the case cascade (order 0);
the party counter `tasks` is non-blocking.

Other section-0 changes: the ordering gate passes only when every customer prepayment milestone is `done` (409
`customer_prepayment_missing` lists received / expected); sending an already sent or confirmed PO gives 409
`purchase_order_already_sent`; a claim's counterparty defaults from its link (PO / receipt / inspection → the PO's
supplier, shipment → carrier, delivery → customer); the PO price check converts across currencies with the cost
sheet's FX entries (direct, reverse or through the pricing currency) and flags an item `fx_missing`
(«نرخ ارز در برگهٔ هزینه نیست») instead of skipping it; a warranty reminder task `execution.warranty_remind_days`
(default 30) before the warranty end.

### Finance (module `app/modules/finance/`, schema `ops`)

| Table | Content |
|---|---|
| `invoice_sequence` | gap-free numbers per prefix and year of the user's calendar, handed out when an invoice is issued: `INV-`, credit notes `CN-`, debit notes `DN-` |
| `sales_invoice` (+ `sales_invoice_line`) | from a sales order: kind invoice / credit_note / debit_note (`corrects_invoice_id` for notes), language fa (domestic) / en (commercial invoice), customer, issue and due date, currency, price basis, subtotal, discount, VAT percent and amount (+ note), total, status draft → issued / cancelled, Moadian tax ID / status / date / note, export fields (Incoterm, origin, marks, weights, packages, transport document, shipment); lines with the sales order item, unit, price, discount, HS code |
| `purchase_invoice` (+ `purchase_invoice_line`) | supplier invoices on a PO or without one: supplier invoice number (unique per supplier unless cancelled), dates, currency, subtotal, VAT, total, status received / approved / disputed / cancelled, difference reason, dispute reason and claim, document |
| `actual_cost` | freight, insurance, bank fees, customs, levy, clearance, storage, inspection, domestic freight, export clearance, other: party, amount + currency, own FX rate and base amount, input VAT, incurred / due date, document, status expected / incurred / paid (paid derived), shipment / PO |
| `payment_allocation` | a payment record to exactly one sales invoice, supplier invoice or actual cost: amount in the payment currency, `fx_rate` when the target's currency differs, target amount |
| `deal_result` | the frozen profit computation of a closed case, the reasons given at close, who closed it |
| `party_rating` | per closed case, party and role: quality, timeliness, communication, price (supplier) or payment behavior (customer), 1–5, a one-line note |

Owned by their modules (same migration): `core.party.national_id`, `economic_code` (parties; the buyer IDs of a
domestic invoice) and `ops.payment_record.fx_rate_to_base`, `base_amount`, `rate_source`, `bank_fee` +
`bank_fee_currency` (execution).

**Sales invoices.** Lines default to delivered-but-not-invoiced quantities (`delivered − invoiced`, invoiced counting
drafts and issued invoices); more than delivered needs a reason (kept and in the event), more than ordered is 422
`over_ordered`; several invoices per order; `POST /api/sales-orders/{id}/invoice-rest` creates the rest in one call.
Issue requires the seller's name, national ID and economic code and, on a domestic invoice (fa to an Iranian
customer), the buyer's national ID and economic code (economic code not for a person): 422
`issue_requirements_missing` lists them. Issue assigns the number and the due date (`finance.payment_days`, default
30), locks the invoice (409 `invoice_locked`) and sets Moadian `not_sent` on a domestic invoice, `not_required`
otherwise; the owner registers it in سامانه مودیان himself and types the tax ID and status. VAT: the `vat` tax
parameter in force on the issue date for the case's deal type on a domestic invoice, 0 on an export one; another
percent needs a note. Corrections are credit / debit notes (a credit note never exceeds the invoice with its notes);
cancel needs a reason, no allocations and no issued notes, and keeps the number. Outputs: print, PDF and Word on the
quote output engine (fa: the Iranian layout, seller / buyer blocks with IDs, amount, discount, after discount, VAT and
total per line, the total in Persian words, Jalali and Persian digits; en: commercial invoice with HS codes and
shipping data, Gregorian and Latin digits; a DRAFT mark before issue).

**Supplier invoices.** From a PO the supplier, currency and lines (received not invoiced, at the PO price) default.
Matching per PO item: ordered, received, invoiced on all supplier invoices of the PO, on this one, PO price, invoice
price, flags `invoiced_above_received`, `invoiced_above_ordered`, `price_difference` (and lines without a PO item).
Approving with differences needs a reason (409 `invoice_differences`); a disputed invoice can link to a claim of the
case. Approved invoices are never deleted (cancel them).

**Payments and allocation.** A payment record not in the base currency (`finance.base_currency`, IRR) needs its real
rate (422 `fx_rate_required`); `base_amount = amount × rate` rounded by the base currency. Older records without a rate
show «نرخ ثبت نشده» and are completed with `PATCH /api/payment-records/{id}`. A bank fee is an actual cost (kind
`bank_fees`, read-only, at the payment's rate). Allocation (`POST /api/payment-records/{id}/allocations`, all or
nothing): money in pays sales invoices and debit notes of the same customer, money out pays supplier invoices of the
same supplier and actual costs; a target in another currency needs `fx_rate` (1 payment unit in the target currency);
over the payment's unallocated amount or the target's open balance is 422. The suggestion is oldest-first (due date)
over the party's open targets in the payment's currency (others listed as `needs_rate`). An allocation made by
mistake is reversed with a reason (event; refused on a closed deal). Unallocated money in is an advance.
Invoice balance = total − allocations (+ issued debit notes − issued credit notes); status unpaid / partly_paid / paid
/ overpaid.

**Actual costs.** Owned rows carry their own rate (required when foreign); expected / incurred is the owner's and
`paid` follows the allocations. Read-only rows come from their modules, never copied: tender costs (a refundable
deposit once refunded is excluded), guarantee fees, payment bank fees. Goods are supplier invoices, never a cost row.

**Profit (`finance.profit`, read-only).** Revenue = issued sales invoices net of VAT (subtotal − discount), credit
notes negative. Cost by cost-sheet line kind: goods = approved supplier invoices (subtotal; one without a PO counts as
`other`) plus received goods not on an approved invoice at the PO price (`estimated`); actual costs by kind (expected
ones `estimated`) and the read-only rows; claim resolutions from a supplier / carrier / insurer (credit note, refund,
discount) lower goods / freight / insurance (a credit given to the customer is a sales credit note). Plan: the final
cost sheet of the accepted quote or approved proposal (else the current sheet) limited to the sales order's items:
per line kind, revenue = total price, cost = sum of the kinds; cost of money and guarantee are information lines.
Values: an amount in the base currency is itself; a paid foreign amount is valued at its payments' real rates
(Σ allocation base / Σ allocation target), an actual cost at its own rate, the rest at the latest rate entered on the
case (payments and costs by date, else the sheet's) and reported as `unrealized`; the deal-currency figure is the
amount itself when in the deal currency, else base ÷ the latest deal-currency rate. FX effect
«سود/زیان تفاوت نرخ ارز» = Σ over foreign amounts of (value at the sheet's rate − real value) for costs and
(real − sheet) for revenue. Variance = actual − planned, variance % = variance ÷ planned. Margin = profit ÷ revenue,
markup = profit ÷ cost. VAT is outside profit: output VAT (issued invoices, credit notes negative), input VAT
(approved supplier invoices and actual costs), net. Actual cost of money = Σ over the periods between payment dates
of the rial cash tied up (out − in, when positive) × days × the sheet's annual percent ÷ 365. Open deals also show an
expected profit (actual where a kind has actuals, else planned; revenue at least the sales order's).

**Closing.** `GET /api/cases/{id}/close-checklist` lists every problem together: items still sold, delivered not
invoiced, invoice drafts, invoices unpaid, Moadian not accepted / not required, supplier invoices not approved or not
paid, received goods without a supplier invoice, costs unpaid, open claims, open milestones, guarantees not released
(a running performance guarantee or warranty is a note, allowed, keeping its tasks), and the open tasks and follow-ups
closing cancels. `POST /api/cases/{id}/close` passes with no problems or a reason per problem code (409
`close_checklist`), and with `confirm_cancel_open` when there is something to cancel (409 `open_tasks`); it stores the
`deal_result` snapshot, sets the case `closed` and the items `closed` through `recompute_item_status` (event
`deal_closed`). A closed deal is read-only: a session `before_flush` guard refuses any write of an execution or finance
row of a case with a deal result (409 `case_closed`), except during close / reopen / the test-data cascade; notes,
ratings, documents and tasks stay writable. `POST /api/cases/{id}/reopen` (a reason) removes the snapshot (event
`deal_result` / `removed`), sets the case `open` and derives the items again. Ratings: `POST /api/cases/{id}/ratings`
for the customer and each supplier with a PO, only on a closed case; one per party, role and case.

**Workspace and exports.** `/api/finance/receivables` (aging 0–30 including not yet due, 31–60, 61–90, 90+ by days
past due; by customer and currency; unallocated advances), `/payables` (supplier invoices and costs: overdue, within 7,
within 30, later), `/invoices` (sales or purchase; status, Moadian, period, party, case), `/payments`, `/deals` (one row
per case with a sales order; planned and actual revenue, cost, profit, margin), `/vat` (per month of the user's
calendar, in rials, information only). CSV (`/api/finance/exports/{sales_invoices|purchase_invoices|payments|
actual_costs|deals|receivables}.csv`): UTF-8 with BOM, headers in the user's language, every date in the user's
calendar followed by an ISO column; `/api/finance/exports/all.zip` zips them for a period (stdlib `zipfile`).

**Hooks and integrations.** New registries: `sourcing.items.register_closed_check` (closed set and cleared only by the
deal), `sourcing.inquiries.register_case_status_guard` (a deal with a sales order is closed / reopened only through
finance: 409 `use_close_deal` / `use_reopen`), `sourcing.capabilities.register_suggestion_extra` (the supplier rating
average next to each Phase 5 suggestion; the ranking is unchanged). Finance registers: command center section
`finance` (receivables overdue, payables due within 7 days or overdue, delivered not invoiced, received without a
supplier invoice, Moadian not sent / rejected, payments without a rate, cases ready to close), search providers
(invoice numbers and Moadian tax IDs, supplier invoice numbers, payment references), party counters (`sales_invoices`,
`purchase_invoices`, `actual_costs`, `ratings`; 409 with counts), the case cascade (order 0, before execution: every
finance row of the case, a closed one included). Party page: a finance tab (receivable / payable and overdue per
currency, invoices, ratings) and the national ID / economic code fields. Settings: `finance.base_currency`,
`finance.payment_days`, `finance.supplier_payment_days`, `execution.warranty_remind_days`.

## AI and data foundation (v0.9.0, migrations `0016_carryover` … `0020_noun_modifier`)

### Reference data (module `reference`, schema `ref`, migration `0017_reference`)

- Tables: `location` (UN/LOCODE: country, 3-character location code, full code, name, name without diacritics, curated
  `name_fa`, subdivision, function flags, coordinates, IATA, `verified` when confirmed by an official UNECE file),
  `airport` (IATA / ICAO from OurAirports, linked to a location by IATA), `legal_form` (ISO 20275 ELF plus Iranian and
  common forms curated by BOMS, with abbreviations), `container_type` (ISO 6346), `transport_mode` (UN/ECE Rec. 19),
  `incoterm` (Incoterms® 2020, 11 rules), `dataset_import` (one row per import with its report). `sys.unit.unece_code`
  carries UN/ECE Rec. 20.
- `python -m app.cli reference-import <dataset> [--file path] [--release r]`: idempotent upsert with a report (inserted,
  updated, deactivated, unchanged, rejected with reason). It accepts a CSV, a `.gz`, a folder or a zip of CSV parts, so
  the owner can load an official file later (Settings → «داده‌های مرجع» does the same through the API). Nothing is ever
  fetched at runtime. The shipped files and their sources are listed in `app/modules/reference/data/SOURCE.md`.
- References on business rows are new nullable columns next to the text fields that stay: shipment origin /
  destination, shipment event location, Incoterm place on quotes, sales orders, POs and invoices, party legal form;
  `ops.shipment_container` gives each container number (ISO 6346 check digit validated) its size/type code.
- Display rule: the code next to the name. Routes «شانگهای SHA ← بوشهر BUZ» (fa) / "Shanghai SHA → Bushehr BUZ" (en),
  air routes by IATA; Incoterms in the citation format "CFR Bandar Abbas (Incoterms® 2020)"; English outputs show the
  UN/ECE unit code next to the unit.
- Downgrade archives the references set on business rows (by natural key) and the container rows in
  `sys.downgrade_archive`; a later upgrade, once the reference rows exist again, puts them back.

### Codes (module `codes`, schema `core`, migration `0018_codes`)

- `core.code_sequence (kind, scope, last_number)`: `codes.next(kind, context)` takes the next number in the creating
  transaction with `INSERT … ON CONFLICT DO UPDATE … RETURNING` (the row stays locked until commit, a rolled-back
  creation gives its number back: no gaps, no duplicates). The scope is the rendered prefix of the pattern, so a pattern
  change simply starts its own sequence and never touches existing codes.
- Patterns are settings `codes.pattern.<kind>` (tokens `{yyyy}` user's calendar year, `{0000}` number, `{country}`,
  `{role}`, `{hs4}`). Kinds: inquiry INQ, case CS, RFQ, tender TDR, shipment SH, receipt RCV, delivery DLV, payment PAY,
  claim CLM, inspection INS, guarantee GTE, contract CT and letter LT (reserved), party SUP/CUS/BP-{country} by the
  roles at creation (never changes), product PRD-{HS heading}. PI, SO, PO, INV, CN, DN numbering moved onto the service
  with their existing sequences carried over (no number changed).
- Modules register their coded tables (`codes.register`); a `before_flush` listener (installed by the API and the
  worker) gives every new registered row its code, so creation paths did not change. Codes are unique, searchable (the
  search ranks exact codes first) and `resolve` opens a record from a typed code.
- Migration 0018 coded every existing row in creation order per kind and year (event `codes` / `backfill` with counts);
  a downgrade archives the codes and a later upgrade gives every row its archived code back.

### Folder view, naming, document control (module `documents`)

- `documents/folders.py`: a derived, read-only view per case under `<data folder>/پرونده‌ها/<code> <title> - <party>/`
  with numbered sub-folders (۰۱ درخواست … ۰۸ مکاتبات, ۰۹ مناقصه only with a tender); the link kind decides the folder
  (setting `folders.mapping`). Files are NTFS hard links to the store (copies when another volume; Settings says
  which). A `folders.sync` job is queued (at most one waiting) when links, case code / title / party or document
  references change; `python -m app.cli folders-rebuild` rebuilds it. Names are sanitised for Windows (reserved names,
  characters, trailing dots, length) and long paths use `\\?\`. The store stays the only source of truth and the only
  thing backed up; the view is never backed up or restored. «باز کردن پوشه» opens Explorer only for a request from the
  PC itself.
- `documents/naming.py`: outputs are named `{code}_{type}_{party}_{date}[_v{n}][_DRAFT].{ext}` in the document's
  language (setting `naming.output`); the RFQ Excel is named by its code; subjects start with `[code]`; message
  templates have a `{code}` placeholder; Persian letters carry «شماره» and «تاریخ» lines.
- `documents/control.py`: every output (quote / proforma, sales order, PO, invoice and notes, tender proposal) gets a
  status stamp (پیش‌نویس / DRAFT, صادرشده / ISSUED, جایگزین‌شده / SUPERSEDED, باطل / VOID), a footer (code, version,
  «صفحهٔ x از y» / "Page x of y" in the page margin box, generation date) and a QR code (segno) with
  `BOMS|{code}|v{n}|{issue date}|{verification code}`. The verification code is the first 10 base-32 characters of
  HMAC-SHA256 over those fields with a key derived by HKDF-SHA256 from the session key under the label `doc-verify`.
  `POST /api/verify-document` («تأیید سند») checks it and shows the record and its current status. Word outputs get the
  same stamp, PAGE / NUMPAGES fields and the QR picture.

### AI layer (module `ai`, schema `ai`, migration `0019_ai`)

- `ai.provider` (claude_subscription, anthropic_api, openai_api, gemini_api, ollama, openai_compatible; the API key in
  Windows Credential Manager under `secret_name`, read by `core.secrets.get_named_secret`, never in the database or
  files), `ai.price` (USD per million tokens per provider and model; an API provider is enabled only with prices),
  `ai.route` (per task kind: primary and fallback provider + model, privacy `cloud` / `cloud_redacted` / `local_only`),
  `ai.call` (the privacy log), `ai.draft` + `ai.draft_field`, `ai.correction`, `ai.case_setting` («فقط محلی»).
- Adapters (`ai/adapters.py`) behind `generate(request) -> result` with usage and timing. HTTP adapters use httpx only
  (Anthropic Messages API with `anthropic-version` and structured `output_config`, OpenAI chat completions, Gemini
  `generateContent`, Ollama `/api/chat`, OpenAI-compatible); tests replace the transport with a fake. The subscription
  adapter drives the Claude Agent SDK (its wheel bundles the Claude Code CLI) in a temporary folder holding only the
  call's inputs, with Read as the only tool, every other tool denied and a permission callback that refuses any path
  outside that folder; the folder is removed after the call.
- Routing (`ai/service.py`): primary, then fallback on error, timeout, rate limit or exhausted quota, when the privacy
  level and the cap allow it; every attempt is logged. Privacy: `local_only` (or a «فقط محلی» case) skips cloud
  providers; `cloud_redacted` replaces names of the case's parties and contacts and the owner's company, e-mails,
  phones, IBANs and national / economic IDs by placeholders and restores them in the answer; local providers (Ollama, an
  OpenAI-compatible server on the PC or LAN) get the text as written.
- Cap: setting `ai.monthly_cap_usd` (default 20, 0 = no API route); before an API call the estimated cost must fit the
  month's remaining budget, else the attempt is logged `cap_reached` and, with nothing else allowed, the task answers
  409 `ai_cap_reached` while local tasks continue. Warnings at 50 % and 80 % in Settings and the command center.
- Prompts live in `ai/prompts/<task>/<version>.md`; the version is logged per call. Every task declares a JSON schema;
  the answer is parsed and validated (`ai/schema.py`), retried once with the errors, then reported as failed. Numbers
  are recomputed by code (quantity × unit price against a stated total) and differences are flagged.
- The log (`ai.call`) holds the input description (file names, pages, characters, images, redaction counts), never
  the content; retention `ai.log_retention_days` (nightly job `ai.purge_log`).
- Execution: tasks run as jobs on the `ai` lane (a second worker thread), so backups and other jobs never wait on a
  model. `tasks.start` creates a pending draft and queues the job; the UI polls the draft.
- Drafts: field by field with confidence and source reference; «پذیرش همهٔ موارد مطمئن», accept / edit / reject;
  «ثبت» calls the target's committer, which writes through the owning module's services with event source `ai_draft`.
  Edited fields are stored in `ai.correction` and the last ones are added to the next prompt of the task as examples.
- Tasks (`ai/builtin.py`): item extraction into a case, an inquiry, a supplier offer (with its supplier, matched to the
  case items) or a Setad listing conversion (from the downloaded attachments; the accepted items replace the listing's
  items table in the conversion); PDF text by PyMuPDF and scanned pages as images, Excel/CSV with the proposed column
  mapping, pasted text; paste to parse a party and its contact; RFQ message and PO cover message drafting with a
  Persian back-translation (the owner sends; BOMS sends nothing).

### Noun-modifier descriptions (module `catalog`, migration `0020_noun_modifier`)

- `core.product_template`: noun fa/en and ordered attributes (text, number with UN/ECE unit and range, or a choice of
  values) with the ones that form the short description. Seeded: pump, valve, pipe, flange, gasket, mechanical seal,
  electric motor, resin/chemical. Products and line items gain `template_id`, `attributes` (validated), `canonical_fa`,
  `canonical_en` and `canonical_override`; `catalog/nounmod.py` builds `PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m` /
  «پمپ، گریز از مرکز، API 610، ۱۲۰ مترمکعب بر ساعت، ۸۵ متر». Quotes and sales orders use the canonical description in
  the document's language when there is one.

### Smart fields (module `lookup`)

- `GET /api/lookup?kind=…&q=…`: one contract for party, contact, product, case, location (function filter), airport,
  currency, unit, HS, ISIC, Incoterm, legal form, container type and record codes; Persian normalisation as in the
  database; ranking exact code (incl. the UN/LOCODE location part and ICAO), code prefix, name prefix, contains,
  trigram; each result returns id, code, names fa/en and a subtitle.
- `GET /api/suggest?context=party|product|case&id=…`: proposed values with their source record (the last sales order or
  quote of a buyer, the last PO or offer of a supplier, the product's last purchase and sale, the case's parties,
  currency and Incoterm).
- `GET /api/validate?kind=…&value=…`: IBAN (ISO 13616), BIC (ISO 9362), Iranian national ID (10 and 11 digits),
  economic code, Chinese USCC (GB 32100-2015), phone (E.164), e-mail, container (ISO 6346). The same rules run in the
  browser (`lib/smart.ts`) while typing; the backend checks again.
- `/api/calc/*`: line totals, margin and markup, conversion at the latest rate on the case, amount in words fa/en,
  time left.
- Shared components (`components/smart.tsx`): `LookupField`, `SuggestedValue`, `ValidatedInput`, `CodeChip`,
  `AmountInWords`; their logic is in `lib/smart.ts` (tested without a browser). `LookupField` acts only on results for
  exactly what is typed.

## Design system and live updates (v0.10.0, migration `0021_live_updates`)

v0.10.0 is presentation only, apart from the carry-over of section 0, the change feed and the structured bank fields.
**Rule: new UI uses only the library in `frontend/src/design/` and the app pickers in `frontend/src/components/fields.tsx`.**
There is no second set of components and no page-level CSS.

### Tokens and themes (`design/tokens.css`, `design/tokens.ts`)

- Every colour, radius, shadow, motion duration and z layer is a CSS custom property. `:root` / `.theme-light` is the light
  theme «جوهر و برنج»; `:root.dark` / `.theme-dark` the dark theme «نیمه‌شب و طلا». Tailwind v4 reads them through
  `@theme inline`; the default Tailwind palette is removed (`--color-*: initial`), so only token colours exist.
- Type scale `text-2xs … 5xl`, radii `xs … 3xl`, motion 150–250 ms (off under `prefers-reduced-motion`), the rail width.
- `tokens.ts` reads both themes and computes WCAG contrast for every text/surface and status pair (`contrastTable`);
  the unit test fails below AA.
- Theme setting: light, dark or system (follows the OS live). `public/theme-init.js` sets it before the first paint
  (CSP forbids inline scripts).
- Fonts: Noto Naskh Arabic (OFL) bundled in `design/fonts`; nothing is fetched at run time.
- `scripts/check-design.mjs` (part of `npm run lint`) fails the build on physical-direction classes, colour literals,
  pixel font sizes and arbitrary spacing.

### Component catalogue (`design/components/`, shown at `/design` in developer mode)

| Group | Components |
|---|---|
| primitives | Button, ButtonLink, IconButton, TextLink, Badge, Status, Chip, Kbd, CodeChip, Tooltip, Spinner, Bdi, Icon |
| forms | Field/FormRow (with source chip), Input, Textarea, Select, Checkbox, RadioGroup, Switch, Segmented, Combobox, DatePicker/DateInput (Jalali and Gregorian), MoneyInput, QuantityInput, FileDrop (full and compact) |
| smart | LookupField (`/api/lookup`, create option), SuggestedValue (source chip, Tab accepts), ValidatedInput (IBAN, BIC, national ID, container …), AmountInWords |
| containers | Card, Section, Tabs/ScrollTabs, Modal, Drawer, Popover, Menu, ConfirmDialog, Toast (focus trap and return) |
| data | DataTable (sort, keyboard rows, selection, dense), Pagination, DescriptionList, Timeline, DatedTimeline, Stepper, KpiTile, Stat, ProgressBar, ProgressRing |
| charts | Sparkline, Bars, ProfitBridge, CashFlow, RouteLine — each with a text alternative (a table or `aria-label`) |
| feedback | Skeleton, Loading, EmptyState (with its next action), ErrorState (with retry), InlineAlert, ErrorNote, Busy |
| layout | Breadcrumb, PageHeader, PageGrid (side column) |

App pickers (`components/fields.tsx`), all on the smart fields: CurrencyField, UnitField, IncotermField, CountryField,
ProductField, PartyField (search or create, duplicate check), ContactField, PartyChoice, and MoneyNote (line total,
conversion at a rate, amount in words). They send the same values as the v0.9.0 pickers they replace.

### Page patterns

- Shell (`shell/AppShell.tsx`): collapsible rail, top bar (command palette Ctrl+K, quick add, theme, language,
  shortcuts sheet, lock, user), skip link, live dot. Pages render inside a full-height wrapper, so a workspace page
  (listings) can fill the screen with its own scrolling table.
- Every page: `PageHeader` (breadcrumb, eyebrow, title, code, status, actions); data regions show a skeleton, an
  `EmptyState` with one next action, or an `ErrorState` with retry; wide tables scroll inside their own box.
- Pages with a reference mockup (`docs/design-reference/`): command center (`overview` section), case (deal path, side
  column, route card), listings and quick triage (`tenders/triage`, keys S/R/D), finance (profit bridge, deal cash flow),
  tender (countdown, dated timeline, envelopes in columns), shipment, party, AI review, AI settings.

### Change feed and live updates (module `live`)

- `GET /api/live/changes?since=` and `GET /api/live/stream` (server-sent events, `Last-Event-ID`) read what the worker,
  the Setad agent and the server wrote: `sys.job` status, `core.event` record changes, `ext.listing_file` downloads,
  `ext.harvest_run` and `ext.agent_status`. Rows are read with a 10 s overlap; each notice has a stable `key`, names
  what changed and never its content. Each source is read newest first up to 300 rows; `overflow: true` tells the
  browser to refresh everything shown. `0021_live_updates` adds the `updated_at` indexes.
- `/api/live/*` does not refresh the idle lock.
- Browser: `LiveUpdatesProvider` maps notices to query roots (`lib/live.ts`), falls back to polling after three stream
  errors; `useJob` / `useJobRunner` keep a job's button busy until the job finishes, so it cannot be submitted twice.

### Structured bank details (setting `company.bank`)

Bank name and account holder per language, IBAN and BIC (validated and normalized by `lookup/validators.py`) and other
lines. Saving them composes `company.bank_details` per language, which quotes, proformas and invoices keep printing as
before; the letterhead page shows the same lines as a preview (`lib/bank.ts` mirrors `settings.bank_text`).
