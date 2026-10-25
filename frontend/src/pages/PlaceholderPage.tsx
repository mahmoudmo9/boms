import { useTranslation } from "react-i18next";

import { Icon } from "../components/Icon";
import { toFaDigits } from "../lib/format";
import type { Workspace } from "../lib/nav";
import { useFormat } from "../lib/prefs";

export function PlaceholderPage({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const f = useFormat();
  const phase = f.digits === "fa" ? toFaDigits(workspace.phase ?? "") : workspace.phase;
  return (
    <div className="mx-auto mt-16 max-w-md rounded-lg border border-dashed border-line-strong bg-surface p-8 text-center">
      <Icon name={workspace.icon} size={32} className="mx-auto text-muted" />
      <h1 className="mt-3 text-lg font-semibold">{t(`nav.${workspace.key}`)}</h1>
      <p className="mt-2 text-sm text-muted">{t("placeholder.text", { phase })}</p>
    </div>
  );
}

export function NotFoundPage() {
  const { t } = useTranslation();
  return <p className="p-8 text-center text-muted">{t("common.notFound")}</p>;
}
