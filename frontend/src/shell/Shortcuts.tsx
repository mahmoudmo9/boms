/** The keyboard shortcut sheet (v0.10.0 section 3), opened with «?» when no field has focus. */
import { useTranslation } from "react-i18next";

import { Kbd, Modal } from "../design/components";

export const SHORTCUTS: { group: string; items: { keys: string[]; label: string }[] }[] = [
  { group: "everywhere", items: [{ keys: ["Ctrl", "K"], label: "palette" }, { keys: ["/"], label: "paletteSlash" }, { keys: ["?"], label: "sheet" },
    { keys: ["Ctrl", "Shift", "L"], label: "quickLog" }, { keys: ["Esc"], label: "close" }] },
  { group: "lists", items: [{ keys: ["↑", "↓"], label: "rows" }, { keys: ["Home", "End"], label: "ends" }, { keys: ["Enter"], label: "openRow" }, { keys: ["Space"], label: "selectRow" }] },
  { group: "triage", items: [{ keys: ["S"], label: "star" }, { keys: ["R"], label: "reviewing" }, { keys: ["D"], label: "dismiss" }, { keys: ["←", "→"], label: "nextPrev" }] },
  { group: "fields", items: [{ keys: ["Tab"], label: "acceptSuggestion" }, { keys: ["Alt", "↓"], label: "openCalendar" }] },
];

export function ShortcutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal open={open} size="md" title={t("shortcuts.title")} onClose={onClose} testId="shortcut-sheet">
      <div className="grid gap-6 sm:grid-cols-2">
        {SHORTCUTS.map((g) => (
          <section key={g.group}>
            <h3 className="mb-2 text-xs font-semibold text-muted">{t(`shortcuts.group.${g.group}`)}</h3>
            <dl className="flex flex-col gap-2">
              {g.items.map((s) => (
                <div key={s.label} className="flex items-center justify-between gap-3 text-sm">
                  <dt className="text-fg">{t(`shortcuts.${s.label}`)}</dt>
                  <dd className="flex shrink-0 gap-1" dir="ltr">{s.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  );
}
