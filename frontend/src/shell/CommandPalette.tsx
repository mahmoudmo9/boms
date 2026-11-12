/** The command palette (v0.10.0 section 3, reference `ProCommand`): Ctrl+K anywhere, or «/» when no field has focus.
 * One field over `/api/search` — cases, listings, parties, products, documents and records by code, an exact code
 * first — and the palette's actions (new inquiry, new party, new task, settings pages, theme, language). With an
 * empty field: recent items and the main actions. Arrow keys, Home, End, Enter, Esc. Logic: lib/palette.ts.
 * The mockup's «از دستیار بپرس» row is not built (the assistant comes in v0.12.0). */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { Icon, Kbd, Spinner, useFocusTrap } from "../design/components";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { buildSections, flatten, GROUP_ICON, highlight, loadRecent, moveActive, type PaletteAction, type PaletteRow, pushRecent, saveRecent,
  staticActions } from "../lib/palette";
import { useFormat } from "../lib/prefs";
import type { SearchGroup, SearchHit } from "../lib/types";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => { const id = window.setTimeout(() => setDebounced(value), ms); return () => window.clearTimeout(id); }, [value, ms]);
  return debounced;
}

function Marked({ text, q }: { text: string; q: string }) {
  return <>{highlight(text, q).map((p, i) => (p.match ? <mark key={i} className="bg-transparent font-semibold text-accent">{p.text}</mark> : <span key={i}>{p.text}</span>))}</>;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const { updatePrefs } = useAuth();
  const navigate = useNavigate();
  const panel = useRef<HTMLDivElement>(null);
  const listId = useId();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState(loadRecent);
  const debounced = useDebounced(q.trim(), 150);
  useFocusTrap(panel, open, onClose);

  const search = useQuery({
    queryKey: ["search", "palette", debounced],
    queryFn: ({ signal }) => api<{ groups: SearchGroup[] }>("/api/search", { query: { q: debounced, limit: 5 }, signal, background: true }),
    enabled: open && debounced.length > 0, staleTime: 10_000,
  });
  const fresh = debounced === q.trim();
  const actions = useMemo(staticActions, []);
  const label = (a: PaletteAction) => t(a.labelKey, Object.fromEntries(Object.entries(a.labelValues ?? {}).map(([k, v]) => [k, k === "page" ? t(v) : v])));
  const sections = useMemo(() => buildSections({ q: fresh ? q : "", groups: fresh && debounced ? search.data?.groups ?? [] : [], actions, recent, label,
    titleOf: (h: SearchHit) => h.title_i18n?.[f.lang] ?? h.title }),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [q, fresh, debounced, search.data, actions, recent, f.lang, i18n.language]);
  const rows = flatten(sections);

  useEffect(() => { if (open) { setQ(""); setActive(0); setRecent(loadRecent()); } }, [open]);
  useEffect(() => setActive(0), [debounced]);
  if (!open) return null;

  const run = (row: PaletteRow) => {
    onClose();
    if (row.kind === "hit") {
      const next = pushRecent(recent, { id: row.hit.id, type: row.group, title: row.title, subtitle: row.hit.subtitle, link: row.hit.link });
      saveRecent(next);
      setRecent(next);
      navigate(row.hit.link);
    } else if (row.kind === "recent") {
      const next = pushRecent(recent, row.recent);
      saveRecent(next);
      setRecent(next);
      navigate(row.recent.link);
    } else {
      const r = row.action.run;
      if (r.kind === "navigate") navigate(r.to);
      else if (r.kind === "theme") void updatePrefs({ theme: r.theme });
      else void updatePrefs({ language: r.language });
    }
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || (e.key === "Home" && e.ctrlKey) || (e.key === "End" && e.ctrlKey)) {
      e.preventDefault();
      setActive((i) => moveActive(i, e.key as "ArrowDown" | "ArrowUp" | "Home" | "End", rows.length));
    } else if (e.key === "Enter" && rows[active]) {
      e.preventDefault();
      run(rows[active]);
    }
  };

  let index = -1;
  return (
    <div className="fixed inset-0 z-(--z-palette) flex animate-fade-in items-start justify-center bg-overlay p-4 pt-24" onMouseDown={onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={t("palette.title")} onMouseDown={(e) => e.stopPropagation()} data-testid="command-palette"
        className="w-full max-w-3xl animate-rise-in overflow-hidden rounded-3xl border border-accent-line bg-surface-3 shadow-xl focus-within:border-accent">
        <div className="flex items-center gap-3 border-b border-line px-5">
          <Icon name="search" size={18} className="text-accent" />
          <input data-autofocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder={t("palette.placeholder")} dir="auto"
            role="combobox" aria-expanded={rows.length > 0} aria-controls={listId} aria-autocomplete="list" aria-label={t("palette.title")}
            aria-activedescendant={rows[active] ? `${listId}-${active}` : undefined} data-testid="palette-input"
            className="h-16 min-w-0 flex-1 bg-transparent text-lg text-title outline-none placeholder:text-muted focus-visible:outline-none" />
          {search.isFetching && <Spinner size={14} />}
          <Kbd>Esc</Kbd>
        </div>
        <div id={listId} role="listbox" aria-label={t("palette.results")} className="max-h-[60vh] overflow-y-auto p-2.5">
          {debounced && fresh && !search.isFetching && (search.data?.groups.length ?? 0) === 0 && (
            <p className="px-3 pt-3 pb-1 text-sm text-muted" data-testid="palette-empty">{t("palette.noResults", { q: debounced })}</p>
          )}
          {sections.map((section) => (
            <div key={section.key} role="group" aria-label={i18n.exists(section.labelKey) ? t(section.labelKey) : section.key} className="pb-1.5" data-group={section.key}>
              <div className="px-3 pt-2.5 pb-1.5 text-xs text-muted">{i18n.exists(section.labelKey) ? t(section.labelKey) : section.key}</div>
              {section.rows.map((row) => {
                index += 1;
                const i = index;
                const selected = i === active;
                const icon = row.kind === "hit" ? GROUP_ICON[row.group] ?? "file" : row.kind === "recent" ? "clock" : row.action.icon;
                const title = row.kind === "hit" ? row.title : row.kind === "recent" ? row.recent.title : label(row.action);
                const subtitle = row.kind === "hit" ? row.hit.subtitle : row.kind === "recent" ? row.recent.subtitle : null;
                return (
                  <div key={row.key} id={`${listId}-${i}`} role="option" aria-selected={selected} data-testid="palette-row" data-kind={row.kind}
                    data-exact={row.kind === "hit" && row.exact ? "true" : undefined} onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => run(row)}
                    className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2 text-sm ${selected ? "border-accent-line bg-accent-soft" : "border-transparent"}`}>
                    <Icon name={icon} size={16} className={selected ? "text-accent" : "text-muted"} />
                    <span className="min-w-0 truncate text-fg"><bdi>{row.kind === "hit" ? <Marked text={title} q={debounced} /> : title}</bdi></span>
                    {subtitle && <bdi className="min-w-0 truncate text-xs text-muted">{subtitle}</bdi>}
                    {row.kind === "hit" && row.exact && <span className="shrink-0 rounded-sm border border-accent-line px-1.5 text-2xs text-accent">{t("palette.exactCode")}</span>}
                    <span className="ms-auto shrink-0">{selected ? <Kbd>Enter</Kbd> : row.kind === "action" && row.action.hint ? <Kbd>{row.action.hint}</Kbd> : null}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-xs text-muted">
          <span className="flex items-center gap-4"><span><Kbd>↑</Kbd> <Kbd>↓</Kbd> {t("palette.move")}</span><span><Kbd>Enter</Kbd> {t("palette.openRow")}</span></span>
          <span><Kbd>Ctrl K</Kbd> <Kbd>/</Kbd> {t("palette.anywhere")}</span>
        </div>
      </div>
    </div>
  );
}
