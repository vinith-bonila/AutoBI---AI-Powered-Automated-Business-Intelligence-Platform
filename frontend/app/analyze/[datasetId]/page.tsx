"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import type { JobState } from "@/types";
import { Button, Card, ProgressBar } from "@/components/ui";
import { formatDuration } from "@/lib/format";

const POLL_INTERVAL_MS = 700;

export default function AnalyzePage({
  params,
}: {
  params: Promise<{ datasetId: string }>;
}) {
  const { datasetId } = use(params);
  const router = useRouter();
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const redirected = useRef(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const state = await api.status(datasetId);
        if (!active) return;
        setJob(state);

        if (state.status === "complete" && !redirected.current) {
          redirected.current = true;
          // A brief beat so the final checkmark is visible before the redirect.
          setTimeout(() => router.replace(`/dashboard/${datasetId}`), 550);
          return;
        }
        if (state.status === "failed") {
          setError(state.error ?? "Analysis failed.");
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (!active) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Lost contact with the analysis service.",
        );
      }
    }

    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [datasetId, router]);

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-xl flex-col justify-center px-4 py-12 sm:px-6">
      <Card className="p-8">
        {error ? (
          <FailureView error={error} onRestart={() => router.push("/")} />
        ) : (
          <ProgressView job={job} filename={job?.filename} />
        )}
      </Card>
    </div>
  );
}

function ProgressView({
  job,
  filename,
}: {
  job: JobState | null;
  filename?: string;
}) {
  const steps = job?.steps ?? [];
  const progress = job?.progress ?? 0;

  return (
    <div>
      <div className="mb-6 text-center">
        <h1 className="text-xl font-semibold text-[var(--color-ink)]">
          Analysing your dataset…
        </h1>
        {filename ? (
          <p className="mt-1 text-sm text-[var(--color-ink-secondary)]">
            {filename}
          </p>
        ) : null}
      </div>

      <div className="mb-6">
        <ProgressBar value={progress} />
        <p className="mt-2 text-center text-xs text-[var(--color-ink-muted)]">
          {Math.round(progress)}% complete
        </p>
      </div>

      <ol className="space-y-1">
        {steps.length === 0
          ? Array.from({ length: 9 }).map((_, index) => (
              <li key={index} className="flex items-center gap-3 py-1.5">
                <span className="skeleton h-5 w-5 rounded-full" />
                <span className="skeleton h-3 w-40 rounded" />
              </li>
            ))
          : steps.map((step) => (
              <li
                key={step.key}
                className="flex items-center gap-3 py-1.5 animate-fade-in"
              >
                <StepIcon status={step.status} />
                <div className="flex-1">
                  <span
                    className={
                      step.status === "complete"
                        ? "text-sm text-[var(--color-ink)]"
                        : step.status === "running"
                          ? "text-sm font-medium text-[var(--color-ink)]"
                          : "text-sm text-[var(--color-ink-muted)]"
                    }
                  >
                    {step.label}
                  </span>
                  {step.detail && step.status === "complete" ? (
                    <span className="ml-2 text-xs text-[var(--color-ink-muted)]">
                      {step.detail}
                    </span>
                  ) : null}
                </div>
                {step.duration_ms ? (
                  <span className="tabular text-[11px] text-[var(--color-ink-muted)]">
                    {formatDuration(step.duration_ms)}
                  </span>
                ) : null}
              </li>
            ))}
      </ol>
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  if (status === "complete") {
    return (
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full text-white"
        style={{ backgroundColor: "var(--color-good)" }}
        aria-label="Done"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
          <path
            d="m5 12 5 5L20 7"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  if (status === "running") {
    return (
      <span
        className="flex h-5 w-5 items-center justify-center"
        aria-label="In progress"
      >
        <svg className="h-5 w-5 animate-spin text-[var(--color-accent)]" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" className="opacity-20" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full text-white"
        style={{ backgroundColor: "var(--color-critical)" }}
        aria-label="Failed"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
          <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className="h-5 w-5 rounded-full border-2 border-[var(--color-axis)]"
      aria-label="Pending"
    />
  );
}

function FailureView({
  error,
  onRestart,
}: {
  error: string;
  onRestart: () => void;
}) {
  return (
    <div className="text-center">
      <span
        className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[color-mix(in_oklab,var(--color-critical)_14%,transparent)] text-[var(--color-critical)]"
        aria-hidden="true"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 8v5m0 3.5h.01M10.3 3.9 2.5 17.4A2 2 0 0 0 4.2 20.4h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <h1 className="mt-4 text-lg font-semibold text-[var(--color-ink)]">
        We couldn't analyse this file
      </h1>
      <p className="mx-auto mt-2 max-w-sm text-sm text-[var(--color-ink-secondary)]">
        {error}
      </p>
      <div className="mt-6">
        <Button onClick={onRestart}>Upload a different file</Button>
      </div>
    </div>
  );
}
