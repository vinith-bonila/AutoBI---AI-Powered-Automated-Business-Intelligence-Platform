"use client";

/**
 * The dashboard filter row.
 *
 * Per the interaction guidance, filters live in ONE row above the charts, never
 * inside a chart card, so a single control set drives every visual at once.
 */

import { useEffect, useRef, useState } from "react";

import type { FilterSpecification, FilterState } from "@/types";
import { formatDateInput } from "@/lib/format";
import { Badge, Button, cn } from "@/components/ui";

interface FilterBarProps {
  filters: FilterSpecification[];
  state: FilterState;
  onChange: (next: FilterState) => void;
  activeCount: number;
}

export function FilterBar({
  filters,
  state,
  onChange,
  activeCount,
}: FilterBarProps) {
  if (!filters.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {filters.map((filter) =>
        filter.kind === "date_range" ? (
          <DateRangeFilter
            key={filter.id}
            filter={filter}
            value={(state[filter.id] as [string, string]) ?? null}
            onChange={(value) => onChange({ ...state, [filter.id]: value })}
          />
        ) : (
          <MultiSelectFilter
            key={filter.id}
            filter={filter}
            value={(state[filter.id] as string[]) ?? []}
            onChange={(value) => onChange({ ...state, [filter.id]: value })}
          />
        ),
      )}
      {activeCount > 0 ? (
        <Button
          variant="ghost"
          className="text-xs"
          onClick={() => onChange({})}
        >
          Clear all ({activeCount})
        </Button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------

function useOutsideClick(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handle(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);
  return ref;
}

function MultiSelectFilter({
  filter,
  value,
  onChange,
}: {
  filter: FilterSpecification;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useOutsideClick(() => setOpen(false));

  const selected = new Set(value);
  const options = filter.options.filter((option) =>
    option.toLowerCase().includes(query.toLowerCase()),
  );

  function toggle(option: string) {
    const next = new Set(selected);
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange([...next]);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={cn(
          "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
          selected.size > 0
            ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
            : "border-[var(--color-hairline)] bg-[var(--color-surface)] text-[var(--color-ink-secondary)] hover:bg-[var(--color-plane)]",
        )}
      >
        <span className="font-medium">{filter.label}</span>
        {selected.size > 0 ? (
          <Badge tone="accent" className="px-1.5 py-0">
            {selected.size}
          </Badge>
        ) : null}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          className={cn("transition-transform", open && "rotate-180")}
        >
          <path
            d="m6 9 6 6 6-6"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1.5 w-64 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-2 shadow-lg">
          {filter.options.length > 8 ? (
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${filter.label.toLowerCase()}…`}
              className="mb-2 w-full rounded-md border border-[var(--color-hairline)] bg-[var(--color-plane)] px-2.5 py-1.5 text-sm text-[var(--color-ink)] outline-none focus:border-[var(--color-accent)]"
            />
          ) : null}
          <ul className="scroll-thin max-h-60 space-y-0.5 overflow-y-auto">
            {options.length === 0 ? (
              <li className="px-2 py-2 text-xs text-[var(--color-ink-muted)]">
                No matches.
              </li>
            ) : (
              options.map((option) => {
                const checked = selected.has(option);
                return (
                  <li key={option}>
                    <button
                      type="button"
                      onClick={() => toggle(option)}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-[var(--color-ink)] hover:bg-[var(--color-plane)]"
                    >
                      <span
                        className={cn(
                          "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                          checked
                            ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                            : "border-[var(--color-axis)]",
                        )}
                      >
                        {checked ? (
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                            <path
                              d="m5 12 5 5L20 7"
                              stroke="currentColor"
                              strokeWidth="3"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        ) : null}
                      </span>
                      <span className="truncate">{option}</span>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
          {selected.size > 0 ? (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mt-2 w-full rounded-md border border-[var(--color-hairline)] px-2 py-1.5 text-xs text-[var(--color-ink-secondary)] hover:bg-[var(--color-plane)]"
            >
              Clear {filter.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function DateRangeFilter({
  filter,
  value,
  onChange,
}: {
  filter: FilterSpecification;
  value: [string, string] | null;
  onChange: (value: [string, string] | null) => void;
}) {
  const min = formatDateInput(filter.min as string);
  const max = formatDateInput(filter.max as string);
  const from = value?.[0] ? formatDateInput(value[0]) : "";
  const to = value?.[1] ? formatDateInput(value[1]) : "";

  function update(next: [string, string]) {
    if (!next[0] && !next[1]) onChange(null);
    else onChange(next);
  }

  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-1.5">
      <span className="text-sm font-medium text-[var(--color-ink-secondary)]">
        {filter.label}
      </span>
      <input
        type="date"
        value={from}
        min={min}
        max={to || max}
        onChange={(event) => update([event.target.value, to])}
        className="rounded-md bg-transparent px-1 py-1 text-sm text-[var(--color-ink)] outline-none [color-scheme:light_dark]"
        aria-label={`${filter.label} from`}
      />
      <span className="text-[var(--color-ink-muted)]">–</span>
      <input
        type="date"
        value={to}
        min={from || min}
        max={max}
        onChange={(event) => update([from, event.target.value])}
        className="rounded-md bg-transparent px-1 py-1 text-sm text-[var(--color-ink)] outline-none [color-scheme:light_dark]"
        aria-label={`${filter.label} to`}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange(null)}
          aria-label={`Clear ${filter.label}`}
          className="ml-0.5 text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path
              d="M18 6 6 18M6 6l12 12"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </button>
      ) : null}
    </div>
  );
}
