"use client";

/**
 * Time-aggregation selector.
 *
 * Changing the grain re-buckets the underlying data (the backend re-runs
 * DATE_TRUNC at the chosen grain) — it is not a relabelling. Only shown when
 * the dataset actually has a usable date column.
 */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/components/ui";

const GRAINS: { value: string; label: string }[] = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
  { value: "year", label: "Yearly" },
];

export function TimeAggregation({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (grain: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = GRAINS.find((g) => g.value === value) ?? GRAINS[2];

  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-ink-secondary)] transition-colors hover:bg-[var(--color-plane)]"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="4" width="18" height="17" rx="2" stroke="currentColor" strokeWidth="2" />
          <path d="M3 9h18M8 2v4m8-4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span className="font-medium text-[var(--color-ink)]">{current.label}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className={cn("transition-transform", open && "rotate-180")}>
          <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1.5 w-40 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1 shadow-lg">
          {GRAINS.map((grain) => (
            <button
              key={grain.value}
              type="button"
              onClick={() => {
                onChange(grain.value);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-[var(--color-plane)]",
                grain.value === current.value
                  ? "text-[var(--color-accent)]"
                  : "text-[var(--color-ink)]",
              )}
            >
              <span className="w-3">{grain.value === current.value ? "✓" : ""}</span>
              {grain.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
