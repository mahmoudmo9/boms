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
