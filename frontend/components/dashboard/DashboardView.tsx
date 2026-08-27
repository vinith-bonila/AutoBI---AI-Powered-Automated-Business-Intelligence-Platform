"use client";

/**
 * The assembled, customizable dashboard.
 *
 * Renders entirely from the central `DashboardConfig` (theme, layout, time
 * grain, KPI order, chart list). Every action — filter, customise, switch a
 * chart, add one, reorder, change the time grain, ask a question, export —
 * runs live with no page reload. Insights sit at the bottom of the main view;
 * data quality is a separate tab.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { DashboardResponse, FieldsResponse, FilterState, KPI } from "@/types";
import { buildFilterPayload, countActiveFilters, humanize } from "@/lib/format";
import { useDashboardConfig } from "@/lib/useDashboardConfig";
import { LAYOUT_COLUMNS, orderedKpis } from "@/lib/dashboardConfig";
import { PALETTE_BY_ID, PALETTES, applyTheme } from "@/lib/palettes";
import { Badge, Button, SectionHeading, cn } from "@/components/ui";
import { KpiCard } from "./KpiCard";
import { FilterBar } from "./FilterBar";
import { TimeAggregation } from "./TimeAggregation";
import { ExportMenu } from "./ExportMenu";
import { CustomizePanel } from "./CustomizePanel";
import { AddVisualizationModal } from "./AddVisualizationModal";
import { ChartCard, type ChartActions } from "@/components/charts/ChartCard";
import { InsightList } from "@/components/insights/InsightList";
import { AskAiPanel } from "@/components/insights/AskAiPanel";
import { QualityPanel } from "@/components/quality/QualityPanel";

type Tab = "dashboard" | "quality";

const WIDTH_SPAN: Record<string, Record<string, string>> = {
  // Maps a chart's declared width to a column span for each layout's grid.
  "two-column": { full: "lg:col-span-2", half: "lg:col-span-1", third: "lg:col-span-1" },
  "three-column": { full: "lg:col-span-3", half: "lg:col-span-1", third: "lg:col-span-1" },
  compact: { full: "lg:col-span-3", half: "lg:col-span-1", third: "lg:col-span-1" },
  wide: { full: "lg:col-span-1", half: "lg:col-span-1", third: "lg:col-span-1" },
  executive: { full: "lg:col-span-2", half: "lg:col-span-1", third: "lg:col-span-1" },
};

export function DashboardView({ data }: { data: DashboardResponse }) {
  const { specification: spec, profile, quality, analysis } = data;
  const cfg = useDashboardConfig(data);
  const { config } = cfg;

  const [tab, setTab] = useState<Tab>("dashboard");
  const [filterState, setFilterState] = useState<FilterState>({});
  const [kpis, setKpis] = useState<KPI[]>(spec.kpis);
  const [rowCount, setRowCount] = useState<number>(profile.n_rows);
  const [kpiLoading, setKpiLoading] = useState(false);
  const [fields, setFields] = useState<FieldsResponse | null>(null);

  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const themeRef = useRef<HTMLDivElement>(null);
  const captureRef = useRef<HTMLDivElement>(null);
  const dragIndex = useRef<number | null>(null);

  const hasDate = Boolean(profile.primary_date_column);

  // Apply the theme + palette to the dashboard container as CSS variables.
  useEffect(() => {
    if (!themeRef.current) return;
    const palette = PALETTE_BY_ID.get(config.theme.paletteId) ?? PALETTES[0];
    applyTheme(themeRef.current, {
      mode: config.theme.mode,
      palette,
      custom: config.theme.custom,
    });
  }, [config.theme]);

  // Load field metadata once, for the customization menus.
  useEffect(() => {
    api.fields(data.dataset_id).then(setFields).catch(() => setFields(null));
  }, [data.dataset_id]);

  const filterPayload = useMemo(
    () => buildFilterPayload(spec.filters, filterState),
    [spec.filters, filterState],
  );
  const activeCount = countActiveFilters(spec.filters, filterState);
  const payloadKey = JSON.stringify(filterPayload);

  // Recompute KPIs on filter change.
  useEffect(() => {
    if (filterPayload.length === 0) {
      setKpis(spec.kpis);
      setRowCount(profile.n_rows);
      return;
    }
    let cancelled = false;
    setKpiLoading(true);
    api
      .kpis(data.dataset_id, filterPayload)
      .then((response) => {
        if (cancelled) return;
        setKpis(response.kpis);
        setRowCount(response.row_count);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setKpiLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadKey]);

  const visibleKpis = orderedKpis(config, kpis);
  const columns = LAYOUT_COLUMNS[config.layout];
  const widthMap = WIDTH_SPAN[config.layout] ?? WIDTH_SPAN["two-column"];

  const gridClass =
    columns === 1
      ? "grid-cols-1"
      : columns === 3
        ? "grid-cols-1 lg:grid-cols-3"
        : "grid-cols-1 lg:grid-cols-2";

  function chartActions(index: number): ChartActions {
    return {
      onReplace: (chart) => cfg.replaceChart(config.charts[index].id, chart),
      onUpdate: (patch) => cfg.updateChart(config.charts[index].id, patch),
      onDuplicate: () => cfg.duplicateChart(config.charts[index].id),
      onRemove: () => cfg.removeChart(config.charts[index].id),
      onMove: (direction) => cfg.moveChart(index, index + direction),
      canMoveUp: index > 0,
      canMoveDown: index < config.charts.length - 1,
    };
  }

  return (
    <div ref={themeRef} className="min-h-screen bg-[var(--color-plane)]">
      <div ref={captureRef} className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
                {spec.title}
              </h1>
              <Badge tone="accent">{humanize(spec.domain)}</Badge>
            </div>
            <p className="mt-1.5 text-sm text-[var(--color-ink-secondary)]">
              {spec.description}
            </p>
            <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">
              {activeCount > 0
                ? `${rowCount.toLocaleString()} of ${profile.n_rows.toLocaleString()} rows match the filters`
                : `${profile.n_rows.toLocaleString()} rows · ${profile.n_columns} columns`}
              {" · "}
              {data.ai_enabled ? "AI-assisted" : "Deterministic engine"}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2" data-html2canvas-ignore="true">
            <Button variant="secondary" onClick={() => setCustomizeOpen(true)}>
              <SlidersIcon /> Customize
            </Button>
            <Button variant="secondary" onClick={() => setAskOpen(true)}>
              <SparkIcon /> Ask AI
            </Button>
            <ExportMenu
              datasetId={data.dataset_id}
              config={config}
              captureRef={captureRef}
              title={spec.title}
            />
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-5 flex gap-1 border-b border-[var(--color-hairline)]" data-html2canvas-ignore="true">
          <TabButton active={tab === "dashboard"} onClick={() => setTab("dashboard")}>
            Dashboard
          </TabButton>
          <TabButton active={tab === "quality"} onClick={() => setTab("quality")}>
            Data Quality
            <span className="ml-1.5 rounded-full bg-[var(--color-plane)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-ink-secondary)]">
              {quality.quality_score.toFixed(0)}
            </span>
          </TabButton>
        </div>

        {tab === "dashboard" ? (
          <div className="mt-5 space-y-6">
            {/* Filter bar + time aggregation */}
            {spec.filters.length || hasDate ? (
              <div className="flex flex-wrap items-center gap-2">
                {hasDate ? (
                  <TimeAggregation
                    value={config.timeGrain}
                    onChange={(grain) => cfg.setTimeGrain(grain)}
                  />
                ) : null}
                <FilterBar
                  filters={spec.filters}
                  state={filterState}
                  onChange={setFilterState}
                  activeCount={activeCount}
                />
              </div>
            ) : null}

            {/* KPIs */}
            {visibleKpis.length ? (
              <section className={cn("grid gap-4", kpiGridClass(visibleKpis.length))}>
                {visibleKpis.map((kpi) => (
                  <KpiCard
                    key={kpi.id}
                    kpi={kpi}
                    loading={kpiLoading}
                    formatOverride={config.kpiConfig[kpi.id]?.formatOverride}
                  />
                ))}
              </section>
            ) : null}

            {/* Charts */}
            {config.charts.length ? (
              <section className={cn("grid gap-4", gridClass)}>
                {config.charts.map((chart, index) => (
                  <div
                    key={chart.id}
                    className={cn(
                      "col-span-1 min-w-0",
                      widthMap[chart.width] ?? "lg:col-span-1",
                    )}
                    draggable
                    onDragStart={() => {
                      dragIndex.current = index;
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      if (dragIndex.current !== null && dragIndex.current !== index) {
                        cfg.moveChart(dragIndex.current, index);
                      }
                      dragIndex.current = null;
                    }}
                  >
                    <ChartCard
                      datasetId={data.dataset_id}
                      spec={chart}
                      filters={filterPayload}
                      timeGrain={config.timeGrain}
                      fields={fields?.fields ?? []}
                      editable
                      actions={chartActions(index)}
                    />
                  </div>
                ))}
              </section>
            ) : (
              <p className="py-8 text-center text-sm text-[var(--color-ink-muted)]">
                No charts yet. Use “Add visualization” to create one.
              </p>
            )}

            <div data-html2canvas-ignore="true">
              <Button variant="secondary" onClick={() => setAddOpen(true)}>
                <PlusIcon /> Add visualization
              </Button>
            </div>

            {/* Insights */}
            {spec.insights.length ? (
              <section className="pt-2">
                <SectionHeading
                  title="AI Insights"
                  description="What is happening and why — each grounded in a computed metric."
                />
                <InsightList
                  insights={spec.insights}
                  aiProvider={data.ai_enabled ? spec.ai_provider : null}
                />
              </section>
            ) : null}
          </div>
        ) : (
          <div className="mt-5">
            <QualityPanel datasetId={data.dataset_id} quality={quality} profile={profile} />
          </div>
        )}
      </div>

      {/* Panels */}
      <CustomizePanel
        open={customizeOpen}
        onClose={() => setCustomizeOpen(false)}
        api={cfg}
        kpis={kpis}
      />
      <AskAiPanel
        open={askOpen}
        onClose={() => setAskOpen(false)}
        datasetId={data.dataset_id}
        filters={filterPayload}
        aiEnabled={data.ai_enabled}
      />
      {fields ? (
        <AddVisualizationModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          datasetId={data.dataset_id}
          fields={fields.fields}
          onAdd={(chart) => cfg.addChart(chart)}
        />
      ) : null}
    </div>
  );
}

function kpiGridClass(count: number): string {
  // Keep KPI tiles a comfortable size regardless of count.
  if (count <= 3) return "grid-cols-1 sm:grid-cols-3";
  if (count === 4) return "grid-cols-2 lg:grid-cols-4";
  if (count === 5) return "grid-cols-2 lg:grid-cols-5";
  return "grid-cols-2 md:grid-cols-3 lg:grid-cols-6";
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative flex items-center px-4 py-2.5 text-sm font-medium transition-colors",
        active
          ? "text-[var(--color-ink)]"
          : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink-secondary)]",
      )}
    >
      {children}
      {active ? (
        <span
          className="absolute inset-x-0 -bottom-px h-0.5 rounded-full"
          style={{ backgroundColor: "var(--color-accent)" }}
        />
      ) : null}
    </button>
  );
}

function SlidersIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
      <path d="M4 21v-7m0-4V3m8 18v-9m0-4V3m8 18v-5m0-4V3M1 14h6m2-6h6m2 8h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
function SparkIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
      <path d="M12 3v4m0 10v4M3 12h4m10 0h4M6.3 6.3l2.8 2.8m5.8 5.8 2.8 2.8m0-11.4-2.8 2.8m-5.8 5.8-2.8 2.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
function PlusIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
