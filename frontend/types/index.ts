/**
 * TypeScript mirrors of the backend Pydantic contracts.
 *
 * These are hand-maintained rather than generated so the frontend depends on a
 * narrow, readable surface. The names and shapes match `backend/app/schemas`
 * exactly; if you change one, change the other.
 */

// ---------------------------------------------------------------------------
// enums (kept as string unions — they cross the wire as strings)
// ---------------------------------------------------------------------------

export type InferredType =
  | "numeric"
  | "categorical"
  | "datetime"
  | "boolean"
  | "text"
  | "empty";

export type SemanticRole =
  | "measure"
  | "currency"
  | "percentage"
  | "quantity"
  | "ratio"
  | "dimension"
  | "time"
  | "geo"
  | "identifier"
  | "demographic"
  | "flag"
  | "text"
  | "unknown";

export type ChartType =
  | "line"
  | "bar"
  | "horizontal_bar"
  | "area"
  | "pie"
  | "donut"
  | "scatter"
  | "histogram"
  | "heatmap"
  | "table";

export type Aggregation =
  | "sum"
  | "avg"
  | "min"
  | "max"
  | "count"
  | "count_distinct"
  | "median"
  | "none";

export type ValueFormat =
  | "currency"
  | "number"
  | "percent"
  | "count"
  | "decimal"
  | "duration_days";

export type FilterKind =
  | "select"
  | "multi_select"
  | "date_range"
  | "numeric_range";

export type FilterOperator = "eq" | "in" | "between" | "gte" | "lte";

export type InsightCategory =
  | "trend"
  | "anomaly"
  | "segment"
  | "correlation"
  | "distribution"
  | "quality"
  | "recommendation"
  | "summary";

export type InsightSeverity = "positive" | "neutral" | "warning" | "critical";

export type JobStatus = "pending" | "running" | "complete" | "failed";

export type GenerationSource = "deterministic" | "ai" | "hybrid";

// ---------------------------------------------------------------------------
// profile
// ---------------------------------------------------------------------------

export interface ValueCount {
  value: string;
  count: number;
  pct: number;
}

export interface NumericStats {
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
  std: number | null;
  p25: number | null;
  p75: number | null;
  p05: number | null;
  p95: number | null;
  skew: number | null;
  sum: number | null;
  zero_pct: number;
  negative_pct: number;
  outlier_count: number;
}

export interface DatetimeStats {
  min: string | null;
  max: string | null;
  range_days: number | null;
  suggested_grain: string | null;
  distinct_days: number | null;
}

export interface ColumnProfile {
  name: string;
  original_dtype: string;
  inferred_type: InferredType;
  semantic_role: SemanticRole;
  role_confidence: number;
  role_evidence: string[];
  count: number;
  missing: number;
  missing_pct: number;
  unique: number;
  cardinality_ratio: number;
  is_constant: boolean;
  is_unique_key: boolean;
  numeric: NumericStats | null;
  datetime: DatetimeStats | null;
  top_values: ValueCount[];
  sample_values: string[];
}

export interface DatasetProfile {
  dataset_id: string;
  name: string;
  n_rows: number;
  n_columns: number;
  n_duplicate_rows: number;
  memory_bytes: number;
  columns: ColumnProfile[];
  numeric_columns: string[];
  categorical_columns: string[];
  datetime_columns: string[];
  boolean_columns: string[];
  text_columns: string[];
  identifier_columns: string[];
  measure_columns: string[];
  dimension_columns: string[];
  primary_date_column: string | null;
  primary_measure_column: string | null;
  domain_guess: string | null;
  domain_signals: string[];
}

// ---------------------------------------------------------------------------
// quality
// ---------------------------------------------------------------------------

export interface CleaningAction {
  action: string;
  column: string | null;
  rows_affected: number;
  reason: string;
  detail: string | null;
}

export interface MissingSummary {
  column: string;
  missing: number;
  missing_pct: number;
  strategy: string;
}

export interface DataQualityReport {
  dataset_id: string;
  rows_before: number;
  rows_after: number;
  columns_before: number;
  columns_after: number;
  duplicates_removed: number;
  total_missing_before: number;
  total_missing_after: number;
  actions: CleaningAction[];
  missing_summary: MissingSummary[];
  dropped_columns: string[];
  warnings: string[];
  completeness_score: number;
  uniqueness_score: number;
  consistency_score: number;
  quality_score: number;
}

// ---------------------------------------------------------------------------
// analysis
// ---------------------------------------------------------------------------

export interface TrendPoint {
  period: string;
  value: number;
}

export interface TrendAnalysis {
  measure: string;
  date_column: string;
  grain: string;
  points: TrendPoint[];
  first_value: number | null;
  last_value: number | null;
  change_pct: number | null;
  direction: string;
  slope: number | null;
  r_squared: number | null;
  best_period: TrendPoint | null;
  worst_period: TrendPoint | null;
  period_over_period_pct: number | null;
  volatility_pct: number | null;
  partial_period_excluded: string | null;
}

export interface SegmentRow {
  label: string;
  value: number;
  share_pct: number;
  count: number;
}

export interface SegmentAnalysis {
  dimension: string;
  measure: string;
  aggregation: string;
  top: SegmentRow[];
  bottom: SegmentRow[];
  n_categories: number;
  concentration_pct: number | null;
  gini: number | null;
  has_negative_values: boolean;
  share_basis: string;
}

export interface CorrelationPair {
  x: string;
  y: string;
  coefficient: number;
  strength: string;
  direction: string;
  p_value: number | null;
  n: number;
}

export interface OutlierReport {
  column: string;
  method: string;
  count: number;
  pct: number;
  lower_bound: number | null;
  upper_bound: number | null;
  extreme_values: number[];
}

export interface AnomalyReport {
  measure: string;
  period: string;
  value: number;
  expected: number;
  deviation_pct: number;
  z_score: number;
}

export interface DistributionSummary {
  column: string;
  shape: string;
  skew: number | null;
  kurtosis: number | null;
  bins: number[];
  counts: number[];
}

export interface AnalysisResult {
  dataset_id: string;
  row_count: number;
  correlations: CorrelationPair[];
  trends: TrendAnalysis[];
  segments: SegmentAnalysis[];
  outliers: OutlierReport[];
  anomalies: AnomalyReport[];
  distributions: DistributionSummary[];
  notes: string[];
}

// ---------------------------------------------------------------------------
// dashboard specification
// ---------------------------------------------------------------------------

export interface KPIComparison {
  previous_value: number | null;
  change: number | null;
  change_pct: number | null;
  direction: string;
  period_label: string | null;
  is_favorable: boolean | null;
}

export interface KPI {
  id: string;
  name: string;
  value: number | null;
  formatted_value: string;
  format: ValueFormat;
  unit: string | null;
  calculation: string;
  why_it_matters: string;
  source_columns: string[];
  comparison: KPIComparison | null;
  priority: number;
  source: GenerationSource;
}

export interface ChartSpecification {
  id: string;
  type: ChartType;
  title: string;
  description: string | null;
  x: string | null;
  y: string | null;
  series: string | null;
  aggregation: Aggregation;
  time_grain: string | null;
  sort: string | null;
  limit: number | null;
  bins: number | null;
  columns: string[];
  section: string;
  width: string;
  rationale: string | null;
  source: GenerationSource;
}

export interface FilterSpecification {
  id: string;
  column: string;
  label: string;
  kind: FilterKind;
  operator: FilterOperator;
  options: string[];
  min: number | string | null;
  max: number | string | null;
  default: unknown;
}

export interface InsightEvidence {
  metric: string;
  value: string;
  detail: string | null;
}

export interface Insight {
  id: string;
  title: string;
  body: string;
  category: InsightCategory;
  severity: InsightSeverity;
  evidence: InsightEvidence[];
  confidence: number;
  source: GenerationSource;
}

export interface DashboardSpecification {
  dataset_id: string;
  title: string;
  description: string;
  domain: string;
  kpis: KPI[];
  charts: ChartSpecification[];
  filters: FilterSpecification[];
  insights: Insight[];
  source: GenerationSource;
  ai_provider: string | null;
  ai_notes: string[];
  created_at: string;
}

// ---------------------------------------------------------------------------
// API payloads
// ---------------------------------------------------------------------------

export interface PipelineStep {
  key: string;
  label: string;
  status: JobStatus;
  detail: string | null;
  duration_ms: number | null;
}

export interface JobState {
  dataset_id: string;
  filename: string;
  status: JobStatus;
  steps: PipelineStep[];
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  dataset_id: string;
  filename: string;
  status: JobStatus;
  message: string;
}

export interface DashboardResponse {
  dataset_id: string;
  filename: string;
  specification: DashboardSpecification;
  profile: DatasetProfile;
  quality: DataQualityReport;
  analysis: AnalysisResult;
  ai_enabled: boolean;
  created_at: string;
}

export interface ChartDataResponse {
  chart_id: string;
  type: string;
  x_key: string;
  y_keys: string[];
  data: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  empty_reason: string | null;
}

export interface KPIRefreshResponse {
  kpis: KPI[];
  row_count: number;
}

export interface PreviewResponse {
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
}

export interface AppConfig {
  app_name: string;
  ai_enabled: boolean;
  ai_provider: string | null;
  max_upload_mb: number;
  allowed_extensions: string[];
  max_rows_analyzed: number;
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  filename: string;
  n_rows: number;
  n_columns: number;
  domain: string | null;
  created_at: string;
  status: JobStatus;
}

export interface FieldInfo {
  name: string;
  label: string;
  inferred_type: InferredType;
  semantic_role: SemanticRole;
  is_measure: boolean;
  is_dimension: boolean;
  is_temporal: boolean;
  unique: number;
  missing_pct: number;
  suggested_aggregation: Aggregation;
}

export interface FieldsResponse {
  fields: FieldInfo[];
  measures: string[];
  dimensions: string[];
  temporal: string[];
  primary_date_column: string | null;
  primary_measure_column: string | null;
  default_time_grain: string | null;
}

export interface ChartValidateResponse {
  ok: boolean;
  reason: string | null;
  allowed_types: ChartType[];
}

export interface AskEvidence {
  label: string;
  value: string;
  detail: string | null;
}

export interface AskChart {
  chart: ChartSpecification;
  data: ChartDataResponse;
}

export interface AskResponse {
  question: string;
  answer: string;
  interpretation: string;
  evidence: AskEvidence[];
  table: Record<string, unknown>[];
  table_columns: string[];
  chart: AskChart | null;
  ai_used: boolean;
  warning: string | null;
}

export interface SavedDashboard {
  id: string;
  dataset_id: string;
  name: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SavedDashboardSummary {
  id: string;
  dataset_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

/** A filter value as sent to the backend. */
export interface FilterValue {
  column: string;
  operator: FilterOperator;
  value: unknown;
}

/** Client-side filter state, keyed by filter id. */
export type FilterState = Record<string, string[] | [string, string] | null>;
