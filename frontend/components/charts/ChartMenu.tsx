"use client";

/**
 * The per-chart edit menu (⋮).
 *
 * Only chart types valid for the chart's current columns are offered — the
 * backend's `validate` endpoint decides, so the menu can never present a
 * combination that would then fail. Axis and aggregation changes are applied
 * optimistically; the card re-fetches through the validated execute path.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type {
  Aggregation,
  ChartSpecification,
  ChartType,
  FieldInfo,
} from "@/types";
import { humanize } from "@/lib/format";
import { cn } from "@/components/ui";
import type { ChartActions } from "./ChartCard";

const TYPE_LABELS: Record<string, string> = {
  bar: "Bar",
  horizontal_bar: "Horizontal bar",
  line: "Line",
  area: "Area",
  pie: "Pie",
  donut: "Donut",
  scatter: "Scatter",
  histogram: "Histogram",
  table: "Table",
};

const AGGREGATIONS: { value: Aggregation; label: string }[] = [
  { value: "sum", label: "Sum" },
  { value: "avg", label: "Average" },
  { value: "count", label: "Count" },
  { value: "count_distinct", label: "Count distinct" },
  { value: "median", label: "Median" },
  { value: "min", label: "Minimum" },
  { value: "max", label: "Maximum" },
];

type Submenu = null | "type" | "x" | "y" | "agg";

export function ChartMenu({
  datasetId,
  spec,
  fields,
  actions,
}: {
  datasetId: string;
  spec: ChartSpecification;
  fields: FieldInfo[];
  actions: ChartActions;
}) {
  const [open, setOpen] = useState(false);
  const [submenu, setSubmenu] = useState<Submenu>(null);
  const [allowedTypes, setAllowedTypes] = useState<ChartType[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
        setSubmenu(null);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Load valid chart types when the type submenu opens.
  useEffect(() => {
    if (submenu !== "type") return;
    let cancelled = false;
    api
      .validateChart(datasetId, {
        type: spec.type,
        x: spec.x ?? undefined,
        y: spec.y ?? undefined,
      })
      .then((r) => !cancelled && setAllowedTypes(r.allowed_types))
      .catch(() => !cancelled && setAllowedTypes([spec.type]));
    return () => {
      cancelled = true;
    };
  }, [submenu, datasetId, spec.type, spec.x, spec.y]);

  const dimensions = fields.filter((f) => f.is_dimension || f.is_temporal);
  const measures = fields.filter((f) => f.is_measure);

  function close() {
    setOpen(false);
    setSubmenu(null);
  }

  function replaceType(type: ChartType) {
    // Switching type may change which axes/aggregation make sense; keep x/y and
    // let the backend re-derive a valid spec.
    const patch: Partial<ChartSpecification> = { type };
    if (type === "histogram") patch.aggregation = "count";
    if (type === "scatter") patch.aggregation = "none";
    if (type === "table") {
      patch.columns = [spec.x, spec.y].filter(Boolean) as string[];
    }
    actions.onUpdate(patch);
    close();
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Chart options"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--color-ink-muted)] transition-colors hover:bg-[var(--color-plane)] hover:text-[var(--color-ink)]"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="5" r="1.6" />
          <circle cx="12" cy="12" r="1.6" />
          <circle cx="12" cy="19" r="1.6" />
        </svg>
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-40 mt-1 w-56 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1.5 text-sm shadow-lg">
          {submenu === null ? (
            <>
              <div className="mb-1 flex items-center gap-1 px-1">
                <ReorderButton
                  label="Move earlier"
                  disabled={!actions.canMoveUp}
                  onClick={() => {
                    actions.onMove(-1);
                    close();
                  }}
                  icon="up"
                />
                <ReorderButton
                  label="Move later"
                  disabled={!actions.canMoveDown}
                  onClick={() => {
                    actions.onMove(1);
                    close();
                  }}
                  icon="down"
                />
              </div>
              <MenuItem label="Change chart type" onClick={() => setSubmenu("type")} chevron />
              {spec.type !== "histogram" && spec.type !== "table" ? (
                <MenuItem label="Change X-axis" onClick={() => setSubmenu("x")} chevron />
              ) : null}
              {spec.type !== "table" ? (
                <MenuItem label="Change Y-axis" onClick={() => setSubmenu("y")} chevron />
              ) : null}
              {spec.type !== "scatter" && spec.type !== "histogram" && spec.type !== "table" ? (
                <MenuItem label="Change aggregation" onClick={() => setSubmenu("agg")} chevron />
              ) : null}
              <Divider />
              <MenuItem label="Duplicate" onClick={() => { actions.onDuplicate(); close(); }} />
              <MenuItem
                label="Remove"
                tone="danger"
                onClick={() => { actions.onRemove(); close(); }}
              />
            </>
          ) : null}

          {submenu === "type" ? (
            <SubmenuShell title="Chart type" onBack={() => setSubmenu(null)}>
              {(allowedTypes.length ? allowedTypes : [spec.type]).map((type) => (
                <MenuItem
                  key={type}
                  label={TYPE_LABELS[type] ?? type}
                  active={type === spec.type}
                  onClick={() => replaceType(type)}
                />
              ))}
            </SubmenuShell>
          ) : null}

          {submenu === "x" ? (
            <SubmenuShell title="X-axis" onBack={() => setSubmenu(null)}>
              {(spec.type === "scatter" ? measures : dimensions).map((field) => (
                <MenuItem
                  key={field.name}
                  label={field.label}
                  active={field.name === spec.x}
                  onClick={() => { actions.onUpdate({ x: field.name }); close(); }}
                />
              ))}
            </SubmenuShell>
          ) : null}

          {submenu === "y" ? (
            <SubmenuShell title="Y-axis" onBack={() => setSubmenu(null)}>
              {measures.map((field) => (
                <MenuItem
                  key={field.name}
                  label={field.label}
                  active={field.name === spec.y}
                  onClick={() => { actions.onUpdate({ y: field.name }); close(); }}
                />
              ))}
            </SubmenuShell>
          ) : null}

          {submenu === "agg" ? (
            <SubmenuShell title="Aggregation" onBack={() => setSubmenu(null)}>
              {AGGREGATIONS.map((agg) => (
                <MenuItem
                  key={agg.value}
                  label={agg.label}
                  active={agg.value === spec.aggregation}
                  onClick={() => { actions.onUpdate({ aggregation: agg.value }); close(); }}
                />
              ))}
            </SubmenuShell>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MenuItem({
  label,
  onClick,
  active,
  chevron,
  tone = "default",
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  chevron?: boolean;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--color-plane)]",
        tone === "danger"
          ? "text-[var(--color-critical)]"
          : "text-[var(--color-ink)]",
      )}
    >
      <span className="flex items-center gap-2">
        {active ? (
          <span className="text-[var(--color-accent)]">✓</span>
        ) : chevron ? null : (
          <span className="w-3" />
        )}
        {label}
      </span>
      {chevron ? <span className="text-[var(--color-ink-muted)]">›</span> : null}
    </button>
  );
}

function SubmenuShell({
  title,
  onBack,
  children,
}: {
  title: string;
  onBack: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="mb-1 flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
      >
        <span>‹</span> {title}
      </button>
      <div className="scroll-thin max-h-64 overflow-y-auto">{children}</div>
    </div>
  );
}

function Divider() {
  return <div className="my-1 h-px bg-[var(--color-hairline)]" />;
}

function ReorderButton({
  label,
  disabled,
  onClick,
  icon,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  icon: "up" | "down";
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-7 flex-1 items-center justify-center rounded-md border border-[var(--color-hairline)] text-[var(--color-ink-secondary)] transition-colors hover:bg-[var(--color-plane)] disabled:opacity-40"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
        <path
          d={icon === "up" ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"}
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
