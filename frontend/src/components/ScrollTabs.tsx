/** A tab bar that never clips (v0.9.0): it scrolls horizontally, fades at the edge that has more tabs, keeps the active
 * tab in view and offers an overflow menu («⋯») listing every tab. Shared so the later restyle changes it in one place. */
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface TabItem { key: string; label: ReactNode; testId?: string }

export function ScrollTabs({ tabs, active, onSelect, label }: { tabs: TabItem[]; active: string; onSelect: (key: string) => void; label?: string }) {
  const { t } = useTranslation();
  const bar = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const [menu, setMenu] = useState(false);

  const measure = useCallback(() => {
    const el = bar.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const pos = Math.abs(el.scrollLeft);              // RTL scrollLeft runs negative in Chromium and Firefox
    setEdges({ start: pos > 1, end: pos < max - 1 });
  }, []);

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    el.querySelector<HTMLElement>(`[data-tab="${active}"]`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(el);
    return () => observer?.disconnect();
  }, [active, measure, tabs.length]);

  return (
    <div className="relative flex items-stretch border-b border-line" data-testid="scroll-tabs">
      <div ref={bar} role="tablist" aria-label={label} onScroll={measure}
        className="flex min-w-0 flex-1 gap-1 overflow-x-auto [scrollbar-width:thin]">
        {tabs.map((tab) => (
          <button key={tab.key} type="button" role="tab" aria-selected={tab.key === active} data-tab={tab.key} data-testid={tab.testId}
            onClick={() => onSelect(tab.key)}
            className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm whitespace-nowrap ${tab.key === active ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
            {tab.label}
          </button>
        ))}
      </div>
      {edges.start && <span aria-hidden className="pointer-events-none absolute inset-y-0 start-0 w-8 bg-gradient-to-r from-bg to-transparent rtl:bg-gradient-to-l" data-fade="start" />}
      {edges.end && <span aria-hidden className="pointer-events-none absolute inset-y-0 end-10 w-8 bg-gradient-to-l from-bg to-transparent rtl:bg-gradient-to-r" data-fade="end" />}
      <div className="relative shrink-0">
        <button type="button" aria-haspopup="menu" aria-expanded={menu} aria-label={t("common.moreTabs")} data-testid="tabs-more"
          onClick={() => setMenu(!menu)} className="h-full px-2.5 text-muted hover:text-fg">⋯</button>
        {menu && (
          <ul role="menu" className="absolute end-0 top-full z-20 mt-1 max-h-80 min-w-48 overflow-y-auto rounded-md border border-line bg-surface py-1 shadow-lg">
            {tabs.map((tab) => (
              <li key={tab.key}><button type="button" role="menuitem" onClick={() => { onSelect(tab.key); setMenu(false); }}
                className={`block w-full px-3 py-1.5 text-start text-sm hover:bg-surface-2 ${tab.key === active ? "font-medium text-accent" : ""}`}>{tab.label}</button></li>))}
          </ul>)}
      </div>
    </div>
  );
}
