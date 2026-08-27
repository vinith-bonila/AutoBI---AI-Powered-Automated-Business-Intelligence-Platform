"use client";

/**
 * One chart, with its own data lifecycle and an edit menu.
 *
 * All charts — the ones the engine generated, ones the user switched the type
 * of, and ones the user added — render through the SAME ad-hoc execute path,
 * so switching a chart's type or axes is just a spec edit that re-fetches. The
 * backend re-validates every spec, so an invalid edit degrades to an error
 * message inside the card and never breaks the dashboard.
 *
 * Loading behaviour: a skeleton only on first load; on filter/spec changes the
 * previous chart stays visible, dimmed, while new data arrives.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type {
  ChartDataResponse,
  ChartSpecification,
  ChartType,
  FieldInfo,
  FilterValue,
} from "@/types";
import { SeriesPalette } from "@/lib/theme";
import { Card, ErrorState, InfoTip, Skeleton, cn } from "@/components/ui";
import { ChartRenderer } from "./ChartRenderer";
import { ChartMenu } from "./ChartMenu";

export interface ChartActions {
  onReplace: (chart: ChartSpecification) => void;
  onUpdate: (patch: Partial<ChartSpecification>) => void;
  onDuplicate: () => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
}

interface ChartCardProps {
  datasetId: string;
  spec: ChartSpecification;
  filters: FilterValue[];
  timeGrain: string | null;
  fields: FieldInfo[];
  editable: boolean;
  actions?: ChartActions;
}

export function ChartCard({
  datasetId,
  spec,
  filters,
  timeGrain,
  fields,
  editable,
  actions,
}: ChartCardProps) {
  const [data, setData] = useState<ChartDataResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(true);
  const [attempt, setAttempt] = useState(0);

  const paletteRef = useRef(new SeriesPalette());

  // The effective spec applies the dashboard-wide time grain to time charts.
  const effectiveSpec = useMemo<ChartSpecification>(() => {
    if (timeGrain && (spec.type === "line" || spec.type === "area")) {
      return { ...spec, time_grain: timeGrain };
    }
    return spec;
  }, [spec, timeGrain]);

  const specKey = JSON.stringify({
    t: effectiveSpec.type,
    x: effectiveSpec.x,
    y: effectiveSpec.y,
    s: effectiveSpec.series,
    a: effectiveSpec.aggregation,
    g: effectiveSpec.time_grain,
    c: effectiveSpec.columns,
    b: effectiveSpec.bins,
    sort: effectiveSpec.sort,
  });
  const filterKey = JSON.stringify(filters);

  useEffect(() => {
    let cancelled = false;
    setIsFetching(true);

    api
      .executeChart(datasetId, effectiveSpec as ChartSpecification, filters)
      .then((response) => {
        if (cancelled) return;
        setData(response);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError ? err.message : "This chart could not be loaded.",
        );
      })
      .finally(() => {
        if (!cancelled) setIsFetching(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, specKey, filterKey, attempt]);

  const isInitialLoad = isFetching && data === null;
  const isRefetching = isFetching && data !== null;

  return (
    <Card className="flex h-full flex-col p-5">
      <div className="mb-4 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
            <span className="truncate">{spec.title}</span>
            {spec.rationale ? (
              <InfoTip label={`Why this chart: ${spec.rationale}`}>
                <span className="block">
                  <strong className="font-semibold text-[var(--color-ink)]">
                    Why this chart
                  </strong>
                  <br />
                  {spec.rationale}
                </span>
              </InfoTip>
            ) : null}
          </h3>
          {spec.description ? (
            <p className="mt-0.5 truncate text-xs text-[var(--color-ink-secondary)]">
              {spec.description}
            </p>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {isRefetching ? (
            <span className="text-[11px] text-[var(--color-ink-muted)]">Updating…</span>
          ) : null}
          {editable && actions ? (
            <ChartMenu
              datasetId={datasetId}
              spec={spec}
              fields={fields}
              actions={actions}
            />
          ) : null}
        </div>
      </div>

      <div className="flex-1">
        {isInitialLoad ? (
          <ChartSkeleton />
        ) : error ? (
          <ErrorState
            title="Chart unavailable"
            message={error}
            onRetry={() => setAttempt((value) => value + 1)}
          />
        ) : data ? (
          <div
            className={cn(
              "transition-opacity duration-200",
              isRefetching && "opacity-55",
            )}
          >
            <ChartRenderer spec={effectiveSpec} data={data} palette={paletteRef.current} />
            {data.truncated ? (
              <p className="mt-3 text-[11px] text-[var(--color-ink-muted)]">
                Showing the top {data.row_count.toLocaleString()} rows.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function ChartSkeleton() {
  const heights = [52, 78, 40, 92, 64, 84, 48, 70];
  return (
    <div className="space-y-3" aria-hidden="true">
      <div className="flex h-[260px] items-end gap-2">
        {heights.map((height, index) => (
          <Skeleton
            key={index}
            className="flex-1 rounded-t-md"
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
      <Skeleton className="h-3 w-1/3" />
    </div>
  );
}
