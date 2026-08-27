/**
 * The central dashboard configuration — the single source of truth the
 * renderer draws from and every customization modifies.
 *
 * It is seeded from the AI/deterministic `DashboardSpecification` the backend
 * produced, then the user can retheme, relayout, reorder, switch chart types,
 * add visualizations and change time aggregation — all by editing this object.
 * It is persisted per-dataset in localStorage and is exactly what "Export
 * dashboard configuration" serialises, so a dashboard can be saved, reloaded
 * and (later) shared.
 */

import type {
  ChartSpecification,
  DashboardResponse,
  DashboardSpecification,
  KPI,
} from "@/types";

export type LayoutMode =
  | "compact"
  | "two-column"
  | "three-column"
  | "wide"
  | "executive";

export type KpiFormatOverride =
  | "number"
  | "currency"
  | "percent"
  | "count"
  | "decimal";

export interface KpiConfig {
  id: string;
  /** null when the KPI is a stored one; set for user-added measures. */
  formatOverride: KpiFormatOverride | null;
  hidden: boolean;
}

export interface ThemeConfig {
  mode: "light" | "dark" | "professional";
  paletteId: string;
  /** Custom token overrides (CSS var name → hex), for the "Custom" theme. */
  custom: Record<string, string>;
}

export interface DashboardConfig {
  version: 1;
  datasetId: string;
  theme: ThemeConfig;
  layout: LayoutMode;
  /** null → each chart keeps its own grain; a value overrides all time charts. */
  timeGrain: string | null;
  /** Ordered KPI ids (drives display order); unknown ids are ignored. */
  kpiOrder: string[];
  kpiConfig: Record<string, KpiConfig>;
  /** The full working set of charts, in display order. */
  charts: ChartSpecification[];
  /** Ids of charts the user removed (kept so a reset can restore them). */
  removedChartIds: string[];
}

const STORAGE_PREFIX = "autobi-dashboard-config:";

export const LAYOUT_COLUMNS: Record<LayoutMode, number> = {
  compact: 3,
  "two-column": 2,
  "three-column": 3,
  wide: 1,
  executive: 2,
};

/** Build a fresh config from the backend specification. */
export function configFromSpec(data: DashboardResponse): DashboardConfig {
  const spec = data.specification;
  return {
    version: 1,
    datasetId: data.dataset_id,
    theme: { mode: "professional", paletteId: "corporate", custom: {} },
    layout: "two-column",
    timeGrain: defaultGrain(spec),
    kpiOrder: spec.kpis.map((k) => k.id),
    kpiConfig: Object.fromEntries(
      spec.kpis.map((k) => [k.id, { id: k.id, formatOverride: null, hidden: false }]),
    ),
    charts: spec.charts.map((c) => ({ ...c })),
    removedChartIds: [],
  };
}

function defaultGrain(spec: DashboardSpecification): string | null {
  const timeChart = spec.charts.find(
    (c) => (c.type === "line" || c.type === "area") && c.time_grain,
  );
  return timeChart?.time_grain ?? null;
}

/**
 * Merge a stored config with the current spec.
 *
 * The spec is authoritative for *what exists* (a re-run may add KPIs); the
 * stored config is authoritative for *user choices* (theme, order, removals).
 * New KPIs/charts from the spec are appended; the user's customisation is kept.
 */
export function reconcile(
  stored: DashboardConfig,
  data: DashboardResponse,
): DashboardConfig {
  const spec = data.specification;
  const specKpiIds = new Set(spec.kpis.map((k) => k.id));
  const knownKpi = new Set(stored.kpiOrder);

  const kpiOrder = [
    ...stored.kpiOrder.filter((id) => specKpiIds.has(id)),
    ...spec.kpis.filter((k) => !knownKpi.has(k.id)).map((k) => k.id),
  ];
  const kpiConfig = { ...stored.kpiConfig };
  for (const kpi of spec.kpis) {
    if (!kpiConfig[kpi.id]) {
      kpiConfig[kpi.id] = { id: kpi.id, formatOverride: null, hidden: false };
    }
  }

  // Keep the user's chart set (including added/removed/switched charts) but
  // make sure any brand-new spec chart the user hasn't seen is available.
  const knownChartIds = new Set([
    ...stored.charts.map((c) => c.id),
    ...stored.removedChartIds,
  ]);
  const newCharts = spec.charts.filter((c) => !knownChartIds.has(c.id));

  return {
    ...stored,
    datasetId: data.dataset_id,
    kpiOrder,
    kpiConfig,
    charts: [...stored.charts, ...newCharts.map((c) => ({ ...c }))],
  };
}

export function load(datasetId: string): DashboardConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + datasetId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DashboardConfig;
    if (parsed.version !== 1 || parsed.datasetId !== datasetId) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function save(config: DashboardConfig): void {
  try {
    localStorage.setItem(
      STORAGE_PREFIX + config.datasetId,
      JSON.stringify(config),
    );
  } catch {
    // Storage may be unavailable (private mode / quota); customisation still
    // works for the session, it just won't persist across reloads.
  }
}

export function clear(datasetId: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + datasetId);
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// pure update helpers — each returns a new config
// ---------------------------------------------------------------------------

export function orderedKpis(config: DashboardConfig, all: KPI[]): KPI[] {
  const byId = new Map(all.map((k) => [k.id, k]));
  const seen = new Set<string>();
  const result: KPI[] = [];
  for (const id of config.kpiOrder) {
    const kpi = byId.get(id);
    if (kpi && !config.kpiConfig[id]?.hidden) {
      result.push(kpi);
      seen.add(id);
    }
  }
  return result;
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
    return items;
  }
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export function applyTimeGrain(
  charts: ChartSpecification[],
  grain: string | null,
): ChartSpecification[] {
  if (!grain) return charts;
  return charts.map((chart) =>
    chart.type === "line" || chart.type === "area"
      ? { ...chart, time_grain: grain }
      : chart,
  );
}
