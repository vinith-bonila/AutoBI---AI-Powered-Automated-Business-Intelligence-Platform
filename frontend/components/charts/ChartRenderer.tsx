"use client";

/**
 * Renders a `ChartSpecification` plus its data.
 *
 * The backend decides *what* to draw; this file decides *how*, once, for every
 * dataset. There is no per-dataset chart code anywhere in the frontend.
 */

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import type { ChartDataResponse, ChartSpecification } from "@/types";
import {
  MARKS,
  SeriesPalette,
  correlationColor,
  correlationTextColor,
} from "@/lib/theme";
import {
  compactNumber,
  formatCellValue,
  fullNumber,
  humanize,
} from "@/lib/format";
import {
  AXIS_PROPS,
  CHART_MARGIN,
  ChartLegend,
  GRID_PROPS,
  SeriesTooltip,
  TooltipShell,
  axisNumberFormatter,
  truncateLabel,
} from "./ChartPrimitives";
import { EmptyState } from "@/components/ui";

const CHART_HEIGHT = 300;

export interface ChartRendererProps {
  spec: ChartSpecification;
  data: ChartDataResponse;
  palette: SeriesPalette;
}

export function ChartRenderer({ spec, data, palette }: ChartRendererProps) {
  if (!data.data.length) {
    return (
      <EmptyState
        title="No data for this selection"
        description={
          data.empty_reason ??
          "Try widening or clearing the filters above the dashboard."
        }
      />
    );
  }

  switch (spec.type) {
    case "line":
    case "area":
      return <TimeSeriesChart spec={spec} data={data} palette={palette} />;
    case "bar":
      return <VerticalBarChart spec={spec} data={data} palette={palette} />;
    case "horizontal_bar":
      return <HorizontalBarChart spec={spec} data={data} palette={palette} />;
    case "pie":
    case "donut":
      return <ShareChart spec={spec} data={data} palette={palette} />;
    case "scatter":
      return <RelationshipChart spec={spec} data={data} />;
    case "histogram":
      return <DistributionChart data={data} />;
    case "heatmap":
      return <CorrelationHeatmap data={data} />;
    case "table":
      return <DetailTable data={data} />;
    default:
      return (
        <EmptyState
          title="Unsupported chart"
          description={`No renderer is registered for "${spec.type}".`}
        />
      );
  }
}

// ---------------------------------------------------------------------------
// line / area
// ---------------------------------------------------------------------------

function TimeSeriesChart({ spec, data, palette }: ChartRendererProps) {
  const keys = data.y_keys;
  palette.register(keys);
  const isArea = spec.type === "area";
  const Chart = isArea ? AreaChart : LineChart;

  const legendItems = keys.map((key) => ({
    label: key,
    color: palette.get(key),
  }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <Chart data={data.data} margin={CHART_MARGIN}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis
            dataKey={data.x_key}
            {...AXIS_PROPS}
            minTickGap={24}
            tickFormatter={(value: string) => truncateLabel(value, 12)}
          />
          <YAxis {...AXIS_PROPS} tickFormatter={axisNumberFormatter} width={56} />
          <Tooltip
            content={<SeriesTooltip />}
            cursor={{ stroke: "var(--color-axis)", strokeWidth: 1 }}
          />
          {keys.map((key) =>
            isArea ? (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                name={key}
                stroke={palette.get(key)}
                fill={palette.get(key)}
                fillOpacity={0.16}
                strokeWidth={MARKS.lineWidth}
                dot={false}
                activeDot={{ r: MARKS.activeDotRadius, strokeWidth: 2 }}
                connectNulls
              />
            ) : (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                name={key}
                stroke={palette.get(key)}
                strokeWidth={MARKS.lineWidth}
                dot={false}
                activeDot={{ r: MARKS.activeDotRadius, strokeWidth: 2 }}
                connectNulls
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
      <ChartLegend items={legendItems} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// bar
// ---------------------------------------------------------------------------

/**
 * A single-series bar chart uses ONE colour for every bar.
 *
 * Bars here encode magnitude, not identity — colouring each bar differently
 * would imply a category meaning that is not there, and would repaint the
 * survivors whenever a filter changed the ranking.
 */
function VerticalBarChart({ spec, data, palette }: ChartRendererProps) {
  const keys = data.y_keys;
  const grouped = keys.length > 1;
  if (grouped) palette.register(keys);

  const legendItems = grouped
    ? keys.map((key) => ({ label: key, color: palette.get(key) }))
    : [];

  return (
    <div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={data.data} margin={CHART_MARGIN} barGap={MARKS.barGap}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis
            dataKey={data.x_key}
            {...AXIS_PROPS}
            interval={0}
            angle={data.data.length > 6 ? -30 : 0}
            textAnchor={data.data.length > 6 ? "end" : "middle"}
            height={data.data.length > 6 ? 64 : 32}
            tickFormatter={(value: string) => truncateLabel(value, 14)}
          />
          <YAxis {...AXIS_PROPS} tickFormatter={axisNumberFormatter} width={56} />
          <Tooltip
            content={<SeriesTooltip showShare={!grouped} />}
            cursor={{ fill: "var(--color-grid)", fillOpacity: 0.5 }}
          />
          {/* A vertical gradient (strong at the top of each bar) gives ranked
              single-measure bars depth without per-bar Cells. */}
          {!grouped ? (
            <defs>
              <linearGradient id="autobi-bar-vertical" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-series-1)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--color-series-1)" stopOpacity={0.62} />
              </linearGradient>
            </defs>
          ) : null}
          {keys.map((key) => (
            <Bar
              key={key}
              dataKey={key}
              name={key}
              fill={grouped ? palette.get(key) : "url(#autobi-bar-vertical)"}
              radius={[MARKS.barRadius, MARKS.barRadius, 0, 0]}
              maxBarSize={56}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <ChartLegend items={legendItems} />
    </div>
  );
}

function HorizontalBarChart({ data }: ChartRendererProps) {
  const key = data.y_keys[0];
  const height = Math.max(CHART_HEIGHT, data.data.length * 28 + 40);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data.data}
        layout="vertical"
        margin={{ ...CHART_MARGIN, left: 8 }}
        barGap={MARKS.barGap}
      >
        <CartesianGrid {...GRID_PROPS} vertical horizontal={false} />
        <XAxis
          type="number"
          {...AXIS_PROPS}
          tickFormatter={axisNumberFormatter}
        />
        <YAxis
          type="category"
          dataKey={data.x_key}
          {...AXIS_PROPS}
          width={140}
          tickFormatter={(value: string) => truncateLabel(value, 20)}
        />
        <Tooltip
          content={<SeriesTooltip showShare />}
          cursor={{ fill: "var(--color-grid)", fillOpacity: 0.5 }}
        />
        {/* A left→right gradient (strong at the base) gives ranked bars depth. */}
        <defs>
          <linearGradient id="autobi-bar-horizontal" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--color-series-1)" stopOpacity={1} />
            <stop offset="100%" stopColor="var(--color-series-1)" stopOpacity={0.62} />
          </linearGradient>
        </defs>
        <Bar
          dataKey={key}
          name={key}
          fill="url(#autobi-bar-horizontal)"
          radius={[0, MARKS.barRadius, MARKS.barRadius, 0]}
          maxBarSize={22}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// share of total
// ---------------------------------------------------------------------------

function ShareChart({ spec, data, palette }: ChartRendererProps) {
  const key = data.y_keys[0];
  const labels = data.data.map((row) => String(row[data.x_key]));
  palette.register(labels);

  const total = data.data.reduce(
    (sum, row) => sum + Math.abs(Number(row[key]) || 0),
    0,
  );

  return (
    <div className="flex flex-col items-center gap-2 sm:flex-row sm:items-center">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT} className="sm:!w-1/2">
        <PieChart>
          <Pie
            data={data.data}
            dataKey={key}
            nameKey={data.x_key}
            innerRadius={spec.type === "donut" ? "58%" : 0}
            outerRadius="82%"
            paddingAngle={1.5}
            // A 2px surface-coloured gap separates neighbouring slices instead
            // of a drawn border.
            stroke="var(--color-surface)"
            strokeWidth={2}
            isAnimationActive={false}
          >
            {data.data.map((row) => (
              <Cell
                key={String(row[data.x_key])}
                fill={palette.get(String(row[data.x_key]))}
              />
            ))}
          </Pie>
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as Record<string, unknown>;
              const value = Number(row[key]) || 0;
              const share = total ? (Math.abs(value) / total) * 100 : 0;
              return (
                <TooltipShell
                  title={String(row[data.x_key])}
                  rows={[
                    {
                      label: key,
                      value: fullNumber(value),
                      color: palette.get(String(row[data.x_key])),
                    },
                    { label: "Share", value: `${share.toFixed(1)}%` },
                  ]}
                />
              );
            }}
          />
        </PieChart>
      </ResponsiveContainer>

      {/*
        Direct labels beside the ring. Light-mode aqua, yellow and magenta sit
        below 3:1 on this surface, so identity is never carried by colour alone.
      */}
      <ul className="w-full space-y-1.5 sm:w-1/2">
        {data.data.map((row) => {
          const label = String(row[data.x_key]);
          const value = Number(row[key]) || 0;
          const share = total ? (Math.abs(value) / total) * 100 : 0;
          return (
            <li
              key={label}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ backgroundColor: palette.get(label) }}
                />
                <span
                  className="truncate text-[var(--color-ink-secondary)]"
                  title={label}
                >
                  {label}
                </span>
              </span>
              <span className="tabular shrink-0 font-medium text-[var(--color-ink)]">
                {share.toFixed(1)}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// scatter
// ---------------------------------------------------------------------------

function RelationshipChart({ spec, data }: { spec: ChartSpecification; data: ChartDataResponse }) {
  const xLabel = humanize(spec.x ?? "x");
  const yLabel = humanize(spec.y ?? "y");

  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <ScatterChart margin={{ ...CHART_MARGIN, bottom: 24, left: 8 }}>
        <CartesianGrid {...GRID_PROPS} vertical />
        <XAxis
          type="number"
          dataKey="x"
          name={xLabel}
          {...AXIS_PROPS}
          tickFormatter={axisNumberFormatter}
          label={{
            value: xLabel,
            position: "insideBottom",
            offset: -16,
            fill: "var(--color-ink-muted)",
            fontSize: 12,
          }}
        />
        <YAxis
          type="number"
          dataKey="y"
          name={yLabel}
          {...AXIS_PROPS}
          tickFormatter={axisNumberFormatter}
          width={56}
        />
        <ZAxis range={[MARKS.scatterSize, MARKS.scatterSize]} />
        <Tooltip
          cursor={{ strokeDasharray: "0", stroke: "var(--color-axis)" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0].payload as { x: number; y: number };
            return (
              <TooltipShell
                title="Data point"
                rows={[
                  { label: xLabel, value: fullNumber(row.x) },
                  { label: yLabel, value: fullNumber(row.y) },
                ]}
              />
            );
          }}
        />
        {/* Larger dots with a surface-coloured ring so overlapping points in a
            dense cluster stay individually visible. */}
        <Scatter
          data={data.data}
          fill="var(--color-series-1)"
          fillOpacity={MARKS.scatterOpacity}
          stroke="var(--color-surface)"
          strokeWidth={1}
          isAnimationActive={false}
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// histogram
// ---------------------------------------------------------------------------

function DistributionChart({ data }: { data: ChartDataResponse }) {
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={data.data} margin={CHART_MARGIN} barCategoryGap={MARKS.barGap}>
        <CartesianGrid {...GRID_PROPS} />
        <XAxis
          dataKey="x"
          {...AXIS_PROPS}
          interval="preserveStartEnd"
          minTickGap={16}
          tickFormatter={(value: string) => truncateLabel(value, 10)}
        />
        <YAxis {...AXIS_PROPS} tickFormatter={axisNumberFormatter} width={48} />
        <Tooltip
          cursor={{ fill: "var(--color-grid)", fillOpacity: 0.5 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0].payload as Record<string, unknown>;
            return (
              <TooltipShell
                title={String(row.x)}
                rows={[
                  { label: "Rows", value: fullNumber(Number(row.Count) || 0) },
                ]}
                footer="Equal-width bins"
              />
            );
          }}
        />
        {/* One hue with a vertical gradient — height already encodes the count. */}
        <defs>
          <linearGradient id="autobi-histogram" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-seq-550)" stopOpacity={1} />
            <stop offset="100%" stopColor="var(--color-seq-550)" stopOpacity={0.55} />
          </linearGradient>
        </defs>
        <Bar
          dataKey="Count"
          radius={[MARKS.barRadius, MARKS.barRadius, 0, 0]}
          fill="url(#autobi-histogram)"
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// correlation heatmap
// ---------------------------------------------------------------------------

function CorrelationHeatmap({ data }: { data: ChartDataResponse }) {
  const { columns, matrix } = useMemo(() => {
    const seen: string[] = [];
    const lookup = new Map<string, number | null>();
    for (const row of data.data) {
      const x = String(row.x);
      const y = String(row.y);
      if (!seen.includes(x)) seen.push(x);
      const value = row.value === null ? null : Number(row.value);
      lookup.set(`${x}|${y}`, Number.isFinite(value as number) ? (value as number) : null);
    }
    return { columns: seen, matrix: lookup };
  }, [data.data]);

  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full border-separate border-spacing-0.5 text-xs">
        <caption className="sr-only">
          Pearson correlation between numeric columns. Values range from -1 to
          +1.
        </caption>
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--color-surface)] p-1" />
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="max-w-[5rem] truncate p-1 text-center align-bottom font-medium text-[var(--color-ink-muted)]"
                title={column}
              >
                {truncateLabel(column, 8)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {columns.map((rowLabel) => (
            <tr key={rowLabel}>
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-[7rem] truncate bg-[var(--color-surface)] p-1 pr-2 text-right font-medium text-[var(--color-ink-muted)]"
                title={rowLabel}
              >
                {truncateLabel(rowLabel, 12)}
              </th>
              {columns.map((columnLabel) => {
                const value =
                  matrix.get(`${columnLabel}|${rowLabel}`) ??
                  matrix.get(`${rowLabel}|${columnLabel}`) ??
                  null;
                return (
                  <td
                    key={columnLabel}
                    className="rounded p-1.5 text-center"
                    style={{
                      backgroundColor: correlationColor(value),
                      color: correlationTextColor(value),
                    }}
                    title={`${rowLabel} vs ${columnLabel}: ${
                      value === null ? "not available" : value.toFixed(2)
                    }`}
                  >
                    {/* The number is always present, so the colour scale is
                        never the only way to read a cell. */}
                    <span className="tabular text-[11px] font-medium">
                      {value === null ? "—" : value.toFixed(2)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-2 text-[11px] text-[var(--color-ink-muted)]">
        <span>-1</span>
        <span
          aria-hidden="true"
          className="h-2 flex-1 rounded-full"
          style={{
            background:
              "linear-gradient(to right, var(--color-diverging-negative), var(--color-diverging-neutral), var(--color-diverging-positive))",
          }}
        />
        <span>+1</span>
        <span className="ml-1">Inverse · none · direct</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// table
// ---------------------------------------------------------------------------

function DetailTable({ data }: { data: ChartDataResponse }) {
  const columns = data.y_keys;

  return (
    <div className="scroll-thin max-h-[26rem] overflow-auto rounded-lg border border-[var(--color-hairline)]">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 z-10 bg-[var(--color-plane)]">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="whitespace-nowrap border-b border-[var(--color-hairline)] px-3 py-2 font-semibold text-[var(--color-ink-secondary)]"
              >
                {humanize(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.data.map((row, index) => (
            <tr
              key={index}
              className="border-b border-[var(--color-hairline)] last:border-0 hover:bg-[var(--color-plane)]"
            >
              {columns.map((column) => {
                const value = row[column];
                return (
                  <td
                    key={column}
                    className={`whitespace-nowrap px-3 py-1.5 text-[var(--color-ink)] ${
                      typeof value === "number" ? "tabular text-right" : ""
                    }`}
                  >
                    {formatCellValue(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export { compactNumber };
