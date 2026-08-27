"use client";

/**
 * Shared chart chrome: tooltip, legend and axis defaults.
 *
 * Keeping these in one place is what makes the dashboard read as one system —
 * every chart gets the same recessive grid, the same ink tokens for text, and
 * the same tooltip, rather than each chart inventing its own.
 */

import type { ReactNode } from "react";
import { CHART_INK } from "@/lib/theme";
import { compactNumber, fullNumber } from "@/lib/format";

export const AXIS_PROPS = {
  stroke: CHART_INK.axis,
  tick: { fill: CHART_INK.muted, fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: CHART_INK.axis },
} as const;

/** Solid hairline grid — dashed rules read as noise. */
export const GRID_PROPS = {
  stroke: CHART_INK.grid,
  strokeDasharray: "0",
  vertical: false,
} as const;

export const CHART_MARGIN = { top: 8, right: 16, bottom: 4, left: 4 };

export interface TooltipRow {
  label: string;
  value: string;
  color?: string;
}

export function TooltipShell({
  title,
  rows,
  footer,
}: {
  title: string;
  rows: TooltipRow[];
  footer?: ReactNode;
}) {
  return (
    <div className="pointer-events-none min-w-[9rem] rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 shadow-lg">
      <p className="mb-1.5 text-xs font-semibold text-[var(--color-ink)]">
        {title}
      </p>
      <div className="space-y-1">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between gap-4 text-xs"
          >
            <span className="flex items-center gap-1.5 text-[var(--color-ink-secondary)]">
              {row.color ? (
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{ backgroundColor: row.color }}
                />
              ) : null}
              {row.label}
            </span>
            <span className="tabular font-medium text-[var(--color-ink)]">
              {row.value}
            </span>
          </div>
        ))}
      </div>
      {footer ? (
        <p className="mt-1.5 border-t border-[var(--color-hairline)] pt-1.5 text-[11px] text-[var(--color-ink-muted)]">
          {footer}
        </p>
      ) : null}
    </div>
  );
}

interface RechartsTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: {
    name?: string;
    value?: number | string;
    color?: string;
    dataKey?: string;
    payload?: Record<string, unknown>;
  }[];
}

/** Default tooltip for line/area/bar charts. */
export function SeriesTooltip({
  active,
  label,
  payload,
  valueFormatter = fullNumber,
  showShare = false,
}: RechartsTooltipProps & {
  valueFormatter?: (value: number) => string;
  showShare?: boolean;
}) {
  if (!active || !payload?.length) return null;

  const rows: TooltipRow[] = payload
    .filter((entry) => entry.value !== null && entry.value !== undefined)
    .map((entry) => ({
      label: entry.name ?? String(entry.dataKey ?? ""),
      value:
        typeof entry.value === "number"
          ? valueFormatter(entry.value)
          : String(entry.value),
      color: entry.color,
    }));

  if (!rows.length) return null;

  const first = payload[0]?.payload as Record<string, unknown> | undefined;
  const share = showShare && typeof first?.share === "number" ? first.share : null;
  const rowCount = typeof first?.rows === "number" ? first.rows : null;

  const footerParts: string[] = [];
  if (share !== null) footerParts.push(`${share.toFixed(1)}% of total`);
  if (rowCount !== null) footerParts.push(`${rowCount.toLocaleString()} rows`);

  return (
    <TooltipShell
      title={String(label ?? "")}
      rows={rows}
      footer={footerParts.length ? footerParts.join(" · ") : undefined}
    />
  );
}

/**
 * Legend for two or more series.
 *
 * A single-series chart gets no legend box — its title already names the
 * measure, and a one-item legend is pure clutter.
 */
export function ChartLegend({
  items,
}: {
  items: { label: string; color: string }[];
}) {
  if (items.length < 2) return null;
  return (
    <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li
          key={item.label}
          className="flex items-center gap-1.5 text-xs text-[var(--color-ink-secondary)]"
        >
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
            style={{ backgroundColor: item.color }}
          />
          <span className="max-w-[12rem] truncate" title={item.label}>
            {item.label}
          </span>
        </li>
      ))}
    </ul>
  );
}

export const axisNumberFormatter = (value: number) => compactNumber(value);

/** Long category names need shortening on a horizontal axis. */
export function truncateLabel(value: string, max = 14): string {
  const text = String(value);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
