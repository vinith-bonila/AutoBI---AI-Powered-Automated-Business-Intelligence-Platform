"use client";

/**
 * Stateful hook wrapping the central `DashboardConfig`.
 *
 * Every customization action funnels through the reducer, so the config stays
 * the single source of truth and is persisted on every change. The dashboard
 * renders from what this returns; nothing mutates the backend spec.
 */

import { useCallback, useEffect, useReducer } from "react";

import type { ChartSpecification, DashboardResponse } from "@/types";
import {
  type DashboardConfig,
  type KpiFormatOverride,
  type LayoutMode,
  type ThemeConfig,
  clear,
  configFromSpec,
  load,
  moveItem,
  reconcile,
  save,
} from "./dashboardConfig";

type Action =
  | { type: "replace"; config: DashboardConfig }
  | { type: "setTheme"; theme: Partial<ThemeConfig> }
  | { type: "setLayout"; layout: LayoutMode }
  | { type: "setTimeGrain"; grain: string | null }
  | { type: "moveKpi"; from: number; to: number }
  | { type: "toggleKpi"; id: string; hidden: boolean }
  | { type: "setKpiFormat"; id: string; format: KpiFormatOverride | null }
  | { type: "addKpi"; id: string }
  | { type: "moveChart"; from: number; to: number }
  | { type: "updateChart"; id: string; patch: Partial<ChartSpecification> }
  | { type: "replaceChart"; id: string; chart: ChartSpecification }
  | { type: "duplicateChart"; id: string }
  | { type: "removeChart"; id: string }
  | { type: "addChart"; chart: ChartSpecification };

function reducer(state: DashboardConfig, action: Action): DashboardConfig {
  switch (action.type) {
    case "replace":
      return action.config;

    case "setTheme":
      return { ...state, theme: { ...state.theme, ...action.theme } };

    case "setLayout":
      return { ...state, layout: action.layout };

    case "setTimeGrain":
      return { ...state, timeGrain: action.grain };

    case "moveKpi":
      return { ...state, kpiOrder: moveItem(state.kpiOrder, action.from, action.to) };

    case "toggleKpi":
      return {
        ...state,
        kpiConfig: {
          ...state.kpiConfig,
          [action.id]: {
            ...(state.kpiConfig[action.id] ?? {
              id: action.id,
              formatOverride: null,
              hidden: false,
            }),
            hidden: action.hidden,
          },
        },
      };

    case "setKpiFormat":
      return {
        ...state,
        kpiConfig: {
          ...state.kpiConfig,
          [action.id]: {
            ...(state.kpiConfig[action.id] ?? {
              id: action.id,
              formatOverride: null,
              hidden: false,
            }),
            formatOverride: action.format,
          },
        },
      };

    case "addKpi":
      if (state.kpiOrder.includes(action.id)) {
        // Un-hide an existing KPI rather than duplicating it.
        return reducer(state, { type: "toggleKpi", id: action.id, hidden: false });
      }
      return {
        ...state,
        kpiOrder: [...state.kpiOrder, action.id],
        kpiConfig: {
          ...state.kpiConfig,
          [action.id]: { id: action.id, formatOverride: null, hidden: false },
        },
      };

    case "moveChart":
      return { ...state, charts: moveItem(state.charts, action.from, action.to) };

    case "updateChart":
      return {
        ...state,
        charts: state.charts.map((c) =>
          c.id === action.id ? { ...c, ...action.patch } : c,
        ),
      };

    case "replaceChart":
      return {
        ...state,
        charts: state.charts.map((c) => (c.id === action.id ? action.chart : c)),
      };

    case "duplicateChart": {
      const index = state.charts.findIndex((c) => c.id === action.id);
      if (index < 0) return state;
      const source = state.charts[index];
      const copy: ChartSpecification = {
        ...source,
        id: `${source.id}_copy_${Date.now().toString(36)}`,
        title: `${source.title} (copy)`,
        section: "secondary",
      };
      const next = [...state.charts];
      next.splice(index + 1, 0, copy);
      return { ...state, charts: next };
    }

    case "removeChart":
      return {
        ...state,
        charts: state.charts.filter((c) => c.id !== action.id),
        removedChartIds: [...state.removedChartIds, action.id],
      };

    case "addChart":
      return { ...state, charts: [...state.charts, action.chart] };

    default:
      return state;
  }
}

export interface DashboardConfigApi {
  config: DashboardConfig;
  setTheme: (theme: Partial<ThemeConfig>) => void;
  setLayout: (layout: LayoutMode) => void;
  setTimeGrain: (grain: string | null) => void;
  moveKpi: (from: number, to: number) => void;
  toggleKpi: (id: string, hidden: boolean) => void;
  setKpiFormat: (id: string, format: KpiFormatOverride | null) => void;
  addKpi: (id: string) => void;
  moveChart: (from: number, to: number) => void;
  updateChart: (id: string, patch: Partial<ChartSpecification>) => void;
  replaceChart: (id: string, chart: ChartSpecification) => void;
  duplicateChart: (id: string) => void;
  removeChart: (id: string) => void;
  addChart: (chart: ChartSpecification) => void;
  reset: () => void;
  /** Replace the whole config (loading a saved view), pinned to this dataset. */
  loadConfig: (config: DashboardConfig) => void;
}

export function useDashboardConfig(data: DashboardResponse): DashboardConfigApi {
  const [config, dispatch] = useReducer(
    reducer,
    data,
    // Lazy init: restore a saved config (reconciled with the current spec), or
    // build a fresh one from the spec.
    (d) => {
      if (typeof window === "undefined") return configFromSpec(d);
      const stored = load(d.dataset_id);
      return stored ? reconcile(stored, d) : configFromSpec(d);
    },
  );

  useEffect(() => {
    save(config);
  }, [config]);

  const reset = useCallback(() => {
    clear(data.dataset_id);
    dispatch({ type: "replace", config: configFromSpec(data) });
  }, [data]);

  return {
    config,
    setTheme: (theme) => dispatch({ type: "setTheme", theme }),
    setLayout: (layout) => dispatch({ type: "setLayout", layout }),
    setTimeGrain: (grain) => dispatch({ type: "setTimeGrain", grain }),
    moveKpi: (from, to) => dispatch({ type: "moveKpi", from, to }),
    toggleKpi: (id, hidden) => dispatch({ type: "toggleKpi", id, hidden }),
    setKpiFormat: (id, format) => dispatch({ type: "setKpiFormat", id, format }),
    addKpi: (id) => dispatch({ type: "addKpi", id }),
    moveChart: (from, to) => dispatch({ type: "moveChart", from, to }),
    updateChart: (id, patch) => dispatch({ type: "updateChart", id, patch }),
    replaceChart: (id, chart) => dispatch({ type: "replaceChart", id, chart }),
    duplicateChart: (id) => dispatch({ type: "duplicateChart", id }),
    removeChart: (id) => dispatch({ type: "removeChart", id }),
    addChart: (chart) => dispatch({ type: "addChart", chart }),
    reset,
    loadConfig: (loaded) =>
      // Keep the current dataset id; a saved view is applied onto this dataset.
      dispatch({
        type: "replace",
        config: { ...loaded, version: 1, datasetId: data.dataset_id },
      }),
  };
}
