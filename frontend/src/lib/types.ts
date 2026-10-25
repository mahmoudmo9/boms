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
  is_primary: boolean;
  status: "active" | "archived";
}

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
