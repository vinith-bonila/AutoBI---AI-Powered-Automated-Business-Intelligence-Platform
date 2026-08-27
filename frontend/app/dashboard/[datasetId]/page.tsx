"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import type { DashboardResponse } from "@/types";
import { Button, ErrorState } from "@/components/ui";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { DashboardSkeleton } from "@/components/dashboard/DashboardSkeleton";

export default function DashboardPage({
  params,
}: {
  params: Promise<{ datasetId: string }>;
}) {
  const { datasetId } = use(params);
  const router = useRouter();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<{ message: string; notReady: boolean } | null>(
    null,
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .dashboard(datasetId)
      .then((response) => !cancelled && setData(response))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 409) {
          // The dataset exists but is still processing — send them back to the
          // progress page rather than showing an error.
          router.replace(`/analyze/${datasetId}`);
          return;
        }
        setError({
          message:
            err instanceof ApiError
              ? err.message
              : "This dashboard could not be loaded.",
          notReady: err instanceof ApiError && err.status === 404,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, attempt, router]);

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-4 py-20">
        <ErrorState
          title={error.notReady ? "Dashboard not found" : "Couldn't load the dashboard"}
          message={error.message}
          onRetry={
            error.notReady ? undefined : () => setAttempt((value) => value + 1)
          }
        />
        <div className="mt-4 text-center">
          <Link href="/">
            <Button variant="secondary">Start a new analysis</Button>
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return <DashboardSkeleton />;
  }

  return <DashboardView data={data} />;
}
