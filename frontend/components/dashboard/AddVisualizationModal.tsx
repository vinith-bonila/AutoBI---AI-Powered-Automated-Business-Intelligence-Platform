"use client";

/**
 * Add Visualization — build a chart without writing code.
 *
 * The user picks a type, axes and aggregation; the modal validates the
 * combination against the dataset (offering only chart types that fit the
 * chosen columns) and shows a live preview. "Add to Dashboard" appends the
 * validated spec to the central config.
 */

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type {
  Aggregation,
  ChartDataResponse,
  ChartSpecification,
  ChartType,
  FieldInfo,
} from "@/types";
import { SeriesPalette } from "@/lib/theme";
import { humanize } from "@/lib/format";
import { Button, cn } from "@/components/ui";
import { ChartRenderer } from "@/components/charts/ChartRenderer";

const ALL_TYPES: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Bar" },
  { value: "horizontal_bar", label: "H. Bar" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  { value: "pie", label: "Pie" },
  { value: "donut", label: "Donut" },
  { value: "scatter", label: "Scatter" },
  { value: "histogram", label: "Histogram" },
  { value: "table", label: "Table" },
];

const AGGS: Aggregation[] = ["sum", "avg", "count", "count_distinct", "median", "min", "max"];

interface DraftChart {
  type: ChartType;
  x?: string;
  y?: string;
  aggregation: Aggregation;
  title: string;
}

export function AddVisualizationModal({
  open,
  onClose,
  datasetId,
  fields,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  datasetId: string;
  fields: FieldInfo[];
  onAdd: (chart: ChartSpecification) => void;
}) {
  const dimensions = useMemo(
    () => fields.filter((f) => f.is_dimension || f.is_temporal),
    [fields],
  );
  const measures = useMemo(() => fields.filter((f) => f.is_measure), [fields]);

  const [draft, setDraft] = useState<DraftChart>(() => initialDraft(dimensions, measures));
  const [allowedTypes, setAllowedTypes] = useState<ChartType[]>([]);
  const [preview, setPreview] = useState<ChartDataResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const paletteRef = useMemo(() => new SeriesPalette(), []);

  // Reset when reopened.
  useEffect(() => {
    if (open) {
      setDraft(initialDraft(dimensions, measures));
      setPreview(null);
      setValidationError(null);
    }
  }, [open, dimensions, measures]);

  const specPayload = useMemo(
    () => ({
      type: draft.type,
      x: draft.x,
      y: draft.y,
      aggregation: draft.aggregation,
      title: draft.title,
    }),
    [draft],
  );

  // Validate + preview whenever the draft changes (debounced).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const validation = await api.validateChart(datasetId, specPayload);
        if (cancelled) return;
        setAllowedTypes(validation.allowed_types);
        if (!validation.ok) {
          setValidationError(validation.reason ?? "This combination is not valid.");
          setPreview(null);
          setLoading(false);
          return;
        }
        setValidationError(null);
        const data = await api.executeChart(datasetId, specPayload, []);
        if (cancelled) return;
        setPreview(data);
      } catch {
        if (!cancelled) {
          setValidationError("Could not build a preview for this chart.");
          setPreview(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [open, datasetId, specPayload]);

  if (!open) return null;

  const needsX = draft.type !== "table";
  const needsY =
    draft.type !== "histogram" && draft.type !== "table" && draft.aggregation !== "count";
  const xOptions = draft.type === "scatter" || draft.type === "histogram" ? measures : dimensions;
  const yOptions = measures;

  function patch(next: Partial<DraftChart>) {
    setDraft((prev) => {
      const merged = { ...prev, ...next };
      // Keep the title in sync unless the user typed their own.
      if (!prev.titleEdited) {
        merged.title = autoTitle(merged);
      }
      return merged;
    });
  }

  function commit() {
    if (validationError || !preview) return;
    const spec: ChartSpecification = {
      id: `user_${Date.now().toString(36)}`,
      type: draft.type,
      title: draft.title || autoTitle(draft),
      description: null,
      x: draft.x ?? null,
      y: draft.y ?? null,
      series: null,
      aggregation: draft.type === "histogram" ? "count" : draft.aggregation,
      time_grain: null,
      sort: "value_desc",
      limit: null,
      bins: draft.type === "histogram" ? 20 : null,
      columns: draft.type === "table" ? [draft.x, draft.y].filter(Boolean) as string[] : [],
      section: "secondary",
      width: "half",
      rationale: "Added by you.",
      source: "deterministic",
    };
    onAdd(spec);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden="true" />
      <div className="relative z-10 flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-2xl">
        <header className="flex items-center justify-between border-b border-[var(--color-hairline)] px-5 py-4">
          <h2 className="text-base font-semibold text-[var(--color-ink)]">
            Add visualization
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--color-ink-muted)] hover:bg-[var(--color-plane)]"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="grid flex-1 gap-5 overflow-y-auto p-5 md:grid-cols-2">
          {/* Controls */}
          <div className="space-y-4">
            <Field label="Chart type">
              <div className="grid grid-cols-3 gap-1.5">
                {ALL_TYPES.map((type) => {
                  const enabled =
                    allowedTypes.length === 0 || allowedTypes.includes(type.value);
                  return (
                    <button
                      key={type.value}
                      type="button"
                      disabled={!enabled}
                      onClick={() => patch({ type: type.value })}
                      className={cn(
                        "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                        draft.type === type.value
                          ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                          : enabled
                            ? "border-[var(--color-hairline)] text-[var(--color-ink-secondary)] hover:bg-[var(--color-plane)]"
                            : "border-transparent text-[var(--color-ink-muted)] opacity-40",
                      )}
                    >
                      {type.label}
                    </button>
                  );
                })}
              </div>
            </Field>

            {needsX ? (
              <Field label={draft.type === "histogram" ? "Column" : "X-axis"}>
                <Select
                  value={draft.x ?? ""}
                  onChange={(value) => patch({ x: value || undefined })}
                  options={xOptions}
                />
              </Field>
            ) : null}

            {needsY ? (
              <Field label="Y-axis (measure)">
                <Select
                  value={draft.y ?? ""}
                  onChange={(value) => patch({ y: value || undefined })}
                  options={yOptions}
                />
              </Field>
            ) : null}

            {draft.type !== "scatter" && draft.type !== "histogram" && draft.type !== "table" ? (
              <Field label="Aggregation">
                <select
                  value={draft.aggregation}
                  onChange={(event) => patch({ aggregation: event.target.value as Aggregation })}
                  className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-ink)]"
                >
                  {AGGS.map((agg) => (
                    <option key={agg} value={agg}>
                      {humanize(agg)}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <Field label="Title">
              <input
                type="text"
                value={draft.title}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, title: event.target.value, titleEdited: true }))
                }
                className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-ink)]"
              />
            </Field>
          </div>

          {/* Preview */}
          <div className="rounded-xl border border-[var(--color-hairline)] bg-[var(--color-plane)] p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
              Preview
            </p>
            {validationError ? (
              <div className="flex h-64 items-center justify-center px-4 text-center text-sm text-[var(--color-ink-secondary)]">
                {validationError}
              </div>
            ) : loading && !preview ? (
              <div className="flex h-64 items-center justify-center text-sm text-[var(--color-ink-muted)]">
                Building preview…
              </div>
            ) : preview ? (
              <div className={cn(loading && "opacity-60")}>
                <ChartRenderer
                  spec={{ ...specPayload, id: "preview", columns: [] } as unknown as ChartSpecification}
                  data={preview}
                  palette={paletteRef}
                />
              </div>
            ) : (
              <div className="flex h-64 items-center justify-center text-sm text-[var(--color-ink-muted)]">
                Choose columns to preview.
              </div>
            )}
          </div>
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-[var(--color-hairline)] px-5 py-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={commit} disabled={!!validationError || !preview}>
            Add to Dashboard
          </Button>
        </footer>
      </div>
    </div>
  );
}

// A private extension of the draft that tracks whether the user edited title.
interface DraftChart {
  titleEdited?: boolean;
}

function initialDraft(dimensions: FieldInfo[], measures: FieldInfo[]): DraftChart {
  // Prefer a readable categorical dimension for the default bar chart — a date
  // column with hundreds of values makes an invalid bar chart and an empty
  // preview.
  const categorical = dimensions.filter(
    (d) => !d.is_temporal && d.unique >= 2 && d.unique <= 30,
  );
  const x = (categorical[0] ?? dimensions.find((d) => !d.is_temporal) ?? dimensions[0])?.name;
  const y = measures[0]?.name;
  const draft: DraftChart = {
    type: "bar",
    x,
    y,
    aggregation: (measures[0]?.suggested_aggregation as Aggregation) ?? "sum",
    title: "",
  };
  draft.title = autoTitle(draft);
  return draft;
}

function autoTitle(draft: DraftChart): string {
  const AGG_WORDS: Record<string, string> = {
    sum: "Total",
    avg: "Average",
    count: "Count of",
    median: "Median",
    min: "Min",
    max: "Max",
  };
  const agg = AGG_WORDS[draft.aggregation] ?? "";
  if (draft.type === "histogram" && draft.x) return `Distribution of ${humanize(draft.x)}`;
  if (draft.type === "scatter" && draft.x && draft.y) return `${humanize(draft.x)} vs ${humanize(draft.y)}`;
  if ((draft.type === "line" || draft.type === "area") && draft.y) return `${humanize(draft.y)} Over Time`;
  if (draft.x && draft.y) return `${agg} ${humanize(draft.y)} by ${humanize(draft.x)}`.trim();
  if (draft.x) return `Records by ${humanize(draft.x)}`;
  return "New Chart";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-[var(--color-ink-secondary)]">
        {label}
      </label>
      {children}
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: FieldInfo[];
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-ink)]"
    >
      <option value="">Select…</option>
      {options.map((field) => (
        <option key={field.name} value={field.name}>
          {field.label}
        </option>
      ))}
    </select>
  );
}
