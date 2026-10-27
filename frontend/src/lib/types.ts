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
  approval: { ok: boolean; failures: GateFailure[]; max_valid_until: string | null } | null;
  default_followup: { action: string; due_on: string } | null;
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
