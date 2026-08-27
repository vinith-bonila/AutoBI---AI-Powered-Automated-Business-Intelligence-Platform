/**
 * Typed client for the AutoBI backend.
 *
 * Every call funnels through `request`, so error handling, JSON parsing and
 * the base URL live in exactly one place.
 */

import type {
  AppConfig,
  AskResponse,
  ChartDataResponse,
  ChartSpecification,
  ChartValidateResponse,
  DashboardResponse,
  DatasetSummary,
  FieldsResponse,
  FilterValue,
  JobState,
  KPIRefreshResponse,
  PreviewResponse,
  SavedDashboard,
  SavedDashboardSummary,
  UploadResponse,
} from "@/types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "error") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** True when retrying the same request could plausibly succeed. */
  get isTransient(): boolean {
    return this.status === 0 || this.status === 409 || this.status >= 500;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      `Could not reach the AutoBI API at ${API_URL}. Is the backend running?`,
      0,
      "network_error",
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const body = payload as { detail?: string; code?: string } | null;
    throw new ApiError(
      body?.detail ?? `Request failed with status ${response.status}.`,
      response.status,
      body?.code ?? "error",
    );
  }

  return payload as T;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResponse>("/api/datasets", {
      method: "POST",
      body: form,
    });
  },

  status: (datasetId: string) =>
    request<JobState>(`/api/datasets/${datasetId}/status`),

  dashboard: (datasetId: string) =>
    request<DashboardResponse>(`/api/datasets/${datasetId}`),

  chartData: (
    datasetId: string,
    chartId: string,
    filters: FilterValue[],
    timeGrain?: string | null,
  ) =>
    request<ChartDataResponse>(
      `/api/datasets/${datasetId}/charts/${chartId}/data`,
      {
        method: "POST",
        body: JSON.stringify({ filters, time_grain: timeGrain ?? null }),
      },
    ),

  // Run an ad-hoc chart spec (chart switching, Add Visualization).
  executeChart: (
    datasetId: string,
    chart: Partial<ChartSpecification> & { type: string },
    filters: FilterValue[],
  ) =>
    request<ChartDataResponse>(`/api/datasets/${datasetId}/charts/execute`, {
      method: "POST",
      body: JSON.stringify({ chart, filters }),
    }),

  validateChart: (
    datasetId: string,
    chart: Partial<ChartSpecification> & { type: string },
  ) =>
    request<ChartValidateResponse>(`/api/datasets/${datasetId}/charts/validate`, {
      method: "POST",
      body: JSON.stringify({ chart, filters: [] }),
    }),

  fields: (datasetId: string) =>
    request<FieldsResponse>(`/api/datasets/${datasetId}/fields`),

  ask: (datasetId: string, question: string, filters: FilterValue[] = []) =>
    request<AskResponse>(`/api/datasets/${datasetId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question, filters }),
    }),

  // Export URLs are plain GET downloads; the browser handles the file save.
  exportUrl: (datasetId: string, kind: string) =>
    `${API_URL}/api/datasets/${datasetId}/export/${kind}`,

  // --- saved dashboards (save / load / share) ---------------------------
  saveDashboard: (datasetId: string, name: string, config: unknown) =>
    request<SavedDashboard>(`/api/datasets/${datasetId}/dashboards`, {
      method: "POST",
      body: JSON.stringify({ name, config }),
    }),

  listDashboards: (datasetId: string) =>
    request<SavedDashboardSummary[]>(`/api/datasets/${datasetId}/dashboards`),

  loadDashboard: (dashboardId: string) =>
    request<SavedDashboard>(`/api/dashboards/${dashboardId}`),

  deleteDashboard: (dashboardId: string) =>
    request<void>(`/api/dashboards/${dashboardId}`, { method: "DELETE" }),

  kpis: (datasetId: string, filters: FilterValue[]) =>
    request<KPIRefreshResponse>(`/api/datasets/${datasetId}/kpis`, {
      method: "POST",
      body: JSON.stringify({ filters }),
    }),

  preview: (datasetId: string, limit = 25) =>
    request<PreviewResponse>(
      `/api/datasets/${datasetId}/preview?limit=${limit}`,
    ),

  list: () => request<DatasetSummary[]>("/api/datasets"),

  remove: (datasetId: string) =>
    request<void>(`/api/datasets/${datasetId}`, { method: "DELETE" }),
};
