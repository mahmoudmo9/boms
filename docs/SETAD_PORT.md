# Setad connector: port from SetadSuite v0.9.23

The site-reading code of the owner's desktop tool SetadSuite v0.9.23 (`reference/SetadSuite_v0.9.23/`, read-only,
never imported or shipped) was copied into `backend/app/connectors/setad/`. Only the Qt/thread plumbing, the
SQLite storage and the import paths were changed. Everything that talks to the site is unchanged.

## File and function mapping

| SetadSuite v0.9.23 | BOMS | Change |
|---|---|---|
| `setad_tender/bridge.py` (all: `SetadBrowser`, JS snippets, `friendly_error`, `redact` use, role page, «فراخوان‌های من», documents, download, recorder, diagnostics) | `connectors/setad/bridge.py` | `SetadBrowser.open()`: persistent profile in the given folder (BOMS: `<data folder>/connectors/setad/browser_profile`) instead of a temporary one; channel order Edge → Chrome → Playwright Chromium (was Chrome → Edge); optional `headless`, `launch_extra`, `on_context` for the offline fake host only. |
| `setad_tender/parsers.py` | `connectors/setad/parsers.py` | none |
| `setad_tender/lifecycle.py` | `connectors/setad/lifecycle.py` | none |
| `setad_tender/dates.py` | `connectors/setad/dates.py` | `jalali_of` no longer imports `g2j` from the Qt module `widgets.py`; `g2j` is copied into `dates.py` unchanged |
| `setad_tender/widgets.py::g2j` | `connectors/setad/dates.py::g2j` | moved, unchanged |
| `setad_tender/worker.py::Worker` (`_sync`, `_sync_my_calls`, `_connect`, `_documents`, `_favorite`, `_unfavorite`, `_download`, `_batch`, `_guarded`, `_dispatch`, `_learn_mapping`, `_persist_learned`, `_after_connect`, `_note_type`, `_session_lost`) | `connectors/setad/tenders.py::Worker` | no `QThread`, no command queue, no `run()` loop: the Setad agent calls `_guarded(cmd, args, browser, store)`. Qt signals are replaced by a small `Signal` class with the same `emit` names. `db` is any store with the `Database` methods (BOMS: `listings.store.ListingStore`). The inquiries hand-off (`attach_inquiries`, `_run_inq`) is gone because the agent drives both engines. |
| `setad_tender/db.py::Database.tender_row`, `extra_fields`, `scalar` | `connectors/setad/rows.py::tender_row`, `extra_fields`, `scalar` | returns the BOMS listing fields (same site field names) and parses Jalali dates to Asia/Tehran datetimes |
| `setad_tender/db.py::Database.add_tenders` (change rows) | `rows.py::tracked_changes` + `listings` store | **bug not ported:** a change is recorded only when a tracked field changes (see below) |
| `setad_tender/db.py` (other methods used by the worker) | `connectors/setad/memory.py::MemoryStore` (tests) and `app/modules/listings/store.py::ListingStore` (BOMS) | same method names on PostgreSQL / in memory |
| `inquiries/engine.py::BrowserEngine` (`_refresh`, `_refresh_search`, `_page_kind`, `_banner_start`, `_rows_if_right_page`, `_resubmit_search`, `_recover_page`, `_load_search_page`, `_wait_captcha`, `JS_SUBMIT_SEARCH`, `_fetch_html`, `_detail`, `_make_background_page`, `_download_one`, `_download`, `_prepare`) | `connectors/setad/eproc_engine.py::BrowserEngine` | not a thread; `emit` calls a callback instead of putting on a queue; always uses the shared `SetadBrowser` (`hub`), so the stand-alone browser launch in `_launch`/`_ensure` is removed |
| `inquiries/parser.py` | `connectors/setad/eproc_parser.py` | none |
| `inquiries/storage.py` | `connectors/setad/eproc_storage.py` | import path only |
| `inquiries/jalali.py` | `connectors/setad/jalali.py` | none |
| `inquiries/pipeline.py` (`DEFAULT_SETTINGS`, `fa_digits`, `fa_text`, `money`, `money_fa`, `parse_amount`, `parse_number`, `number_words`, `norm_text`, `deadline_hours_from_text`, `remaining_text`, `remaining_hours`, `Item`, `items_of`, `detail_field`, `required_validity`, `exact_deadline`, `payment_months`, `find_keywords`, `need_text_for_scan`) | `connectors/setad/pipeline.py` | subset, unchanged. Not ported: stages, `rfq_text`, `Quote`, `quote_warnings`, pricing (`price_plan` …), `proforma_number`, because BOMS's sourcing, costing and quotes modules replace them. |
| `inquiries/app.py::_quick_since`, `_load_last_list` (0.9.23 list rule), `_poll_events` (`clear_needs` / `quick_start` / `needs` handling) | `app/modules/listings/` (harvest runs, `last_full_run_id`) | the rules are kept, the Qt event loop is not |
| `inquiries/db.py::Store.upsert_needs`, `set_exact_deadline` | `listings` store (`response_deadline`, `deadline_exact`) | same rule: the list's countdown only estimates the deadline until the detail page gives the exact one |
| `inquiries/proforma.py` (docxtpl) | not ported | the Setad proforma is a BOMS quote (Phase 6 output + Setad terms template); docxtpl is not a permitted dependency |
| `suite/*`, `inquiries/ui_*.py`, `inquiries/app.py` (UI), `setad_tender/ui.py`, `workspace*.py`, `steps_ui.py`, `dialogs.py`, `widgets.py` (other than `g2j`), `theme.py`, `icons.py` | not ported | Qt UI; replaced by the BOMS screening workspace. The tender workspace (envelopes, guarantees) is Phase 7b. |

## Behaviour changes and reasons

1. **Persistent browser profile in the BOMS data folder.** SetadSuite 0.9.x used a temporary profile per run for
   tenders. The brief asks for `connectors/setad/browser_profile` under the data folder (never in the repo or
   install folder) so the login survives an agent restart. No password, cookie or token is written to the
   database or logs; the profile is the browser's own store.
2. **Edge first.** Edge is always present on Windows 11; SetadSuite tried Chrome first for tenders.
3. **Change tracking.** SetadSuite hashed the whole raw row (minus two countdown fields), so `recCount` and other
   volatile list metadata produced a change row on almost every sync. BOMS records `(field, old, new)` only for
   the tracked fields (`rows.TRACKED_FIELDS`): number, title, organisation, province, city, category, the dates
   (published, documents, proposal, inquiry, opening, edition date and number), document price, guarantee amount,
   estimate, site state, and for purchase calls the response deadline and price validity. Everything else updates
   `raw` silently.
4. **No Qt.** Progress, captcha waits and results go to the agent, which writes `ext.agent_status` and
   `ext.harvest_run` for the UI.
5. **Dates.** Jalali strings are also stored as `timestamptz` (Asia/Tehran); a date without a time gets 23:59 for
   deadlines (SetadSuite's `jalali.to_datetime` default) and 00:00 for published / opening dates. The original
   text stays in `raw`.

## Tests

Ported (`backend/tests/connectors/setad/`):

| Original | BOMS |
|---|---|
| `tests/inquiries/test_parser.py` (all 7) | `test_eproc_parser.py` (imports only) |
| `tests/inquiries/test_pipeline.py::test_jalali_roundtrip`, `test_number_words_and_money`, `test_detail_helpers` | `test_pipeline.py` |
| `tests/tenders/test_browser_detection.py` (all 7) | `test_browser_detection.py` (imports only) |
| `tests/tenders/test_core.py` (all 6) | `test_tenders.py` (`test_db_preserves_user_selection_and_history` and `test_document_tracking_persists` on the in-memory store, with per-field change rows) |
| `tests/tenders/test_lifecycle_v06.py` (all 6) | `test_tenders.py` |
| `tests/tenders/test_v02.py` (all except `test_old_database_is_migrated`) | `test_tenders.py` |
| `tests/tenders/test_v03.py::test_jalali_conversion`, `test_site_titles_come_from_site_headers_first`, `test_group_pairs_sections`, `test_sync_extra_passes_recover_ids_with_other_page_sizes` | `test_tenders.py` |
| `tests/tenders/test_sync_offline.py` | `test_tenders.py::test_unstable_pages_second_pass_recovers_missing_id` (no Qt stubs needed) |

Not ported: `test_pipeline.py::test_rfq_text`, `test_pricing_and_warnings`, `test_store_roundtrip`,
`test_unstar_and_supplier_delete` (SetadSuite's own RFQ text, pricing and SQLite supplier store; BOMS has its own);
`test_proforma.py` (docxtpl); `test_storage_v08.py` (moving the download folder between drives: not in scope);
`test_v02.py::test_old_database_is_migrated` (SQLite migrations); `test_v03.py::test_offer_calculation_and_blockers`,
`test_workspace_db` (tender workspace, Phase 7b).

New for the changed behaviour: `test_port_changes.py` (Edge first with the persistent profile; a `recCount`-only
change writes nothing; only tracked fields are compared).
