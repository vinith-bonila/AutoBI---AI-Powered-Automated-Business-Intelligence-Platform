"use client";

/**
 * The data quality report.
 *
 * This is the trust surface of the product: it shows exactly what the cleaner
 * changed, why, and how many rows each change touched — so a user can believe
 * the numbers on the dashboard.
 */

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type {
  DataQualityReport,
  DatasetProfile,
  PreviewResponse,
} from "@/types";
import { formatCellValue, humanize } from "@/lib/format";
import {
  Badge,
  Card,
  ProgressBar,
  SectionHeading,
  Skeleton,
  Stat,
} from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  parse_datetime: "Parsed dates",
  parse_numeric: "Parsed numbers",
  strip_currency: "Removed currency symbols",
  parse_percent: "Parsed percentages",
  trim_whitespace: "Trimmed whitespace",
  normalize_empty: "Normalised blanks",
  drop_duplicates: "Removed duplicates",
  fill_missing: "Filled missing labels",
  drop_column: "Dropped column",
  cast_boolean: "Cast to true/false",
  normalize_category: "Merged category variants",
  flag_outliers: "Flagged outliers",
};

function scoreTone(score: number): "good" | "warning" | "critical" {
  if (score >= 90) return "good";
  if (score >= 75) return "warning";
  return "critical";
}

export function QualityPanel({
  datasetId,
  quality,
  profile,
}: {
  datasetId: string;
  quality: DataQualityReport;
  profile: DatasetProfile;
}) {
  return (
    <div className="space-y-6">
      <QualityScoreCard quality={quality} />
      <div className="grid gap-6 lg:grid-cols-2">
        <CleaningActions quality={quality} />
        <MissingValues quality={quality} />
      </div>
      <ColumnProfileTable profile={profile} />
      <DataPreview datasetId={datasetId} />
    </div>
  );
}

function QualityScoreCard({ quality }: { quality: DataQualityReport }) {
  const scores = [
    { label: "Completeness", value: quality.completeness_score, hint: "Share of cells with a value" },
    { label: "Uniqueness", value: quality.uniqueness_score, hint: "After removing duplicates" },
    { label: "Consistency", value: quality.consistency_score, hint: "Columns with a confident type" },
  ];

  return (
    <Card className="p-6">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-center">
        <div className="lg:w-56 lg:shrink-0">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-ink-muted)]">
            Overall quality score
          </p>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-4xl font-semibold text-[var(--color-ink)]">
              {quality.quality_score.toFixed(0)}
            </span>
            <span className="text-sm text-[var(--color-ink-muted)]">/ 100</span>
          </div>
          <div className="mt-3">
            <ProgressBar
              value={quality.quality_score}
              tone={scoreTone(quality.quality_score)}
            />
          </div>
        </div>

        <div className="grid flex-1 grid-cols-1 gap-5 sm:grid-cols-3">
          {scores.map((score) => (
            <div key={score.label}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-[var(--color-ink-secondary)]">
                  {score.label}
                </span>
                <span className="tabular text-sm font-semibold text-[var(--color-ink)]">
                  {score.value.toFixed(0)}
                </span>
              </div>
              <div className="mt-1.5">
                <ProgressBar value={score.value} tone={scoreTone(score.value)} />
              </div>
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                {score.hint}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 border-t border-[var(--color-hairline)] pt-5 sm:grid-cols-4">
        <Stat
          label="Rows analysed"
          value={quality.rows_after.toLocaleString()}
          hint={
            quality.rows_before - quality.rows_after > 0
              ? `${(quality.rows_before - quality.rows_after).toLocaleString()} removed`
              : "None removed"
          }
        />
        <Stat label="Columns" value={quality.columns_after} />
        <Stat
          label="Duplicates removed"
          value={quality.duplicates_removed.toLocaleString()}
        />
        <Stat
          label="Cleaning actions"
          value={quality.actions.length}
        />
      </div>

      {quality.warnings.length ? (
        <ul className="mt-5 space-y-1.5 rounded-lg bg-[var(--color-plane)] p-4">
          {quality.warnings.map((warning, index) => (
            <li
              key={index}
              className="flex gap-2 text-xs text-[var(--color-ink-secondary)]"
            >
              <span aria-hidden="true" className="text-[var(--color-warning)]">
                !
              </span>
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function CleaningActions({ quality }: { quality: DataQualityReport }) {
  return (
    <Card className="p-5">
      <SectionHeading
        title="Cleaning log"
        description="Every transformation applied, with the rows it touched."
      />
      {quality.actions.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-secondary)]">
          The data was already clean — no transformations were needed.
        </p>
      ) : (
        <ul className="scroll-thin max-h-96 space-y-2 overflow-y-auto pr-1">
          {quality.actions.map((action, index) => (
            <li
              key={index}
              className="rounded-lg border border-[var(--color-hairline)] p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-medium text-[var(--color-ink)]">
                  <span
                    aria-hidden="true"
                    className="text-[var(--color-success-text)]"
                  >
                    ✓
                  </span>
                  {ACTION_LABEL[action.action] ?? action.action}
                  {action.column ? (
                    <code className="rounded bg-[var(--color-plane)] px-1.5 py-0.5 text-xs text-[var(--color-ink-secondary)]">
                      {action.column}
                    </code>
                  ) : null}
                </span>
                {action.rows_affected > 0 ? (
                  <Badge>{action.rows_affected.toLocaleString()} rows</Badge>
                ) : null}
              </div>
              <p className="mt-1.5 text-xs text-[var(--color-ink-secondary)]">
                {action.reason}
                {action.detail ? (
                  <span className="text-[var(--color-ink-muted)]">
                    {" "}
                    {action.detail}
                  </span>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function MissingValues({ quality }: { quality: DataQualityReport }) {
  return (
    <Card className="p-5">
      <SectionHeading
        title="Missing values"
        description="How gaps in each column were handled."
      />
      {quality.missing_summary.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-secondary)]">
          No missing values remained after cleaning.
        </p>
      ) : (
        <ul className="scroll-thin max-h-96 space-y-3 overflow-y-auto pr-1">
          {quality.missing_summary.map((entry) => (
            <li key={entry.column}>
              <div className="flex items-center justify-between text-sm">
                <code className="rounded bg-[var(--color-plane)] px-1.5 py-0.5 text-xs text-[var(--color-ink)]">
                  {entry.column}
                </code>
                <span className="tabular text-xs font-medium text-[var(--color-ink-secondary)]">
                  {entry.missing_pct.toFixed(1)}% missing
                </span>
              </div>
              <div className="mt-1.5">
                <ProgressBar
                  value={entry.missing_pct}
                  tone={entry.missing_pct > 20 ? "warning" : "accent"}
                />
              </div>
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                {entry.strategy}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ColumnProfileTable({ profile }: { profile: DatasetProfile }) {
  return (
    <Card className="p-5">
      <SectionHeading
        title="Column profile"
        description={`${profile.n_columns} columns, each with a detected type and business role.`}
      />
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-[var(--color-ink-muted)]">
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 text-right font-medium">Missing</th>
              <th className="px-3 py-2 text-right font-medium">Unique</th>
              <th className="px-3 py-2 font-medium">Why this role</th>
            </tr>
          </thead>
          <tbody>
            {profile.columns.map((column) => (
              <tr
                key={column.name}
                className="border-t border-[var(--color-hairline)]"
              >
                <td className="px-3 py-2 font-medium text-[var(--color-ink)]">
                  {column.name}
                </td>
                <td className="px-3 py-2">
                  <Badge>{column.inferred_type}</Badge>
                </td>
                <td className="px-3 py-2 text-[var(--color-ink-secondary)]">
                  {humanize(column.semantic_role)}
                </td>
                <td className="tabular px-3 py-2 text-right text-[var(--color-ink-secondary)]">
                  {column.missing_pct.toFixed(1)}%
                </td>
                <td className="tabular px-3 py-2 text-right text-[var(--color-ink-secondary)]">
                  {column.unique.toLocaleString()}
                </td>
                <td className="max-w-[16rem] px-3 py-2 text-[var(--color-ink-muted)]">
                  {column.role_evidence[0] ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DataPreview({ datasetId }: { datasetId: string }) {
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .preview(datasetId, 12)
      .then((response) => !cancelled && setPreview(response))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  return (
    <Card className="p-5">
      <SectionHeading
        title="Cleaned data preview"
        description={
          preview
            ? `A sample of the ${preview.total_rows.toLocaleString()} cleaned rows the dashboard is built from.`
            : "The data after cleaning."
        }
      />
      {error ? (
        <p className="text-sm text-[var(--color-ink-secondary)]">
          Preview is unavailable.
        </p>
      ) : !preview ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-6 w-full" />
          ))}
        </div>
      ) : (
        <div className="scroll-thin overflow-x-auto rounded-lg border border-[var(--color-hairline)]">
          <table className="w-full text-left text-xs">
            <thead className="bg-[var(--color-plane)]">
              <tr>
                {preview.columns.map((column) => (
                  <th
                    key={column}
                    className="whitespace-nowrap px-3 py-2 font-semibold text-[var(--color-ink-secondary)]"
                  >
                    {humanize(column)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, index) => (
                <tr
                  key={index}
                  className="border-t border-[var(--color-hairline)]"
                >
                  {preview.columns.map((column) => (
                    <td
                      key={column}
                      className="whitespace-nowrap px-3 py-1.5 text-[var(--color-ink)]"
                    >
                      {formatCellValue(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
