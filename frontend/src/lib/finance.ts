/** Deal finance (v0.8.0): types of the finance API and pure, unit-tested helpers — the aging bucket, the profit table
 * rows (variance sign and tone in both currencies), the close checklist problems and the invoice statuses. */
import type { Tone } from "./execution";

export type Pair = { deal: string | null; base: string | null } | null;

export interface ProfitRow {
  kind: string;
  planned: Pair;
  actual: { deal: string; base: string };
  variance: Pair;
  variance_percent: string | null;
  estimated: boolean;
  unrealized: boolean;
}

export interface Profit {
  case_id: string;
  status: "open" | "closed";
  frozen: boolean;
  computed_at?: string;
  deal_currency: string;
  base_currency: string;
  plan: { sheet_id: string; version: number; currency: string } | { error: string } | null;
  rows: ProfitRow[];
  revenue: { planned: Pair; actual: { deal: string; base: string }; variance: Pair };
  cost: { planned: Pair; actual: { deal: string; base: string }; variance: Pair };
  profit: { planned: Pair; actual: { deal: string; base: string }; variance: Pair };
  margin_percent: { planned: string | null; actual: string | null };
  markup_percent: { planned: string | null; actual: string | null };
  fx_effect: { deal: string; base: string };
  unrealized: { revenue: string; cost: string };
  vat: { output: { deal: string; base: string }; input: { deal: string; base: string }; net: { deal: string; base: string } };
  cost_of_money: { planned: Pair; actual: { deal: string; base: string }; days: number; annual_percent: string };
  /** v0.9.0: the sales order's revenue (± notes) and the cost still to come; estimated parts reported apart */
  expected: { revenue: string; cost: string; profit: string; margin_percent: string | null;
    estimated: { goods: string; planned_costs: string } } | null;
  missing_rates: string[];
}

export interface InvoiceLine {
  id: string; sales_order_item_id: string | null; position: number; description: string; quantity: string; unit: string | null;
  unit_price: string; discount: string; total: string; hs_code: string | null;
}

export interface SalesInvoice {
  id: string; case_id: string; sales_order_id: string; number: string | null; kind: "invoice" | "credit_note" | "debit_note";
  corrects_invoice_id: string | null; corrects_number: string | null; language: "fa" | "en"; issue_date: string | null;
  due_date: string | null; currency: string; subtotal: string; discount: string; vat_rate: string; vat_amount: string; vat_note: string | null;
  total: string; status: "draft" | "issued" | "cancelled"; moadian_tax_id: string | null;
  moadian_status: "not_required" | "not_sent" | "sent" | "accepted" | "rejected"; moadian_on: string | null; moadian_note: string | null;
  lines: InvoiceLine[]; allocated: string; balance_due: string; payment_status: string; missing_for_issue: string[];
  notes_list: { id: string; kind: string; number: string | null; status: string; total: string }[]; default_vat_rate?: string;
  over_delivered_reason: string | null; notes: string | null; customer: { id: string; name_fa: string | null; name_en: string | null };
}

export interface MatchingRow {
  purchase_order_item_id: string; description: string; ordered: string; received: string; invoiced: string; this_invoice: string;
  po_price: string; invoice_price: string | null; price_difference: string | null; flags: string[];
}

export interface PurchaseInvoice {
  id: string; case_id: string; purchase_order_id: string | null; purchase_order_number: string | null; supplier_party_id: string;
  supplier_invoice_no: string; invoice_date: string; due_date: string | null; currency: string; subtotal: string; vat_amount: string;
  total: string; status: "received" | "approved" | "disputed" | "cancelled"; difference_reason: string | null; dispute_reason: string | null;
  claim_id: string | null; lines: { id: string; description: string; quantity: string; unit_price: string; total: string }[];
  matching: { rows: MatchingRow[]; unmatched: unknown[]; differences: { flags: string[]; description?: string }[] };
  allocated: string; balance_due: string; payment_status: string; supplier: { id: string; name_fa: string | null; name_en: string | null };
}

export interface CostRow {
  id?: string; source: string; source_id?: string; kind: string; description: string; party_id?: string | null; amount: string;
  currency: string; fx_rate_to_base?: string | null; base_amount: string | null; vat_amount?: string | null; incurred_on: string | null;
  status: string; read_only: boolean; balance_due?: string;
}

export interface Allocation { id: string; sales_invoice_id: string | null; purchase_invoice_id: string | null; actual_cost_id: string | null;
  amount: string; fx_rate: string | null; target_amount: string }

export interface PaymentRecordRow {
  id: string; milestone_id: string; direction: "in" | "out"; case_id: string; party_id: string; paid_on: string; amount: string;
  amount_currency: string; fx_rate_to_base: string | null; base_amount: string | null; rate_source: string | null; bank_fee: string | null;
  reference: string | null; allocated: string; unallocated: string; rate_missing: boolean; allocations: Allocation[];
}

export interface Suggestion { sales_invoice_id?: string; purchase_invoice_id?: string; actual_cost_id?: string; label: string;
  due_date: string | null; currency: string; balance: string; needs_rate: boolean; amount: string | null }

export interface CaseFinance {
  sales_invoices: SalesInvoice[]; purchase_invoices: PurchaseInvoice[]; actual_costs: CostRow[]; payments: PaymentRecordRow[];
  advances: { record_id: string; unallocated: string; currency: string }[]; profit: Profit;
}

export interface ChecklistProblem { code: string; [key: string]: unknown }
export interface Checklist {
  passes: boolean; problems: ChecklistProblem[]; notes: { code: string; [key: string]: unknown }[];
  to_cancel: { tasks: { id: string; title: string }[]; followups: { id: string; action: string }[] };
}

export interface FinanceSummary {
  receivables_overdue: { invoice_id: string; number: string; case_id: string; case_title: string | null; balance: string; currency: string; days_past_due: number }[];
  payables_due: { id: string; label: string; case_id: string; case_title: string | null; balance: string; currency: string; due_date: string | null; window: string }[];
  delivered_not_invoiced: { sales_order_id: string; case_id: string; number: string; quantity: string; case_title: string | null }[];
  received_not_invoiced: { purchase_order_id: string; case_id: string; number: string; items: number; case_title: string | null }[];
  moadian_pending: { invoice_id: string; case_id: string; number: string; moadian_status: string; case_title: string | null }[];
  payments_without_rate: { record_id: string; case_id: string; paid_on: string; amount: string; currency: string; case_title: string | null }[];
  ready_to_close: { case_id: string; case_title: string | null }[];
}

export const AGING_BUCKETS = ["0-30", "31-60", "61-90", "90+"] as const;
export type AgingBucket = (typeof AGING_BUCKETS)[number];

/** Aging by days past the due date (same rule as the server): 0-30 including not yet due, 31-60, 61-90, 90+. */
export function agingBucket(dueDate: string, today: string): AgingBucket {
  const days = Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${dueDate}T00:00:00Z`)) / 86_400_000);
  if (days <= 30) return "0-30";
  if (days <= 60) return "31-60";
  if (days <= 90) return "61-90";
  return "90+";
}

/** A cost variance above plan is bad (danger), below plan good (success); for revenue and profit the other way. */
export function varianceTone(variance: string | null | undefined, side: "cost" | "revenue"): Tone {
  const n = Number(variance ?? 0);
  if (!n) return "neutral";
  return (side === "cost" ? n > 0 : n < 0) ? "danger" : "success";
}

/** "+1,200" / "−1,200" / "0": the sign is always shown (a real minus sign, U+2212). */
export function signed(value: string | null | undefined, format: (v: string) => string): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!n) return format("0");
  return `${n > 0 ? "+" : "−"}${format(String(Math.abs(n)))}`;
}

export interface TableLine { key: string; side: "cost" | "revenue" | "profit"; planned: Pair; actual: { deal: string; base: string } | null;
  variance: Pair; percent: string | null; estimated?: boolean; unrealized?: boolean }

/** The profit table: revenue first, then each cost kind, total cost and profit. */
export function profitLines(p: Profit): TableLine[] {
  return [
    { key: "revenue", side: "revenue", planned: p.revenue.planned, actual: p.revenue.actual, variance: p.revenue.variance, percent: null },
    ...p.rows.map((r) => ({ key: r.kind, side: "cost" as const, planned: r.planned, actual: r.actual, variance: r.variance,
      percent: r.variance_percent, estimated: r.estimated, unrealized: r.unrealized })),
    { key: "cost_total", side: "cost", planned: p.cost.planned, actual: p.cost.actual, variance: p.cost.variance, percent: null },
    { key: "profit", side: "profit", planned: p.profit.planned, actual: p.profit.actual, variance: p.profit.variance, percent: null },
  ];
}

export const PAYMENT_TONE: Record<string, Tone> = { unpaid: "warning", partly_paid: "accent", paid: "success", overpaid: "danger", none: "neutral" };
export const MOADIAN_TONE: Record<string, Tone> = { not_required: "neutral", not_sent: "warning", sent: "accent", accepted: "success", rejected: "danger" };
export const COST_KINDS = ["freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance", "storage",
  "inspection", "freight_domestic", "export_clearance", "other"] as const;

/** A checklist problem with a reason typed for it no longer blocks closing. */
export function unexplained(problems: ChecklistProblem[], reasons: Record<string, string>): string[] {
  return problems.filter((p) => !(reasons[p.code] ?? "").trim()).map((p) => p.code);
}
