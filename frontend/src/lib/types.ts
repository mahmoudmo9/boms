import type { Calendar, Digits } from "./format";

export type Language = "fa" | "en";
export type Theme = "light" | "dark" | "system";

export interface User {
  id: string;
  username: string;
  language: Language;
  calendar: Calendar;
  digits: Digits;
  theme: Theme;
  idle_lock_minutes: number;
}

export interface AuthState {
  user_exists: boolean;
  authenticated: boolean;
  locked: boolean;
  username: string | null;
  language: Language | null;
  theme: Theme | null;
  user: User | null;
}

export interface DocumentItem {
  id: string;
  sha256: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  title: string;
  notes: string | null;
  language: string | null;
  text_status: "none" | "pending" | "done" | "empty" | "failed";
  source: string;
  uploaded_at: string;
  updated_at: string;
}

export interface DocumentLink {
  id: string;
  entity_type: string;
  entity_id: string;
  role: string;
  created_at: string;
}

export interface DocumentDetail extends DocumentItem {
  links: DocumentLink[];
  previewable: boolean;
}

export interface EventItem {
  id: number;
  occurred_at: string;
  actor: string;
  entity_type: string;
  entity_id: string | null;
  action: string;
  data: Record<string, unknown>;
  source: string;
}

export interface Country {
  iso2: string;
  iso3: string;
  name_fa: string;
  name_en: string;
  active: boolean;
  sort_order: number;
}

export interface Currency {
  code: string;
  name_fa: string;
  name_en: string;
  symbol: string | null;
  minor_units: number | null;
  active: boolean;
}

export interface Unit {
  code: string;
  name_fa: string;
  name_en: string;
  kind: string;
  base_factor: string;
  active: boolean;
}

export interface BackupRun {
  id: string;
  kind: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  db_dump_path: string | null;
  db_dump_sha256: string | null;
  db_dump_bytes: number | null;
  files_copied: number | null;
  files_bytes: number | null;
  secondary_status: string | null;
  restore_test_at: string | null;
  restore_test_status: "passed" | "failed" | null;
  restore_test_details: { failures?: string[] } | null;
  details: { error?: string; secondary_reason?: string | null; archive?: { status: string; reason?: string } };
}

export interface RunSummary {
  id: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  db_dump_bytes: number | null;
  secondary_status: string | null;
  restore_test_at: string | null;
  restore_test_status: string | null;
}

export interface Health {
  worker: { last_seen: string | null; alive: boolean };
  jobs: { queued: number; running: number; done: number; failed: number };
  disk: { path: string; free_bytes: number | null; total_bytes: number | null };
  last_backup: RunSummary | null;
  last_successful_backup: RunSummary | null;
  last_restore_test: RunSummary | null;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  run_after: string;
  last_error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface SettingsResponse {
  values: {
    "backup.time": string;
    "backup.secondary_path": string | null;
    "backup.archive_enabled": boolean;
    "backup.archive_path": string | null;
    "upload.max_mb": number;
    "parties.stale_lead_days": number;
    "company.name": string;
    "company.signature": Record<string, string>;
  };
  data_dir: string;
  version: string;
  archive_password_set: boolean;
  can_store_secrets: boolean;
}

export interface SearchHit {
  id: string;
  title: string;
  link: string;
  score: number;
  subtitle: string | null;
  title_i18n: Record<string, string> | null;
  extra: Record<string, unknown>;
}

export interface SearchGroup {
  type: string;
  label_key: string;
  items: SearchHit[];
}

// ---- Phase 3: parties ---------------------------------------------------------------

export type PartyRoleName = "buyer" | "supplier" | "forwarder" | "customs_broker" | "agent" | "other";
export type Channel = "whatsapp" | "call" | "email" | "tender_portal" | "in_person" | "other";
export type MethodType = "whatsapp" | "phone" | "email" | "telegram" | "other";

export interface PartyRole {
  role: PartyRoleName;
  stage: string;
  stage_changed_at: string;
}

export interface NextFollowup {
  id: string;
  action: string;
  due_on: string;
}

export interface Party {
  id: string;
  name_fa: string | null;
  name_en: string | null;
  kind: "company" | "person";
  country_iso2: string | null;
  website: string | null;
  national_id?: string | null;
  economic_code?: string | null;
  notes: string | null;
  do_not_contact: boolean;
  do_not_contact_reason: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  roles: PartyRole[];
  last_interaction_at: string | null;
  next_followup: NextFollowup | null;
}

export interface ContactMethod {
  id: string;
  type: MethodType;
  value: string;
  value_norm: string;
  /** International format with spaces for phone/WhatsApp ("+98 912 345 6789"); the value otherwise. */
  value_display: string;
  is_primary: boolean;
  status: "active" | "archived";
}

/** Another active contact that already holds a number being added (v0.2.1: a warning, not an error). */
export interface SharedWith {
  type: MethodType;
  value: string;
  contact_id: string;
  contact_name: string | null;
  party_id: string;
  party_name: string | null;
}

/** POST /api/contacts/{id}/methods, PATCH /api/contacts/methods/{id}, POST /api/contacts. */
export type SharedResult<T> = (T & { created: true; shared_with: SharedWith[] }) | { created: false; shared_with: SharedWith[] };

export interface Contact {
  id: string;
  party_id: string;
  name_fa: string | null;
  name_en: string | null;
  job_title: string | null;
  is_primary: boolean;
  notes: string | null;
  status: "active" | "archived";
  methods: ContactMethod[];
}

export interface Interaction {
  id: string;
  party_id: string;
  contact_id: string | null;
  channel: Channel;
  direction: "in" | "out";
  occurred_at: string;
  subject: string | null;
  body: string | null;
  no_followup_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface Followup {
  id: string;
  interaction_id: string | null;
  party_id: string;
  action: string;
  due_on: string;
  status: "open" | "done" | "cancelled";
  done_at: string | null;
  done_note: string | null;
  created_at: string;
}

export interface LinkedDocument {
  link_id: string;
  entity_type: string;
  entity_id: string;
  document_id: string;
  title: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  linked_at: string;
}

export interface PartyDetail extends Party {
  contacts: Contact[];
  recent_interactions: Interaction[];
  open_followups: Followup[];
  documents: LinkedDocument[];
}

export interface PossibleDuplicate {
  id: string;
  name_fa: string | null;
  name_en: string | null;
  status: string;
  do_not_contact: boolean;
  reason: string;
  score: number;
}

export interface FollowupRow {
  id: string;
  party_id: string;
  party_name_fa: string | null;
  party_name_en: string | null;
  do_not_contact: boolean;
  party_status: "active" | "archived";
  action: string;
  due_on: string;
  interaction_id: string | null;
}

export interface StaleLead {
  party_id: string;
  party_name_fa: string | null;
  party_name_en: string | null;
  do_not_contact: boolean;
  role: PartyRoleName;
  stage: string;
  last_interaction_at: string | null;
}

export interface CommandCenter {
  today_date: string;
  overdue: FollowupRow[];
  overdue_count: number;
  today: FollowupRow[];
  upcoming_7_days: FollowupRow[];
  stale_leads: StaleLead[];
  stale_lead_days: number;
  funnel_counts: Record<string, Record<string, number>>;
  sourcing: SourcingSummary;
  setad?: SetadSummary;
  tenders?: TendersSummary;
  execution?: ExecutionSummary;
  /** v0.8.0: «کارها», overdue and due today / tomorrow */
  tasks?: import("./tasks").TasksSummary;
  /** v0.8.0: «مالی» */
  finance?: import("./finance").FinanceSummary;
}

/** Command center section "Setad" (v0.5.0). */
export interface SetadSummary {
  due: { id: string; source: string; external_no: string; title: string; organization: string; status: string; inquiry_id: string | null; deadline: string; passed: boolean }[];
  deadline_changed: { listing_id: string; inquiry_id: string; number: string; title: string; old: string | null; new: string }[];
  warn_new: { id: string; source: string; external_no: string; title: string; organization: string; keywords: string[] }[];
  runs: { source: string; run_id: string | null; kind: string | null; status: string | null; at: string | null; errors: string | null; stale: boolean }[];
  stale_days: number;
}

export interface FunnelCard {
  party_id: string;
  name_fa: string | null;
  name_en: string | null;
  do_not_contact: boolean;
  stage_changed_at: string;
  last_interaction_at: string | null;
  next_followup: NextFollowup | null;
}

export interface FunnelBoard {
  role: PartyRoleName;
  stages: { code: string; label_fa: string; label_en: string; is_terminal: boolean; cards: FunnelCard[] }[];
}

// ---- sourcing (Phase 5) ------------------------------------------------------------------------------

export interface Spec {
  key: string;
  value: string;
  unit?: string;
}

export type ItemStatus = "uncovered" | "rfq_sent" | "has_offer" | "selected" | "sold" | "delivered" | "closed" | "cancelled";

export interface LineItem {
  id: string;
  inquiry_id: string | null;
  case_id: string | null;
  position: number;
  name: string;
  description: string | null;
  product_id: string | null;
  quantity: string | null;
  unit_code: string | null;
  unit_text: string | null;
  target_price: string | null;
  target_currency: string | null;
  destination_country_iso2: string | null;
  incoterm: string | null;
  incoterm_place: string | null;
  required_by: string | null;
  packaging: string | null;
  hs_code: string | null;
  route: "domestic" | "foreign" | "both" | "unknown";
  notes: string | null;
  specs: Spec[];
  status: ItemStatus;
  no_coverage_confirmed: boolean;
  no_coverage_reason: string | null;
  selected_offer_item_id: string | null;
  documents?: LinkedDocument[];
}

export interface ItemWarning {
  code: "duplicate_name";
  item_id?: string;
  name?: string;
}

export type Check = "yes" | "no" | "unknown";

export interface Decision {
  id: string;
  light: "green" | "yellow" | "red";
  reason: string;
  feasible_sourcing: Check;
  feasible_sourcing_note: string | null;
  exposure_acceptable: Check;
  exposure_acceptable_note: string | null;
  requirements_ok: Check;
  requirements_ok_note: string | null;
  exposure_estimate: string | null;
  exposure_currency: string | null;
  payment_term: string | null;
  ordering_before_payment_reason: string | null;
  confirmed: boolean;
  updated_at: string;
}

export interface Gate {
  ok: boolean;
  code: string | null;
  details: { checks?: string[]; reason?: string };
}

export interface Inquiry {
  id: string;
  party_id: string | null;
  source_channel: string;
  kind: string;
  received_at: string;
  response_due_on: string | null;
  subject: string | null;
  raw_text: string | null;
  status: string;
  source_interaction_id: string | null;
  reject_reason: string | null;
  /** v0.5.0: converted from a Setad listing */
  listing_id?: string | null;
  external_no?: string | null;
  external_url?: string | null;
  response_due_at?: string | null;
  required_price_validity?: string | null;
  delivery_province?: string | null;
  delivery_city?: string | null;
  created_at: string;
  updated_at: string;
  party_name_fa?: string | null;
  party_name_en?: string | null;
}

export interface InquiryDetail extends Inquiry {
  items: LineItem[];
  warnings: ItemWarning[];
  decision: Decision | null;
  gate: Gate;
  case_id: string | null;
  documents: LinkedDocument[];
}

export interface Case {
  id: string;
  inquiry_id: string | null;
  party_id: string | null;
  title: string;
  status: "open" | "won" | "lost" | "closed" | "cancelled";
  payment_term: string | null;
  ordering_before_payment_reason: string | null;
  exposure_estimate: string | null;
  exposure_currency: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  party_name_fa?: string | null;
  party_name_en?: string | null;
}

export interface CaseDetail extends Case {
  items: LineItem[];
  warnings: ItemWarning[];
  documents: LinkedDocument[];
}

export interface PaymentTerm {
  code: string;
  label_fa: string;
  label_en: string;
  requires_reason: boolean;
}

export interface RfqRecipient {
  id: string;
  rfq_id: string;
  party_id: string;
  contact_id: string | null;
  channel: "email" | "whatsapp" | "letter" | "phone" | "other";
  language: string;
  template_id: string | null;
  status: "draft" | "sent" | "replied" | "declined" | "no_response" | "expired";
  sent_at: string | null;
  subject: string | null;
  message_text: string | null;
  interaction_id: string | null;
  party_name_fa: string | null;
  party_name_en: string | null;
  party_country: string | null;
  contact_name_fa: string | null;
  contact_name_en: string | null;
  mailto: string | null;
  email: string | null;
}

export interface Rfq {
  id: string;
  case_id: string;
  title: string;
  status: "draft" | "sent" | "answered" | "no_response" | "expired" | "cancelled";
  language: string;
  respond_by: string | null;
  notes: string | null;
  created_at: string;
  items: { id: string; line_item_id: string; quantity: string | null; unit_code: string | null; unit_text: string | null; note: string | null; line_item: LineItem }[];
  recipients: RfqRecipient[];
}

export interface SupplierChoice {
  party_id: string;
  name_fa: string | null;
  name_en: string | null;
  country_iso2: string | null;
  do_not_contact?: boolean;
  supplier_stage: string | null;
  channel?: string;
  language?: string;
  match?: "heading" | "chapter";
  codes?: string[];
}

export interface OfferItem {
  id: string;
  offer_id: string;
  line_item_id: string;
  available: boolean;
  unit_price: string | null;
  price_per_quantity: string;
  unit_code: string | null;
  unit_text: string | null;
  moq: string | null;
  moq_unit: string | null;
  lead_time_days: number | null;
  spec_deviation: string | null;
  packaging: string | null;
  notes: string | null;
}

export interface Offer {
  id: string;
  case_id: string;
  party_id: string;
  party_name_fa: string | null;
  party_name_en: string | null;
  contact_id: string | null;
  contact_name_fa: string | null;
  contact_name_en: string | null;
  rfq_recipient_id: string | null;
  received_at: string;
  channel: string;
  valid_until: string | null;
  currency: string;
  incoterm: string | null;
  incoterm_place: string | null;
  payment_terms: string | null;
  lead_time_days: number | null;
  compliance_notes: string | null;
  notes: string | null;
  raw_text: string | null;
  status: "active" | "superseded" | "withdrawn" | "expired";
  superseded_by_id: string | null;
  status_note: string | null;
  valid: boolean;
  items: OfferItem[];
  documents: LinkedDocument[];
}

export interface ComparisonRow {
  offer_item_id: string;
  offer_id: string;
  party_id: string;
  party_name_fa: string | null;
  party_name_en: string | null;
  contact_id: string | null;
  contact_name_fa: string | null;
  contact_name_en: string | null;
  unit_price: string | null;
  currency: string;
  price_per_quantity: string;
  unit_code: string | null;
  unit_text: string | null;
  unit_group: string;
  normalized_price: string | null;
  incoterm: string | null;
  incoterm_place: string | null;
  moq: string | null;
  moq_unit: string | null;
  lead_time_days: number | null;
  payment_terms: string | null;
  valid_until: string | null;
  days_left: number | null;
  expiring: boolean;
  compliance_notes: string | null;
  spec_deviation: string | null;
  packaging: string | null;
  notes: string | null;
  documents: LinkedDocument[];
  badges: ("incoterm_differs" | "unit_differs")[];
  lowest: boolean;
  selected: boolean;
}

export interface ComparisonGroup {
  currency: string;
  unit_groups: { unit_group: string; comparable: boolean; rows: ComparisonRow[] }[];
}

export interface ComparisonItem {
  item_id: string;
  position: number;
  name: string;
  status: ItemStatus;
  quantity: string | null;
  unit_code: string | null;
  unit_text: string | null;
  selected_offer_item_id: string | null;
  groups: ComparisonGroup[];
}

export interface Coverage {
  case_id: string;
  items: {
    item_id: string;
    position: number;
    name: string;
    status: ItemStatus;
    no_coverage_confirmed: boolean;
    no_coverage_reason: string | null;
    valid_offers: number;
    best_prices: { currency: string; unit_group: string; unit_price: string; price_per_quantity: string; unit_code: string | null; unit_text: string | null; offer_id: string; party_id: string }[];
    selected_offer_item_id: string | null;
    selection_lost: boolean;
  }[];
  gate: { ok: boolean; missing: { item_id: string; name: string; status: string; valid_offers: number }[] };
}

export interface MessageTemplate {
  id: string;
  kind: string;
  language: string;
  channel: "email" | "whatsapp" | "letter";
  name: string;
  subject_template: string;
  body_template: string;
  is_default: boolean;
  status: "active" | "archived";
}

export interface ProductAliasRef {
  id: string;
  alias: string;
}

export interface Product {
  id: string;
  name_fa: string | null;
  name_en: string | null;
  kind_note: string | null;
  default_unit_code: string | null;
  hs_code: string | null;
  category_id: string | null;
  notes: string | null;
  status: "active" | "archived";
  aliases: ProductAliasRef[];
  last_requested?: string | null;
  offers?: number;
}

export interface PriceStats {
  count: number;
  min: string | null;
  median: string | null;
  max: string | null;
}

export interface ProductPage extends Product {
  prices: {
    offers: { id: string; unit_price: string; price_per_quantity: string; unit_code: string | null; unit_text: string | null; moq: string | null; moq_unit: string | null; offer_id: string; received_at: string; currency: string; incoterm: string | null; incoterm_place: string | null; valid_until: string | null; status: string; party_id: string; party_fa: string | null; party_en: string | null; contact_id: string | null; contact_fa: string | null; contact_en: string | null; quantity: string | null; case_id: string; unit_group: string; normalized_price: string | null }[];
    summary: { currency: string; unit_group: string; all_time: PriceStats; last_12_months: PriceStats }[];
  };
  demand: {
    inquiries: number;
    cases: number;
    last_requested: string | null;
    quantity_by_month: { month: string; unit_group: string; quantity: string }[];
    buyers: { party_id: string; name_fa: string | null; name_en: string | null; requests: number }[];
  };
  suppliers_by_offers: { party_id: string; name_fa: string | null; name_en: string | null; offers: number; last_price: string; price_per_quantity: string; unit_code: string | null; unit_text: string | null; currency: string; last_at: string }[];
  suppliers_by_capability: SupplierChoice[];
}

export interface RefCode {
  code: string;
  level: number | string;
  parent_code: string | null;
  title_en: string;
  title_fa: string | null;
  title_fa_missing: boolean;
  edition: string;
  parent?: RefCode | null;
}

export interface Capability {
  id: string;
  kind: "hs" | "isic" | "tag";
  code: string | null;
  tag_text: string | null;
  notes: string | null;
  info?: (RefCode & { unknown?: false }) | { code: string; unknown: true };
}

export interface SourcingSummary {
  items_without_rfq: { item_id: string; name: string; case_id: string; case_title: string }[];
  rfq_overdue: { recipient_id: string; party_id: string; party_name_fa: string | null; party_name_en: string | null; rfq_id: string; rfq_title: string; case_id: string; respond_by: string }[];
  offers_expiring: { offer_id: string; case_id: string; case_title: string; party_id: string; party_name_fa: string | null; party_name_en: string | null; valid_until: string; currency: string; days_left: number }[];
  cases_not_covered: { case_id: string; case_title: string; items: number; not_covered: number }[];
  no_response_resend: { item_id: string; name: string; case_id: string; case_title: string; recipients: number; respond_by: string | null }[];
  quotes_awaiting_approval?: { quote_id: string; number: string; case_id: string; case_title: string; total: string; currency: string; created_at: string }[];
  quotes_expiring?: { quote_id: string; number: string; case_id: string; case_title: string; valid_until: string; days_left: number; currency: string; total: string; party_name_fa: string | null; party_name_en: string | null }[];
  sheets_stale_fx?: { cost_sheet_id: string; case_id: string; case_title: string; version: number; status: string; as_of: string; age_days: number }[];
  quotes_won_30_days?: number;
  quotes_lost_30_days?: number;
  selection_lost: { item_id: string; name: string; case_id: string; case_title: string; lost_at: string; cause: string }[];
  coverage_status_percent: number | null;
  open_items: number;
  open_items_with_status: number;
}


// ---- costing (v0.4.0) ------------------------------------------------------------------------------------

export type DealType = "import" | "export" | "domestic";
export type CostLineKind = "purchase" | "freight_international" | "insurance" | "bank_fees" | "customs_duty" | "levy"
  | "customs_clearance" | "storage" | "inspection" | "freight_domestic" | "export_clearance" | "vat" | "other";
export type CostBasis = "total" | "per_unit" | "percent_of_cif" | "percent_of_purchase";
export type Allocation = "by_value" | "by_quantity" | "equal" | "manual";

export interface TaxKind { code: string; label_fa: string; label_en: string; sort_order: number }

export interface TaxParameter {
  id: string;
  kind: string;
  name: string;
  rate_percent: string;
  deal_type: DealType | "all";
  effective_from: string;
  effective_to: string | null;
  note: string | null;
  confirmed_by: string | null;
  confirmed_on: string | null;
}

export interface CostTemplateLine {
  id?: string;
  kind: CostLineKind;
  label_fa: string | null;
  label_en: string | null;
  basis: CostBasis;
  allocation: Allocation;
  paid_before_receipt: boolean;
  tax_kind: string | null;
}

export interface CostTemplate {
  id: string;
  name: string;
  name_fa: string | null;
  deal_type: DealType;
  is_default: boolean;
  status: "active" | "archived";
  lines: CostTemplateLine[];
}

export interface CostLine {
  id: string;
  cost_sheet_id: string;
  position: number;
  kind: CostLineKind;
  label: string;
  scope: "case" | "item";
  line_item_id: string | null;
  amount: string | null;
  currency: string | null;
  basis: CostBasis;
  percent: string | null;
  allocation: Allocation;
  manual_shares: Record<string, string> | null;
  paid_before_receipt: boolean;
  tax_parameter_id: string | null;
  source_offer_item_id: string | null;
  notes: string | null;
}

export interface FxEntry {
  id: string;
  from_currency: string;
  to_currency: string;
  rate: string;
  rate_kind: string | null;
  source_note: string | null;
  as_of: string;
}

export interface ComputedItem {
  item_id: string;
  name: string;
  quantity: string | null;
  unit_code: string | null;
  unit_text: string | null;
  purchase: string;
  cif: string;
  lines: { line_id: string; kind: string; amount: string }[];
  cost_of_money: string;
  guarantee: string;
  vat: string;
  landed_cost: string;
  unit_cost: string | null;
  unit_price: string | null;
  total_price: string | null;
  manual: boolean;
  profit: string | null;
  margin_percent: string | null;
  markup_percent: string | null;
  min_unit_price: string | null;
  below_minimum: boolean;
}

export interface ComputedLine {
  line_id: string;
  kind: string;
  label: string;
  total: string;
  shares: Record<string, string>;
  vat: boolean;
  percent?: string;
  base?: string;
  fx: { from_currency: string; to_currency: string; rate: string; as_of: string; reverse: boolean } | null;
}

export interface Computation {
  currency: string;
  decimals: number;
  items: ComputedItem[];
  lines: ComputedLine[];
  totals: {
    purchase: string; cif: string; cost_before_vat: string; cost_of_money: string; guarantee: string; vat: string;
    price_before_vat: string | null; price_with_vat: string | null; profit: string | null;
    margin_percent: string | null; markup_percent: string | null;
  };
  below_minimum: boolean;
  exposure: { supplier_prepayment: string; paid_before_receipt: string; customer_prepayment: string; exposure: string };
  cost_of_money: { cash_tied_up: string; annual_percent: string; days: number; amount: string };
  guarantee: { percent: string; days: number; annual_percent: string; amount: string };
  fx_used: { from_currency: string; to_currency: string; rate: string; as_of: string }[];
  newest_fx_as_of: string | null;
  problems: { code: string; line_id?: string; item_id?: string; label?: string }[];
}

export interface GateFailure { code: string; [key: string]: unknown }

export interface CostGate {
  ok: boolean;
  failures: GateFailure[];
  valid_until: string;
  max_valid_until: string | null;
  valid_until_capped: boolean;
  overrides: { fx_stale: string | null; unconfirmed_parameter: string | null };
}

export interface CostSheet {
  id: string;
  case_id: string;
  version: number;
  status: "draft" | "final" | "superseded";
  deal_type: DealType;
  pricing_currency: string;
  template_id: string | null;
  sheet_date: string;
  notes: string | null;
  supplier_prepay_percent: string;
  customer_prepay_percent: string;
  days_from_payment_to_receipt: number;
  annual_cost_of_money_percent: string;
  guarantee_percent: string;
  guarantee_days: number;
  pricing_method: "margin" | "markup";
  target_percent: string | null;
  min_acceptable_price: string | null;
  item_min_prices: Record<string, string>;
  price_overrides: Record<string, string>;
  rounding: "none" | "nearest" | "up";
  rounding_step: string | null;
  validity_days: number | null;
  fx_override_reason: string | null;
  parameter_override_reason: string | null;
  finalized_at: string | null;
  decimals: number;
  lines: CostLine[];
  fx: FxEntry[];
  items: { id: string; name: string; quantity: string | null; unit_code: string | null; unit_text: string | null; status: string; selected_offer_item_id: string | null }[];
  computation: Computation | null;
  compute_error: { code: string; message: string; details: Record<string, unknown> } | null;
  warnings: { code: string; [key: string]: unknown }[];
  gate: CostGate;
  unfilled_line_ids: string[];
}

export interface CaseCosting {
  sheets: { id: string; version: number; status: CostSheet["status"]; deal_type: DealType; pricing_currency: string; sheet_date: string; created_at: string; finalized_at: string | null }[];
  current: { sheet_id: string; version: number; currency?: string; exposure?: string; cost?: string; price?: string | null;
    margin_percent?: string | null; markup_percent?: string | null; error?: string } | null;
}

// ---- quotes (v0.4.0) -----------------------------------------------------------------------------------------

export type QuoteStatus = "draft" | "approved" | "sent" | "accepted" | "partially_accepted" | "rejected" | "expired"
  | "withdrawn" | "superseded";
export type Outcome = "accepted" | "rejected" | "no_reply" | "negotiating";

export interface QuoteItem {
  id: string;
  quote_id: string;
  line_item_id: string;
  name: string;
  position: number;
  description_override: string | null;
  quantity: string;
  unit_code: string | null;
  unit_text: string | null;
  unit_price: string;
  total: string;
  vat_amount: string;
  unit_cost: string | null;
  price_manual: boolean;
  lead_time_days: number | null;
  note: string | null;
  outcome: Outcome | null;
  outcome_reason: string | null;
  outcome_note: string | null;
  competitor_price: string | null;
  competitor_currency: string | null;
  decided_on: string | null;
  min_unit_price?: string | null;
}

export interface QuoteRow {
  id: string;
  case_id: string;
  number: string;
  version: number;
  status: QuoteStatus;
  currency: string;
  subtotal: string;
  total: string;
  valid_until: string;
  sent_at: string | null;
  created_at: string;
  price_basis: "before_vat" | "with_vat";
  language: "fa" | "en";
  buyer_party_id: string | null;
  buyer_name_fa: string | null;
  buyer_name_en: string | null;
}

export interface Quote extends QuoteRow {
  cost_sheet_id: string;
  incoterm: string | null;
  incoterm_place: string | null;
  payment_terms: string | null;
  delivery_terms: string | null;
  lead_time_days: number | null;
  terms_text: string | null;
  terms_manual: boolean;
  notes: string | null;
  vat_amount: string;
  contact_id: string | null;
  contact_name_fa: string | null;
  contact_name_en: string | null;
  supersedes_id: string | null;
  interaction_id: string | null;
  approved_at: string | null;
  approved_by: string | null;
  decimals: number;
  cost_sheet: { id: string; version: number; status: string };
  items: QuoteItem[];
  outputs: LinkedDocument[];
  approval: { ok: boolean; failures: GateFailure[]; max_valid_until: string | null; required_valid_until?: string | null;
    validity_override_reason?: string | null } | null;
  default_followup: { action: string; due_on: string } | null;
  /** v0.5.0: the case's inquiry came from Setad */
  setad: { inquiry_id: string; setad_number: string; url: string | null; required_valid_until: string | null } | null;
  validity_override_reason?: string | null;
}

export interface CaseQuotes {
  summary: { count: number; won: number; lost: number; open: number; all_decided: boolean;
    latest: { id: string; number: string; status: QuoteStatus; valid_until: string } | null };
  items: QuoteRow[];
}

export interface OutcomeReason { code: string; label_fa: string; label_en: string }

export interface ProductQuotes {
  quotes: { id: string; quote_id: string; number: string; case_id: string; sent_at: string; currency: string; incoterm: string | null;
    incoterm_place: string | null; status: string; quantity: string; unit_code: string | null; unit_text: string | null;
    unit_price: string; outcome: Outcome | null; outcome_reason: string | null; party_id: string | null;
    party_fa: string | null; party_en: string | null; unit_group: string; normalized_price: string | null }[];
  summary: { currency: string; unit_group: string; count: number; min: string; median: string; max: string }[];
}

// ---- Setad listings and screening (v0.5.0) -----------------------------------------------------------------

export interface ListingRow {
  id: string;
  source: "setad_purchase" | "setad_tender";
  external_no: string;
  title: string;
  organization: string;
  province: string;
  city: string;
  category: string;
  goods_group: string;
  service_group: string;
  published_at: string | null;
  deadline: string | null;
  deadline_exact: boolean;
  document_price: string | null;
  in_my_calls: boolean;
  site_state: string;
  site_state_name: string;
  status: "new" | "starred" | "reviewing" | "converted" | "dismissed";
  inquiry_id: string | null;
  dismiss_reason: string | null;
  is_new: boolean;
  documents: { downloaded: number; total: number };
  warn: string[];
}

export interface ListingCounts {
  all: number; new: number; starred: number; reviewing: number; converted: number; dismissed: number;
  open: number; soon: number; passed: number; downloaded: number; my_calls: number; free: number; paid: number;
}

export interface ListingPage {
  items: ListingRow[];
  total: number;
  page: number;
  page_size: number;
  counts: ListingCounts;
  since: string | null;
}

export interface ListingFile {
  id: string;
  group: string;
  group_key: string;
  appendix_id: string;
  name: string;
  extension: string;
  size: string;
  state: "pending" | "downloaded" | "missing" | "error";
  sha256: string | null;
  document_id: string | null;
  error: string | null;
}

export interface ListingDetail {
  listing: {
    id: string; source: ListingRow["source"]; external_id: string; external_no: string; title: string; organization: string;
    province: string; city: string; category: string; goods_group: string; service_group: string; type_name: string;
    need_type: string; description: string; published_at: string | null; documents_deadline: string | null;
    proposal_deadline: string | null; inquiry_deadline: string | null; opening_at: string | null; edition_date: string | null;
    edition_no: string; response_deadline: string | null; deadline_exact: boolean; price_valid_until: string | null;
    document_price: string | null; guarantee_amount: string | null; estimate: string | null; site_state: string;
    guarantee_currency: string | null; guarantee_description: string | null; estimate_currency: string | null;
    site_state_name: string; in_my_calls: boolean; detail_url: string | null; first_seen: string; last_seen: string;
  };
  groups: { title: string; pairs: [string, string][] }[];
  technical: [string, string][];
  detail: { buyer_note: string; items: { headers: string[]; rows: string[][] }; fetched_at: string; text: string;
    attachments: string[] | null } | null;
  files: ListingFile[];
  changes: { field: string; old: string | null; new: string | null; at: string }[];
  screening: { status: ListingRow["status"]; dismiss_reason: string | null; note: string | null; checklist: boolean[];
    inquiry_id: string | null; starred_at: string | null; converted_at: string | null } | null;
  warn: string[];
  checklist_questions: string[];
  events: { action: string; at: string; source: string; actor: string | null; data: Record<string, unknown> }[];
}

export interface HarvestRunInfo {
  id: string; kind: "full" | "quick"; status: "running" | "done" | "needs_review" | "cancelled" | "error";
  started_at: string; finished_at: string | null; reported_count: number | null; pages_total: number | null;
  pages_done: number; rows_seen: number; new_count: number; changed_count: number; duplicates: number; errors: string;
}

export interface AgentState {
  alive: boolean;
  connected: boolean;
  pid?: number | null;
  role?: "EPROC" | "ETEND" | null;
  browser_channel?: string | null;
  command?: string | null;
  pages_done?: number | null;
  pages_total?: number | null;
  rows_seen?: number | null;
  captcha_waiting?: boolean;
  captcha_message?: string | null;
  message?: string | null;
  last_error?: string | null;
  recording?: boolean;
  queued: number;
  /** v0.6.0: queued / running commands with their listings, and the running command's listing and attachment n of m */
  jobs?: { id: string; command: string; status: string; listing_ids: string[]; created_at: string }[];
  job_id?: string | null;
  listing_id?: string | null;
  files_done?: number | null;
  files_total?: number | null;
  runs: Record<"setad_purchase" | "setad_tender", HarvestRunInfo | null>;
}

// ---- tenders (v0.6.0) -----------------------------------------------------------------------------------------------
export type TenderStage = "screening" | "documents" | "pricing" | "guarantee" | "envelopes" | "submitted" | "opening" | "result" | "closed";
export interface PartyRef { id: string; name_fa: string | null; name_en: string | null }
export interface TenderDateRow {
  id: string; tender_id: string; kind: string; label: string | null; at: string; all_day: boolean; note: string | null;
  remind_days_before: number[]; source: "setad" | "manual" | "addendum";
  reminders: { id: string; due_on: string; days_before: number | null }[];
}
export interface TenderDateChangeRow { id: string; tender_date_id: string; old_at: string | null; new_at: string; reason: string; addendum_id: string | null; created_at: string }
export interface AddendumRow {
  id: string; number: string | null; received_on: string; kind: string; summary: string; document_id: string | null;
  question: string | null; asked_on: string | null; answer: string | null; answered_on: string | null;
}
export interface EnvelopeItemRow {
  id: string; envelope: "A" | "B" | "C"; position: number; title: string; kind: "document" | "bid_bond" | "price_form";
  status: "not_ready" | "in_progress" | "needs_signature" | "ready" | "submitted"; company_document_id: string | null;
  document_id: string | null; guarantee_id: string | null; note: string | null;
  company_document: { id: string; title: string; expires_on: string | null; expiry: "ok" | "soon" | "expired" | "none"; days_left: number | null; document_id: string | null } | null;
}
export interface GuaranteeRow {
  id: string; case_id: string; tender_id: string | null; purpose: string; form: string | null; status: string;
  beneficiary_party_id: string | null; reminder_party_id: string | null; amount: string | null; amount_currency: string | null;
  bank_name: string | null; branch: string | null; number: string | null; issued_on: string | null; valid_until: string | null;
  claim_period_until: string | null; fee: string | null; fee_currency: string | null; blocked_deposit: string | null;
  blocked_deposit_currency: string | null; document_id: string | null; description: string | null; note: string | null;
  history: { id: string; kind: string; on_date: string; old_status: string | null; new_status: string | null; valid_until: string | null; reason: string | null }[];
  beneficiary: PartyRef | null; reminder_party: PartyRef | null;
  coverage: { code: string; valid_until: string; needed_until: string } | null;
  reminders: { id: string; due_on: string; action: string; purpose: string }[];
  case_title?: string; tender_no?: string | null; beneficiary_name?: string | null;
}
export interface TenderCostRow { id: string; kind: string; amount: string; amount_currency: string; paid_on: string | null; refundable: boolean; refunded_on: string | null; note: string | null; document_id: string | null }
export interface ProposalRow {
  id: string; tender_id: string; cost_sheet_id: string; version: number; status: "draft" | "approved" | "superseded";
  price_basis: string; currency: string; subtotal: string; vat_amount: string; total: string; valid_until: string | null;
  approved_at: string | null; below_cost_reason: string | null; decimals: number; words: string;
  lines: { id: string; line_item_id: string; name: string; position: number; quantity: string; unit_code: string | null; unit_text: string | null; unit_price: string; total: string; vat_amount: string; unit_cost: string | null }[];
  below_cost: { line_id: string; name: string | null; unit_price: string; unit_cost: string }[];
  outputs: { link_id: string; document_id: string; original_filename: string; linked_at: string }[];
}
export interface Blocker { code: string; [key: string]: unknown }
export interface TenderDetail {
  id: string; case_id: string; tender_no: string | null; listing_id: string | null; organizer_party_id: string | null;
  tender_type: string | null; stages: string | null; stage: TenderStage; participation: "undecided" | "yes" | "no";
  participation_reason: string | null; document_price: string | null; document_price_currency: string | null;
  documents_obtained_at: string | null; estimate: string | null; estimate_currency: string | null;
  proposal_validity_days: number | null; proposal_valid_until: string | null; financial_mode: "buyer_form" | "letterhead";
  submitted_at: string | null; submit_channel: string | null; submit_note: string | null; submit_override_reason: string | null;
  result: "won" | "lost" | "cancelled" | "no_result" | null; result_reason: string | null; result_note: string | null;
  winner_name: string | null; winner_price: string | null; winner_price_currency: string | null; our_rank: number | null; result_on: string | null;
  organizer: PartyRef | null; stage_hint: TenderStage;
  dates: TenderDateRow[]; date_changes: TenderDateChangeRow[];
  next_date: { id: string; kind: string; label: string | null; at: string } | null;
  setad_date_changes: { kind: string; date_id: string | null; old: string | null; new: string }[];
  new_appendices: Record<string, number>;
  addenda: AddendumRow[]; envelope_items: EnvelopeItemRow[]; envelope_progress: Record<"A" | "B" | "C" | "all", [number, number]>;
  guarantees: GuaranteeRow[]; bid_bond: { id: string; status: string; valid_until: string | null } | null;
  needed_until: string | null; tied_up: Record<string, { blocked_deposit: string; fee: string; total: string }>;
  costs: TenderCostRow[]; cost_totals: Record<string, { spent: string; refundable_outstanding: string; refunded: string; unpaid: string; net: string }>;
  proposals: ProposalRow[]; blockers: Blocker[];
  other_reminders: { id: string; due_on: string; action: string; purpose: string }[];
}
export interface CompanyDocumentRow {
  id: string; title: string; category: string; document_id: string | null; issued_on: string | null; expires_on: string | null;
  note: string | null; status: "active" | "archived"; expiry: "ok" | "soon" | "expired" | "none"; days_left: number | null;
}
export interface EnvelopeTemplateRow { id: string; name: string; is_default: boolean; lines: { id: string; envelope: "A" | "B" | "C"; position: number; title: string; kind: string }[] }
export interface ResultReasonRow { code: string; label_fa: string; label_en: string; sort_order: number; active: boolean }
export interface TendersSummary {
  dates_soon: { tender_id: string; case_id: string; case_title: string; tender_no: string | null; kind: string; label: string; at: string }[];
  envelopes_incomplete: { tender_id: string; case_id: string; case_title: string; tender_no: string | null; at: string; done: number; total: number }[];
  guarantees_expiring: { guarantee_id: string; case_id: string; case_title: string; purpose: string; number: string | null; valid_until: string | null; status: string }[];
  guarantees_release: { guarantee_id: string; case_id: string; case_title: string; purpose: string; number: string | null; status: string }[];
  documents_expiring: CompanyDocumentRow[];
  setad_changes: { tender_id: string; case_id: string; case_title: string; tender_no: string | null; date_changes: number; new_appendices: Record<string, number> }[];
  waiting_result: { tender_id: string; case_id: string; case_title: string; tender_no: string | null; opening: string }[];
}


// ---- execution (v0.7.0) ------------------------------------------------------------------------------------------------
export interface PartyRef { id: string; name_fa: string | null; name_en: string | null }
export interface OutputLink { link_id: string; document_id: string; title: string | null; original_filename: string; mime_type: string; linked_at: string }
export interface PaymentRecordRow { id: string; milestone_id: string; amount: string; amount_currency: string; paid_on: string; method: string | null; reference: string | null; document_id: string | null; note: string | null }
export interface MilestoneRow {
  id: string; case_id: string; direction: "in" | "out"; sales_order_id: string | null; purchase_order_id: string | null; party_id: string;
  kind: string; label: string | null; position: number; percent: string | null; amount: string | null; amount_currency: string | null;
  due_on: string | null; due_event: string | null; status: "expected" | "partly" | "done" | "cancelled"; actual_amount: string | null;
  actual_amount_currency: string | null; actual_on: string | null; method: string | null; reference: string | null;
  receipt_document_id: string | null; note: string | null; expected_amount: string; expected_currency: string; party: PartyRef; records: PaymentRecordRow[];
}
export interface SalesOrderItemRow { id: string; line_item_id: string; position: number; description: string; quantity: string; unit: string | null; unit_price: string; total: string; vat_amount: string; delivery_due_on: string | null; delivered: string }
export interface OrderChangeRow { id: string; sales_order_item_id?: string | null; field: string; old_value: string | null; new_value: string | null; reason: string; document_id: string | null; created_at: string }
export interface SalesOrderRow {
  id: string; case_id: string; number: string; customer_party_id: string; contact_id: string | null; source: string; quote_id: string | null;
  tender_proposal_id: string | null; customer_ref: string | null; contract_date: string | null; signed_document_id: string | null;
  currency: string; price_basis: string; incoterm: string | null; incoterm_place: string | null; payment_terms: string | null;
  delivery_terms: string | null; delivery_due_on: string | null; delivery_place: string | null; warranty_months: number | null;
  performance_guarantee_id: string | null; status: string; subtotal: string; vat_amount: string; total: string; confirmed_at: string | null;
  no_document_reason: string | null; delivered_at: string | null; cancel_reason: string | null; notes: string | null; updated_at: string;
  customer: PartyRef; items: SalesOrderItemRow[]; changes: OrderChangeRow[]; milestones: MilestoneRow[]; outputs: OutputLink[];
  progress: { items: { sales_order_item_id: string; ordered: string; delivered: string; complete: boolean }[]; items_total: number; items_delivered: number };
}
export interface PurchaseOrderItemRow { id: string; line_item_id: string; sales_order_item_id: string | null; position: number; description: string; quantity: string; unit: string | null; unit_price: string; total: string; received_quantity: string }
export interface PurchaseOrderRow {
  id: string; case_id: string; sales_order_id: string | null; number: string; version: number; supersedes_id: string | null;
  supplier_party_id: string; contact_id: string | null; offer_id: string | null; language: "fa" | "en"; currency: string;
  incoterm: string | null; incoterm_place: string | null; payment_terms: string | null; delivery_terms: string | null;
  ready_due_on: string | null; delivery_place: string | null; direct_to_customer: boolean; status: string; subtotal: string; total: string;
  approved_at: string | null; price_override_reason: string | null; sent_at: string | null; prepayment_override_reason: string | null;
  confirmed_at: string | null; supplier_ref: string | null; confirmed_ready_on: string | null; confirmation_document_id: string | null;
  ready_on: string | null; status_note: string | null; terms_text: string | null; cancel_reason: string | null; notes: string | null;
  supplier: PartyRef; items: PurchaseOrderItemRow[]; changes: OrderChangeRow[]; offer_payment_terms: string | null;
  /** v0.8.0: ``check`` "above" (converted with the sheet's FX entries when the currencies differ) or "fx_missing" */
  above_cost_sheet: { purchase_order_item_id: string; description: string; unit_price: string; cost_sheet_price: string; tolerance_percent: string;
    currency: string; check?: "above" | "fx_missing"; cost_sheet_currency?: string; unit_price_converted?: string; rate?: string }[];
  milestones: MilestoneRow[]; followups: { id: string; purpose: string; due_on: string; action: string }[]; outputs: OutputLink[];
}
export interface ProcessStepRow {
  id: string; process_id: string; position: number; group: string | null; code: string; label_fa: string; label_en: string;
  reference_label: string | null; requires_document: boolean; status: "pending" | "in_progress" | "done" | "not_applicable";
  reference: string | null; started_on: string | null; done_on: string | null; due_on: string | null; remind_days_before: number[];
  document_id: string | null; no_document_reason: string | null; shipment_id: string | null; note: string | null; updated_at: string;
  reminders: { id: string; due_on: string; days_before: number | null }[];
}
export interface ProcessRow {
  id: string; case_id: string; deal_type: "import" | "export" | "domestic"; template_id: string | null; name: string; base_date: string | null;
  steps: ProcessStepRow[];
  progress: { done: number; total: number; next: { id: string; code: string; label_fa: string; label_en: string; due_on: string | null; overdue: boolean } | null };
}
export interface ProcessTemplateRow {
  id: string; deal_type: "import" | "export" | "domestic"; name: string; is_default: boolean; status: string;
  steps: { id: string; position: number; group: string | null; code: string; label_fa: string; label_en: string; reference_label: string | null; requires_document: boolean; default_offset_days: number | null }[];
}
export interface ShipmentRow {
  id: string; case_id: string; direction: "inbound" | "outbound"; purchase_order_id: string | null; sales_order_id: string | null; mode: string;
  carrier_party_id: string | null; forwarder_party_id: string | null; transport_doc_kind: string | null; transport_doc_no: string | null;
  containers: string[]; vessel_or_flight: string | null; origin: string | null; destination: string | null; incoterm: string | null;
  etd: string | null; eta: string | null; first_eta: string | null; atd: string | null; ata: string | null; status: string;
  policy_no: string | null; notes: string | null;
  items: { id: string; purchase_order_item_id: string | null; sales_order_item_id: string | null; quantity: string }[];
  events: { id: string; at: string; kind: string; note: string | null; document_id: string | null }[];
  documents: { id: string; kind: string; document_id: string; number: string | null; issued_on: string | null }[];
}
export interface ClaimSuggestion { case_id: string; direction: string; kind: string; counterparty_id: string | null; purchase_order_id: string | null; shipment_id: string | null; inspection_id?: string; receipt_id?: string; items: Record<string, unknown>[]; opened_on: string; notes?: string | null }
export interface InspectionRow { id: string; case_id: string; shipment_id: string | null; purchase_order_id: string | null; kind: string; inspector_party_id: string | null; planned_on: string | null; done_on: string | null; result: string; report_document_id: string | null; notes: string | null; claim_suggestion: ClaimSuggestion | null }
export interface ReceiptRow { id: string; purchase_order_id: string; shipment_id: string | null; received_on: string; document_id: string | null; note: string | null; items: { id: string; purchase_order_item_id: string; quantity: string; condition: string; note: string | null }[]; claim_suggestion: ClaimSuggestion | null }
export interface ClaimRow {
  id: string; case_id: string; direction: string; counterparty_id: string; kind: string; purchase_order_id: string | null; shipment_id: string | null;
  receipt_id: string | null; delivery_id: string | null; inspection_id: string | null; claimed_amount: string | null; claimed_amount_currency: string | null;
  opened_on: string; status: string; resolution: string | null; resolution_amount: string | null; resolution_amount_currency: string | null;
  resolved_on: string | null; notes: string | null; counterparty: PartyRef; followups: { id: string; due_on: string; action: string }[];
}
export interface DeliveryRow { id: string; sales_order_id: string; shipment_id: string | null; delivered_on: string; delivery_place: string | null; receiver_name: string | null; receipt_document_id: string | null; note: string | null; items: { id: string; sales_order_item_id: string; quantity: string }[] }
export interface CashPosition {
  actual: Record<string, { received: string; paid: string; net_tied_up: string }>;
  outstanding: Record<string, { in: string; out: string }>;
  plan: { exposure: string; currency: string } | null;
}
export interface DelayWarning { kind: "eta_passed" | "eta_moved" | "ready_passed"; case_id: string; shipment_id?: string; purchase_order_id?: string; number?: string; eta?: string; first_eta?: string; ready_due_on?: string; days: number; transport_doc_no?: string | null; case_title?: string }
export interface ExecutionHeader {
  order: { id: string; number: string; status: string; warranty_ends_on: string | null } | null; items_delivered: number; items_total: number;
  next: { kind: "step" | "delivery_due"; due_on: string | null; label_fa?: string; label_en?: string; number?: string; overdue?: boolean } | null;
  cash: CashPosition["actual"]; warnings: number;
}
export interface CaseExecution {
  sales_orders: SalesOrderRow[]; candidates: { source: "quote" | "tender_proposal"; quote_id?: string; tender_proposal_id?: string; number: string | null; status?: string; version?: number; total: string; currency: string }[];
  cash: CashPosition; milestones_out: MilestoneRow[]; purchase_orders: PurchaseOrderRow[]; processes: ProcessRow[]; shipments: ShipmentRow[];
  inspections: InspectionRow[]; receipts: ReceiptRow[]; claims: ClaimRow[]; deliveries: DeliveryRow[]; warnings: DelayWarning[]; header: ExecutionHeader | null;
}
export interface ExecutionSummary {
  pos_unconfirmed: { purchase_order_id: string; case_id: string; number: string; sent_at: string; days: number; case_title: string }[];
  ready_passed: DelayWarning[]; shipments_delayed: DelayWarning[];
  steps_due: { step_id: string; case_id: string; label_fa: string; label_en: string; due_on: string; overdue: boolean; case_title: string }[];
  payments_overdue: { milestone_id: string; case_id: string; direction: "in" | "out"; kind: string; due_on: string; amount: string; currency: string; case_title: string }[];
  claims_open: { claim_id: string; case_id: string; kind: string; direction: string; status: string; opened_on: string; case_title: string }[];
  deliveries_due: { sales_order_id: string; case_id: string; number: string; delivery_due_on: string; overdue: boolean; case_title: string }[];
}
