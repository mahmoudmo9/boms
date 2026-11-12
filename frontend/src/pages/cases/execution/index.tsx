/** Execution (v0.7.0): the four case tabs and the case header facts. */
import { useTranslation } from "react-i18next";

import { Badge, Bdi } from "../../../design/components";
import { SO_TONE } from "../../../lib/execution";
import { useFormat } from "../../../lib/prefs";
import { Money } from "../../sourcing/shared";
import { useExecution } from "./shared";

export { DeliveryTab } from "./DeliveryTab";
export { LogisticsTab } from "./LogisticsTab";
export { OrderTab } from "./OrderTab";
export { PurchaseTab } from "./PurchaseTab";

/** Order status, delivery progress («۲ از ۳ قلم»), the next due step or date, the cash so far. */
export function ExecutionHeaderFacts({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const ex = useExecution(caseId);
  const h = ex.data?.header;
  if (!h) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="execution-header">
      {h.order && <Badge tone={SO_TONE[h.order.status]}><Bdi ltr>{h.order.number}</Bdi>&nbsp;{t(`execution.order.statuses.${h.order.status}`)}</Badge>}
      {h.items_total > 0 && <Badge tone={h.items_delivered === h.items_total ? "success" : "neutral"}>{t("execution.order.itemsDelivered", { done: f.num(h.items_delivered), total: f.num(h.items_total) })}</Badge>}
      {h.next && <span className={`text-xs ${h.next.overdue ? "text-danger" : ""}`}>{t("execution.header.next")}: {h.next.kind === "step"
        ? <span dir="auto">{f.lang === "fa" ? h.next.label_fa : h.next.label_en}</span> : t("execution.header.deliveryDue")}{h.next.due_on && <> · <span className="tabular-nums">{f.day(h.next.due_on)}</span></>}</span>}
      {Object.entries(h.cash).map(([cur, v]) => <span key={cur} className="text-xs">{t("execution.cash.net")}: <Money amount={v.net_tied_up} currency={cur} /></span>)}
      {h.warnings > 0 && <Badge tone="danger">{t("execution.header.warnings", { n: f.num(h.warnings) })}</Badge>}
    </span>
  );
}
