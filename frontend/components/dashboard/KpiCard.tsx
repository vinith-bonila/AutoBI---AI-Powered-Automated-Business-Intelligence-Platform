"use client";

/**
 * A single KPI tile.
 *
 * The big number is the hero. It uses proportional figures (never tabular),
 * stays in the system sans, and the period-over-period delta below it carries
 * an icon plus a sign so the good/bad direction never rests on colour alone —
 * a rising cost and rising revenue are both "up" but only one is favourable.
 */

import type { KPI } from "@/types";
import { formatChange, formatKpiValue } from "@/lib/format";
import { Card, InfoTip } from "@/components/ui";

const SOURCE_LABEL: Record<string, string> = {
  deterministic: "Computed by rule",
  ai: "Proposed by AI, computed here",
  hybrid: "Named by AI, computed here",
};

export function KpiCard({
  kpi,
  loading,
  formatOverride,
}: {
  kpi: KPI;
  loading?: boolean;
  formatOverride?: string | null;
}) {
  const displayValue = formatOverride
    ? formatKpiValue(kpi.value, formatOverride, kpi.unit)
    : kpi.formatted_value;
  const comparison = kpi.comparison;
  const favorable = comparison?.is_favorable;
  const direction = comparison?.direction ?? "flat";

  const deltaTone =
    favorable === true
      ? "text-[var(--color-success-text)]"
      : favorable === false
        ? "text-[var(--color-critical)]"
        : "text-[var(--color-ink-muted)]";

  return (
    <Card className="flex flex-col justify-between p-5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-ink-muted)]">
          {kpi.name}
        </p>
        <InfoTip label={`${kpi.calculation}. ${kpi.why_it_matters}`}>
          <span className="block space-y-1">
            <span className="block font-mono text-[11px] text-[var(--color-ink)]">
              {kpi.calculation}
            </span>
            <span className="block">{kpi.why_it_matters}</span>
            <span className="block text-[10px] text-[var(--color-ink-muted)]">
              {SOURCE_LABEL[kpi.source] ?? "Computed here"}
            </span>
          </span>
        </InfoTip>
      </div>

      <p
        className={`mt-3 text-3xl font-semibold tracking-tight text-[var(--color-ink)] ${
          loading ? "opacity-50" : ""
        }`}
      >
        {displayValue}
      </p>

      {comparison && comparison.change_pct !== null ? (
        <div className="mt-2 flex items-center gap-1.5 text-xs">
          <span
            aria-hidden="true"
            className={deltaTone}
          >
            {direction === "up" ? "▲" : direction === "down" ? "▼" : "→"}
          </span>
          <span className={`font-medium ${deltaTone}`}>
            {formatChange(comparison.change_pct)}
          </span>
          <span className="text-[var(--color-ink-muted)]">
            {comparison.period_label}
          </span>
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
          {kpi.why_it_matters.length > 60
            ? `${kpi.why_it_matters.slice(0, 60)}…`
            : kpi.why_it_matters}
        </p>
      )}
    </Card>
  );
}

export function KpiCardSkeleton() {
  return (
    <Card className="flex flex-col justify-between p-5">
      <div className="skeleton h-3 w-24 rounded" />
      <div className="skeleton mt-4 h-8 w-28 rounded" />
      <div className="skeleton mt-3 h-3 w-32 rounded" />
    </Card>
  );
}
