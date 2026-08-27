"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api } from "@/lib/api";
import type { AppConfig, DatasetSummary } from "@/types";
import { UploadZone } from "@/components/upload/UploadZone";
import { Badge, Card } from "@/components/ui";
import { humanize } from "@/lib/format";

const PIPELINE_STEPS = [
  ["Profile", "Detect types, roles and the dataset's domain"],
  ["Clean", "Fix currencies, dates and duplicates — auditable, never destructive"],
  ["Analyse", "Trends, segments, correlations, anomalies and outliers"],
  ["Visualise", "Pick the right KPIs and charts for the data at hand"],
];

const SAMPLE_HINTS = [
  "E-commerce sales",
  "HR & headcount",
  "Marketing campaigns",
  "Financial transactions",
];

export default function LandingPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [recent, setRecent] = useState<DatasetSummary[]>([]);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
    api
      .list()
      .then((list) => setRecent(list.filter((d) => d.status === "complete").slice(0, 6)))
      .catch(() => setRecent([]));
  }, []);

  return (
    <div className="mx-auto max-w-[1100px] px-4 py-12 sm:px-6 sm:py-16">
      <section className="mx-auto max-w-2xl text-center">
        <Badge tone="accent" className="mb-5">
          {config?.ai_enabled
            ? `AI narration on · ${config.ai_provider}`
            : "Deterministic engine · no API key required"}
        </Badge>
        <h1 className="text-balance text-4xl font-semibold tracking-tight text-[var(--color-ink)] sm:text-5xl">
          Turn any CSV into an intelligent dashboard.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-pretty text-lg text-[var(--color-ink-secondary)]">
          Upload a file and AutoBI does the analyst's work for you — profiling,
          cleaning, exploring and visualising the data into an interactive
          dashboard with plain-English insights.
        </p>
      </section>

      <section className="mx-auto mt-10 max-w-2xl">
        <UploadZone config={config} />
        <p className="mt-3 text-center text-xs text-[var(--color-ink-muted)]">
          Works with {SAMPLE_HINTS.join(", ")} and any other structured table.
        </p>
      </section>

      <section className="mt-16">
        <h2 className="text-center text-sm font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
          What happens after you upload
        </h2>
        <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PIPELINE_STEPS.map(([title, description], index) => (
            <li key={title}>
              <Card className="h-full p-5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent-soft)] text-sm font-semibold text-[var(--color-accent)]">
                  {index + 1}
                </span>
                <h3 className="mt-3 text-sm font-semibold text-[var(--color-ink)]">
                  {title}
                </h3>
                <p className="mt-1 text-sm text-[var(--color-ink-secondary)]">
                  {description}
                </p>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      {recent.length ? (
        <section className="mt-16">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
            Recent dashboards
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {recent.map((dataset) => (
              <Link key={dataset.dataset_id} href={`/dashboard/${dataset.dataset_id}`}>
                <Card className="flex h-full items-center justify-between gap-3 p-4 transition-colors hover:border-[var(--color-accent)]">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-[var(--color-ink)]">
                      {dataset.name}
                    </p>
                    <p className="text-xs text-[var(--color-ink-muted)]">
                      {dataset.n_rows.toLocaleString()} rows ·{" "}
                      {dataset.n_columns} columns
                    </p>
                  </div>
                  {dataset.domain ? (
                    <Badge>{humanize(dataset.domain)}</Badge>
                  ) : null}
                </Card>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <section className="mt-16 grid gap-4 sm:grid-cols-3">
        {[
          [
            "Grounded, never invented",
            "Every KPI and insight is computed in Python from your data. The AI layer only chooses and narrates — it never produces a number.",
          ],
          [
            "Works for any domain",
            "Sales, HR, marketing, finance and more. AutoBI infers the domain and builds the dashboard that fits, not a fixed template.",
          ],
          [
            "Transparent cleaning",
            "See exactly what was changed and why. Missing values are excluded from totals, never quietly imputed.",
          ],
        ].map(([title, body]) => (
          <Card key={title} className="p-5">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">
              {title}
            </h3>
            <p className="mt-1.5 text-sm text-[var(--color-ink-secondary)]">
              {body}
            </p>
          </Card>
        ))}
      </section>
    </div>
  );
}
