/** Listing panel helpers (v0.6.0, pure and unit-tested): labels for the technical fields (the site's own titles
 * first, the raw key only as a hint), value labels (TRUE -> «بله»), grouping as SetadSuite's group_pairs, Jalali
 * dates written by the site, and the agent's work on one listing. */
import { parse as parseJalali, isValid } from "date-fns-jalali";

import { stripRemainingRemark } from "./timeLeft";

type Lang = "fa" | "en";

/** Purchase-call raw keys (SetadSuite inquiries/storage.py FIELDS) and common tender keys without a site title. */
const TECH_LABELS: Record<string, { fa: string; en: string }> = {
  need_no: { fa: "شماره نیاز", en: "Need number" },
  request_id: { fa: "شناسه داخلی", en: "Internal id" },
  description: { fa: "شرح کامل نیاز", en: "Full description" },
  organization: { fa: "دستگاه خریدار", en: "Buyer organisation" },
  province: { fa: "استان", en: "Province" },
  need_type: { fa: "نوع نیاز", en: "Need type" },
  category: { fa: "طبقه‌بندی", en: "Category" },
  goods_group: { fa: "گروه کالا", en: "Goods group" },
  service_group: { fa: "گروه خدمت", en: "Service group" },
  published_date: { fa: "تاریخ اعلام", en: "Published" },
  response_deadline: { fa: "مهلت پاسخ", en: "Response deadline" },
  detail_url: { fa: "آدرس جزئیات", en: "Detail page" },
  remainingTime: { fa: "زمان باقی‌مانده", en: "Time left" },
  recCount: { fa: "تعداد کل ردیف‌ها", en: "Rows in the list" },
  favoriteCount: { fa: "تعداد علاقه‌مندی", en: "Favourites" },
  tenderTypeId: { fa: "کد نوع فراخوان", en: "Tender type code" },
  setupCode: { fa: "کد نوع برگزاری", en: "Setup code" },
  guarantyPrice: { fa: "مبلغ تضمین", en: "Guarantee amount" },
  guarantyPriceCurrency: { fa: "واحد پول تضمین", en: "Guarantee currency" },
  guarantyDescription: { fa: "شرح تضمین", en: "Guarantee description" },
  financialEstimatePrice: { fa: "برآورد مالی", en: "Financial estimate" },
  renewalAppendixCount: { fa: "تعداد الحاقیهٔ تمدید", en: "Renewal addenda" },
  priceAppendixCount: { fa: "تعداد الحاقیهٔ قیمت", en: "Price addenda" },
  cancelAppendixCount: { fa: "تعداد الحاقیهٔ لغو", en: "Cancellation addenda" },
};

const VALUE_LABELS: Record<string, { fa: string; en: string }> = {
  TRUE: { fa: "بله", en: "Yes" }, FALSE: { fa: "خیر", en: "No" },
  ONE_STAGE_TENDER: { fa: "مناقصه یک مرحله‌ای", en: "One-stage tender" },
  TWO_STAGE_TENDER: { fa: "مناقصه دو مرحله‌ای", en: "Two-stage tender" },
  QUALITY_EVALUATION_TENDER: { fa: "مناقصه با ارزیابی کیفی", en: "Tender with quality evaluation" },
  ADD_TO_MY_FAVORITE: { fa: "در فراخوان‌های من", en: "In my calls" },
};

export function technicalLabel(key: string, siteLabel: string | null | undefined, lang: Lang): string | null {
  if (siteLabel) return siteLabel;
  const short = key.split(".").pop() ?? key;
  return TECH_LABELS[key]?.[lang] ?? TECH_LABELS[short]?.[lang] ?? null;
}

export function valueLabel(value: string, lang: Lang): string {
  const v = String(value ?? "").trim();
  return VALUE_LABELS[v.toUpperCase()]?.[lang] ?? v;
}

/** SetadSuite group_pairs: the same section words, applied to the label (or the key). */
const SECTIONS: [string, string[]][] = [
  ["schedule", ["تاریخ", "مهلت", "زمان", "ساعت", "بازگشایی", "date", "deadline", "time"]],
  ["money", ["مبلغ", "تضمین", "ضمانت", "ریال", "قیمت", "برآورد", "سپرده", "هزینه", "بودجه", "اعتبار", "price", "estimate", "guarant"]],
  ["organisation", ["دستگاه", "سازمان", "کارفرما", "مناقصه‌گزار", "آدرس", "نشانی", "تلفن", "پست", "نماینده", "organ", "address", "phone"]],
];

export interface TechRow { key: string; label: string | null; value: string }

export function groupTechnical(rows: TechRow[], filter = ""): { group: string; rows: TechRow[] }[] {
  const q = filter.trim().toLowerCase();
  const groups: Record<string, TechRow[]> = { general: [], schedule: [], money: [], organisation: [] };
  for (const r of rows) {
    if (q && ![r.key, r.label ?? "", r.value].some((x) => x.toLowerCase().includes(q))) continue;
    const text = `${r.label ?? ""} ${r.key}`.toLowerCase();
    const hit = SECTIONS.find(([, words]) => words.some((w) => text.includes(w.toLowerCase())));
    groups[hit ? hit[0] : "general"].push(r);
  }
  return Object.entries(groups).filter(([, v]) => v.length)
    .map(([group, list]) => ({ group, rows: [...list].sort((a, b) => (a.label ?? a.key).localeCompare(b.label ?? b.key, "fa")) }));
}

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const latin = (s: string) => s.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));

/** A Jalali date (and time) as the site writes it («1405/08/06 - 10:03», «1405/08/12 ساعت 14:00»), without the
 * «(باقی‌مانده …)» remark -> {iso, time}; null when the value is not just a date. */
export function siteDate(value: string): { iso: string; time: boolean } | null {
  const text = latin(stripRemainingRemark(String(value ?? "")));
  const m = text.match(/^\s*(\d{4})\/(\d{1,2})\/(\d{1,2})(?:\s*(?:-|ساعت|،)?\s*(\d{1,2}):(\d{2})(?::\d{2})?)?\s*$/);
  if (!m) return null;
  const [, y, mo, d, h, mi] = m;
  const parsed = parseJalali(`${y}/${mo.padStart(2, "0")}/${d.padStart(2, "0")} ${h ? h.padStart(2, "0") : "00"}:${mi ?? "00"}`,
    "yyyy/MM/dd HH:mm", new Date());
  return isValid(parsed) ? { iso: parsed.toISOString(), time: Boolean(h) } : null;
}

/** What the agent is doing for one listing: queued / running (with attachment n of m) / nothing. */
export interface AgentJobs {
  jobs?: { id: string; command: string; status: string; listing_ids: string[] }[];
  job_id?: string | null;
  listing_id?: string | null;
  files_done?: number | null;
  files_total?: number | null;
}

export function listingJobState(agent: AgentJobs | undefined, listingId: string, command: "download_files" | "fetch_detail") {
  const job = (agent?.jobs ?? []).find((j) => j.command === command && j.listing_ids.includes(listingId));
  if (!job) return null;
  const running = job.status === "running" && agent?.job_id === job.id && agent?.listing_id === listingId;
  return { jobId: job.id, state: running ? "running" as const : "queued" as const,
    done: running ? agent?.files_done ?? null : null, total: running ? agent?.files_total ?? null : null };
}

export interface TrackedJob { command: string; listing_ids: string[] }

/** Jobs that were queued or running before and are gone now (finished): their listings are refreshed and the owner
 * gets a toast. Returns [finished, the map to keep for the next poll]. */
export function finishedJobs(before: Map<string, TrackedJob>, jobs: { id: string; command: string; listing_ids: string[] }[]):
  [{ id: string; job: TrackedJob }[], Map<string, TrackedJob>] {
  const now = new Map(jobs.map((j) => [j.id, { command: j.command, listing_ids: j.listing_ids }]));
  const done = [...before].filter(([id]) => !now.has(id)).map(([id, job]) => ({ id, job }));
  return [done, now];
}
