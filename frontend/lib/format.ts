/** Presentation helpers shared across the dashboard. */

import type { FilterSpecification, FilterState, FilterValue } from "@/types";

const UNITS: [number, string][] = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

/** `1234567` -> `1.2M`. Used on axes where space is tight. */
export function compactNumber(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const magnitude = Math.abs(value);
  for (const [threshold, suffix] of UNITS) {
    if (magnitude >= threshold) {
      const scaled = (magnitude / threshold).toFixed(decimals);
      return `${sign}${scaled.replace(/\.0+$/, "")}${suffix}`;
    }
  }
  if (magnitude >= 100 || Number.isInteger(magnitude)) {
    return `${sign}${magnitude.toLocaleString(undefined, {
      maximumFractionDigits: 0,
    })}`;
  }
  return `${sign}${magnitude.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
}

/** Full precision with separators, for tooltips and tables. */
export function fullNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function formatPercent(value: number | null, decimals = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/**
 * Re-format a KPI's raw value into a chosen display format. Used by the KPI
 * format override in the customizer, so a measure can be shown as currency,
 * percent, count, etc. without a server round-trip.
 */
export function formatKpiValue(
  value: number | null,
  format: string,
  unit?: string | null,
): string {
  if (value === null || !Number.isFinite(value)) return "—";
  switch (format) {
    case "currency":
      return `${unit || "$"}${compactNumber(value)}`;
    case "percent":
      return `${value.toFixed(1)}%`;
    case "count":
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    case "decimal":
      return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    default:
      return compactNumber(value);
  }
}

export function formatChange(value: number | null, decimals = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

/** `total_revenue_usd` -> `Total Revenue USD`. Mirrors the backend helper. */
export function humanize(name: string): string {
  const cleaned = name.replace(/[_-]+/g, " ").trim();
  if (!cleaned) return name;
  const acronyms = new Set([
    "id",
    "usd",
    "eur",
    "gbp",
    "roi",
    "kpi",
    "ctr",
    "cpc",
    "aov",
    "roas",
  ]);
  return cleaned
    .split(/\s+/)
    .map((word) => {
      if (acronyms.has(word.toLowerCase())) return word.toUpperCase();
      if (word === word.toUpperCase() && word.length <= 4) return word;
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
}

export function formatCellValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return fullNumber(value);
  const text = String(value);
  // ISO timestamps read better as plain dates in a table.
  const isoMatch = text.match(/^(\d{4}-\d{2}-\d{2})T[\d:.]+/);
  if (isoMatch) return isoMatch[1];
  return text;
}

export function formatDateInput(value: string | number | null): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return text.slice(0, 10);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * Convert UI filter state into the wire format the backend validates.
 * Empty selections are dropped rather than sent as no-op clauses.
 */
export function buildFilterPayload(
  filters: FilterSpecification[],
  state: FilterState,
): FilterValue[] {
  const payload: FilterValue[] = [];

  for (const filter of filters) {
    const value = state[filter.id];
    if (value === null || value === undefined) continue;

    if (filter.kind === "date_range") {
      const [from, to] = value as [string, string];
      if (!from && !to) continue;
      payload.push({
        column: filter.column,
        operator: "between",
        value: [from || filter.min, to || filter.max],
      });
      continue;
    }

    const selected = value as string[];
    if (!Array.isArray(selected) || selected.length === 0) continue;
    payload.push({
      column: filter.column,
      operator: "in",
      value: selected,
    });
  }

  return payload;
}

export function countActiveFilters(
  filters: FilterSpecification[],
  state: FilterState,
): number {
  return buildFilterPayload(filters, state).length;
}
