/** Case tab «مالی» (v0.8.0): invoices, supplier invoices, actual costs, payments and allocations, the profit table
 * and «بستن» with the checklist; the header facts show invoiced / paid status and profit so far. */
import { useTranslation } from "react-i18next";

import { ErrorNote, Loading } from "../../../design/components";
import { useFormat } from "../../../lib/prefs";
import type { CaseDetail } from "../../../lib/types";
import { useExecution } from "../execution/shared";
import { CloseCard } from "./CloseCard";
import { CostsCard } from "./CostsCard";
import { DealCashCard } from "./DealCashCard";
import { InvoicesCard } from "./InvoicesCard";
import { PaymentsCard } from "./PaymentsCard";
import { ProfitBridgeCard, ProfitCard } from "./ProfitCard";
import { useFinance } from "./shared";
import { SupplierInvoicesCard } from "./SupplierInvoicesCard";

export function FinanceTab({ caseData }: { caseData: CaseDetail }) {
  const finance = useFinance(caseData.id);
  const execution = useExecution(caseData.id);
  if (finance.isLoading) return <Loading />;
  if (finance.error || !finance.data) return <ErrorNote error={finance.error} />;
  const d = finance.data;
  const closed = caseData.status === "closed";   // a closed deal is read-only
  return (
    <div className="flex flex-col gap-4" data-testid="finance-tab">
      <ProfitBridgeCard profit={d.profit} />
      <DealCashCard execution={execution.data} />
      <div className="grid gap-4 xl:grid-cols-2">
        <InvoicesCard caseId={caseData.id} invoices={d.sales_invoices} execution={execution.data} readOnly={closed} />
        <SupplierInvoicesCard caseId={caseData.id} invoices={d.purchase_invoices} execution={execution.data} readOnly={closed} />
        <CostsCard caseId={caseData.id} costs={d.actual_costs} readOnly={closed} />
        <PaymentsCard caseId={caseData.id} payments={d.payments} readOnly={closed} />
      </div>
      <ProfitCard profit={d.profit} />
      <CloseCard caseId={caseData.id} closed={closed} />
    </div>
  );
}

export function FinanceHeaderFacts({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const finance = useFinance(caseId);
  const d = finance.data;
  if (!d || (!d.sales_invoices.length && !d.purchase_invoices.length)) return null;
  const issued = d.sales_invoices.filter((i) => i.status === "issued" && i.kind === "invoice");
  const due = issued.reduce((s, i) => s + Number(i.balance_due), 0);
  return (
    <span className="text-xs text-muted" data-testid="finance-header">
      {t("finance.header", { n: f.num(issued.length), due: f.num(due), profit: f.num(d.profit.profit.actual.deal), cur: d.profit.deal_currency })}
    </span>
  );
}
