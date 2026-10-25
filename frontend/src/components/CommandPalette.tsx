/** Ctrl+K global search. Results grouped by type; arrow keys move across groups, Enter opens. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { api } from "../lib/api";
import { useFormat } from "../lib/prefs";
import type { SearchGroup, SearchHit } from "../lib/types";
import { Bdi } from "./Bdi";
import { Icon } from "./Icon";
import { Spinner } from "./ui";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const f = useFormat();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const debounced = useDebounced(q.trim(), 200);

  const { data, isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: ({ signal }) => api<{ groups: SearchGroup[] }>("/api/search", { query: { q: debounced, limit: 6 }, signal }),
    enabled: open && debounced.length > 0,
    staleTime: 10_000,
  });
  const groups = useMemo(() => (debounced ? data?.groups ?? [] : []), [data, debounced]);
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);
  useEffect(() => setActive(0), [debounced]);

  if (!open) return null;

  const go = (hit: SearchHit) => {
    onClose();
    navigate(hit.link);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(flat.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter" && flat[active]) {
      e.preventDefault();
      go(flat[active]);
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  let index = -1;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("search.title")}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-xl overflow-hidden rounded-lg border border-line bg-surface shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Icon name="search" className="text-muted" />
          <input
            ref={input}
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder={t("search.placeholder")}
            role="combobox"
            aria-expanded={flat.length > 0}
            aria-controls="palette-results"
            aria-activedescendant={flat[active] ? `hit-${active}` : undefined}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
          {isFetching && <Spinner size={14} />}
          <kbd className="rounded border border-line px-1.5 text-xs text-muted">Esc</kbd>
        </div>
        <div id="palette-results" role="listbox" className="max-h-[60vh] overflow-y-auto py-1">
          {debounced && !isFetching && groups.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted">{t("search.noResults")}</p>
          )}
          {!debounced && <p className="px-4 py-6 text-center text-sm text-muted">{t("search.hint")}</p>}
          {groups.map((group) => (
            <div key={group.type} className="py-1">
              <div className="px-4 py-1 text-xs font-semibold text-muted">
                {i18n.exists(group.label_key) ? t(group.label_key) : group.type}
              </div>
              {group.items.map((hit) => {
                index += 1;
                const i = index;
                const title = hit.title_i18n?.[f.lang] ?? hit.title;
                return (
                  <div
                    key={`${group.type}-${hit.id}`}
                    id={`hit-${i}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => go(hit)}
                    className={`mx-1 flex cursor-pointer items-center justify-between gap-3 rounded px-3 py-2 text-sm ${
                      i === active ? "bg-accent-soft" : ""
                    }`}
                  >
                    <span className="truncate">{title}</span>
                    {hit.subtitle && (
                      <Bdi className="shrink-0 truncate text-xs text-muted">{hit.subtitle}</Bdi>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
